# OmniRoute on one EC2 instance with an Elastic IP.
#   443/tcp  from Cloudflare's published ranges only (Caddy, Origin CA cert)  -> 127.0.0.1:20128
#   41641/udp from anywhere (Tailscale direct path; WireGuard, authenticated)
#   no SSH: Tailscale SSH for operators, SSM Session Manager as break-glass
# The Elastic IP is the origin behind Cloudflare and the stable egress IP every provider sees.

data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
  }
  filter {
    name   = "architecture"
    values = ["arm64"]
  }
}

data "http" "cf_ips_v4" {
  url = "https://www.cloudflare.com/ips-v4"
}

data "http" "cf_ips_v6" {
  url = "https://www.cloudflare.com/ips-v6"
}

locals {
  cf_v4         = [for c in split("\n", trimspace(data.http.cf_ips_v4.response_body)) : trimspace(c) if trimspace(c) != ""]
  cf_v6         = [for c in split("\n", trimspace(data.http.cf_ips_v6.response_body)) : trimspace(c) if trimspace(c) != ""]
  ssm_prefix    = "/${var.name}"
  backup_bucket = "${var.name}-backups-${data.aws_caller_identity.current.account_id}"
}

# ------------------------------------------------------------------ network

resource "aws_security_group" "gw" {
  name        = "${var.name}-sg"
  description = "OmniRoute gateway: 443 from Cloudflare only, Tailscale UDP"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTPS from Cloudflare (IPv4)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = local.cf_v4
  }
  ingress {
    description      = "HTTPS from Cloudflare (IPv6)"
    from_port        = 443
    to_port          = 443
    protocol         = "tcp"
    ipv6_cidr_blocks = local.cf_v6
  }
  ingress {
    description      = "Tailscale direct connections"
    from_port        = 41641
    to_port          = 41641
    protocol         = "udp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
  egress {
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
}

# ------------------------------------------------------------------ backups (S3)

resource "aws_s3_bucket" "backups" {
  bucket        = local.backup_bucket
  force_destroy = var.backups_force_destroy
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    id     = "expire-old-backups"
    status = "Enabled"
    filter {
      prefix = "backups/"
    }
    expiration {
      days = 35
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }
}

# ------------------------------------------------------------------ instance role

data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "gw" {
  name               = "${var.name}-instance"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.gw.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "gw" {
  statement {
    sid       = "BackupsWrite"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.backups.arn, "${aws_s3_bucket.backups.arn}/*"]
  }
  statement {
    sid       = "ReadOwnParameters"
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = ["arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.ssm_prefix}/*"]
  }
  statement {
    sid       = "ConsumeOneShotTailscaleKey"
    actions   = ["ssm:DeleteParameter"]
    resources = ["arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.ssm_prefix}/tailscale/*"]
  }
  statement {
    sid       = "DecryptSecureStrings"
    actions   = ["kms:Decrypt"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.aws_region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "gw" {
  name   = "${var.name}-instance"
  role   = aws_iam_role.gw.id
  policy = data.aws_iam_policy_document.gw.json
}

resource "aws_iam_instance_profile" "gw" {
  name = "${var.name}-instance"
  role = aws_iam_role.gw.name
}

# ------------------------------------------------------------------ instance + Elastic IP

resource "aws_instance" "gw" {
  ami                     = data.aws_ami.ubuntu.id
  instance_type           = var.instance_type
  subnet_id               = sort(data.aws_subnets.default.ids)[0]
  vpc_security_group_ids  = [aws_security_group.gw.id]
  iam_instance_profile    = aws_iam_instance_profile.gw.name
  disable_api_termination = var.termination_protection

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.volume_size_gb
    encrypted   = true
    tags        = { Snapshot = var.name }
  }

  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    name              = var.name
    region            = var.aws_region
    omniroute_version = var.omniroute_version
    tailnet_hostname  = var.tailnet_hostname
    backup_bucket     = aws_s3_bucket.backups.bucket
    ssm_prefix        = local.ssm_prefix
    cf_ranges         = join(" ", concat(local.cf_v4, local.cf_v6))
  })
  user_data_replace_on_change = false

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}

resource "aws_eip" "gw" {
  domain   = "vpc"
  instance = aws_instance.gw.id
}

# ------------------------------------------------------------------ snapshots (DLM): 7 daily

data "aws_iam_policy_document" "assume_dlm" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["dlm.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dlm" {
  name               = "${var.name}-dlm"
  assume_role_policy = data.aws_iam_policy_document.assume_dlm.json
}

resource "aws_iam_role_policy_attachment" "dlm" {
  role       = aws_iam_role.dlm.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

resource "aws_dlm_lifecycle_policy" "snapshots" {
  description        = "${var.name} root volume, 7 daily snapshots"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"
  policy_details {
    resource_types = ["VOLUME"]
    target_tags    = { Snapshot = var.name }
    schedule {
      name = "daily"
      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["02:30"]
      }
      retain_rule {
        count = 7
      }
      copy_tags = true
    }
  }
}

# ------------------------------------------------------------------ alarms and budget

resource "aws_sns_topic" "alarms" {
  name = "${var.name}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "system_check" {
  alarm_name          = "${var.name}-system-check"
  alarm_description   = "Recover the gateway instance when the host fails its system status check"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_System"
  dimensions          = { InstanceId = aws_instance.gw.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_actions       = ["arn:aws:automate:${var.aws_region}:ec2:recover", aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "instance_check" {
  alarm_name          = "${var.name}-instance-check"
  alarm_description   = "Reboot the gateway instance when the OS stops answering its status check"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_Instance"
  dimensions          = { InstanceId = aws_instance.gw.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_actions       = ["arn:aws:automate:${var.aws_region}:ec2:reboot", aws_sns_topic.alarms.arn]
}

resource "aws_budgets_budget" "monthly" {
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_alarm_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = var.alarm_email == "" ? [] : [["ACTUAL", 100], ["FORECASTED", 100]]
    content {
      comparison_operator        = "GREATER_THAN"
      notification_type          = notification.value[0]
      threshold                  = notification.value[1]
      threshold_type             = "PERCENTAGE"
      subscriber_email_addresses = [var.alarm_email]
    }
  }
}
