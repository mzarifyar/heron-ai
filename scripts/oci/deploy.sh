#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Heron OCI Ampere A1 deploy script
# Runs FROM YOUR LAPTOP — provisions the VM and configures it end-to-end.
#
# Prerequisites:
#   1. OCI CLI installed and configured:  brew install oci-cli && oci setup config
#   2. SSH key pair in ~/.ssh/  (default: id_rsa / id_rsa.pub)
#   3. OCI_COMPARTMENT_ID exported (root compartment OCID)
#   4. .env file in the repo root with all required vars
#
# Usage:
#   export OCI_COMPARTMENT_ID=ocid1.compartment.oc1..aaaa...
#   bash scripts/oci/deploy.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REGION=${OCI_REGION:-us-ashburn-1}
COMPARTMENT=${OCI_COMPARTMENT_ID:?"OCI_COMPARTMENT_ID must be set"}
SHAPE=VM.Standard.A1.Flex      # 4 OCPUs, 24 GB RAM — always free
OCPUS=4
MEMORY_GB=24
SSH_KEY=${SSH_PUBLIC_KEY_FILE:-$HOME/.ssh/id_rsa.pub}
DISPLAY_NAME=heron-ai
OS_IMAGE="Canonical Ubuntu"     # Ubuntu 22.04 ARM64
OS_VERSION="22.04"

echo "═══════════════════════════════════════════════════════"
echo "  Heron → OCI Ampere A1 (always-free ARM64)"
echo "  Region:      $REGION"
echo "  Compartment: $COMPARTMENT"
echo "  Shape:       $SHAPE ($OCPUS OCPUs, ${MEMORY_GB}GB RAM)"
echo "═══════════════════════════════════════════════════════"

# ── 1. Find Ubuntu 22.04 ARM64 image ─────────────────────────────────────────
echo ""
echo "▶ Finding Ubuntu 22.04 ARM64 image..."
# List platform images from the tenancy (not compartment) — shape filter removed
IMAGE_ID=$(oci compute image list \
  --compartment-id "$COMPARTMENT" \
  --operating-system "$OS_IMAGE" \
  --operating-system-version "$OS_VERSION" \
  --sort-by TIMECREATED \
  --sort-order DESC \
  --query 'data[0].id' \
  --raw-output)
echo "  Image: $IMAGE_ID"

# ── 2. Get first availability domain ─────────────────────────────────────────
AD=$(oci iam availability-domain list \
  --compartment-id "$COMPARTMENT" \
  --query 'data[0].name' \
  --raw-output)
echo "  Availability Domain: $AD"

# ── 3. Get or create VCN / subnet ────────────────────────────────────────────
echo ""
echo "▶ Getting default VCN..."
VCN_ID=$(oci network vcn list \
  --compartment-id "$COMPARTMENT" \
  --query 'data[0].id' \
  --raw-output 2>/dev/null || echo "")

if [ -z "$VCN_ID" ]; then
  echo "  Creating VCN..."
  VCN_ID=$(oci network vcn create \
    --compartment-id "$COMPARTMENT" \
    --cidr-block "10.0.0.0/16" \
    --display-name "heron-vcn" \
    --query 'data.id' \
    --raw-output)
  oci network internet-gateway create \
    --compartment-id "$COMPARTMENT" \
    --vcn-id "$VCN_ID" \
    --is-enabled true \
    --display-name "heron-igw" > /dev/null
fi
echo "  VCN: $VCN_ID"

SUBNET_ID=$(oci network subnet list \
  --compartment-id "$COMPARTMENT" \
  --vcn-id "$VCN_ID" \
  --query 'data[0].id' \
  --raw-output 2>/dev/null || echo "")

if [ -z "$SUBNET_ID" ]; then
  echo "  Creating subnet..."
  RT_ID=$(oci network route-table list \
    --compartment-id "$COMPARTMENT" \
    --vcn-id "$VCN_ID" \
    --query 'data[0].id' --raw-output)
  IGW_ID=$(oci network internet-gateway list \
    --compartment-id "$COMPARTMENT" \
    --vcn-id "$VCN_ID" \
    --query 'data[0].id' --raw-output)
  oci network route-table update \
    --rt-id "$RT_ID" \
    --route-rules "[{\"cidrBlock\":\"0.0.0.0/0\",\"networkEntityId\":\"$IGW_ID\"}]" \
    --force > /dev/null
  SUBNET_ID=$(oci network subnet create \
    --compartment-id "$COMPARTMENT" \
    --vcn-id "$VCN_ID" \
    --cidr-block "10.0.0.0/24" \
    --display-name "heron-subnet" \
    --availability-domain "$AD" \
    --query 'data.id' \
    --raw-output)
fi
echo "  Subnet: $SUBNET_ID"

# ── 4. Open ports 22, 80, 443, 8080 in security list ─────────────────────────
echo ""
echo "▶ Configuring security list (ports 22, 80, 443, 8080)..."
SL_ID=$(oci network security-list list \
  --compartment-id "$COMPARTMENT" \
  --vcn-id "$VCN_ID" \
  --query 'data[0].id' \
  --raw-output)

oci network security-list update \
  --security-list-id "$SL_ID" \
  --ingress-security-rules '[
    {"source":"0.0.0.0/0","protocol":"6","tcpOptions":{"destinationPortRange":{"min":22,"max":22}},"isStateless":false},
    {"source":"0.0.0.0/0","protocol":"6","tcpOptions":{"destinationPortRange":{"min":80,"max":80}},"isStateless":false},
    {"source":"0.0.0.0/0","protocol":"6","tcpOptions":{"destinationPortRange":{"min":443,"max":443}},"isStateless":false},
    {"source":"0.0.0.0/0","protocol":"6","tcpOptions":{"destinationPortRange":{"min":8080,"max":8080}},"isStateless":false}
  ]' \
  --force > /dev/null
echo "  Ports open: 22 (SSH), 80 (HTTP), 443 (HTTPS), 8080 (direct)"

# ── 5. Launch Ampere A1 instance ─────────────────────────────────────────────
echo ""
echo "▶ Launching Ampere A1 instance ($SHAPE)..."
INSTANCE_ID=$(oci compute instance launch \
  --availability-domain "$AD" \
  --compartment-id "$COMPARTMENT" \
  --image-id "$IMAGE_ID" \
  --shape "$SHAPE" \
  --shape-config "{\"ocpus\":$OCPUS,\"memoryInGBs\":$MEMORY_GB}" \
  --subnet-id "$SUBNET_ID" \
  --display-name "$DISPLAY_NAME" \
  --assign-public-ip true \
  --ssh-authorized-keys-file "$SSH_KEY" \
  --boot-volume-size-in-gbs 100 \
  --query 'data.id' \
  --raw-output)
echo "  Instance ID: $INSTANCE_ID"

# ── 6. Wait for instance to be RUNNING ───────────────────────────────────────
echo ""
echo "▶ Waiting for instance to start (this takes ~2 minutes)..."
for i in $(seq 1 24); do
  STATE=$(oci compute instance get \
    --instance-id "$INSTANCE_ID" \
    --query 'data."lifecycle-state"' \
    --raw-output)
  echo "  State: $STATE (attempt $i/24)"
  if [ "$STATE" = "RUNNING" ]; then break; fi
  sleep 10
done

PUBLIC_IP=$(oci compute instance list-vnics \
  --instance-id "$INSTANCE_ID" \
  --query 'data[0]."public-ip"' \
  --raw-output)
echo "  Public IP: $PUBLIC_IP"

# ── 7. Attach IAM Instance Principal policy ───────────────────────────────────
echo ""
echo "▶ Attaching Instance Principal IAM policy..."
echo "  NOTE: If this fails, create the policy manually in OCI IAM:"
echo "  Allow dynamic-group heron-instances to use metrics in compartment $COMPARTMENT"
echo "  Allow dynamic-group heron-instances to manage objects in compartment $COMPARTMENT"

# Create dynamic group for this instance
oci iam dynamic-group create \
  --compartment-id "$COMPARTMENT" \
  --name "heron-instances" \
  --description "Heron AI instance principals" \
  --matching-rule "Any {instance.id = '$INSTANCE_ID'}" 2>/dev/null || \
  echo "  Dynamic group may already exist — continuing"

# ── 8. Bootstrap the VM via SSH ───────────────────────────────────────────────
echo ""
echo "▶ Waiting for SSH to become available..."
sleep 30
for i in $(seq 1 12); do
  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "ubuntu@$PUBLIC_IP" "echo ok" 2>/dev/null && break
  echo "  SSH not ready yet ($i/12)..."
  sleep 10
done

echo ""
echo "▶ Installing Docker + Docker Compose on VM..."
ssh -o StrictHostKeyChecking=no "ubuntu@$PUBLIC_IP" << 'REMOTE'
set -e
# Update and install deps
sudo apt-get update -q
sudo apt-get install -y -q ca-certificates curl gnupg git nginx certbot python3-certbot-nginx

# Docker
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update -q
sudo apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Allow ubuntu user to run docker without sudo
sudo usermod -aG docker ubuntu
echo "Docker installed: $(docker --version)"
echo "Compose installed: $(docker compose version)"
REMOTE

# ── 9. Copy repo and .env to VM ───────────────────────────────────────────────
echo ""
echo "▶ Syncing repo to VM..."
REPO_ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
rsync -az --exclude '.git' --exclude 'node_modules' --exclude '__pycache__' \
  --exclude 'frontend/dist' --exclude 'data/*.db' \
  "$REPO_ROOT/" "ubuntu@$PUBLIC_IP:/home/ubuntu/heron/"
echo "  Repo synced"

# Copy .env if it exists
if [ -f "$REPO_ROOT/.env" ]; then
  scp "$REPO_ROOT/.env" "ubuntu@$PUBLIC_IP:/home/ubuntu/heron/.env"
  echo "  .env copied"
else
  echo "  ⚠ No .env found — copy it manually before starting"
fi

# ── 10. Build and start Heron on the VM ──────────────────────────────────────
echo ""
echo "▶ Building and starting Heron..."
ssh "ubuntu@$PUBLIC_IP" << 'REMOTE'
set -e
cd /home/ubuntu/heron
# Build ARM64 image
docker compose -f docker-compose.oci.yml build
# Start (without SSL profile — add domain + cert first)
docker compose -f docker-compose.oci.yml up -d heron
echo "Heron started"
docker compose -f docker-compose.oci.yml ps
REMOTE

# ── 11. Create systemd service for auto-restart on reboot ────────────────────
echo ""
echo "▶ Creating systemd service..."
ssh "ubuntu@$PUBLIC_IP" << 'REMOTE'
sudo tee /etc/systemd/system/heron.service > /dev/null << 'UNIT'
[Unit]
Description=Heron AI
After=docker.service
Requires=docker.service

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/heron
ExecStart=/usr/bin/docker compose -f docker-compose.oci.yml up
ExecStop=/usr/bin/docker compose -f docker-compose.oci.yml down
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable heron
echo "Systemd service enabled"
REMOTE

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✅  Heron deployed to OCI Ampere A1"
echo ""
echo "  Public IP:   $PUBLIC_IP"
echo "  Dashboard:   http://$PUBLIC_IP:8080"
echo "  Health:      http://$PUBLIC_IP:8080/api/v1/health"
echo "  Instance:    $INSTANCE_ID"
echo ""
echo "  Next steps:"
echo "  1. Point your domain DNS → $PUBLIC_IP"
echo "  2. Update scripts/oci/nginx.conf with YOUR_DOMAIN"
echo "  3. Run certbot for SSL:"
echo "     ssh ubuntu@$PUBLIC_IP"
echo "     cd heron && sudo certbot --nginx -d YOUR_DOMAIN"
echo "     docker compose -f docker-compose.oci.yml up -d nginx certbot"
echo "  4. Set SLACK_WEBHOOK_URL + HERON_AI_API_KEY in .env and restart:"
echo "     docker compose -f docker-compose.oci.yml restart heron"
echo "═══════════════════════════════════════════════════════"
