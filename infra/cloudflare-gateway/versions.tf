terraform {
  required_version = ">= 1.10"
  required_providers {
    cloudflare = { source = "cloudflare/cloudflare", version = "~> 5.0" }
    aws        = { source = "hashicorp/aws", version = "~> 5.80" }
    tls        = { source = "hashicorp/tls", version = "~> 4.0" }
  }
  # Partial S3 backend (same bucket as the aws stack). This state holds the origin certificate key:
  # it is secret and lives only in the company account's encrypted, private state bucket.
  backend "s3" {}
}

# Token comes from CLOUDFLARE_API_TOKEN, which scripts/fleet/cloud_gateway.sh reads from the
# Keychain after scripts/fleet/cloud_guard.py has proved it belongs to cf_account_id / cf_zone_id.
provider "cloudflare" {}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
  default_tags {
    tags = { Project = "snow-gloves-os", Component = "cloud-gateway", Name = var.name }
  }
}
