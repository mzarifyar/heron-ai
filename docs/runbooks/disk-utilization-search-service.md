# Search Service — Disk Utilization

Tags: search-service, disk, storage, sev2, sev3

## Symptoms
- `disk_utilization` > 85% on search-service nodes
- Index replication lag increasing
- Search queries slowing down or failing

## Diagnosis
```bash
# Check disk usage on pods
kubectl exec -n prod deploy/search-service -- df -h

# Find large files
kubectl exec -n prod deploy/search-service -- du -sh /data/* | sort -rh | head -20

# Check index size
kubectl exec -n prod deploy/search-service -- du -sh /data/index/
```

## Resolution

### Step 1 — Clean up old indices (immediate)
```bash
# List indices older than 7 days
kubectl exec -n prod deploy/search-service -- \
  find /data/index -name "*.seg" -mtime +7 -exec ls -lh {} \;

# Delete old segments (verify first)
kubectl exec -n prod deploy/search-service -- \
  find /data/index -name "*.seg" -mtime +7 -delete
```

### Step 2 — Trigger index compaction
```bash
curl -X POST http://search-service.prod.svc/admin/compact
```

### Step 3 — Expand storage
If disk is consistently > 80%, request a PVC resize:
```bash
kubectl patch pvc search-data -n prod -p '{"spec":{"resources":{"requests":{"storage":"100Gi"}}}}'
```

## Prevention
- Set up automated index cleanup for segments > 7 days old
- Alert at 80% disk, page at 90%
- Review index retention policy quarterly
