# API Gateway — Latency Spike

Tags: api-gateway, latency, sev1, sev2, p99

## Symptoms
- `latency_p99_ms` > 1000ms on api-gateway
- Downstream services report timeouts
- Error rate climbing

## Diagnosis
```bash
# Check current pod health
kubectl get pods -n prod -l app=api-gateway

# Check resource usage
kubectl top pods -n prod -l app=api-gateway

# Recent logs
kubectl logs -n prod deploy/api-gateway --tail=100 | grep -i "error\|timeout\|slow"
```

## Resolution

### Step 1 — Restart the gateway
```bash
kubectl rollout restart deploy/api-gateway -n prod
kubectl rollout status deploy/api-gateway -n prod
```

### Step 2 — Scale up if CPU > 80%
```bash
kubectl scale deploy/api-gateway -n prod --replicas=+2
```

### Step 3 — Check upstream dependencies
- auth-service latency (gateway waits for auth on every request)
- Check if a recent deploy to any upstream service coincides

### Step 4 — Enable circuit breaker
If a specific upstream is causing the spike, temporarily route around it.

## Escalate if
- Latency > 2000ms for more than 5 minutes
- All replicas are affected simultaneously
- CPU and memory are normal (suggests a code-level issue)
