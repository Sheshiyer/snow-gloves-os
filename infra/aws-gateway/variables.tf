variable "name" {
  description = "Prefix for every resource and the SSM parameter path (/<name>/...)."
  type        = string
  default     = "snowgloves-gw"
}

variable "aws_region" {
  description = "From fleet.yaml cloud_gateway.region (the private data repo); no default."
  type        = string
}

variable "aws_profile" {
  description = "Named AWS CLI profile of the company account. Never `default`."
  type        = string
  validation {
    condition     = var.aws_profile != "" && var.aws_profile != "default"
    error_message = "Use a named profile for the company account, not `default`."
  }
}

variable "instance_type" {
  type    = string
  default = "t4g.medium"
}

variable "volume_size_gb" {
  type    = number
  default = 40
}

variable "omniroute_version" {
  description = "npm version of omniroute to install (pinned; upgrade deliberately)."
  type        = string
  default     = "3.8.50"
}

variable "tailnet_hostname" {
  description = "Tailscale machine name; the tailnet fallback URL is http://<tailnet_hostname>:20128."
  type        = string
  default     = "snowgloves-gw"
}

variable "budget_alarm_usd" {
  description = "Monthly AWS Budgets alarm for this account, in USD."
  type        = number
  default     = 60
}

variable "alarm_email" {
  description = "Where budget and instance-recovery alarms go. Empty disables the email subscriptions."
  type        = string
  default     = ""
}

variable "termination_protection" {
  description = "EC2 API termination protection. Keep true; scripts/fleet/cloud_gateway.sh aws destroy sets it false for the instance just before destroying."
  type        = bool
  default     = true
}
