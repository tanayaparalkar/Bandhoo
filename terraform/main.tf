# ==============================================================================
# Bandhoo Terraform AWS Infrastructure as Code (Main Definition)
#
# Resources:
#   1. AWS Default VPC & Subnet Data Sources (Zero NAT Gateway / Zero ALB cost)
#   2. Amazon Elastic Container Registry (ECR) with Lifecycle Retention Policy
#   3. Amazon CloudWatch Logs Group (7-day cost-optimized retention)
#   4. AWS Security Group (Ingress port 8001, full outbound connectivity)
#   5. IAM Task Execution Role (Minimal ECR pull & CloudWatch logging)
#   6. Amazon Elastic Container Service (ECS) Cluster
#   7. Amazon ECS Task Definition (Fargate, Linux AMD64, Health Checks)
#   8. Amazon ECS Service (1 single replica, assign_public_ip enabled)
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. VPC & Subnet Discovery (Default VPC - No NAT Gateway required)
# ------------------------------------------------------------------------------

# Discover the pre-existing default VPC in the chosen AWS region
data "aws_vpc" "default" {
  default = true
}

# Discover all public subnets belonging to the default VPC
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ------------------------------------------------------------------------------
# 2. Amazon Elastic Container Registry (ECR)
# ------------------------------------------------------------------------------

resource "aws_ecr_repository" "backend" {
  name                 = "bandhoo-backend"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# ECR Lifecycle Policy: Retains only recent images to eliminate unnecessary storage costs
resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Retain only the last ${var.ecr_image_retention_count} images to optimize ECR storage cost"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.ecr_image_retention_count
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# 3. Amazon CloudWatch Logs Group
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/bandhoo-backend"
  retention_in_days = var.log_retention_in_days
}

# ------------------------------------------------------------------------------
# 4. AWS Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project_name}-backend-sg"
  description = "Controls inbound and outbound traffic for Bandhoo ECS Fargate tasks"
  vpc_id      = data.aws_vpc.default.id

  # Inbound application traffic on port 8001
  ingress {
    description = "FastAPI HTTP application traffic on port 8001"
    from_port   = var.container_port
    to_port     = var.container_port
    protocol    = "tcp"
    cidr_blocks = var.inbound_cidr_blocks
  }

  # Outbound traffic (required for ECR image pull, AWS API calls, and CloudWatch log streaming)
  egress {
    description = "Allow all outbound traffic for image pulls and telemetry"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ------------------------------------------------------------------------------
# 5. IAM Task Execution Role
# ------------------------------------------------------------------------------

resource "aws_iam_role" "ecs_execution_role" {
  name        = "${var.project_name}-ecs-execution-role"
  description = "Allows ECS agent to pull container images from ECR and stream logs to CloudWatch"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

# Attach standard AWS managed policy for ECS task execution
resource "aws_iam_role_policy_attachment" "ecs_execution_role_policy" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ------------------------------------------------------------------------------
# 6. Amazon ECS Cluster
# ------------------------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = "bandhoo-cluster"
}

# ------------------------------------------------------------------------------
# 7. Amazon ECS Task Definition
# ------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "backend" {
  family                   = "bandhoo-backend"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.fargate_cpu
  memory                   = var.fargate_memory
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name      = "bandhoo-backend"
      image     = "${aws_ecr_repository.backend.repository_url}:${var.container_image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = var.container_port
          hostPort      = var.container_port
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "BANDHOO_HOST", value = "0.0.0.0" },
        { name = "BANDHOO_PORT", value = tostring(var.container_port) },
        { name = "BANDHOO_STORAGE_DIR", value = "/app/private_storage" },
        { name = "BANDHOO_SKIP_DOTENV", value = "1" },
        { name = "ENABLE_METRICS", value = "true" },
        { name = "REQUIRE_METRICS", value = "1" },
        { name = "DATABASE_URL", value = "sqlite:///bandhoo_persistence.db" },
        { name = "BANDHOO_CORS_ORIGINS", value = var.cors_origins }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8001/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
    }
  ])
}

# ------------------------------------------------------------------------------
# 8. Amazon ECS Service
# ------------------------------------------------------------------------------

resource "aws_ecs_service" "backend" {
  name            = "bandhoo-backend-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  # Ensure execution role and log group exist before the service starts tasks
  depends_on = [
    aws_iam_role_policy_attachment.ecs_execution_role_policy,
    aws_cloudwatch_log_group.ecs
  ]
}
