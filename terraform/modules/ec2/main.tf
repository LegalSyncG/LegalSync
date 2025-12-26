resource "aws_instance" "this" {
  ami                           = var.ami_id
  instance_type                 = var.instance_type
  subnet_id                     = var.subnet_id
  vpc_security_group_ids        = var.security_groups
  iam_instance_profile          = var.instance_profile_arn
  key_name                      = var.key_name
  associate_public_ip_address   = var.associate_public_ip
  user_data                     = var.user_data


  lifecycle {
    ignore_changes = [
      subnet_id,
      vpc_security_group_ids,
    ]
  }
  root_block_device {
    volume_size = var.root_volume_size
    volume_type = var.root_volume_type
  }

  tags = merge(
    var.tags,
    {
      Name = var.name
    }
  )
}
