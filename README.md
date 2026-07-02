# Surge Data Loader

Standalone plan and scaffolding for an RRMS/Molnix data loader that produces sanitized Power BI JSON for surge training visuals.

The planned loader will:

- fetch event-organized data from `https://rrms.ifrc.org/api/api/events/`
- avoid saving personal information
- enrich event participants with safe tag, region, gender, and organization fields
- write at most two JSON outputs under `data/powerbi/`
- support scheduled GitHub Actions updates

See [PLAN.md](PLAN.md) for the full implementation plan.

## Credentials

Do not commit credentials.

Local runs should use a `.env` file copied from `.env.example`.

```powershell
Copy-Item .env.example .env
```

Then edit `.env` locally:

```text
RRMS_USERNAME=your_molnix_username
RRMS_PASSWORD=your_molnix_password
```

Optional tuning values are also supported:

```text
RRMS_PERSON_WORKERS=4
RRMS_REQUEST_RETRIES=5
```

The staging training metrics endpoint uses a separate API key:

```text
TRAINING_METRICS_URL=https://rrms.staging.molnix.com/api/api/v1/training-metrics
TRAINING_METRICS_API_TOKEN=your_training_metrics_api_token
```

GitHub Actions should use repository secrets:

```text
RRMS_USERNAME
RRMS_PASSWORD
```

The loader should call `POST https://rrms.ifrc.org/api/api/login` on each run and keep access/refresh tokens only in memory.

This loader does not currently call the IFRC GO API, so it does not need a GO API token. If a later version adds GO API calls, use a separate `GO_API_TOKEN` value in your local `.env` and a matching GitHub repository secret. Do not commit the real token.

## Running

Install and run through `uv`:

```powershell
uv run python scripts/build_powerbi_json.py --max-pages 1 --verbose
```

Fetch training metrics with:

```powershell
uv run python scripts/fetch_training_metrics.py --verbose
```

For the scheduled full refresh, GitHub Actions runs:

```powershell
uv run python scripts/build_powerbi_json.py --all-pages --incremental --verbose
```

Use `--incremental` for regular updates. It reads the existing Power BI JSON,
adds new events, replaces events whose `updated_at` changed, and stops once it
reaches a page of already-known unchanged events. Omit `--incremental` when you
intentionally want a full rebuild.
