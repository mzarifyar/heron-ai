# Heron on OCI — 30-Minute Setup Guide

Deploy Heron to Oracle Cloud's **always-free** Ampere A1 instance:
- **4 ARM cores** (aarch64)
- **24 GB RAM**
- **200 GB boot volume**
- **Never expires**

---

## Prerequisites (5 min)

### 1. OCI Account
Create a free account at [cloud.oracle.com](https://cloud.oracle.com/free) if you don't have one.

### 2. OCI CLI
```bash
brew install oci-cli          # macOS
oci setup config              # follow prompts — creates ~/.oci/config
```

Test it works:
```bash
oci iam region list
```

### 3. SSH key pair
```bash
ls ~/.ssh/id_rsa.pub   # use existing, or:
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa
```

### 4. Compartment OCID
In the OCI Console: **Identity → Compartments** → copy the root compartment OCID.

---

## Deploy (15 min)

### Run the deploy script

```bash
export OCI_COMPARTMENT_ID=ocid1.compartment.oc1..aaaa...
export OCI_REGION=us-ashburn-1    # or your preferred region

bash scripts/oci/deploy.sh
```

The script:
1. Finds the latest Ubuntu 22.04 ARM64 image
2. Creates VCN + subnet + security list (ports 22, 80, 443, 8080)
3. Launches a `VM.Standard.A1.Flex` instance (4 OCPUs, 24GB)
4. Opens ports in the security list
5. Installs Docker + Docker Compose on the VM
6. Syncs your repo + `.env` to the VM
7. Builds the ARM64 Docker image and starts Heron
8. Creates a systemd service for auto-restart on reboot

At the end you'll see:
```
✅  Heron deployed to OCI Ampere A1
   Public IP:   xxx.xxx.xxx.xxx
   Dashboard:   http://xxx.xxx.xxx.xxx:8080
```

### Verify it's running
```bash
curl http://YOUR_PUBLIC_IP:8080/api/v1/health
# {"status": "ok", ...}
```

Open `http://YOUR_PUBLIC_IP:8080` in your browser — the Heron dashboard.

---

## SSL / Custom Domain (5 min)

### 1. Point DNS to your instance
In your DNS provider, create an A record:
```
heron.yourcompany.com  →  YOUR_PUBLIC_IP
```

### 2. Update nginx config
```bash
ssh ubuntu@YOUR_PUBLIC_IP
cd heron
sed -i 's/YOUR_DOMAIN/heron.yourcompany.com/g' scripts/oci/nginx.conf
```

### 3. Get Let's Encrypt certificate
```bash
sudo certbot certonly --standalone \
  -d heron.yourcompany.com \
  --email your@email.com \
  --agree-tos --non-interactive
```

### 4. Start nginx
```bash
docker compose -f docker-compose.oci.yml up -d nginx
```

Access Heron at `https://heron.yourcompany.com`.

---

## Configure Integrations (5 min)

Edit `.env` on the VM and restart:

```bash
ssh ubuntu@YOUR_PUBLIC_IP
cd heron
nano .env       # or vi .env
```

Minimum to activate the full loop:

```bash
# AI (Decide step + Intelligence page)
HERON_AI_PROVIDER=anthropic
HERON_AI_API_KEY=sk-ant-...

# Slack notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
CORTEX_ENV=prod

# Slack bot (if using /heron commands)
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
```

Update Slack slash command URLs to `https://heron.yourcompany.com/slack/commands` and interactivity URL to `https://heron.yourcompany.com/slack/interactive`.

Restart:
```bash
docker compose -f docker-compose.oci.yml restart heron
```

### Enable live Slack escalation
```bash
# In config/policy.yaml on the VM:
nano config/policy.yaml
```
Set `escalation_channels.slack.live.prod: true`.

---

## OCI Monitoring (optional)

With the VM running, OCI Instance Principals authenticate automatically — no static keys needed.

Enable CloudWatch-equivalent (OCI Monitoring) alert ingestion:
```bash
# config/pullers.yaml
sources:
  prometheus:
    enabled: true          # if Prometheus is in your environment
```

For the Discovery page to scan your OCI account:
```bash
OCI_COMPARTMENT_ID=ocid1.compartment.oc1...
# OCI_REGION auto-detected from instance metadata
```

The Discovery page will use Instance Principal auth to scan EC2/RDS/EKS equivalents (Compute/ADB/OKE).

---

## Useful Commands

```bash
# SSH into the VM
ssh ubuntu@YOUR_PUBLIC_IP

# View Heron logs
cd heron
docker compose -f docker-compose.oci.yml logs -f heron

# Restart Heron
docker compose -f docker-compose.oci.yml restart heron

# Update to latest code
git pull
docker compose -f docker-compose.oci.yml build heron
docker compose -f docker-compose.oci.yml up -d heron

# Check status
docker compose -f docker-compose.oci.yml ps

# Full restart (all services)
docker compose -f docker-compose.oci.yml down
docker compose -f docker-compose.oci.yml up -d
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Deploy script fails at VCN creation | You may already have a VCN — the script will use it |
| SSH connection refused | Wait another 30s after launch, then retry |
| Ampere A1 capacity unavailable | Try another region (`eu-frankfurt-1`, `uk-london-1`, `ap-sydney-1`) |
| `docker: permission denied` | Log out and back in (group membership refresh) |
| Port 8080 not reachable | Check OCI Security List — TCP ingress on 8080 must be open |
| OCI API errors | Run `oci setup repair-file-permissions` |

### Check OCI API connectivity from VM
```bash
# On the VM — tests Instance Principal auth
curl -H "Authorization: Bearer $(curl -s http://169.254.169.254/opc/v2/identity/token/...)" \
  https://monitoring.us-ashburn-1.oraclecloud.com/...
```

Or simpler — the Discovery page → select OCI → scan will confirm if Instance Principals work.

---

## Architecture on OCI

```
Internet
    │
    ▼
OCI Load Balancer (optional) or
nginx container (port 80/443)
    │
    ▼
Heron container (port 8080)
    │ SQLite on /app/data (bind-mounted to VM disk)
    │ config/ bind-mounted (edit on VM, restart to apply)
    │
    ├── Signal ingest (Prometheus / OTLP / GitHub webhooks)
    ├── LLM Decide step (calls Anthropic API)
    ├── Slack bot (receives from Slack → responds)
    └── OCI Discovery (Instance Principals → scans OCI resources)
```

**Data persistence:** `data/` directory is bind-mounted from the VM — SQLite survives container restarts and redeploys. For production scale, replace SQLite with PostgreSQL (OCI Autonomous DB free tier).

---

## Cost

With the always-free tier:
- **Compute:** $0 (VM.Standard.A1.Flex, 4 OCPUs, 24GB RAM)
- **Storage:** $0 (100GB boot volume included)
- **Networking:** $0 (10TB outbound/month free)
- **Anthropic API:** ~$0.01–0.10/day depending on incident volume

Total: **$0/month** to run Heron on OCI with AI enabled.
