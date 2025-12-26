
terraform {
  backend "s3" {
    bucket         = "terraform-state-864298146673-eu-central-1"
    key            = "terraform.tfstate"
    region         = "eu-central-1"
    dynamodb_table = "dynamoDB_to_lock_terraform_state-864298146673-eu-central-1"
    encrypt        = true
  }
}