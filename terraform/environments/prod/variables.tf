variable "region" {}
variable "role_arn" {}

variable "project" {
  default = "legalsync"
}

variable "project_upper" {
  default = "LegalSync"
}

variable "vpc_cidr" {}
variable "azs" {}
variable "public_subnets" {}
variable "private_subnets" {}

variable "instance_type" {}
variable "db_instance_class" {}
variable "ami_id" {
  description = "Override AMI ID"
  type        = string
  default     = null
}
variable "db_username" {
  description = "The username for the RDS database"
  type        = string
}
variable "db_password" {
  description = "The password for the RDS database"
  type        = string
}
