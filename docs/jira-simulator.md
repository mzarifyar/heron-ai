# Jira Simulator

The Jira Simulator provides deterministic, Jira-compatible payloads for validating Heron detection and remediation flows without reaching a live Jira tenant. It implements the Jira endpoints currently consumed by Heron, supports dataset-driven replays, deterministic noise injection, and sanitized "known-bad" scenario replays. The simulator remains disabled by default and is activated only through explicit configuration.

## Supported Endpoints

The simulator mirrors the subset of the Jira REST API that Heron calls today:

- `GET /rest/api/2/search` – supports `jql`, `startAt`, and `maxResults`. Returns Jira-style pages with `issues[]` entries containing `key`, `id`, and `fields`.
- `GET /rest/api/2/issue/{key}` – returns a Jira-compatible issue document including the fields requested by Heron.
- `GET /rest/api/2/issue/{key}/comment` – returns `{ "comments": [...] }`.
- `POST /rest/api/2/issue/{key}/comment` – accepts `{ "body": "..." }` and appends a deterministic comment.
- `PUT /rest/api/2/issue/{key}` – accepts label update payloads (`{"update": {"labels": [{"add": "processed"}]}}`).
- `POST /rest/api/2/issue` – creates a synthetic issue when Heron exercises the ticket creation flow.
- `GET /rest/api/2/field` – returns a minimal set of field metadata used by `get_fields_map`.

Additional simulator endpoints:

- `POST /simulator/run` – starts a run with `mode`, `dataset`, `seed`, `cadence_seconds`, `duration_seconds`, etc.
- `GET /simulator/run/{run_id}` – returns run status and progress.
- `GET /simulator/run/{run_id}/metrics` and `GET /simulator/metrics` – report coverage metrics (pattern totals and DVM vs. unknown percentages).
- `POST /simulator/run/{run_id}/stop` – stops an active run early.

## Configuration and Startup

Enable the simulator via `config/settings.json` or environment variables:

```json
"jira": {
  "base_url": "https://jira-sd.mc1.amazoniaas.com/rest/api/2",
  "simulator": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8090,
    "mode": "replay",
    "dataset": "replay/baseline.json",
    "seed": 42,
    "cadence_seconds": 60.0,
    "noise_cadence_seconds": null
  }
}
```

When `jira.simulator.enabled` is `true`, `get_jira_base_url()` resolves to `http://{host}:{port}/rest/api/2`. Heron can therefore target the simulator by setting the configuration before importing `app.integrations.jira`.

### CLI Helper

Run the simulator locally using the CLI:

```bash
python -m simulators.jira.cli --host 127.0.0.1 --port 8090 --mode replay --dataset replay/baseline.json --seed 42
```

The CLI pulls defaults from `jira.simulator` settings, starts the HTTP server, and kicks off a run unless `--no-autostart` is provided.

## Dataset Format

Datasets live under `datasets/jira/`:

- `datasets/jira/replay/` – baseline replay datasets.
- `datasets/jira/known-bad/` – sanitized incident signature replays.

Each dataset file is JSON with the following structure:

```json
{
  "metadata": {
    "name": "baseline_replay",
    "description": "Synthetic baseline dataset",
    "default_cadence_seconds": 60,
    "patterns": {
      "dvm": ["dvm_cpu_burst"],
      "unknown": ["unknown_service_warning"]
    }
  },
  "tickets": [
    {
      "key": "SIM-1001",
      "id": "10001",
      "pattern": { "id": "dvm_cpu_burst", "family": "dvm" },
      "fields": {
        "summary": "[DVM] CPU burst detected",
        "labels": ["AutoCut", "DVM"],
        "created": "2024-05-01T10:00:00.000+0000"
      },
      "comments": [
        {
          "id": "201",
          "body": "Synthetic acknowledgement",
          "author": { "displayName": "Simulator Bot" },
          "created": "2024-05-01T10:05:00.000+0000"
        }
      ]
    }
  ]
}
```

Required fields:

- `pattern.family` distinguishes DVM vs. unknown signatures.
- `fields.labels` must contain only sanitized, non-sensitive labels.
- `created`/`updated` timestamps use Jira’s ISO8601 format with timezone offsets.

### Adding New Datasets

1. Create a JSON file in `datasets/jira/replay/` or `datasets/jira/known-bad/`.
2. Ensure all keys, summaries, and descriptions are synthetic and sanitized.
3. Include `pattern_id`/`pattern_family` to maintain coverage metrics.
4. Run the determinism and contract test suite to confirm schema compatibility.

## Run Modes

- **replay** – emits dataset tickets at the configured cadence.
- **known_bad** – identical to replay but sourced from the `known-bad` directory.
- **noise** – emits deterministic benign tickets with `sim_noise` labeling. Content varies based on the provided seed.
- **mixed** – replays dataset tickets and injects noise using `noise_cadence_seconds`.

Run control example:

```bash
curl -X POST http://127.0.0.1:8090/simulator/run \
  -H 'Content-Type: application/json' \
  -d '{
    "mode": "mixed",
    "dataset": "replay/baseline.json",
    "seed": 123,
    "cadence_seconds": 45,
    "noise_cadence_seconds": 120
  }'
```

## Coverage Metrics

`GET /simulator/metrics` returns totals across all runs:

```json
{
  "run_id": "overall",
  "mode": "aggregate",
  "total_emitted": 12,
  "pattern_counts": { "dvm": 8, "unknown": 4 },
  "coverage": { "dvm": 0.6667, "unknown": 0.3333 },
  "noise_emitted": 3,
  "completed": true
}
```

Per-run metrics are available at `/simulator/run/{run_id}/metrics`.

## Contract and Regression Tests

The test suite exercises:

- Search, issue fetch, comment, label update, and issue creation contracts via the existing Heron Jira client.
- Determinism: identical datasets + seeds yield identical sequences and `/search` results.
- Noise schema safety: all synthetic noise tickets parse through `get_issue_full` and `get_issue_labels` without schema mismatches.
- Known-bad fidelity: emitted issues preserve sanitized keys, summaries, and timestamps defined in the dataset.
- Metrics: DVM vs. unknown coverage percentages and per-pattern counts.

Run all simulator tests with:

```bash
pytest tests/simulator
```

(See the test module docstrings for detailed expectations.)
