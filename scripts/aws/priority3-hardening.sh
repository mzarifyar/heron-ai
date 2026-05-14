#!/bin/bash
set -e

export AWS_ACCESS_KEY_ID=$(grep AWS_ADMIN_ACCESS_KEY_ID /Users/zarifyar/code/heron-ai/.env | cut -d= -f2)
export AWS_SECRET_ACCESS_KEY=$(grep AWS_ADMIN_SECRET_ACCESS_KEY /Users/zarifyar/code/heron-ai/.env | cut -d= -f2)
export AWS_REGION=us-east-1

echo "🔧 Setting up Priority 3 AWS Hardening..."

# 1. Create VPC
echo "📍 Creating VPC heron-vpc..."
VPC_ID=$(aws ec2 create-vpc --cidr-block 10.0.0.0/16 --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=heron-vpc}]' --query 'Vpc.VpcId' --output text)
echo "   VPC ID: $VPC_ID"

# 2. Create Public Subnet
echo "📍 Creating public subnet..."
PUBLIC_SUBNET=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.1.0/24 --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=heron-public-subnet}]' --query 'Subnet.SubnetId' --output text)
echo "   Public Subnet ID: $PUBLIC_SUBNET"

# 3. Create Private Subnet
echo "📍 Creating private subnet..."
PRIVATE_SUBNET=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.10.0/24 --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=heron-private-subnet}]' --query 'Subnet.SubnetId' --output text)
echo "   Private Subnet ID: $PRIVATE_SUBNET"

# 4. Create Internet Gateway
echo "📍 Creating Internet Gateway..."
IGW_ID=$(aws ec2 create-internet-gateway --tag-specifications 'ResourceType=internet-gateway,Tags=[{Key=Name,Value=heron-igw}]' --query 'InternetGateway.InternetGatewayId' --output text)
aws ec2 attach-internet-gateway --vpc-id $VPC_ID --internet-gateway-id $IGW_ID
echo "   IGW ID: $IGW_ID"

# 5. Create ALB Security Group
echo "📍 Creating ALB security group..."
ALB_SG=$(aws ec2 create-security-group --group-name heron-alb-sg --description "ALB for Heron" --vpc-id $VPC_ID --tag-specifications 'ResourceType=security-group,Tags=[{Key=Name,Value=heron-alb-sg}]' --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id $ALB_SG --protocol tcp --port 80 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id $ALB_SG --protocol tcp --port 443 --cidr 0.0.0.0/0
echo "   ALB SG ID: $ALB_SG"

# 6. Create Heron App Security Group
echo "📍 Creating Heron app security group..."
APP_SG=$(aws ec2 create-security-group --group-name heron-app-sg --description "Heron app server" --vpc-id $VPC_ID --tag-specifications 'ResourceType=security-group,Tags=[{Key=Name,Value=heron-app-sg}]' --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id $APP_SG --protocol tcp --port 8080 --source-group $ALB_SG
echo "   App SG ID: $APP_SG"

# 7. Enable EBS Encryption by Default
echo "📍 Enabling EBS encryption by default..."
aws ec2 enable-ebs-encryption-by-default

# 8. Enable S3 Default Encryption
echo "📍 Enabling S3 default encryption..."
aws s3api put-bucket-encryption --bucket $(aws s3api list-buckets --query 'Buckets[0].Name' --output text) --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' 2>/dev/null || echo "   (S3 bucket encryption may require manual setup per bucket)"

echo ""
echo "✅ Priority 3 hardening complete!"
echo ""
echo "VPC Setup:"
echo "  VPC ID: $VPC_ID"
echo "  Public Subnet: $PUBLIC_SUBNET"
echo "  Private Subnet: $PRIVATE_SUBNET"
echo "  ALB Security Group: $ALB_SG"
echo "  App Security Group: $APP_SG"
echo ""
echo "Next: Create NAT Gateway in public subnet for private subnet outbound access"