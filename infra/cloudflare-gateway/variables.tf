variable "name" {
  description = "Must match the aws stack: the instance reads /<name>/tls/* from SSM."
  type        = string
  default     = "snowgloves-gw"
}

variable "aws_region" {
  type    = string
  default = "eu-west-3"
}

variable "aws_profile" {
  type = string
  validation {
    condition     = var.aws_profile != "" && var.aws_profile != "default"
    error_message = "Use a named profile for the company account, not `default`."
  }
}

variable "cf_account_id" {
  type = string
}

variable "cf_zone_id" {
  type = string
}

variable "zone" {
  description = "Zone apex, e.g. example.com. Must be the zone that cf_zone_id names."
  type        = string
}

variable "hostname" {
  description = "Gateway hostname under the zone, e.g. gw.example.com."
  type        = string
}

variable "origin_ip" {
  description = "Elastic IP from the aws stack (cloud_gateway.sh passes it)."
  type        = string
}

variable "allow_ips" {
  description = "Office egress IPs (or CIDRs) allowed to call /v1 and /healthz. Everything else is blocked at the edge."
  type        = list(string)
  validation {
    condition     = length(var.allow_ips) > 0
    error_message = "At least one office egress IP is required; an empty list would leave /v1 open to the internet."
  }
}

variable "access_emails" {
  description = "People allowed through Cloudflare Access to the dashboard and management API."
  type        = list(string)
  validation {
    condition     = length(var.access_emails) > 0
    error_message = "At least one Access email is required."
  }
}

variable "deny_domains" {
  description = "Domains (and Access team names) this stack must never write to: the personal setup."
  type        = list(string)
  default     = []
}
