variable "cidr" {
  description = "VPC CIDR block"
  type        = string
}

variable "azs" {
  description = "Availability zones"
  type        = list(string)
}

variable "public_subnets" {
  description = "Public subnet CIDR blocks"
  type        = list(string)
}

variable "private_subnets" {
  description = "Private subnet CIDR blocks"
  type        = list(string)
}

variable "tags" {
  description = "Common resource tags"
  type        = map(string)
}
