# ==============================================================================
# Bandhoo AWS Provider Configuration
# ==============================================================================

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}
