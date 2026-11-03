# Bandhoo AWS Infrastructure as Code (Terraform)

This directory contains production-ready Terraform configurations for deploying the **Bandhoo** Criminal Law Decision Support & Complaint Structuring Backend to **Amazon Web Services (AWS)** using **Amazon Elastic Container Service (ECS) with AWS Fargate** and **Amazon Elastic Container Registry (ECR)**.

---

## 1. Architecture Overview

```
                                Client / Browser
                                       |
                              HTTP Port 8001
                                       v
+-----------------------------------------------------------------------------------+
| AWS Cloud (Region: ap-south-1 / Mumbai)                                           |
|                                                                                   |
|  Default VPC (data.aws_vpc.default)                                               |
|  Default Public Subnets (data.aws_subnets.default)                                |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | AWS Security Group: bandhoo-backend-sg                                      |  |
|  |   - Inbound:  TCP 8001 from var.inbound_cidr_blocks (default 0.0.0.0/0)      |  |
|  |   - Outbound: All traffic (-1) to 0.0.0.0/0 (for ECR pull & CloudWatch logs) |  |
|  +-----------------------------------------------------------------------------+  |
|                                        |                                          |
|                                        v                                          |
|  +-----------------------------------------------------------------------------+  |
|  | Amazon ECS Cluster: bandhoo-cluster                                         |  |
|  |                                                                             |  |
|  |   Amazon ECS Service: bandhoo-backend-service (Launch Type: FARGATE)        |  |
|  |   +----------------------------------------------------------------------+  |  |
|  |   | ECS Task: bandhoo-backend (Fargate, Linux AMD64, 1 running replica)  |  |  |
|  |   |   - CPU: 512 (0.5 vCPU) | Memory: 1024 MiB (1.0 GB)                  |  |  |
|  |   |   - Network: awsvpc (assign_public_ip = true)                        |  |  |
|  |   |   - Health Check: curl -f http://localhost:8001/health (30s grace)   |  |  |
|  |   |   - Ephemeral SQLite: sqlite:///bandhoo_persistence.db               |  |  |
|  |   |   - Metrics Exposed: http://<TASK_PUBLIC_IP>:8001/metrics            |  |  |
|  |   |   - Logging: awslogs -> CloudWatch Log Group                         |  |  |
|  |   +----------------------------------+-----------------------------------+  |  |
|  +--------------------------------------|---------------------------------------+  |
|                                         |                                         |
|                          Pull Image     | Stream Logs                             |
|                              v          v                                         |
|  +------------------------------------+  +-------------------------------------+  |
|  | Amazon ECR: bandhoo-backend        |  | CloudWatch Logs:                    |  |
|  |   - Image Tag: 1.0.0               |  |   /ecs/bandhoo-backend              |  |
|  |   - Lifecycle: retain 5 images     |  |   - Retention: 7 days               |  |
|  |   - Scanning: on push              |  |                                     |  |
|  +------------------------------------+  +-------------------------------------+  |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | IAM Execution Role: bandhoo-ecs-execution-role                               |  |
|  |   - Policy: AmazonECSTaskExecutionRolePolicy (ECR pull + CloudWatch logging)|  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

---

## 2. Manifest Inventory

| File | Purpose |
| :--- | :--- |
| [`versions.tf`](file:///Users/tanaya/Desktop/Bandhoo-1/terraform/versions.tf) | Declares required Terraform CLI (`>= 1.5.0`) and AWS provider (`~> 5.0`). |
| [`providers.tf`](file:///Users/tanaya/Desktop/Bandhoo-1/terraform/providers.tf) | Configures the `aws` provider with default tags and region `ap-south-1`. |
| [`variables.tf`](file:///Users/tanaya/Desktop/Bandhoo-1/terraform/variables.tf) | Declares configurable parameters with validation (Fargate CPU/Memory pairings, CIDR blocks, log retention). |
| [`main.tf`](file:///Users/tanaya/Desktop/Bandhoo-1/terraform/main.tf) | Defines AWS resources: Default VPC discovery, ECR repository with lifecycle cleanup, CloudWatch log group, Security Group, IAM Task Execution Role, ECS Cluster, Fargate Task Definition, and ECS Service. |
| [`outputs.tf`](file:///Users/tanaya/Desktop/Bandhoo-1/terraform/outputs.tf) | Exposes operational details, ECR push commands, and a one-liner to discover the running Fargate task's public IP. |
| [`terraform.tfvars.example`](file:///Users/tanaya/Desktop/Bandhoo-1/terraform/terraform.tfvars.example) | Template variable file for AWS deployment. |
| [`.gitignore`](file:///Users/tanaya/Desktop/Bandhoo-1/terraform/.gitignore) | Excludes `.terraform/`, `*.tfstate`, and local variable secret files from Git tracking. |

---

## 3. Cost-Control Design & AWS Billing Implications

To prevent unexpected cloud expenditures during academic or development evaluations, this architecture enforces several cost controls:

1. **Zero Application Load Balancer (ALB)**: ALBs incur an idle charge of ~$16-$22/month regardless of traffic. The Fargate task runs directly in the default VPC's public subnet with an assigned public IP, eliminating load balancer charges.
2. **Zero NAT Gateway**: NAT Gateways cost ~$32/month plus data processing fees. By utilizing default public subnets with `assign_public_ip = true`, tasks route traffic directly via the AWS Internet Gateway at zero hourly gateway cost.
3. **Single Task Replica**: The ECS service is locked to `desired_count = 1` with no auto-scaling, preventing horizontal scale-out costs.
4. **Fargate Compute**: Sized conservatively at `0.5 vCPU` (512 units) and `1.0 GB RAM` (1024 MiB). In AWS Mumbai (`ap-south-1`), Fargate pricing is approximately \$0.020 per hour (~$14-$15 per month if left running 24/7, or cents per hour during active testing).
5. **7-Day CloudWatch Log Retention**: Standard CloudWatch log retention is indefinite by default. This configuration enforces `log_retention_in_days = 7` to avoid long-term storage accumulation.
6. **ECR Lifecycle Cleanup**: Amazon ECR storage costs ~$0.10/GB/month. The ECR lifecycle policy automatically expires old images, keeping only the latest 5 image tags.

> [!TIP]
> Always run `terraform destroy` when your demonstration or testing session concludes to immediately stop all AWS billing.

---

## 4. SQLite Persistence & Architectural Limitations

> [!WARNING]
> **Ephemeral Storage Limitation**:
> Bandhoo currently uses SQLite local persistence (`sqlite:///bandhoo_persistence.db`).
> In AWS ECS Fargate, container local disk storage is **ephemeral**. When the Fargate task is replaced, restarted, stopped, or redeployed, any data written to the local SQLite database file will be permanently lost.
>
> **Production Scaling Recommendation**:
> For persistent and multi-replica production deployments, update `DATABASE_URL` to point to a managed relational database service such as **Amazon RDS for PostgreSQL** or **Amazon Aurora Serverless**, and set up an Amazon EFS persistent volume if local file uploads must be preserved across task lifecycles.

---

## 5. Prerequisites

1. **Terraform CLI**: Version `>= 1.5.0` installed (`terraform version`).
2. **AWS CLI (`aws`)**: Version `>= 2.0` installed (`aws --version`).
3. **Docker**: Running locally for building and pushing the container image (`docker info`).
4. **AWS Account**: With active credentials configured for the `ap-south-1` (Mumbai) region.

---

## 6. AWS Authentication Setup

Ensure your local terminal has authenticated AWS credentials:

```bash
# Verify existing AWS configuration and caller identity
aws sts get-caller-identity

# If not yet configured, configure your AWS CLI profile:
aws configure
# AWS Access Key ID: <YOUR_ACCESS_KEY>
# AWS Secret Access Key: <YOUR_SECRET_KEY>
# Default region name: ap-south-1
# Default output format: json
```

---

## 7. Step-by-Step Deployment Workflow

### Step 7.1: Initialize and Plan Terraform

Navigate to the `terraform/` directory:

```bash
cd terraform

# 1. Initialize Terraform (downloads AWS provider ~> 5.0)
terraform init

# 2. Check formatting and validate configuration syntax
terraform fmt -check
terraform validate

# 3. Create execution plan
terraform plan -out=tfplan
```

### Step 7.2: Two-Phase Deployment (ECR Repository First)

Because the ECS Task Definition references the Docker image in ECR, provision the ECR repository first so the Docker image can be pushed before the ECS task starts:

```bash
# 1. Provision the ECR repository, IAM role, security group, and log group
terraform apply -target=aws_ecr_repository.backend \
                -target=aws_ecr_lifecycle_policy.backend \
                -target=aws_cloudwatch_log_group.ecs \
                -target=aws_iam_role.ecs_execution_role \
                -target=aws_iam_role_policy_attachment.ecs_execution_role_policy \
                -target=aws_security_group.ecs_tasks \
                -target=aws_ecs_cluster.main
```

### Step 7.3: Build, Tag, and Push Docker Image

Authenticate your local Docker client to the provisioned Amazon ECR repository and push the image:

```bash
# 1. Retrieve the ECR repository URL from Terraform outputs
ECR_URL=$(terraform output -raw ecr_repository_url)
AWS_REGION=$(terraform output -raw aws_region)

# 2. Authenticate Docker with Amazon ECR
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_URL

# 3. Build the local image (if not already built)
cd ..
docker build -t bandhoo-backend:1.0.0 .
cd terraform

# 4. Tag the local image with the ECR repository destination
docker tag bandhoo-backend:1.0.0 ${ECR_URL}:1.0.0

# 5. Push the image to Amazon ECR
docker push ${ECR_URL}:1.0.0
```

### Step 7.4: Deploy ECS Service & Task Definition

Once the container image is in ECR, apply the full Terraform configuration to launch the ECS Service:

```bash
terraform apply
```

---

## 8. Verifying the Deployment

### Step 8.1: Discover the Fargate Task Public IP

Because ECS Fargate allocates dynamic public IPs to tasks upon startup, retrieve the active public IP with this one-liner:

```bash
# Run the discovery command exposed by Terraform output:
eval $(terraform output -raw task_public_ip_discovery_command | sed 's/^/PUBLIC_IP=$(/' | sed 's/$/)/')
echo "Bandhoo Task Public IP: $PUBLIC_IP"
```

Or query manually using the AWS CLI:

```bash
TASK_ARN=$(aws ecs list-tasks --cluster bandhoo-cluster --service-name bandhoo-backend-service --query 'taskArns[0]' --output text --region ap-south-1)
ENI_ID=$(aws ecs describe-tasks --cluster bandhoo-cluster --tasks $TASK_ARN --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' --output text --region ap-south-1)
PUBLIC_IP=$(aws ec2 describe-network-interfaces --network-interface-ids $ENI_ID --query 'NetworkInterfaces[0].Association.PublicIp' --output text --region ap-south-1)

echo "Discovered Public IP: $PUBLIC_IP"
```

### Step 8.2: Verify Health Probe

```bash
curl -i http://${PUBLIC_IP}:8001/health
```

Expected response:
```json
{"status":"healthy","service":"bandhoo-backend","version":"1.0.0"}
```

### Step 8.3: Verify Prometheus Metrics

```bash
curl -i http://${PUBLIC_IP}:8001/metrics
```

Expected response:
```
# HELP python_gc_objects_collected_total Objects collected during gc
# TYPE python_gc_objects_collected_total counter
...
```

### Step 8.4: Inspect CloudWatch Logs

To inspect live application logs streaming from the container:

```bash
aws logs tail /ecs/bandhoo-backend --follow --region ap-south-1
```

---

## 9. Cleanup & Teardown

To prevent ongoing cloud charges, destroy all provisioned AWS resources when finished:

```bash
# 1. Destroy all Terraform-managed AWS infrastructure
terraform destroy

# 2. Confirm clean state
terraform show
```
