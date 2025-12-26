locals {
  tags = {
    Environment = "prod"
    Project     = var.project
    ManagedBy   = "terraform"
  }
}

module "iam" {
  source = "../../modules/iam"
  name   = "legalsync"
  tags   = local.tags
}

module "vpc" {
  source = "../../modules/vpc"

  cidr            = var.vpc_cidr
  azs             = var.azs
  public_subnets  = var.public_subnets
  private_subnets = var.private_subnets
  tags            = local.tags
}

module "security_groups" {
  source = "../../modules/security-groups"

  vpc_id = module.vpc.vpc_id
  tags   = local.tags
}

module "s3" {
  source = "../../modules/s3"

  bucket_name = "${var.project}-prod-bucket"
  tags        = local.tags
}

module "ecr" {
  source = "../../modules/ecr"

  name = "${var.project}"
  tags = local.tags
}

module "ec2" {
  source             = "../../modules/ec2"

  name                 = "${var.project_upper}App"
  ami_id               = var.ami_id
  instance_type        = var.instance_type
  subnet_id            = module.vpc.public_subnet_ids[0]
  security_groups      = [module.security_groups.ec2_sg_id]
  instance_profile_arn = module.iam.instance_profile_name
  root_volume_size     = 15
  tags                 = local.tags
  
}

module "rds" {
  source = "../../modules/rds"

  subnet_ids      = module.vpc.private_subnet_ids
  security_groups = [module.security_groups.rds_sg_id]
  instance_class  = var.db_instance_class
  tags            = local.tags
}
