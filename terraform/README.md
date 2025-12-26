# Terraform Infrastructure

This directory contains Terraform code for provisioning cloud infrastructure for the project.

## Structure

- **bootstrap**  
  Contains Terraform configuration to create the S3 bucket and DynamoDB table used to store the remote Terraform state. This ensures state locking and consistency.  

- **environments/prod**  
  Contains the Terraform configuration for the production environment. The structure allows easy creation of additional environments in the future.

- **modules**  
  Reusable Terraform modules for different resources:
  - **ec2**: EC2 instances configuration
  - **ecr**: Elastic Container Registry
  - **iam**: IAM roles and policies
  - **rds**: RDS database instances
  - **s3**: S3 buckets
  - **security-groups**: Security group definitions
  - **vpc**: VPC and subnet configuration

## Usage

1. **Bootstrap**  
   Navigate to the `bootstrap` directory and run Terraform to create the S3 bucket and DynamoDB table for remote state storage.

2. **Environment Deployment**  
   Navigate to the desired environment (currently `environments/prod`) and run Terraform using the remote backend defined in `backend.tf`.

