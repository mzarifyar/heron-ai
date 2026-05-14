#!/bin/bash
set -e

# OCI Permanent Free Tier Setup (never expires, indefinite)
# Prerequisites:
# 1. Create OCI account at https://www.oracle.com/cloud/free/
# 2. Set OCI_TENANCY_OCID, OCI_USER_OCID, OCI_FINGERPRINT, OCI_KEY_FILE, OCI_REGION
# 3. Configure ~/.oci/config with credentials

export OCI_REGION=${OCI_REGION:-"us-ashburn-1"}
export OCI_COMPARTMENT_ID=${OCI_COMPARTMENT_ID:-"your-root-compartment"}

echo "🚀 Provisioning OCI permanent free tier resources..."

# 1. Create Compute Instance (VM.Standard.E2.1.Micro - always free)
echo "📍 Creating Compute Instance (VM.Standard.E2.1.Micro)..."
INSTANCE_ID=$(oci compute instance launch \
  --availability-domain "$(oci iam availability-domain list --compartment-id $OCI_COMPARTMENT_ID --query 'data[0]."name"' --raw-output)" \
  --compartment-id $OCI_COMPARTMENT_ID \
  --image-id "$(oci compute image list --compartment-id $OCI_COMPARTMENT_ID --query 'data[0]."id"' --raw-output)" \
  --shape VM.Standard.E2.1.Micro \
  --display-name heron-test-web-server \
  --query 'data.id' --raw-output)
echo "   Instance: $INSTANCE_ID"

# 2. Create MySQL Database (DB.t3.micro - always free)
echo "📍 Creating MySQL Database Service..."
DB_SYSTEM=$(oci mysql db-system create \
  --compartment-id $OCI_COMPARTMENT_ID \
  --db-name heron_test_db \
  --admin-username admin \
  --admin-password "HeronisFree2024!" \
  --shape-name "MySQL.VM.Standard.E3.1.1GU" \
  --mysql-version 8.0 \
  --display-name heron-test-db-system \
  --query 'data.id' --raw-output)
echo "   Database System: $DB_SYSTEM"

# 3. Create Object Storage bucket (20GB free per month)
echo "📍 Creating Object Storage bucket..."
BUCKET_NAME="heron-test-bucket-$(date +%s)"
oci os bucket create \
  --compartment-id $OCI_COMPARTMENT_ID \
  --name $BUCKET_NAME \
  --region $OCI_REGION
echo "   Bucket: $BUCKET_NAME"

# 4. Create Block Volume (100GB free)
echo "📍 Creating Block Volume..."
VOLUME=$(oci bv volume create \
  --availability-domain "$(oci iam availability-domain list --compartment-id $OCI_COMPARTMENT_ID --query 'data[0]."name"' --raw-output)" \
  --compartment-id $OCI_COMPARTMENT_ID \
  --display-name heron-test-volume \
  --size-in-gbs 50 \
  --query 'data.id' --raw-output)
echo "   Volume: $VOLUME"

echo ""
echo "✅ OCI permanent free tier resources created!"
echo ""
echo "Resources created:"
echo "  Compute: $INSTANCE_ID (VM.Standard.E2.1.Micro - always free)"
echo "  Database: $DB_SYSTEM (MySQL - always free)"
echo "  Storage: $BUCKET_NAME (20GB/month free)"
echo "  Block Volume: $VOLUME (100GB free)"
echo ""
echo "To use with Heron, add to .env:"
echo "  OCI_REGION=$OCI_REGION"
echo "  OCI_COMPARTMENT_ID=$OCI_COMPARTMENT_ID"
