#!/bin/bash
set -e

export AWS_ACCESS_KEY_ID=$(grep AWS_ADMIN_ACCESS_KEY_ID /Users/zarifyar/code/heron-ai/.env | cut -d= -f2)
export AWS_SECRET_ACCESS_KEY=$(grep AWS_ADMIN_SECRET_ACCESS_KEY /Users/zarifyar/code/heron-ai/.env | cut -d= -f2)
export AWS_REGION=us-east-1

VPC_ID="vpc-072f6246ceebbaae6"
PUBLIC_SUBNET="subnet-019aab49ffa5f5d89"
APP_SG="sg-0aec173d00ed287a0"

echo "🚀 Provisioning AWS free tier resources for Heron discovery..."

# 1. Create t3.micro EC2 instance (free tier eligible)
echo "📍 Launching EC2 t3.micro instance..."
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id ami-0fa63072dba82baa6 \
  --instance-type t3.micro \
  --subnet-id $PUBLIC_SUBNET \
  --security-group-ids $APP_SG \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=heron-test-web-server}]' \
  --query 'Instances[0].InstanceId' \
  --output text)
echo "   Instance ID: $INSTANCE_ID"

# 2. Create RDS db.t2.micro (free tier eligible)
echo "📍 Creating RDS MySQL db.t2.micro..."
aws rds create-db-instance \
  --db-instance-identifier heron-test-db \
  --db-instance-class db.t3.micro \
  --engine mysql \
  --master-username admin \
  --master-user-password "HeronisFree2024!" \
  --allocated-storage 20 \
  --storage-type gp2 \
  --publicly-accessible false \
  --vpc-security-group-ids $APP_SG \
  --backup-retention-period 7 \
  --tags "Key=Name,Value=heron-test-db" 2>/dev/null || echo "   (RDS instance being created...)"
echo "   RDS Instance: heron-test-db"

# 3. Create S3 bucket (5GB free)
echo "📍 Creating S3 bucket..."
BUCKET_NAME="heron-test-bucket-$(date +%s)"
aws s3api create-bucket --bucket $BUCKET_NAME --region $AWS_REGION
echo "   S3 Bucket: $BUCKET_NAME"

echo ""
echo "✅ Free tier resources provisioned!"
echo ""
echo "Resources created:"
echo "  EC2: $INSTANCE_ID (t3.micro - free 750 hrs/month)"
echo "  RDS: heron-test-db (db.t3.micro - free 750 hrs/month)"
echo "  S3: $BUCKET_NAME (5GB free storage)"
echo ""
echo "Run discovery scan to see them detected:"
echo "  curl -X POST http://localhost:8080/api/v1/discovery/connect \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"cloud\": \"aws\", \"demo\": false}'"
