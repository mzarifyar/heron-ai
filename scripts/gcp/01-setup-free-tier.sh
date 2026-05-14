#!/bin/bash
set -e

# GCP Free Tier Setup ($300 credit for 90 days + always-free services)
# Prerequisites:
# 1. Create GCP account at https://console.cloud.google.com
# 2. Set GCP_PROJECT_ID to your project ID
# 3. Create service account with Compute Viewer, SQL Viewer, Kubernetes Viewer roles
# 4. Download service account JSON key to ~/.gcp/heron-sa-key.json

export GCP_PROJECT_ID=${GCP_PROJECT_ID:-"your-project-id"}
export GOOGLE_APPLICATION_CREDENTIALS=${GOOGLE_APPLICATION_CREDENTIALS:-"$HOME/.gcp/heron-sa-key.json"}

echo "🚀 Provisioning GCP free tier resources for Heron discovery..."

# 1. Create Compute Engine e2-micro instance (free tier eligible)
echo "📍 Creating Compute Engine e2-micro VM..."
gcloud compute instances create heron-test-web-server \
  --machine-type=e2-micro \
  --zone=us-central1-a \
  --project=$GCP_PROJECT_ID \
  --image-family=debian-11 \
  --image-project=debian-cloud \
  --tags=heron
echo "   Instance: heron-test-web-server"

# 2. Create Cloud SQL MySQL db-f1-micro (free tier eligible)
echo "📍 Creating Cloud SQL MySQL db-f1-micro..."
gcloud sql instances create heron-test-db \
  --database-version=MYSQL_8_0 \
  --tier=db-f1-micro \
  --region=us-central1 \
  --project=$GCP_PROJECT_ID
echo "   Instance: heron-test-db"

# 3. Create GCS bucket (5GB free per month)
echo "📍 Creating Cloud Storage bucket..."
BUCKET_NAME="heron-test-bucket-$(date +%s)"
gsutil mb -p $GCP_PROJECT_ID gs://$BUCKET_NAME
echo "   Bucket: $BUCKET_NAME"

echo ""
echo "✅ GCP free tier resources created!"
echo ""
echo "Resources created:"
echo "  Compute Engine: heron-test-web-server (e2-micro - always free)"
echo "  Cloud SQL: heron-test-db (db-f1-micro - $6.50/month shared, free tier credit covers)"
echo "  Cloud Storage: $BUCKET_NAME (5GB/month free)"
echo ""
echo "To use with Heron, add to .env:"
echo "  GCP_PROJECT_ID=$GCP_PROJECT_ID"
echo "  GOOGLE_APPLICATION_CREDENTIALS=$GOOGLE_APPLICATION_CREDENTIALS"
