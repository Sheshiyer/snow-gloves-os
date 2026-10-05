terraform {
  required_version = ">= 1.10"
  required_providers {
    aws  = { source = "hashicorp/aws", version = "~> 5.80" }
    http = { source = "hashicorp/http", version = "~> 3.4" }
  }
  # Partial S3 backend: scripts/fleet/cloud_gateway.sh passes bucket, key, region and profile
  # from the private fleet.yaml. State is treated as secret (encrypted, versioned, private bucket).
  backend "s3" {}
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
  default_tags {
    tags = { Project = "snow-gloves-os", Component = "cloud-gateway", Name = var.name }
  }
}
