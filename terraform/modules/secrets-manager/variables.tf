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

variable "db_username" {
  type = string
}

variable "db_password" {
  type = string
  sensitive = true
}

variable "db_host" {
  type = string
}

variable "db_port" {
  type = number
}

variable "db_name" {
  type = string
}

variable "db_instance_id" {
  type = string
}
