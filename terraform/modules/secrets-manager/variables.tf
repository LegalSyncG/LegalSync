variable "name" {
  description = "Secret name"
  type        = string
}

variable "description" {
  description = "Secret description"
  type        = string
  default     = null
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
}
