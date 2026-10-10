output "gateway_url" {
  value = "https://${var.hostname}"
}

output "origin_cert_expires_on" {
  value = cloudflare_origin_ca_certificate.origin.expires_on
}

output "ssm_tls_parameters" {
  value = [aws_ssm_parameter.tls_cert.name, aws_ssm_parameter.tls_key.name]
}
