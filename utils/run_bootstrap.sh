#!/bin/bash
set -e

REGION="eu-central-1"
TAG_NAME="LegalSyncApp"
TIMEOUT=240  # seconds to wait for SSM command

# Get all instance IDs with the given tag
INSTANCE_IDS=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$TAG_NAME" "Name=instance-state-name,Values=running" \
    --query "Reservations[].Instances[].InstanceId" \
    --output text \
    --region "$REGION")

if [[ -z "$INSTANCE_IDS" ]]; then
    echo "No running instances found with tag Name=$TAG_NAME"
    exit 1
fi

echo "Found instances: $INSTANCE_IDS"

# Send SSM command to all instances
COMMAND_ID=$(aws ssm send-command \
  --targets $(for id in $INSTANCE_IDS; do echo "Key=InstanceIds,Values=$id "; done) \
  --document-name "AWS-RunShellScript" \
  --comment "Run EC2 bootstrap script" \
  --parameters "commands=[
    \"aws s3 cp s3://bootstrapfiles-legalsync-ec2/ec2bootstrap.sh /usr/local/bin/ec2bootstrap.sh\",
    \"chmod +x /usr/local/bin/ec2bootstrap.sh\",
    \"/usr/local/bin/ec2bootstrap.sh\"
  ]" \
  --region "$REGION" \
  --query "Command.CommandId" \
  --output text)

echo "SSM Command ID: $COMMAND_ID"

# Wait for each instance command to finish
for INSTANCE_ID in $INSTANCE_IDS; do
    echo "Waiting for instance $INSTANCE_ID..."
    STATUS="Pending"
    SECONDS_WAITED=0

    while [[ "$STATUS" == "Pending" || "$STATUS" == "InProgress" ]]; do
        sleep 5
        SECONDS_WAITED=$((SECONDS_WAITED + 5))
        STATUS=$(aws ssm get-command-invocation \
            --command-id "$COMMAND_ID" \
            --instance-id "$INSTANCE_ID" \
            --region "$REGION" \
            --query "Status" \
            --output text)
        echo "Instance $INSTANCE_ID: $STATUS"

        if [[ $SECONDS_WAITED -ge $TIMEOUT ]]; then
            echo "Timeout reached waiting for SSM command on $INSTANCE_ID"
            break
        fi
    done

    # Fetch and print logs
    OUTPUT=$(aws ssm get-command-invocation \
        --command-id "$COMMAND_ID" \
        --instance-id "$INSTANCE_ID" \
        --region "$REGION" \
        --query "[StandardOutputContent,StandardErrorContent]" \
        --output text)

    echo "Logs for instance $INSTANCE_ID:"
    echo "$OUTPUT"
done

echo "Bootstrap finished."
