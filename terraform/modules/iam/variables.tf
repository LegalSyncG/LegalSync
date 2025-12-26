variable "name" {
  description = "Base name for the IAM role and instance profile"
  type        = string
}

variable "tags" {
  description = "Tags to apply to IAM resources"
  type        = map(string)
  default     = {}
}
