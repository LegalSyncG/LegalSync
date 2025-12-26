resource "aws_db_subnet_group" "this" {
  name       = "rds-subnet-group"
  subnet_ids = var.subnet_ids

  tags = merge(var.tags, { Name = "${var.tags["Project"]}-rds-subnet-group" })
}

resource "aws_db_instance" "this" {
  allocated_storage      = 20
  engine                 = "postgres"
  engine_version         = "17.4"
  instance_class         = var.instance_class
  db_name                = var.db_name
  username               = var.db_username
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = var.security_groups
  skip_final_snapshot    = true

  tags = merge(var.tags, { Name = "${var.tags["Project"]}-rds" })
}
