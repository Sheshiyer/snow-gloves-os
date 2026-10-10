# Cloudflare edge for the gateway, inside one zone of one account.
#   DNS      hostname -> Elastic IP, proxied (orange cloud)
#   TLS      Origin CA certificate (key generated here, delivered to the instance through SSM)
#   WAF      /v1/* and /healthz only from allow_ips
#   Access   everything else on the host (dashboard, management API) needs an allowed email;
#            /v1 and /healthz bypass Access (CLIs cannot do the Access login) and rely on WAF + scoped keys
# Note: SSL mode "strict" is a zone-wide setting. Use a zone that only serves the gateway, or
# confirm every other proxied record in the zone already has a valid origin certificate.

locals {
  denied = [for d in var.deny_domains : d if
    var.hostname == d || endswith(var.hostname, ".${d}") || var.zone == d || endswith(var.zone, ".${d}") || strcontains(var.hostname, d)
  ]
  allow_list = join(" ", var.allow_ips)
  api_paths  = "(starts_with(http.request.uri.path, \"/v1\") or http.request.uri.path eq \"/healthz\")"
}

resource "terraform_data" "boundary" {
  input = var.hostname
  lifecycle {
    precondition {
      condition     = length(local.denied) == 0
      error_message = "hostname/zone falls under a denied domain: ${join(", ", local.denied)}"
    }
    precondition {
      condition     = var.hostname == var.zone || endswith(var.hostname, ".${var.zone}")
      error_message = "hostname must sit under zone."
    }
  }
}

# ------------------------------------------------------------------ origin certificate

resource "tls_private_key" "origin" {
  algorithm   = "ECDSA"
  ecdsa_curve = "P256"
}

resource "tls_cert_request" "origin" {
  private_key_pem = tls_private_key.origin.private_key_pem
  dns_names       = [var.hostname]
  subject {
    common_name = var.hostname
  }
}

resource "cloudflare_origin_ca_certificate" "origin" {
  csr                = tls_cert_request.origin.cert_request_pem
  hostnames          = [var.hostname]
  request_type       = "origin-ecc"
  requested_validity = 5475
  depends_on         = [terraform_data.boundary]
}

resource "aws_ssm_parameter" "tls_cert" {
  name  = "/${var.name}/tls/cert"
  type  = "SecureString"
  value = cloudflare_origin_ca_certificate.origin.certificate
}

resource "aws_ssm_parameter" "tls_key" {
  name  = "/${var.name}/tls/key"
  type  = "SecureString"
  value = tls_private_key.origin.private_key_pem
}

# ------------------------------------------------------------------ DNS and zone TLS

resource "cloudflare_dns_record" "gw" {
  zone_id    = var.cf_zone_id
  name       = var.hostname
  type       = "A"
  content    = var.origin_ip
  proxied    = true
  ttl        = 1
  comment    = "Snow Gloves fleet gateway (managed by infra/cloudflare-gateway)"
  depends_on = [terraform_data.boundary]
}

resource "cloudflare_zone_setting" "ssl" {
  zone_id    = var.cf_zone_id
  setting_id = "ssl"
  value      = "strict"
}

resource "cloudflare_zone_setting" "min_tls" {
  zone_id    = var.cf_zone_id
  setting_id = "min_tls_version"
  value      = "1.2"
}

# ------------------------------------------------------------------ WAF: API paths from the office only

# A zone has one custom-rules ruleset per phase. If the zone already has one, import it first:
#   tofu import cloudflare_ruleset.waf 'zones/<zone_id>/<ruleset_id>'  and keep its existing rules here.
resource "cloudflare_ruleset" "waf" {
  zone_id     = var.cf_zone_id
  name        = "${var.name} gateway"
  description = "Snow Gloves gateway: API paths only from the office"
  kind        = "zone"
  phase       = "http_request_firewall_custom"
  rules = [{
    action      = "block"
    description = "${var.name}: block /v1 and /healthz outside allow_ips"
    enabled     = true
    expression  = "(http.host eq \"${var.hostname}\" and ${local.api_paths} and not ip.src in {${local.allow_list}})"
  }]
  depends_on = [terraform_data.boundary]
}

# ------------------------------------------------------------------ Access

resource "cloudflare_zero_trust_access_policy" "people" {
  account_id = var.cf_account_id
  name       = "${var.name} operators"
  decision   = "allow"
  include    = [for e in var.access_emails : { email = { email = e } }]
}

resource "cloudflare_zero_trust_access_policy" "api_bypass" {
  account_id = var.cf_account_id
  name       = "${var.name} API bypass (WAF + scoped keys guard it)"
  decision   = "bypass"
  include    = [{ everyone = {} }]
}

resource "cloudflare_zero_trust_access_application" "dashboard" {
  account_id       = var.cf_account_id
  name             = "${var.name} dashboard"
  type             = "self_hosted"
  domain           = var.hostname
  session_duration = "24h"
  policies         = [{ id = cloudflare_zero_trust_access_policy.people.id, precedence = 1 }]
  depends_on       = [terraform_data.boundary]
}

resource "cloudflare_zero_trust_access_application" "api" {
  account_id       = var.cf_account_id
  name             = "${var.name} API"
  type             = "self_hosted"
  destinations     = [{ uri = "${var.hostname}/v1" }, { uri = "${var.hostname}/healthz" }]
  session_duration = "24h"
  policies         = [{ id = cloudflare_zero_trust_access_policy.api_bypass.id, precedence = 1 }]
  depends_on       = [terraform_data.boundary]
}
