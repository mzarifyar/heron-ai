# OCI Account — Todo List

## Status: Waiting for provisioning email from Oracle

---

## When the email arrives

1. **Verify account is ready**
   ```bash
   oci iam user list --all
   ```
   Should return your users. If it does, proceed.

2. **Run the deploy**
   ```bash
   export OCI_COMPARTMENT_ID=ocid1.tenancy.oc1..aaaaaaaahcgttqyay2qjtdj3pz7vuwgjjkysyamsij7an2er7m5c3snfazja
   export OCI_REGION=us-phoenix-1
   bash scripts/oci/deploy.sh
   ```

3. **After deploy — get the public IP and verify**
   ```bash
   curl http://PUBLIC_IP:8080/api/v1/health
   ```

4. **Point domain DNS → public IP**

5. **Get SSL cert**
   ```bash
   ssh ubuntu@PUBLIC_IP
   cd heron
   sudo certbot --nginx -d YOUR_DOMAIN
   docker compose -f docker-compose.oci.yml up -d nginx
   ```

6. **Update Slack bot URLs** to the new domain:
   - Slash command: `https://YOUR_DOMAIN/slack/commands`
   - Interactivity: `https://YOUR_DOMAIN/slack/interactive`

7. **Add production env vars** to `.env` on the VM:
   ```bash
   HERON_AI_PROVIDER=anthropic
   HERON_AI_API_KEY=sk-ant-...
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
   HERON_ENV=prod
   ```

## Notes
- Home region: `us-phoenix-1` (not ashburn)
- CLI config: `~/.oci/config` with unencrypted key
- Full setup guide: `docs/setup-oci.md`
