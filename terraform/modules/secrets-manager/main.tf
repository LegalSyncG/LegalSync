resource "aws_secretsmanager_secret" "this" {
  name        = var.name
  description = var.description

  tags = merge(var.tags, {
    Name = var.name
  })
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.this.id

  secret_string = jsonencode({
    username             = var.db_username
    password             = var.db_password
    engine               = "postgres"
    host                 = var.db_host
    port                 = var.db_port
    dbname               = var.db_name
    dbInstanceIdentifier = var.db_instance_id
  })
}

