# ==============================================================================
# Bandhoo Terraform Outputs (AWS)
# ==============================================================================

output "aws_region" {
  description = "Target AWS Region where infrastructure is provisioned."
  value       = var.aws_region
}

output "ecr_repository_name" {
  description = "Name of the Amazon ECR repository for Bandhoo backend."
  value       = aws_ecr_repository.backend.name
}

output "ecr_repository_url" {
  description = "Full URL of the Amazon ECR repository used to push Docker images."
  value       = aws_ecr_repository.backend.repository_url
}

output "ecs_cluster_name" {
  description = "Name of the Amazon ECS cluster."
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "Name of the Amazon ECS service running Bandhoo."
  value       = aws_ecs_service.backend.name
}

output "ecs_task_definition_family" {
  description = "Family name of the ECS task definition."
  value       = aws_ecs_task_definition.backend.family
}

output "ecs_task_definition_arn" {
  description = "ARN of the provisioned ECS task definition."
  value       = aws_ecs_task_definition.backend.arn
}

output "cloudwatch_log_group_name" {
  description = "Name of the Amazon CloudWatch log group capturing container stdout/stderr."
  value       = aws_cloudwatch_log_group.ecs.name
}

output "security_group_id" {
  description = "ID of the security group guarding the ECS Fargate task."
  value       = aws_security_group.ecs_tasks.id
}

output "ecr_docker_push_commands" {
  description = "Step-by-step commands to authenticate, tag, and push the local Docker image to Amazon ECR."
  value       = <<-EOT
    # 1. Authenticate Docker with Amazon ECR:
    aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${aws_ecr_repository.backend.repository_url}

    # 2. Tag local Bandhoo Docker image for ECR:
    docker tag bandhoo-backend:${var.container_image_tag} ${aws_ecr_repository.backend.repository_url}:${var.container_image_tag}

    # 3. Push container image to Amazon ECR:
    docker push ${aws_ecr_repository.backend.repository_url}:${var.container_image_tag}
  EOT
}

output "task_public_ip_discovery_command" {
  description = "AWS CLI one-liner to discover the dynamic public IP of the active Fargate task."
  value       = "TASK_ARN=$(aws ecs list-tasks --cluster ${aws_ecs_cluster.main.name} --service-name ${aws_ecs_service.backend.name} --query 'taskArns[0]' --output text --region ${var.aws_region}) && ENI_ID=$(aws ecs describe-tasks --cluster ${aws_ecs_cluster.main.name} --tasks $TASK_ARN --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' --output text --region ${var.aws_region}) && aws ec2 describe-network-interfaces --network-interface-ids $ENI_ID --query 'NetworkInterfaces[0].Association.PublicIp' --output text --region ${var.aws_region}"
}
