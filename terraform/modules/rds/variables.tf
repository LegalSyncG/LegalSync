variable "subnet_ids" {
  description = "List of private subnet IDs for the RDS subnet group"
  type        = list(string)
}

variable "security_groups" {
  description = "List of security group IDs for the RDS instance"
  type        = list(string)
}

variable "instance_class" {
  description = "RDS instance class (size)"
  type        = string
}

variable "tags" {
  description = "Tags to apply to the RDS instance"
  type        = map(string)
  default     = {}
}

variable "db_name" {
  description = "Name of the initial database to create"
  type        = string
  default     = "mydb"
}

variable "db_username" {
  description = "Username for the RDS instance"
  type        = string
}

variable "db_password" {
  description = "Password for the RDS instance"
  type        = string
}