# Cloud Discovery Setup Guide

Heron can automatically discover and monitor infrastructure across AWS, Google Cloud, Azure, and Oracle Cloud. This guide walks you through setting up each cloud provider.

**Last updated:** 2026-05-13  
**Status:** Production ready

---

## Quick Start: AWS (Recommended)

AWS has the most generous free tier. New accounts get:
- 12 months of free compute, database, storage
- 1 million API requests/month free
- No credit card required for most free tier services

### Step 1: Create AWS Account

1. Go to https://aws.amazon.com/free/
2. Click "Create a Free Account"
3. Enter email, password, AWS account name
4. Verify with email and phone number
5. Log in to AWS Console at https://console.aws.amazon.com

### Step 2: Create IAM User for Heron

1. Go to **IAM Console** → **Users** → **Create User**
2. Name: `heron-discovery` (or any name)
3. Click **Next**
4. **Set Permissions:**
   - Choose "Attach policies directly"
   - Search for and select: **`ReadOnlyAccess`** (or `ViewOnlyAccess` for stricter permissions)
   - Click **Next** → **Create User**

5. **Generate Access Key:**
   - Click the newly created user
   - Go to **Security credentials** tab
   - Click **Create access key**
   - Choose **Application running outside AWS**
   - Accept the warning, click **Next**
   - Note the **Access key ID** and **Secret access key** (never shown again)

### Step 3: Configure Heron

Add to `.env`:

```bash
# AWS Discovery
AWS_ACCESS_KEY_ID=AKIA...         # From step 2
AWS_SECRET_ACCESS_KEY=...         # From step 2
AWS_REGION=us-east-1              # or your preferred region
AWS_ACCOUNT_ID=123456789012       # Optional, for display purposes
```

### Step 4: Enable Discovery in Heron

Edit `config/pullers.yaml`:

```yaml
sources:
  discovery:
    enabled: true                 # Was: false
    interval_seconds: 300         # Rescan every 5 minutes (optional)
```

### Step 5: Restart Heron

```bash
make docker-restart
# or
docker-compose restart heron
```

### Step 6: Test Discovery

```bash
# Start a discovery scan
curl -X POST http://localhost:8080/api/v1/discovery/connect \
  -H "Content-Type: application/json" \
  -d '{"cloud": "aws", "demo": false}'

# Response: {"scan_id": "scan-12345", "status": "scanning"}
# Copy the scan_id
```

Check status:

```bash
curl http://localhost:8080/api/v1/discovery/status?scan_id=scan-12345
# Polls until: {"status": "completed", "resource_count": 42}
```

View results:

```bash
curl http://localhost:8080/api/v1/discovery/report?scan_id=scan-12345 | jq

# Returns:
# {
#   "cloud": "aws",
#   "scan_duration_seconds": 8.5,
#   "resources": [
#     {
#       "id": "i-0123456789abcdef0",
#       "name": "web-server-1",
#       "resource_type": "EC2_INSTANCE",
#       "region": "us-east-1",
#       "status": "monitored",      # or "partial", "unmonitored", "unknown"
#       "alarm_count": 3,
#       "monitoring_sources": ["cloudwatch"]
#     },
#     ...
#   ],
#   "monitored": 12,
#   "partial": 3,
#   "unmonitored": 7,
#   "unknown": 0
# }
```

**Status meanings:**
- **monitored** — Has CloudWatch alarms configured
- **partial** — Some monitoring in place (tags detected, but no alarms)
- **unmonitored** — No CloudWatch alarms or monitoring tags
- **unknown** — Status cannot be determined

---

## AWS Resources Discovered

Heron automatically discovers and monitors:

| Resource Type | Detection | Monitoring Check |
|---|---|---|
| EC2 instances | Enumerate running + stopped instances | CloudWatch alarms by name/tag |
| RDS databases | Enumerate RDS instances, clusters | CloudWatch alarms |
| EKS clusters | Enumerate cluster names | Check for kube-state-metrics exporter |
| Lambda functions | Enumerate functions by name | CloudWatch alarms + error rates |
| ALB/NLB load balancers | Enumerate by region | CloudWatch alarms |
| Auto Scaling Groups | Enumerate ASGs | CloudWatch alarms on scaling events |
| S3 buckets | Enumerate bucket names | Access logging status |

Each resource is tagged with:
- AWS region
- Resource ARN
- Service name (parsed from tags or resource name)
- Alarm count
- Monitoring status

---

## Demo Mode (No Credentials Needed)

Test the API without AWS credentials:

```bash
curl -X POST http://localhost:8080/api/v1/discovery/connect \
  -H "Content-Type: application/json" \
  -d '{"cloud": "aws", "demo": true}'
```

Returns 12 realistic demo AWS resources with active alarms, making it perfect for:
- Testing the dashboard
- Understanding the API response format
- Developing without a real AWS account
- Teaching and demos

---

## Activate Resources for Monitoring

Once you have a discovery report, activate resources:

```bash
curl -X POST http://localhost:8080/api/v1/discovery/activate \
  -H "Content-Type: application/json" \
  -d '{
    "scan_id": "scan-12345",
    "resources": [
      {
        "name": "prod-api-db",
        "resource_type": "RDS_DATABASE"
      },
      {
        "name": "us-east-1-web-server-1",
        "resource_type": "EC2_INSTANCE"
      }
    ]
  }'
```

This creates or updates monitoring configuration for these resources so Heron pulls their metrics and alerts continuously.

---

## Google Cloud (GCP)

GCP offers $300 free credit for 90 days plus always-free services.

### Setup

1. **Create GCP Project:**
   - Go to https://console.cloud.google.com
   - Click "Create Project" → enter name → create

2. **Enable APIs:**
   - Compute Engine API
   - Cloud SQL Admin API
   - Kubernetes Engine API
   - Cloud Functions API
   - Cloud Monitoring API

3. **Create Service Account:**
   - IAM & Admin → Service Accounts → Create Service Account
   - Name: `heron-discovery`
   - Grant roles: **Viewer** (or more specific: Compute Viewer, SQL Viewer, Kubernetes Engine Viewer)
   - Click on service account → Keys tab → Create key → JSON
   - Save the JSON file

4. **Configure Heron:**

```bash
# .env
GCP_PROJECT_ID=my-project-id          # From GCP Console
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
GCP_REGION=us-central1                # optional
```

5. **Enable Discovery:**

```yaml
# config/pullers.yaml
sources:
  discovery:
    enabled: true
```

6. **Restart and test:**

```bash
make docker-restart

curl -X POST http://localhost:8080/api/v1/discovery/connect \
  -H "Content-Type: application/json" \
  -d '{"cloud": "gcp", "demo": false}'
```

### GCP Resources Discovered

- Compute Engine instances
- Cloud SQL instances
- GKE clusters
- Cloud Functions
- Cloud Load Balancers
- Monitoring: Cloud Monitoring alerting policies

---

## Microsoft Azure

Azure offers $200 free credit for 30 days plus always-free services (12 months for new accounts).

### Setup

1. **Create Azure Account:**
   - Go to https://azure.microsoft.com/free/
   - Sign up with email → verify

2. **Create Service Principal:**

```bash
az login
az account list --output table  # Note subscription ID
az ad sp create-for-rbac \
  --name "heron-discovery" \
  --role "Reader" \
  --scopes "/subscriptions/<subscription-id>"

# Returns: appId, password, tenant
```

3. **Configure Heron:**

```bash
# .env
AZURE_SUBSCRIPTION_ID=...             # From az account list
AZURE_TENANT_ID=...                   # From sp create output
AZURE_CLIENT_ID=...                   # appId
AZURE_CLIENT_SECRET=...               # password
AZURE_RESOURCE_GROUP=...              # optional — scans all if unset
```

4. **Enable Discovery:**

```yaml
# config/pullers.yaml
sources:
  discovery:
    enabled: true
```

5. **Restart and test:**

```bash
make docker-restart

curl -X POST http://localhost:8080/api/v1/discovery/connect \
  -H "Content-Type: application/json" \
  -d '{"cloud": "azure", "demo": false}'
```

### Azure Resources Discovered

- Virtual Machines
- Azure SQL databases
- AKS clusters
- Load Balancers
- Function Apps
- App Service instances
- Monitoring: Azure Monitor metric alerts

---

## Oracle Cloud (OCI)

OCI has the **best permanent free tier** — you can keep resources running indefinitely without expiring free credits.

### Setup

1. **Create OCI Account:**
   - Go to https://www.oracle.com/cloud/free/
   - Sign up → verify email → create account

2. **Create API User:**
   - Top-right: User menu → My Profile
   - Click username → API keys → Add API key
   - Choose "Generate API Key Pair"
   - Download the private key (save securely)
   - Copy User OCID, Tenancy OCID

3. **Get Fingerprint:**

```bash
openssl rsa -pubout -outform DER -in private-key.pem | \
  openssl md5 -c | awk '{print $NF}' | tr -d ':'
```

4. **Configure Heron:**

```bash
# .env
OCI_TENANCY_OCID=ocid1.tenancy.oc1...    # From API key creation
OCI_USER_OCID=ocid1.user.oc1...          # From User Profile
OCI_FINGERPRINT=aa:bb:cc:dd...          # From step 3
OCI_KEY_FILE=/path/to/private-key.pem    # Absolute path
OCI_REGION=us-ashburn-1                  # Your home region
OCI_COMPARTMENT_ID=ocid1.compartment...  # Optional — defaults to root compartment
```

Alternatively, use **instance profiles** if running Heron on OCI Compute:

```bash
# Just set:
OCI_REGION=us-ashburn-1
# OCI SDK auto-detects instance credentials
```

5. **Enable Discovery:**

```yaml
# config/pullers.yaml
sources:
  discovery:
    enabled: true
```

6. **Restart and test:**

```bash
make docker-restart

curl -X POST http://localhost:8080/api/v1/discovery/connect \
  -H "Content-Type: application/json" \
  -d '{"cloud": "oci", "demo": false}'
```

### OCI Resources Discovered

- Compute instances
- Autonomous databases
- OKE (Kubernetes) clusters
- Load balancers
- Network resources (VCNs, subnets)
- Monitoring: OCI Monitoring alarms and metrics

---

## Running Multiple Clouds Simultaneously

Heron can monitor multiple clouds at once:

```bash
# AWS
curl -X POST http://localhost:8080/api/v1/discovery/connect \
  -H "Content-Type: application/json" \
  -d '{"cloud": "aws", "demo": false}'

# GCP in parallel
curl -X POST http://localhost:8080/api/v1/discovery/connect \
  -H "Content-Type: application/json" \
  -d '{"cloud": "gcp", "demo": false}'

# Both scan independently with separate scan IDs
```

Scans run in the background (single-threaded to prevent resource exhaustion). Check status for each:

```bash
curl http://localhost:8080/api/v1/discovery/status?scan_id=scan-aws-12345
curl http://localhost:8080/api/v1/discovery/status?scan_id=scan-gcp-67890
```

---

## API Reference

### Start Discovery Scan

**POST** `/api/v1/discovery/connect`

```json
{
  "cloud": "aws|gcp|azure|oci",
  "region": "us-east-1",           // optional region filter
  "demo": false                     // true for demo mode (no credentials needed)
}
```

Response:
```json
{
  "scan_id": "scan-uuid-123",
  "status": "scanning",
  "started_at": "2026-05-13T12:34:56Z"
}
```

### Check Scan Status

**GET** `/api/v1/discovery/status?scan_id=scan-uuid-123`

Response:
```json
{
  "scan_id": "scan-uuid-123",
  "status": "completed",            // or "scanning", "error"
  "resource_count": 42,
  "monitored_count": 28,
  "partial_count": 8,
  "unmonitored_count": 6,
  "error_message": null,
  "completed_at": "2026-05-13T12:35:04Z"
}
```

### Get Scan Report

**GET** `/api/v1/discovery/report?scan_id=scan-uuid-123`

Returns full resource list with details.

### Activate Resources

**POST** `/api/v1/discovery/activate`

```json
{
  "scan_id": "scan-uuid-123",
  "resources": [
    {
      "name": "prod-api-server",
      "resource_type": "EC2_INSTANCE"
    }
  ]
}
```

### Get Service Catalog

**GET** `/api/v1/discovery/catalog`

Returns merged catalog + customer overrides:
```json
{
  "webservers": [
    {
      "display_name": "Nginx",
      "default_ports": {"http": [80], "https": [443]},
      "metrics_exporter": {"type": "prometheus", "default_port": 9113}
    }
  ],
  "databases": [...],
  "monitoring": [...]
}
```

---

## Troubleshooting

### "scan_id not found"
The scan may have timed out or not started. Create a new scan:
```bash
curl -X POST http://localhost:8080/api/v1/discovery/connect \
  -H "Content-Type: application/json" \
  -d '{"cloud": "aws", "demo": false}'
```

### AWS: "AccessDenied: User is not authorized"
The IAM user credentials are invalid or the user doesn't have `ReadOnlyAccess`. Verify:
```bash
aws sts get-caller-identity --region us-east-1
# Should return user ARN
```

### GCP: "Error 403: The caller does not have permission"
Service account doesn't have required roles. Re-create with **Viewer** role.

### Azure: "AADSTS70001: Application not found"
Service principal wasn't created correctly. Re-run:
```bash
az ad sp create-for-rbac --name "heron-discovery" --role "Reader"
```

### OCI: "Invalid fingerprint format"
Fingerprint must be in format `aa:bb:cc:dd...`. Regenerate:
```bash
openssl rsa -pubout -outform DER -in private-key.pem | \
  openssl md5 -c | awk '{print $NF}' | tr -d ':'
# Convert to: aa:bb:cc:dd...
```

### Discovery runs but finds 0 resources
1. Check region is correct (`AWS_REGION`, `GCP_REGION`, etc.)
2. Verify credentials by running native CLI:
   - AWS: `aws ec2 describe-instances`
   - GCP: `gcloud compute instances list`
   - Azure: `az vm list`
   - OCI: `oci compute instance list`
3. Try demo mode first to verify the API works
4. Check Heron logs: `make docker-logs | grep discovery`

### Scan is stuck on "scanning"
Scans timeout after 300 seconds. Check logs for errors:
```bash
make docker-logs | grep -i discovery
```

---

## Best Practices

1. **Start with demo mode** to understand the API before using real credentials
2. **Use read-only credentials** (Viewer/ReadOnly role) — Heron only needs to read resources
3. **Rescan periodically** — Set `interval_seconds` in `config/pullers.yaml`
4. **Filter by region** — Reduces scan time and costs
5. **Activate selectively** — Only enable monitoring for resources you care about
6. **Monitor scan duration** — Track how long scans take to optimize frequency

---

## Cost Implications

**AWS:**
- Discovery scans are free (API calls are within free tier)
- CloudWatch queries are free

**GCP:**
- Within $300 credit or always-free tier
- Cloud Monitoring queries are free for up to 150MB/month

**Azure:**
- Within $200 credit or always-free tier
- Azure Monitor queries are free

**OCI:**
- Completely free on Always Free tier
- No cost limits

---

## Next Steps

1. Set up your preferred cloud
2. Test demo mode first
3. Configure real credentials
4. Enable discovery in pullers.yaml
5. Start first scan and verify results
6. Activate resources you want to monitor

---

**Questions?** Check `IMPLEMENTATIONS_GUIDE.md` for integration details or open an issue.
