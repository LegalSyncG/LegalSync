#!/bin/bash
set -euo pipefail

echo "Starting EC2 bootstrap script..."

echo "Installing Docker Engine on Amazon Linux 2023..."

dnf update -y
# Remove old version if installed
dnf remove -y docker docker-client docker-client-latest docker-common docker-latest docker-latest-logrotate docker-logrotate docker-engine

# Install dnf plugin
dnf -y install dnf-plugins-core

# Add CentOS repository
dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

# Adjust release server version for Amazon Linux 2023
sed -i 's/$releasever/9/g' /etc/yum.repos.d/docker-ce.repo

# Install Docker
dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start Docker (use service directly if systemctl fails)
if command -v systemctl &>/dev/null; then
    systemctl enable --now docker || true
else
    service docker start || true
fi

echo "Installing needed packages..."
dnf install -y certbot python3-certbot-nginx git nginx jq

echo "Importing LegalSync files from S3..."
mkdir -p /opt/legalsync
aws s3 cp s3://bootstrapfiles-legalsync-ec2/LegalSync /opt/legalsync --recursive

echo "Importing Let's Encrypt files..."
mkdir -p /etc/letsencrypt
aws s3 cp s3://bootstrapfiles-legalsync-ec2/letsencrypt /etc/letsencrypt --recursive
chown -R root:root /etc/letsencrypt
chmod -R 600 /etc/letsencrypt
chmod 700 /etc/letsencrypt/{live,archive,accounts,renewal}

echo "Importing Nginx configuration..."
aws s3 cp s3://bootstrapfiles-legalsync-ec2/nginx /etc/nginx --recursive

sudo nginx 
# Reload Nginx
if command -v systemctl &>/dev/null; then
    systemctl reload nginx || true
else
    nginx -s reload || true
fi

echo "Creating load-db-secret.sh..."
cat > /usr/local/bin/load-db-secret.sh << 'EOF'
#!/bin/bash
set -euo pipefail

SECRET_NAME="prod/legalsync/postgres"
REGION="eu-central-1"

SECRET_JSON=$(aws secretsmanager get-secret-value \
  --region "$REGION" \
  --secret-id "$SECRET_NAME" \
  --query SecretString \
  --output text)

DB_USER=$(jq -r .username <<< "$SECRET_JSON")
DB_PASS=$(jq -r .password <<< "$SECRET_JSON")
DB_HOST=$(jq -r .host <<< "$SECRET_JSON")
DB_PORT=$(jq -r .port <<< "$SECRET_JSON")
DB_NAME=$(jq -r .dbname <<< "$SECRET_JSON")

export DATABASE_URL="postgresql+psycopg2://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

echo "DATABASE_URL exported successfully"
EOF

chmod +x /usr/local/bin/load-db-secret.sh
chown root:root /usr/local/bin/load-db-secret.sh

echo "Creating cleanup.sh..."
cat > /usr/local/bin/cleanup.sh << 'EOF'
#!/bin/bash
set -e

# CONFIG
KEEP_IMAGES=2
LOG_FILE="/var/log/docker-cleanup.log"

echo "----------------------------------------" >> $LOG_FILE
echo "$(date) - Starting Docker cleanup" >> $LOG_FILE

echo "Removing stopped containers..." >> $LOG_FILE
docker container prune -f >> $LOG_FILE 2>&1

echo "Removing dangling images..." >> $LOG_FILE
docker image prune -f >> $LOG_FILE 2>&1

echo "Removing old images (keeping last $KEEP_IMAGES)..." >> $LOG_FILE

docker images --format "{{.Repository}} {{.ID}} {{.CreatedAt}}" \
| sort -k1,1 -k3,3r \
| awk -v keep=$KEEP_IMAGES '
{
  repo=$1
  image=$2
  if (repo != last_repo) {
    count=0
    last_repo=repo
  }
  count++
  if (count > keep && repo != "<none>") {
    print image
  }
}' \
| xargs -r docker rmi -f >> $LOG_FILE 2>&1


echo "$(date) - Docker cleanup finished" >> $LOG_FILE
EOF

echo "Bootstrap finished."
