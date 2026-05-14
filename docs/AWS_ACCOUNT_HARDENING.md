# AWS Account Hardening Guide

Essential security hardening for your AWS account before production use.

**Status:** Critical before production  
**Estimated time:** 30-45 minutes  
**Account ID:** 810738286426

---

## Priority 1: Immediate (Do This First)

### 1.1 Secure Root Account

**What:** The root account has complete access and can't be restricted. Lock it down.

**Steps:**

1. **Enable MFA on root account:**
   - Go to AWS Console → Account → Security Credentials
   - Scroll to "Multi-factor authentication (MFA)"
   - Click "Activate MFA"
   - Choose: **Authenticator app** (or security key) — NOT SMS
   - Scan QR code with Google Authenticator, Authy, or Microsoft Authenticator
   - Save backup codes somewhere safe (not in AWS)

2. **Create strong root password:**
   - Already done when you created account
   - Use AWS password manager or 1Password to store it
   - Never share or use in applications

3. **Disable root account from normal use:**
   - Only use for:
     - Account recovery
     - Billing changes
     - Root-only operations (account closure, organization setup)
   - Never use for day-to-day work

**Verification:**
```bash
# Root should have MFA enabled
# Check: Account → Security Credentials → Multifactor authentication (MFA)
```

### 1.2 Fix IAM User Permissions (Heron Discovery)

**What:** Currently `heron-discovery` has `ReadOnlyAccess` (too broad). Restrict to only what it needs.

**Current issue:**
- `ReadOnlyAccess` = read ALL AWS services
- Heron only needs: EC2, RDS, EKS, Lambda, CloudWatch

**Steps:**

1. **Create a custom policy for Heron:**
   - IAM Console → Policies → Create Policy
   - **Policy name:** `HeroniDiscoveryReadOnly`
   - **JSON editor:** Use this policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2ReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "ec2:Get*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "RDSReadOnly",
      "Effect": "Allow",
      "Action": [
        "rds:Describe*",
        "rds:List*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "EKSReadOnly",
      "Effect": "Allow",
      "Action": [
        "eks:Describe*",
        "eks:List*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "LambdaReadOnly",
      "Effect": "Allow",
      "Action": [
        "lambda:List*",
        "lambda:Get*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchReadOnly",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:Describe*",
        "cloudwatch:Get*",
        "cloudwatch:List*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchLogsReadOnly",
      "Effect": "Allow",
      "Action": [
        "logs:Describe*",
        "logs:Get*",
        "logs:List*"
      ],
      "Resource": "*"
    }
  ]
}
```

2. **Attach to heron-discovery user:**
   - IAM Console → Users → heron-discovery
   - Permissions tab
   - Remove `ReadOnlyAccess`
   - Add `HeroniDiscoveryReadOnly` (your new policy)

3. **Test it works:**
   ```bash
   # Heron should still discover resources
   curl -X POST http://localhost:8080/api/v1/discovery/connect \
     -H "Content-Type: application/json" \
     -d '{"cloud": "aws", "demo": false}'
   ```

**Verification:**
```bash
# Check heron-discovery has minimal permissions
# IAM → Users → heron-discovery → Permissions
```

---

## Priority 2: High (Do This Before Production)

### 2.1 Enable CloudTrail (Audit Logging)

**What:** Log all API calls for security auditing.

**Steps:**

1. **Enable CloudTrail:**
   - CloudTrail Console → Create trail
   - **Trail name:** `heron-account-audit`
   - **Apply trail to all AWS Regions:** ✅ Yes
   - **Data events:** ✅ Log all S3 data events + Lambda invocations
   - **Create S3 bucket:** `heron-account-audit-logs-810738286426` (unique name)
   - **CloudWatch Logs:** ✅ Enable

2. **Protect the audit logs:**
   - S3 bucket that stores logs → Block all public access
   - Enable versioning
   - Enable server-side encryption

**Verification:**
```bash
# CloudTrail should show recent API calls
# CloudTrail Console → Event History
```

### 2.2 Enable AWS Config (Configuration Tracking)

**What:** Tracks configuration changes and detects non-compliance.

**Steps:**

1. **Enable AWS Config:**
   - AWS Config Console → Get started
   - **All resources:** ✅ Yes
   - **Include global resources:** ✅ Yes
   - **Create S3 bucket:** `heron-config-bucket-810738286426`
   - **Enable CloudTrail integration:** ✅ Yes

2. **Set up compliance rules:**
   - Rules → Add rule
   - Pre-built rules to add:
     - `iam-mfa-enabled-for-iam-console-access`
     - `root-account-mfa-enabled`
     - `ec2-security-group-ssh-restriction` (if using SSH)
     - `encrypted-volumes`
     - `rds-encryption-enabled`

**Verification:**
```bash
# AWS Config should show compliance status
# AWS Config Console → Rules
```

### 2.3 Enable Billing Alerts

**What:** Get notified if spending exceeds threshold.

**Steps:**

1. **Enable cost anomaly detection:**
   - Billing & Cost Management Console → Billing Preferences
   - ✅ "Receive Billing Alerts"
   - Set alert threshold: **$5** (free tier limit buffer)

2. **Create CloudWatch alarm:**
   - CloudWatch → Alarms → Create alarm
   - Metric: `EstimatedCharges`
   - Threshold: **$10**
   - Action: Send email (to yourself)

**Why:** Free tier is ~$750/month worth of services. But accidental usage (data transfer, NAT gateway, etc.) can quickly exceed that.

**Verification:**
```bash
# Check alerts are enabled
# Billing Console → Billing Preferences
# CloudWatch → Alarms
```

### 2.4 Secure API Keys (heron-discovery)

**What:** Rotate keys regularly and monitor usage.

**Steps:**

1. **Set up key rotation schedule:**
   - Every 90 days: generate new key, update Heron, delete old key
   - Add calendar reminder now

2. **Monitor key usage:**
   - CloudTrail → Event history
   - Filter by: User `heron-discovery`
   - Should only see EC2/RDS/EKS/Lambda/CloudWatch calls
   - Alert if you see unexpected API calls

3. **Store keys securely:**
   - ✅ Currently in `.env` (acceptable for dev)
   - Before production: use AWS Secrets Manager
   ```bash
   aws secretsmanager create-secret \
     --name heron/aws-discovery \
     --secret-string '{"access_key_id":"AKIA...","secret_access_key":"..."}'
   ```

---

## Priority 3: Medium (Before Production Use)

### 3.1 Set Up VPC & Security Groups

**What:** Network isolation if you run Heron on EC2.

**Steps:**

1. **Create VPC for Heron:**
   - VPC Console → Create VPC
   - **VPC name:** `heron-vpc`
   - **CIDR block:** `10.0.0.0/16`

2. **Create subnets:**
   - **Public subnet:** `10.0.1.0/24` (for ALB)
   - **Private subnet:** `10.0.10.0/24` (for Heron app)

3. **Create security groups:**
   - **ALB security group:**
     - Inbound: HTTP 80 (0.0.0.0/0), HTTPS 443 (0.0.0.0/0)
     - Outbound: All traffic
   - **Heron app security group:**
     - Inbound: Port 8080 from ALB security group only
     - Outbound: All traffic (for API calls)

4. **Create NAT Gateway:**
   - For private subnet to reach AWS APIs
   - Attach to public subnet

### 3.2 Enable VPC Flow Logs

**What:** Log all network traffic for security analysis.

**Steps:**

1. **Enable for each VPC:**
   - VPC Console → VPC → Flow logs
   - **Destination:** CloudWatch Logs
   - **Log group:** `heron-vpc-flows`

### 3.3 Set Up Encryption

**What:** Encrypt data at rest and in transit.

**Checklist:**
- ✅ EBS volumes: Enable encryption by default
  - EC2 Console → Settings → EBS encryption
  - ✅ "Enable"
- ✅ RDS: Require encryption
  - RDS Console → Security Groups
  - Require SSL/TLS connections
- ✅ S3 buckets: Enable default encryption
  - S3 Console → Bucket properties → Default encryption
  - AES-256 or KMS

---

## Priority 4: Low (Nice to Have)

### 4.1 Enable GuardDuty

**What:** AI-powered threat detection.

**Steps:**
1. GuardDuty Console → Enable GuardDuty
2. Review findings monthly

### 4.2 Set Up Trusted Advisor

**What:** AWS best practices scanner.

**Steps:**
1. Support Plans → AWS Support Plan (requires Business/Enterprise)
2. OR: Use free Trusted Advisor checks (available to all)

### 4.3 Create AWS SSO (if team grows)

**What:** Centralized identity for team members.

**For now:** Keep minimal IAM users (just `heron-discovery`)

---

## Security Checklist

Before production, verify:

- [ ] Root account has MFA enabled
- [ ] Root account password stored securely (not in code)
- [ ] `heron-discovery` has minimal permissions (custom policy, not ReadOnlyAccess)
- [ ] CloudTrail enabled and logging to S3
- [ ] AWS Config enabled with compliance rules
- [ ] Billing alerts set ($5 threshold)
- [ ] API key rotation schedule set (every 90 days)
- [ ] VPC created with security groups (if running on EC2)
- [ ] Encryption enabled for EBS, RDS, S3
- [ ] VPC Flow Logs enabled
- [ ] No secrets in `.env` file committed to Git

---

## Cost Implications

**Free tier covers:**
- CloudTrail (first 100,000 API calls/month)
- AWS Config (free tier available)
- VPC (no charge)
- Security Groups (no charge)
- GuardDuty (first 30 days free)

**Will charge (minimal):**
- S3 storage for logs (~$1-5/month)
- CloudWatch Logs (~$1-3/month)
- NAT Gateway ($32/month if used 24/7)

**Total estimated cost:** $5-10/month for full hardening

---

## Ongoing Security

**Monthly (1st of month):**
- Review CloudTrail for unauthorized API calls
- Check AWS Config compliance rules

**Quarterly (every 90 days):**
- Rotate `heron-discovery` API keys
- Review IAM permissions
- Check billing anomalies

**Annually:**
- Security audit
- Update security policies
- Review all IAM users

---

## Emergency Procedures

**If API key is compromised:**
1. Immediately delete the key in IAM Console
2. Generate a new key
3. Update `.env` in Heron
4. Review CloudTrail for unauthorized access
5. Rotate all other keys

**If account is breached:**
1. Contact AWS Support immediately
2. Check root account access
3. Review all IAM users
4. Check for unexpected resources (EC2, Lambda, etc.)
5. Review billing for unauthorized charges

---

## Resources

- [AWS Well-Architected Security Pillar](https://docs.aws.amazon.com/waf/latest/developerguide/aws-waf-chapter.html)
- [AWS Security Best Practices](https://aws.amazon.com/security/best-practices/)
- [IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [CloudTrail User Guide](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/)

---

**Next Steps:**
1. Implement Priority 1 (immediate) - 10 min
2. Implement Priority 2 (high) - 20 min
3. Test Heron still works after changes
4. Document any custom policies in your repo

