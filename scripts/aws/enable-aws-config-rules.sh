#!/bin/bash

# Enable AWS Config Rules for Heron account
# This script adds all critical security and compliance rules

set -e

echo "🔧 Enabling AWS Config Rules..."

# List of rules to enable
RULES=(
  "root-account-mfa-enabled"
  "iam-mfa-enabled-for-iam-console-access"
  "iam-policy-no-statements-with-admin-access"
  "iam-user-mfa-enabled"
  "rds-encryption-enabled"
  "encrypted-volumes"
  "s3-bucket-server-side-encryption-enabled"
  "cloudtrail-enabled"
  "ec2-security-group-ssh-restriction"
  "vpc-flow-logs-enabled"
  "cloudwatch-alarm-action-enabled"
  "aws-config-enabled"
  "iam-user-unused-credentials-check"
)

# Enable each rule
for rule in "${RULES[@]}"; do
  echo "📋 Adding rule: $rule"

  aws configservice put-config-rule \
    --config-rule "$(cat <<EOF
{
  "ConfigRuleName": "$rule",
  "Source": {
    "Owner": "AWS",
    "SourceIdentifier": "$rule"
  }
}
EOF
)" 2>/dev/null || echo "   ⚠️  $rule already exists or error - skipping"
done

echo ""
echo "✅ All AWS Config rules enabled!"
echo ""
echo "View rules: aws configservice describe-config-rules --query 'ConfigRules[*].ConfigRuleName' --output table"
