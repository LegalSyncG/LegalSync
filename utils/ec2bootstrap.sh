echo "Starting EC2 bootstrap script..."
echo "Switching to root user..."
sudo -i

echo "Installing Docker Engine on Amazon Linux 2023..."

sudo dnf update -y
# Remove old version if installed
sudo dnf remove -y docker docker-client docker-client-latest docker-common docker-latest docker-latest-logrotate docker-logrotate docker-engine

# Install dnf plugin
sudo dnf -y install dnf-plugins-core

# Add CentOS repository
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

# Adjust release server version in the path as it will not match with Amazon Linux 2023
# so we'll hard code it to Alamlinux 9/Centos 9
sudo sed -i 's/$releasever/9/g' /etc/yum.repos.d/docker-ce.repo

# Install as usual
sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Enable the docker service
sudo systemctl enable --now docker

echo "Installing needed packages"

echo "Installing needed packages..."
sudo dnf install -y certbot python3-certbot-nginx
sudo dnf install -y git nginx

echo "Importing needed files"

#LegalSync directory

sudo mkdir -p /home/ec2-user
sudo chown ec2-user:ec2-user /home/ec2-user
sudo chmod 755 /home/ec2-user
sudo aws s3 cp \
  s3://bootstrapfiles-legalsync-ec2/LegalSync \
  /home/ec2-user/LegalSync \
  --recursive
sudo chown -R ec2-user:ec2-user /home/ec2-user/LegalSync


#LetsEncrypt directory 
sudo mkdir -p /etc/letsencrypt
sudo aws s3 cp \
  s3://bootstrapfiles-legalsync-ec2/letsencrypt \
  /etc/letsencrypt \
  --recursive
sudo chown -R root:root /etc/letsencrypt
sudo chmod -R 600 /etc/letsencrypt
sudo chmod 700 /etc/letsencrypt
sudo chmod 700 /etc/letsencrypt/{live,archive,accounts,renewal}


#Nginx configuration
sudo aws s3 cp \
  s3://bootstrapfiles-legalsync-ec2/nginx \
  /etc/nginx \
  --recursive


echo "Reloading Nginx to apply new configuration..."
sudo systemctl reload nginx


