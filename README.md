# api-health-checker

Watch the APIs your work depends on.

A small Python tool that checks a list of HTTP endpoints on a schedule and
reports what a support engineer needs before opening an incident: which
services are up, which are slow, and which are down — with latency, status
codes and retry counts for each.

## Features

- Per-endpoint classification: **UP** / **DEGRADED** (over the latency
  warning threshold) / **DOWN**
- Expected status codes, custom headers (e.g. `Authorization`), per-endpoint
  timeouts and retry counts
- Defaults in the config apply to every endpoint; any endpoint can override
  them
- Text report by default, JSON with `--json`, Markdown report file with
  `--markdown --output report.md`
- Exit code 1 when anything is DOWN — plugs into cron, CI or a Docker
  HEALTHCHECK (degraded is a warning, not a failure)
- `--interval N` runs the checks every N seconds for continuous monitoring
- Standard library only — no dependencies, no installation step

## Usage

Copy the example config and point it at your services:

```bash
cp endpoints.example.json endpoints.json   # edit to taste
python3 health_checker.py --config endpoints.json
```

Try it against the bundled demo API (serves a fast 200, a slow 200, a 500
and a 404):

```bash
python3 demo_server.py --port 8901 &
python3 health_checker.py --config endpoints.json
```

Monitoring mode:

```bash
python3 health_checker.py --config endpoints.json --interval 60
```

## Docker

Single run (mount your config):

```bash
docker build -t api-health-checker .
docker run --rm -v "$PWD/endpoints.json:/app/endpoints.json" api-health-checker --config /app/endpoints.json
```

Monitoring stack (checker + demo API, checks every 60 seconds):

```bash
docker compose up
```

## Sample output

From a run against the demo API:

```
api-health-checker — 2026-10-24T02:43:09+00:00
  UP       demo-ok                200   40.9ms  (1 attempt)
  DEGRADED demo-slow              200 1201.7ms  (1 attempt)
  DOWN     demo-error             500    1.2ms  (2 attempts) — HTTP 500, expected 200
  DOWN     demo-missing           404    1.2ms  (2 attempts) — HTTP 404, expected 200
Summary: 1 up, 1 degraded, 2 down of 4 endpoints
Findings:
  - DEGRADED: demo-slow — 1201.7ms exceeds 1000ms warning threshold
  - DOWN: demo-error — HTTP 500 (expected 200)
  - DOWN: demo-missing — HTTP 404 (expected 200)
```

## Config reference

```json
{
  "defaults": {
    "expected_status": [200],
    "timeout": 10,
    "retries": 1,
    "warn_latency_ms": 1000
  },
  "endpoints": [
    {
      "name": "auth-api",
      "url": "https://auth.example.com/health",
      "expected_status": [200, 204],
      "headers": {"Authorization": "Bearer <token>"},
      "timeout": 5,
      "retries": 2,
      "warn_latency_ms": 500
    }
  ]
}
```
