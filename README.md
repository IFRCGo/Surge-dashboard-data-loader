# Surge Data Loader

Python data loader for producing sanitized Power BI JSON from RRMS/Molnix surge training event data.

The main loader:

- logs in to RRMS/Molnix at runtime using username/password credentials
- fetches event-organized data from `https://rrms.ifrc.org/api/api/events`
- keeps one top-level JSON object per event
- nests participant links inside each event
- enriches participants with safe gender, region, National Society, and organization fields
- blocks forbidden personal fields before writing output
- supports incremental refreshes so routine runs do not reprocess the whole historical dataset
- writes compact JSON suitable for GitHub and Power BI

## Outputs

Primary Power BI outputs:

```text
data/powerbi/powerbi_training_events.json
data/powerbi/powerbi_loader_manifest.json
```

`powerbi_training_events.json` contains the event-organized dashboard data.

`powerbi_loader_manifest.json` contains run metadata such as pages fetched,
events processed, participant links written, enrichment counts, output path,
incremental-refresh counts, and any errors.

The production event JSON is intentionally minified. Power BI can load compact JSON normally, and the smaller file is easier to store in GitHub.

Optional human-review samples may also exist:

```text
data/powerbi/powerbi_loader_manifest_pretty.json
data/powerbi/powerbi_training_events_tagged_sample_pretty.json
```

Training metrics, when fetched successfully, is written separately:

```text
data/powerbi/training_metrics.json
data/powerbi/training_metrics_manifest.json
```

## Event Output

Each top-level record is an event. Participant records remain nested under `participants`.

Current event-level fields include:

```text
event_id
event_name
event_tag_name
event_tag_name_N
event_type
event_scale_type
event_from
event_to
event_updated_at
event_venue
event_organization
participants
```

`event_tag_name` is derived from source event tags and tag descriptions.

`event_tag_name_N` is derived from the event name itself, for names such as:

```text
MOT - Managing IFRC Operations
Emergency Team Leader (ETL) training 2023
```

Participant fields include only dashboard-safe values such as `person_id`, role, participation dates, gender, region, National Society, and matched organization.

## Endpoints Used

The main RRMS/Molnix event loader uses:

```text
POST https://rrms.ifrc.org/api/api/login
GET  https://rrms.ifrc.org/api/api/events?page=N
GET  https://rrms.ifrc.org/api/api/system/organizations
GET  https://rrms.ifrc.org/api/api/people/{person_id}/tags
GET  https://rrms.ifrc.org/api/api/people/{person_id}
```

The login endpoint is called with `RRMS_USERNAME` and `RRMS_PASSWORD`. The
returned access token is used in memory for the same run as:

```text
Authorization: Bearer <access_token>
```

The separate training metrics command uses:

```text
GET https://rrms.staging.molnix.com/api/api/v1/training-metrics
```

That endpoint uses the `TRAINING_METRICS_API_TOKEN` value as an API-token header.

## PII Policy

The loader does not save raw event pages, raw person detail payloads, or raw person tag payloads.

Forbidden fields are blocked before output is written, including:

```text
firstnames
surname
fullname
email
phone
mobile
address
decrypted_ssn
passport
document
user
signatures
photo
avatar
```

## Credentials

Do not commit credentials.

Local runs use a repo-root `.env` file copied from `.env.example`:

```powershell
Copy-Item .env.example .env
```

Set:

```text
RRMS_USERNAME=your_molnix_username
RRMS_PASSWORD=your_molnix_password
```

Optional tuning:

```text
RRMS_PERSON_WORKERS=4
RRMS_REQUEST_RETRIES=5
```

The loader calls `POST https://rrms.ifrc.org/api/api/login` on each run and keeps the access token in memory only.

## Running

Run tests:

```powershell
uv run --extra dev pytest -q
```

One-page smoke test:

```powershell
uv run python scripts/build_powerbi_json.py --max-pages 1 --verbose
```

Routine incremental refresh:

```powershell
uv run python scripts/build_powerbi_json.py --all-pages --incremental --verbose --person-workers 4
```

Full rebuild:

```powershell
uv run python scripts/build_powerbi_json.py --all-pages --verbose --person-workers 4
```

Use a full rebuild only when intentionally replacing the whole output.

## Incremental Refresh

`--incremental` reads the existing `powerbi_training_events.json`, indexes events by `event_id`, and fetches newest RRMS event pages.

It:

- adds new events
- replaces events when both old and new records have `event_updated_at` and the value changed
- skips unchanged existing events
- stops early when it reaches a page where all events are already known and unchanged

## GitHub Actions

The scheduled workflow is:

```text
.github/workflows/update-powerbi-json.yml
```

It runs daily and can also be started manually from GitHub Actions.

Required repository secrets:

```text
RRMS_USERNAME
RRMS_PASSWORD
```

The workflow command is:

```powershell
uv run python scripts/build_powerbi_json.py --all-pages --incremental --verbose --person-workers 4
```

It validates JSON output sizes and commits changed JSON files under `data/powerbi/`.

## Training Metrics Endpoint

A separate command exists for the staging training metrics endpoint:

```powershell
uv run python scripts/fetch_training_metrics.py --verbose
```

It writes separate files:

```text
data/powerbi/training_metrics.json
data/powerbi/training_metrics_manifest.json
```
