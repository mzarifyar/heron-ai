#!/bin/bash
set -e

export AWS_ACCESS_KEY_ID=$(grep AWS_ADMIN_ACCESS_KEY_ID /Users/zarifyar/code/heron-ai/.env | cut -d= -f2)
export AWS_SECRET_ACCESS_KEY=$(grep AWS_ADMIN_SECRET_ACCESS_KEY /Users/zarifyar/code/heron-ai/.env | cut -d= -f2)
export AWS_REGION=us-east-1

# Your VPC IDs from the previous run
VPC_ID="vpc-072f6246ceebbaae6"
PUBLIC_SUBNET="subnet-019aab49ffa5f5d89"
PRIVATE_SUBNET="subnet-0514969e9c1b4ffee"
IGW_ID="igw-0967f8812c602bc13"
NAT_ID="nat-0871fe027f45c87b7"
EIP_ALLOC="eipalloc-09d71b465fe9bc8be"

echo "🔧 Setting up routing for NAT Gateway..."

# Check if NAT Gateway is ready
echo "📍 Checking NAT Gateway status..."
aws ec2 wait nat-gateway-available --nat-gateway-ids $NAT_ID
echo "   ✅ NAT Gateway is ready"

# Tag the NAT Gateway
aws ec2 create-tags --resources $NAT_ID --tags Key=Name,Value=heron-nat 2>/dev/null || true

# Create and configure route tables
echo "📍 Setting up route tables..."

# Public route table (traffic to IGW)
PUBLIC_RT=$(aws ec2 create-route-table --vpc-id $VPC_ID --tag-specifications 'ResourceType=route-table,Tags=[{Key=Name,Value=heron-public-rt}]' --query 'RouteTable.RouteTableId' --output text)
aws ec2 create-route --route-table-id $PUBLIC_RT --destination-cidr-block 0.0.0.0/0 --gateway-id $IGW_ID
aws ec2 associate-route-table --subnet-id $PUBLIC_SUBNET --route-table-id $PUBLIC_RT
echo "   Public Route Table: $PUBLIC_RT"

# Private route table (traffic to NAT Gateway)
PRIVATE_RT=$(aws ec2 create-route-table --vpc-id $VPC_ID --tag-specifications 'ResourceType=route-table,Tags=[{Key=Name,Value=heron-private-rt}]' --query 'RouteTable.RouteTableId' --output text)
aws ec2 create-route --route-table-id $PRIVATE_RT --destination-cidr-block 0.0.0.0/0 --nat-gateway-id $NAT_ID
aws ec2 associate-route-table --subnet-id $PRIVATE_SUBNET --route-table-id $PRIVATE_RT
echo "   Private Route Table: $PRIVATE_RT"

echo ""
echo "✅ Priority 3 hardening complete!"
echo ""
echo "Network Configuration:"
echo "  VPC: $VPC_ID"
echo "  Public Subnet: $PUBLIC_SUBNET → Route to IGW"
echo "  Private Subnet: $PRIVATE_SUBNET → Route to NAT Gateway"
echo "  NAT Gateway: $NAT_ID (Elastic IP: $EIP_ALLOC)"
echo ""
echo "✅ Your private subnet can now reach AWS APIs via NAT Gateway"