resource "aws_secretsmanager_secret" "this" {
  name        = var.name
  description = var.description

  tags = merge(var.tags, {
    Name = var.name
  })
}
