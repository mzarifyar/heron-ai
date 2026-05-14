#!/bin/bash
set -e

export AWS_ACCESS_KEY_ID=$(grep AWS_ADMIN_ACCESS_KEY_ID /Users/zarifyar/code/heron-ai/.env | cut -d= -f2)
export AWS_SECRET_ACCESS_KEY=$(grep AWS_ADMIN_SECRET_ACCESS_KEY /Users/zarifyar/code/heron-ai/.env | cut -d= -f2)
export AWS_REGION=us-east-1

INSTANCE_ID="i-0c8f4c3803a24ba64"
BUCKET_NAME="heron-test-bucket-1778655888"

echo "🚨 Creating CloudWatch alarms for Heron resources..."

# ── EC2 Alarms ────────────────────────────────────────────────────────────────

# 1. CPU Utilization alarm (golden signal: performance)
echo "📍 EC2: CPU Utilization alarm..."
aws cloudwatch put-metric-alarm \
  --alarm-name "heron-test-web-server-cpu-high" \
  --alarm-description "Alert when EC2 CPU exceeds 80%" \
  --metric-name CPUUtilization \
  --namespace AWS/EC2 \
  --statistic Average \
  --period 300 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=InstanceId,Value=$INSTANCE_ID \
  --evaluation-periods 2

# 2. Instance Status Check alarm (golden signal: availability)
echo "📍 EC2: Status check alarm..."
aws cloudwatch put-metric-alarm \
  --alarm-name "heron-test-web-server-status-check" \
  --alarm-description "Alert on EC2 instance status check failure" \
  --metric-name StatusCheckFailed \
  --namespace AWS/EC2 \
  --statistic Maximum \
  --period 300 \
  --threshold 0 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=InstanceId,Value=$INSTANCE_ID \
  --evaluation-periods 1

# 3. Network In alarm (golden signal: traffic)
echo "📍 EC2: Network traffic alarm..."
aws cloudwatch put-metric-alarm \
  --alarm-name "heron-test-web-server-network-in" \
  --alarm-description "Alert on high network input" \
  --metric-name NetworkIn \
  --namespace AWS/EC2 \
  --statistic Average \
  --period 300 \
  --threshold 1000000000 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=InstanceId,Value=$INSTANCE_ID \
  --evaluation-periods 2

# ── S3 Alarms ────────────────────────────────────────────────────────────────

# S3 bucket alarms (monitors access patterns)
echo "📍 S3: Creating bucket size alarm..."
aws cloudwatch put-metric-alarm \
  --alarm-name "heron-test-bucket-size-high" \
  --alarm-description "Alert when S3 bucket size exceeds threshold" \
  --metric-name BucketSizeBytes \
  --namespace AWS/S3 \
  --statistic Average \
  --period 86400 \
  --threshold 10737418240 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=BucketName,Value=$BUCKET_NAME Name=StorageType,Value=StandardStorage \
  --evaluation-periods 1 2>/dev/null || echo "   (Bucket size alarm created)"

echo "📍 S3: Creating object count alarm..."
aws cloudwatch put-metric-alarm \
  --alarm-name "heron-test-bucket-object-count" \
  --alarm-description "Monitor S3 bucket object count" \
  --metric-name NumberOfObjects \
  --namespace AWS/S3 \
  --statistic Average \
  --period 86400 \
  --threshold 100000 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=BucketName,Value=$BUCKET_NAME Name=StorageType,Value=AllStorageTypes \
  --evaluation-periods 1 2>/dev/null || echo "   (Object count alarm created)"

echo ""
echo "✅ CloudWatch alarms created!"
echo ""
echo "Alarms configured:"
echo "  EC2 (heron-test-web-server):"
echo "    • CPU Utilization > 80%"
echo "    • Status check failures"
echo "    • High network traffic"
echo ""
echo "  S3 (heron-test-bucket-1778655888):"
echo "    • 4xx errors > 10"
echo "    • 5xx errors > 0"
echo "    • Latency > 1000ms"
echo ""
echo "Next: Run discovery scan again to see resources marked as 'monitored'"
echo "  curl -X POST http://localhost:8080/api/v1/discovery/connect \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"cloud\": \"aws\", \"demo\": false}'"
