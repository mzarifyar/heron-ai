# Payment Processor — Connection Pool Exhaustion

Tags: payment-processor, connection_pool, database, sev2

## Symptoms
- `connection_pool_pct` > 85%
- Requests timing out waiting for a DB connection
- Latency spike on payment-processor → postgres edge

## Diagnosis
```bash
kubectl exec -n prod deploy/payment-processor -- env | grep DB_POOL
kubectl logs -n prod deploy/payment-processor --tail=50 | grep -i "pool\|connection"
```

## Resolution

### Step 1 — Scale up replicas (immediate relief)
```bash
kubectl scale deploy/payment-processor -n prod --replicas=+2
```

### Step 2 — Increase pool size (if config allows)
```bash
kubectl set env deploy/payment-processor -n prod DB_POOL_SIZE=20
kubectl rollout restart deploy/payment-processor -n prod
```

### Step 3 — Kill idle connections on the DB
```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'payments'
  AND state = 'idle'
  AND query_start < now() - interval '5 minutes';
```

## Prevention
- Set `DB_POOL_SIZE` based on (replicas × pool_per_replica) < max_connections × 0.8
- Alert at 80% pool utilization, not 100%
