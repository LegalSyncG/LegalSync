variable "vpc_id" {
  description = "The VPC ID where security groups will be created"
  type        = string
}

variable "tags" {
  description = "Common tags to apply to all security groups"
  type        = map(string)
  default     = {}
}
