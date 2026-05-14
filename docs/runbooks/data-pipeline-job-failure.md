# Data Pipeline — Job Failure

Tags: data-pipeline, pipeline, sev2, sev3, batch

## Symptoms
- Pipeline job missed 2+ consecutive scheduled runs
- `error_rate` elevated on data-pipeline
- Downstream analytics data stale

## Diagnosis
```bash
# Check pod status
kubectl get pods -n prod -l app=data-pipeline

# Check recent job history
kubectl get jobs -n prod | grep data-pipeline | tail -10

# Check logs from last failed job
kubectl logs -n prod job/data-pipeline-$(date +%Y%m%d) --tail=100
```

## Resolution

### Step 1 — Manually trigger a run
```bash
kubectl create job --from=cronjob/data-pipeline data-pipeline-manual -n prod
kubectl logs -n prod job/data-pipeline-manual -f
```

### Step 2 — Check upstream data sources
```bash
# Verify Kafka consumer lag
kubectl exec -n prod deploy/data-pipeline -- \
  kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
  --group pipeline-consumer-1 --describe
```

### Step 3 — Restart with backfill
```bash
kubectl set env deploy/data-pipeline -n prod \
  BACKFILL_FROM=$(date -d '2 hours ago' +%Y-%m-%dT%H:%M:%S)
kubectl rollout restart deploy/data-pipeline -n prod
```

## Escalate if
- 3+ consecutive failures
- Kafka consumer lag > 100,000 messages
- Data is more than 4 hours stale
