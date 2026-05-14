# Heron Sense Component

## Purpose

Heron Sense is the entry point for the Heron signal pipeline. It ingests telemetry from the T2 Metrics Collector, normalizes the payloads, and buffers them for analysis by subsequent components (Insight, Core, etc.). In v1 the buffer is in-memory, optimized for local development and integration testing.

## Signal schema

```json
{
  "source": "t2-metrics-collector",
  "context": {
    "service": "payments-api",
    "tier": "backend",
    "environment": "prod",
    "region": "phx",
    "component": "ingest-worker",
    "labels": {
      "team": "reliability"
    }
  },
  "signals": [
    {
      "signal_id": "sig-123",
      "type": "metric",
      "detected_at": "2024-03-11T20:00:00Z",
      "metric": {
        "value": 95.2,
        "unit": "percent",
        "window_seconds": 60
      },
      "summary": "High CPU usage",
      "details": {
        "threshold": 90,
        "observed_series": [72.4, 81.0, 95.2]
      }
    }
  ]
}
```

### Field reference

- `source`: upstream collector name (must be `t2-metrics-collector` in v1).
- `context`: location and ownership metadata.
  - `tier`: service tier classification.
  - `environment`: `dev | test | stage | prod`.
  - `labels`: arbitrary key/value tags from source systems.
- `signals`: list of telemetry entries.
  - `type`: `metric | event | log`.
  - `detected_at`: ISO-8601 timestamp.
  - `metric`: required for `metric` type signals.
  - `summary`: human friendly description.
  - `details`: opaque dictionary preserved for later components.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/sense/signals` | Ingest a batch of signals |
| `GET` | `/api/v1/sense/signals?limit=20` | Retrieve recent buffered signals |
| `GET` | `/healthz` | Liveness check |
| `GET` | `/readyz` | Readiness check |

### Authentication

If `HERON_INGEST_TOKEN` is set, clients must provide `Authorization: Bearer <token>` when calling `POST /api/v1/sense/signals`.

## Running locally

```bash
cp .env.example .env
make docker-up
# POST a sample signal
curl -X POST http://localhost:8080/api/v1/sense/signals \
  -H "Content-Type: application/json" \
  -d @docs/sample-signal.json
```

Stop the stack with `make docker-down`.

## Next steps

Sense exposes an in-process buffer that later components will consume:

- **Insight** will attach anomaly detection logic.
- **Core** will evaluate decisions based on anomaly context.
- **Policy** will provide guardrails for auto-mitigation.

Until those components are implemented, the Sense buffer is the primary verification surface for integration tests.

