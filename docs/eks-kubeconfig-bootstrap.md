# EKS Kubeconfig Bootstrap Guide (AWS + `update_kubeconfig.sh`)

This runbook explains how to bootstrap EKS kubeconfigs from scratch when you start with no usable `~/.kube/config.<cluster>` files.

It is designed for new on-call engineers and follows the AWS-first approach we validated in production-like usage.

## Goal

Generate kubeconfigs only for real, active clusters, then create local files via:

- `/Users/$USER/code/bots-terraform/scripts/update_kubeconfig.sh`

We intentionally avoid generating commands from stale naming data alone.

## Prerequisites

1. AWS CLI is installed.
2. `jq` is installed.
3. You can browser-login for AWS security token auth.
4. `bots-terraform` is present at:
   `/Users/$USER/code/bots-terraform`
5. AWS profile exists in `~/.aws/config` (example: `aws1.ssh`).

## Important Notes

1. Always pass `--auth security_token` for AWS calls in this workflow.
2. `ce cluster list --account-id` requires a **account AWSID**, not account AWSID.
3. `update_kubeconfig.sh` can skip clusters due to script guardrails (env/region support), even when clusters are active in AWS.
4. Run bootstrap commands in small batches (5-10) to keep troubleshooting simple.

## Phase 1: Session and Base Context

```bash
export PROFILE="aws1.ssh"
export AUTH="security_token"
export WORKDIR="$HOME/code/cortex-AI/data/aws_truth"
mkdir -p "$WORKDIR"

aws --profile "$PROFILE" session validate --local
```

If invalid, authenticate:

```bash
aws session authenticate --profile-name "$PROFILE" --region us-ashburn-1 --account-name aws_operator_access --auth security_token
```

Resolve account from profile block:

```bash
export account_ID="$(awk -F= -v p="[$PROFILE]" '
$0==p {in_profile=1; next}
in_profile && /^\[/ {in_profile=0}
in_profile && $1 ~ /^[[:space:]]*account[[:space:]]*$/ {
  gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2)
  print $2
  exit
}
' ~/.aws/config)"
echo "account_ID=$account_ID"
```

Resolve home region:

```bash
export HOME_REGION="$(aws --profile "$PROFILE" --auth "$AUTH" iam region-subscription list \
  --account-id "$account_ID" --all \
  --query 'data[?"is-home-region"==`true`]."region-name" | [0]' \
  --raw-output)"
echo "HOME_REGION=$HOME_REGION"
```

## Phase 2: Build Missing Cluster Input

From the current Cortex cluster access export:

```bash
jq -r '.entries[] | [.environment,.region,.cluster] | @tsv' \
  "$HOME/code/cortex-AI/data/kubeconfig_missing_clusters_filtered.json" \
  > "$WORKDIR/missing_clusters.tsv"
```

Build unique `(env,region)` pairs (performance optimization):

```bash
awk -F'\t' '{print $1 "\t" $2}' "$WORKDIR/missing_clusters.tsv" | sort -u > "$WORKDIR/missing_env_region.tsv"
```

## Phase 3: Get Account Mappings from `update_kubeconfig.sh`

Extract env->account mappings from script:

```bash
python3 - <<'PY'
import re, pathlib
script = pathlib.Path.home() / "code/bots-terraform/scripts/update_kubeconfig.sh"
text = script.read_text(errors="ignore").splitlines()
target = {"d1","dc","p0","pc","pd","s0"}
current_envs = []
rows = []
for line in text:
    m_env = re.match(r'^\s*([a-z0-9|]+)\s*\)\s*$', line)
    if m_env:
        current_envs = [e.strip() for e in m_env.group(1).split("|") if e.strip() in target]
        continue
    m_tid = re.search(r'_TENANT_ID\s*=\s*(awsid1\.account\.[a-z0-9.]+)', line)
    if m_tid and current_envs:
        tid = m_tid.group(1)
        for e in current_envs:
            rows.append((e, tid))
out = pathlib.Path.home() / "code/cortex-AI/data/aws_truth/env_account.tsv"
out.write_text("".join(f"{e}\t{tid}\n" for e, tid in sorted(set(rows))))
print(out)
PY
```

For AWS1-only bootstrap:

```bash
awk -F'\t' '$2 ~ /^awsid1\.account\.aws1\./ {print $0}' "$WORKDIR/env_account.tsv" > "$WORKDIR/env_account_oc1.tsv"
cat "$WORKDIR/env_account_oc1.tsv"
```

## Phase 4: Resolve Account awsids (`<env>-dp`, `<env>-cp`)

```bash
: > "$WORKDIR/oc1_accounts.tsv"
while IFS=$'\t' read -r ENV TID; do
  for SUF in dp cp; do
    CNAME="${ENV}-${SUF}"
    CID="$(aws --profile "$PROFILE" --auth "$AUTH" iam account list \
      --region "$HOME_REGION" \
      --account-id "$TID" \
      --account-id-in-subtree true \
      --access-level ACCESSIBLE \
      --all \
      --query "data[?name=='$CNAME'].id | [0]" \
      --raw-output)"
    echo -e "${ENV}\t${CNAME}\t${CID}" >> "$WORKDIR/oc1_accounts.tsv"
  done
done < "$WORKDIR/env_account_oc1.tsv"
```

## Phase 5: AWS Source-of-Truth Cluster Discovery (ACTIVE only)

```bash
: > "$WORKDIR/oc1_active_clusters.jsonl"
: > "$WORKDIR/oc1_active_errors.log"

while IFS=$'\t' read -r ENV REGION; do
  CROW="$(awk -F'\t' -v e="$ENV" '$1==e && $2==(e"-dp") {print $0; exit}' "$WORKDIR/oc1_accounts.tsv")"
  [ -z "$CROW" ] && continue
  CID="$(echo "$CROW" | awk -F'\t' '{print $3}')"
  [ -z "$CID" ] || [ "$CID" = "null" ] && continue

  aws --profile "$PROFILE" --auth "$AUTH" ce cluster list \
    --region "$REGION" \
    --account-id "$CID" \
    --lifecycle-state ACTIVE \
    --all \
    --output json 2>>"$WORKDIR/oc1_active_errors.log" \
  | jq -c --arg env "$ENV" --arg region "$REGION" '.data[]? | . + {env:$env, region:$region}' \
  >> "$WORKDIR/oc1_active_clusters.jsonl"
done < "$WORKDIR/missing_env_region.tsv"

jq -s 'unique_by(.id)' "$WORKDIR/oc1_active_clusters.jsonl" > "$WORKDIR/oc1_active_clusters.json"
jq 'length' "$WORKDIR/oc1_active_clusters.json"
```

## Phase 6: Generate Final Bootstrap Commands

Intersect `missing list` with `AWS ACTIVE` names:

```bash
jq -r '.[].name' "$WORKDIR/oc1_active_clusters.json" | sort -u > "$WORKDIR/oc1_active_names.txt"

python3 - <<'PY'
import json, pathlib
home = pathlib.Path.home()
work = home / "code/cortex-AI/data/aws_truth"
missing = json.loads((home / "code/cortex-AI/data/kubeconfig_missing_clusters_filtered.json").read_text()).get("entries", [])
active = set((work / "oc1_active_names.txt").read_text().splitlines())
out = []
for e in missing:
    cluster = str(e.get("cluster") or "").strip()
    env = str(e.get("environment") or "").strip()
    region = str(e.get("region") or "").strip()
    if not cluster or not env or not region:
        continue
    if cluster not in active:
        continue
    comp = "cp" if ("-cp-cluster-" in cluster or "-ss-cp-cluster-" in cluster) else "dp"
    cmd = f'/Users/$USER/code/bots-terraform/scripts/update_kubeconfig.sh aws1.ssh {region} {env} {cluster} {comp}'
    verify = f'test -s ~/.kube/config.{cluster} && echo OK || echo MISSING'
    out.append(cmd + " && " + verify)
out.sort()
(work / "oc1_update_commands.sh").write_text("\n".join(out) + ("\n" if out else ""))
print("commands", len(out))
print(work / "oc1_update_commands.sh")
PY
```

## Phase 7: Execute in Batches

```bash
export CMDS="$WORKDIR/oc1_update_commands.sh"
sed -n '1,5p'   "$CMDS" | bash
sed -n '6,10p'  "$CMDS" | bash
sed -n '11,15p' "$CMDS" | bash
sed -n '16,20p' "$CMDS" | bash
sed -n '21,25p' "$CMDS" | bash
```

Optional logging:

```bash
sed -n '1,5p' "$CMDS" | bash | tee -a "$WORKDIR/bootstrap_run.log"
```

## Result Classification

After batch runs, classify each command:

1. **Success**: `Saved ~/.kube/config.<cluster>` + `OK`
2. **Script Guardrail Skip**: `Skipping ... unsupported environment ...`
3. **Failure**: `MISSING` or CLI error

## Common Troubleshooting

1. `jq: Invalid numeric literal`
   - Output file contains non-JSON error text.
   - Verify AWS command/auth/flags.

2. `NotAuthorizedOrNotFound` on `ce cluster list`
   - Usually wrong `--account-id` (account used instead of account).

3. `config invalid: user missing`
   - Missing `--auth security_token`.

4. Loop too slow
   - Use unique `(env,region)` pairs, not per-cluster repeated queries.

## Expected Outputs

Key artifacts written under:

- `~/code/cortex-AI/data/aws_truth/env_account.tsv`
- `~/code/cortex-AI/data/aws_truth/oc1_accounts.tsv`
- `~/code/cortex-AI/data/aws_truth/oc1_active_clusters.json`
- `~/code/cortex-AI/data/aws_truth/oc1_update_commands.sh`
- `~/code/cortex-AI/data/aws_truth/bootstrap_run.log` (if logging enabled)

Use these as auditable evidence for bootstrap decisions and outcomes.

## Optional: One-Command Automation Script

This repo also includes an automation wrapper:

- `scripts/automate_kubeconfig_bootstrap.py`

It now supports interactive AWS auth automatically:

- If `aws session validate --local` is invalid, the script runs `aws session authenticate`, opens the browser login flow, then continues automatically after successful login.
- Default auth profile inputs are:
  - `--profile aws1.ssh`
  - `--auth security_token`
  - `--auth-region us-ashburn-1`
  - `--account-name aws_operator_access`
- Override when needed:
  - `--auth-region <region>`
  - `--account-name <account-name>`
- Disable browser auto-auth and only print the command:
  - `--no-interactive-auth`

### Plan only (safe default)

```bash
/Users/$USER/code/cortex-AI/scripts/automate_kubeconfig_bootstrap.py \
  --profile aws1.ssh
```

### Plan only with custom interactive auth inputs

```bash
/Users/$USER/code/cortex-AI/scripts/automate_kubeconfig_bootstrap.py \
  --profile aws1.ssh \
  --auth-region us-ashburn-1 \
  --account-name aws_operator_access
```

### Execute all planned rows serially

```bash
/Users/$USER/code/cortex-AI/scripts/automate_kubeconfig_bootstrap.py \
  --profile aws1.ssh \
  --execute
```

### Execute first N rows

```bash
/Users/$USER/code/cortex-AI/scripts/automate_kubeconfig_bootstrap.py \
  --profile aws1.ssh \
  --execute \
  --limit 10
```

Outputs are written under:

- `data/aws_truth/bootstrap_automation_plan.json`
- `data/aws_truth/bootstrap_automation_commands.sh`
- `data/aws_truth/bootstrap_automation_run.log` (execute mode)
- `data/aws_truth/bootstrap_automation_summary.json`
