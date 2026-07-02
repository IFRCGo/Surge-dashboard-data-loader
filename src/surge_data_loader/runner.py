from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .client import RRMSClient
from .config import LoaderConfig
from .pii import validate_no_forbidden_fields
from .transform import (
    build_organization_lookup,
    collect_person_ids,
    enrich_person,
    transform_event,
)


OUTPUT_DIR = Path("data/powerbi")
EVENTS_OUTPUT = OUTPUT_DIR / "powerbi_training_events.json"
MANIFEST_OUTPUT = OUTPUT_DIR / "powerbi_loader_manifest.json"


def run_loader(
    config: LoaderConfig,
    *,
    max_pages: int | None,
    all_pages: bool,
    incremental: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    started_at = now_utc()
    client = RRMSClient(config, verbose=verbose)
    manifest: dict[str, Any] = {
        "started_at": started_at,
        "finished_at": None,
        "event_pages_fetched": 0,
        "events_processed": 0,
        "existing_events_loaded": 0,
        "events_added": 0,
        "events_replaced": 0,
        "events_skipped_existing": 0,
        "incremental": incremental,
        "stopped_after_existing_page": False,
        "participant_links_written_inside_events": 0,
        "unique_person_ids_enriched": 0,
        "organizations_loaded": 0,
        "personal_fields_saved": False,
        "output_file": str(EVENTS_OUTPUT).replace("\\", "/"),
        "errors": [],
    }

    organizations = client.fetch_organizations()
    manifest["organizations_loaded"] = len(organizations)
    organization_lookup = build_organization_lookup(organizations)
    existing_events = load_existing_events() if incremental else []
    manifest["existing_events_loaded"] = len(existing_events)
    existing_by_id = index_existing_events(existing_events)

    raw_events: list[dict[str, Any]] = []
    for page_number, events in client.iter_event_pages(max_pages=max_pages, all_pages=all_pages):
        manifest["event_pages_fetched"] += 1
        page_candidates: list[dict[str, Any]] = []
        page_existing_skipped = 0
        for event in events:
            event_id = event_identity(event)
            if incremental and event_id is not None and event_id in existing_by_id:
                existing_event = existing_by_id[event_id]
                if event_changed(event, existing_event):
                    page_candidates.append(event)
                    manifest["events_replaced"] += 1
                else:
                    page_existing_skipped += 1
                    manifest["events_skipped_existing"] += 1
            else:
                page_candidates.append(event)
                manifest["events_added"] += 1

        raw_events.extend(page_candidates)
        if (
            incremental
            and all_pages
            and events
            and page_existing_skipped == len(events)
            and not page_candidates
        ):
            manifest["stopped_after_existing_page"] = True
            if verbose:
                print(
                    f"Stopping incremental fetch after page {page_number}; all events already exist.",
                    flush=True,
                )
            break

    person_ids = collect_person_ids(raw_events)
    person_enrichment = enrich_people(
        client=client,
        person_ids=person_ids,
        organization_lookup=organization_lookup,
        manifest=manifest,
        workers=config.person_workers,
        verbose=verbose,
    )

    transformed_events = [
        transform_event(event, person_enrichment=person_enrichment)
        for event in raw_events
    ]
    output_events = merge_events(existing_events, transformed_events) if incremental else transformed_events
    manifest["events_processed"] = len(output_events)
    manifest["participant_links_written_inside_events"] = sum(
        len(event["participants"]) for event in output_events
    )
    manifest["unique_person_ids_enriched"] = len(person_enrichment)
    manifest["finished_at"] = now_utc()

    validate_no_forbidden_fields(output_events)
    validate_no_forbidden_fields(manifest)
    write_json_outputs(output_events, manifest)
    return manifest


def load_existing_events(path: Path = EVENTS_OUTPUT) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Existing output is not valid JSON: {path}") from exc
    if not isinstance(loaded, list):
        raise RuntimeError(f"Existing output must be a JSON array: {path}")
    return [event for event in loaded if isinstance(event, dict)]


def index_existing_events(events: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    indexed: dict[int, dict[str, Any]] = {}
    for event in events:
        event_id = event_identity(event)
        if event_id is not None:
            indexed[event_id] = event
    return indexed


def merge_events(
    existing_events: list[dict[str, Any]],
    transformed_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    transformed_by_id = index_existing_events(transformed_events)
    merged: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for event in existing_events:
        event_id = event_identity(event)
        if event_id is not None and event_id in transformed_by_id:
            merged.append(transformed_by_id[event_id])
            seen_ids.add(event_id)
        else:
            merged.append(event)
            if event_id is not None:
                seen_ids.add(event_id)

    for event in transformed_events:
        event_id = event_identity(event)
        if event_id is None or event_id not in seen_ids:
            merged.append(event)
            if event_id is not None:
                seen_ids.add(event_id)

    return sorted(merged, key=event_sort_key, reverse=True)


def event_changed(raw_event: dict[str, Any], existing_event: dict[str, Any]) -> bool:
    raw_updated_at = event_updated_at(raw_event)
    existing_updated_at = event_updated_at(existing_event)
    if raw_updated_at and existing_updated_at:
        return raw_updated_at != existing_updated_at
    return False


def event_identity(event: dict[str, Any]) -> int | None:
    value = event.get("event_id") or event.get("id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def event_updated_at(event: dict[str, Any]) -> str | None:
    value = event.get("event_updated_at") or event.get("updated_at")
    if value in (None, ""):
        return None
    return str(value)


def event_sort_key(event: dict[str, Any]) -> tuple[str, str, int]:
    event_from = event.get("event_from") or event.get("from") or ""
    updated_at = event_updated_at(event) or ""
    event_id = event_identity(event) or 0
    return (str(event_from), updated_at, event_id)


def enrich_people(
    *,
    client: RRMSClient,
    person_ids: set[int],
    organization_lookup: Any,
    manifest: dict[str, Any],
    workers: int,
    verbose: bool,
) -> dict[int, dict[str, Any]]:
    sorted_person_ids = sorted(person_ids)
    total = len(sorted_person_ids)
    if total == 0:
        return {}

    if verbose:
        print(f"Enriching {total} unique people with {workers} workers.", flush=True)

    person_enrichment: dict[int, dict[str, Any]] = {}
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(enrich_one_person, client, person_id, organization_lookup): person_id
            for person_id in sorted_person_ids
        }
        for future in as_completed(futures):
            person_id = futures[future]
            completed += 1
            try:
                person_enrichment[person_id] = future.result()
            except Exception as exc:  # noqa: BLE001 - keep full run moving and record the person id.
                manifest["errors"].append(f"person {person_id} enrichment failed: {exc}")
                person_enrichment[person_id] = {}
            if verbose and (completed == total or completed % 100 == 0):
                print(f"Enriched {completed}/{total} people.", flush=True)
    return person_enrichment


def enrich_one_person(
    client: RRMSClient,
    person_id: int,
    organization_lookup: Any,
) -> dict[str, Any]:
    tags = client.fetch_person_tags(person_id)
    detail = client.fetch_person_detail(person_id)
    return enrich_person(
        person_tags=tags,
        person_detail=detail,
        organization_lookup=organization_lookup,
    )


def write_json_outputs(events: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_OUTPUT.write_text(
        json.dumps(events, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    MANIFEST_OUTPUT.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
