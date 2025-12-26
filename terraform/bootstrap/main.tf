resource "aws_s3_bucket" "terraform_state" {
  bucket = "terraform-state-864298146673-eu-central-1"
}

resource "aws_s3_bucket_versioning" "versioning" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"
  }
}
 
resource "aws_dynamodb_table" "terraform_lock_state" {
  name         = "dynamoDB_to_lock_terraform_state-864298146673-eu-central-1"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
}