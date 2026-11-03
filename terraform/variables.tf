# ==============================================================================
# Bandhoo Terraform Variable Definitions (AWS)
# ==============================================================================

variable "aws_region" {
  type        = string
  description = "Target AWS region for deploying Bandhoo infrastructure."
  default     = "ap-south-1" # Mumbai
}

variable "project_name" {
  type        = string
  description = "Base project name used in resource naming."
  default     = "bandhoo"
}

variable "environment" {
  type        = string
  description = "Deployment environment (e.g. dev, staging, prod)."
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "The environment must be one of: dev, staging, prod."
  }
}

variable "container_image_tag" {
  type        = string
  description = "Docker image tag for the Bandhoo backend container."
  default     = "1.0.0"
}

variable "container_port" {
  type        = number
  description = "Port on which the Bandhoo FastAPI container listens."
  default     = 8001
}

variable "fargate_cpu" {
  type        = string
  description = "CPU units allocated for the Fargate task (256 = 0.25 vCPU, 512 = 0.5 vCPU, 1024 = 1 vCPU)."
  default     = "512"

  validation {
    condition     = contains(["256", "512", "1024", "2048", "4096"], var.fargate_cpu)
    error_message = "fargate_cpu must be one of: '256', '512', '1024', '2048', '4096'."
  }
}

variable "fargate_memory" {
  type        = string
  description = "Memory in MiB allocated for the Fargate task (512, 1024, 2048, 4096). Must be compatible with fargate_cpu."
  default     = "1024"

  validation {
    condition = (
      (var.fargate_cpu == "256" && contains(["512", "1024", "2048"], var.fargate_memory)) ||
      (var.fargate_cpu == "512" && contains(["1024", "2048", "3072", "4096"], var.fargate_memory)) ||
      (var.fargate_cpu == "1024" && contains(["2048", "3072", "4096", "5120", "6144", "7168", "8192"], var.fargate_memory)) ||
      (var.fargate_cpu == "2048" && contains(["4096", "5120", "6144", "7168", "8192", "9216", "10240", "11264", "12288", "13312", "14336", "15360", "16384"], var.fargate_memory)) ||
      (var.fargate_cpu == "4096" && contains(["8192", "9216", "10240", "11264", "12288", "13312", "14336", "15360", "16384", "17408", "18432", "19456", "20480", "21504", "22528", "23552", "24576", "25600", "26624", "27648", "28672", "29696", "30720"], var.fargate_memory))
    )
    error_message = "Invalid AWS Fargate CPU and Memory combination. See AWS Fargate documentation for supported vCPU and memory pairings."
  }
}

variable "inbound_cidr_blocks" {
  type        = list(string)
  description = "Allowed IPv4 CIDR blocks for inbound access to port 8001. Explicit configuration required (e.g. ['YOUR_IP/32'])."
  default     = []
}

variable "cors_origins" {
  type        = string
  description = "Comma-separated list of allowed CORS origins for the FastAPI application."
  default     = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"
}

variable "log_retention_in_days" {
  type        = number
  description = "Retention period in days for CloudWatch log events (default 7 days for cost control)."
  default     = 7

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365], var.log_retention_in_days)
    error_message = "log_retention_in_days must be a valid CloudWatch retention value (e.g. 1, 3, 5, 7, 14, 30)."
  }
}

variable "ecr_image_retention_count" {
  type        = number
  description = "Maximum number of Docker images to retain in Amazon ECR before expiring older images."
  default     = 5

  validation {
    condition     = var.ecr_image_retention_count >= 1 && var.ecr_image_retention_count <= 100
    error_message = "ecr_image_retention_count must be between 1 and 100."
  }
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to all provisioned AWS infrastructure resources."
  default = {
    Project     = "Bandhoo"
    ManagedBy   = "Terraform"
    Environment = "dev"
    Component   = "Backend"
  }
}
