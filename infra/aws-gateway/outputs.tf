output "elastic_ip" {
  description = "Static IP: the Cloudflare origin and the egress IP providers see."
  value       = aws_eip.gw.public_ip
}

output "instance_id" {
  value = aws_instance.gw.id
}

output "backup_bucket" {
  value = aws_s3_bucket.backups.bucket
}

output "ssm_prefix" {
  description = "SSM Parameter Store path the instance reads (tls/, tailscale/)."
  value       = local.ssm_prefix
}

output "tailnet_url" {
  value = "http://${var.tailnet_hostname}:20128"
}
