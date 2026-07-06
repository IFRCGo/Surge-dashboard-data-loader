from __future__ import annotations

import json
from collections import Counter, defaultdict
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
TRAININGS_FACILITATOR_MODEL_OUTPUT = OUTPUT_DIR / "trainings_facilitator_model.json"
OUTPUT_SCHEMA_VERSION = 2
MODEL_SCHEMA_VERSION = 1
REQUIRED_PARTICIPANT_FIELDS = {
    "subregion_tag",
    "subregion_label",
    "language_codes",
    "language_names",
    "person_training_tags",
}
REFERENCE_TRAINING_TAGS = ("Induction", "CAP", "ETL", "MOT", "TAF")
ORGANISATION_TYPE_LABELS = ("National Society", "IFRC", "Other")


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
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
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
    merged_events = merge_events(existing_events, transformed_events) if incremental else transformed_events
    output_events, duplicate_event_ids = deduplicate_events_by_id(merged_events)
    manifest["events_processed"] = len(output_events)
    manifest["duplicate_events_removed"] = len(merged_events) - len(output_events)
    manifest["duplicate_event_ids_removed"] = duplicate_event_ids
    manifest["participant_links_written_inside_events"] = count_participant_links(output_events)
    role_counts = count_roles(output_events)
    manifest["participant_role_counts"] = dict(sorted(role_counts.items()))
    manifest["non_participant_role_links"] = sum(
        count for role, count in role_counts.items() if role != "participant"
    )
    manifest["unique_person_ids_enriched"] = len(person_enrichment)
    manifest["dashboard_summary"] = build_dashboard_summary(output_events)
    model = build_trainings_facilitator_model(output_events)
    manifest["model_file"] = str(TRAININGS_FACILITATOR_MODEL_OUTPUT).replace("\\", "/")
    manifest["model_schema_version"] = MODEL_SCHEMA_VERSION
    manifest["model_counts"] = model_table_counts(model)
    manifest["finished_at"] = now_utc()

    validate_no_forbidden_fields(output_events)
    validate_no_forbidden_fields(manifest)
    validate_no_forbidden_fields(model)
    write_json_outputs(output_events, manifest, model)
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


def deduplicate_events_by_id(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[int]]:
    deduplicated: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    duplicate_ids: list[int] = []
    for event in events:
        event_id = event_identity(event)
        if event_id is not None:
            if event_id in seen_ids:
                duplicate_ids.append(event_id)
                continue
            seen_ids.add(event_id)
        deduplicated.append(event)
    return deduplicated, duplicate_ids


def event_changed(raw_event: dict[str, Any], existing_event: dict[str, Any]) -> bool:
    if event_missing_current_output_fields(existing_event):
        return True
    raw_updated_at = event_updated_at(raw_event)
    existing_updated_at = event_updated_at(existing_event)
    if raw_updated_at and existing_updated_at:
        return raw_updated_at != existing_updated_at
    return False


def event_missing_current_output_fields(existing_event: dict[str, Any]) -> bool:
    participants = existing_event.get("participants")
    if not isinstance(participants, list):
        return False
    for participant in participants:
        if not isinstance(participant, dict):
            continue
        if any(field not in participant for field in REQUIRED_PARTICIPANT_FIELDS):
            return True
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
    languages = client.fetch_person_languages(person_id)
    detail = client.fetch_person_detail(person_id)
    return enrich_person(
        person_tags=tags,
        person_languages=languages,
        person_detail=detail,
        organization_lookup=organization_lookup,
    )


def count_roles(events: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for event in events:
        for participant in event.get("participants", []) or []:
            if not isinstance(participant, dict):
                continue
            role = participant.get("role") or "(blank)"
            counts[str(role)] += 1
    return counts


def count_participant_links(events: list[dict[str, Any]]) -> int:
    return sum(len(event.get("participants", []) or []) for event in events)


def build_dashboard_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    participant_links = 0
    unique_people: set[int] = set()
    unique_people_per_event: list[int] = []

    gender = grouped_counter()
    region = grouped_counter()
    subregion = grouped_counter()
    sending_org = grouped_counter()
    org_type = grouped_counter()
    language = grouped_counter()
    event_training_type = grouped_counter()
    person_training_tag = grouped_counter()
    role = grouped_counter()
    event_type = grouped_counter()
    location = grouped_counter()

    time_values: list[str] = []
    slicer_values: dict[str, set[str]] = {
        "region": set(),
        "subregion": set(),
        "sending_organisation": set(),
        "location": set(),
        "gender": set(),
        "language": set(),
        "training_type": set(),
        "event_role": set(),
    }

    for event in events:
        event_id = event.get("event_id")
        event_people: set[int] = set()
        training_type = event.get("event_tag_name") or event.get("event_tag_name_N")
        event_type_value = event.get("event_type")
        location_value = event.get("event_venue")

        add_event_group(event_type, event_type_value, event_id)
        add_event_group(location, location_value, event_id)
        if location_value:
            slicer_values["location"].add(str(location_value))
        if training_type:
            slicer_values["training_type"].add(str(training_type))

        for participant in event.get("participants", []) or []:
            if not isinstance(participant, dict):
                continue
            participant_links += 1
            person_id = as_int_value(participant.get("person_id"))
            if person_id is not None:
                unique_people.add(person_id)
                event_people.add(person_id)

            add_participant_group(gender, participant.get("sex_or_gender"), person_id)
            add_participant_group(region, participant.get("region_label"), person_id)
            add_participant_group(subregion, participant.get("subregion_label"), person_id)
            add_participant_group(sending_org, sending_organization(participant), person_id)
            add_participant_group(org_type, organization_type(participant), person_id)
            add_participant_group(role, participant.get("role"), person_id)
            add_participant_group(event_training_type, training_type, person_id)

            for language_name in participant.get("language_names", []) or []:
                add_participant_group(language, language_name, person_id)
                if language_name:
                    slicer_values["language"].add(str(language_name))

            for training_tag in participant.get("person_training_tags", []) or []:
                add_participant_group(person_training_tag, training_tag, person_id)

            for slicer_key, value in (
                ("gender", participant.get("sex_or_gender")),
                ("region", participant.get("region_label")),
                ("subregion", participant.get("subregion_label")),
                ("sending_organisation", sending_organization(participant)),
                ("event_role", participant.get("role")),
            ):
                if value:
                    slicer_values[slicer_key].add(str(value))

            time_value = participant.get("participant_start") or participant.get("participant_end")
            if not time_value:
                time_value = event.get("event_from") or event.get("event_to")
            if time_value:
                time_values.append(str(time_value))

        unique_people_per_event.append(len(event_people))

    return {
        "schema_version": 1,
        "cards": {
            "trainings": len(events),
            "people_trained": len(unique_people),
            "participant_links": participant_links,
            "avg_participant_links_per_training": round(
                participant_links / len(events), 2
            )
            if events
            else 0,
            "avg_unique_people_per_training": round(
                sum(unique_people_per_event) / len(unique_people_per_event), 2
            )
            if unique_people_per_event
            else 0,
        },
        "visuals": {
            "participants_by_gender": grouped_rows(gender, "gender"),
            "participants_by_region": grouped_rows(region, "region"),
            "participants_by_subregion": grouped_rows(subregion, "subregion"),
            "participants_by_sending_organisation": grouped_rows(
                sending_org, "sending_organisation"
            ),
            "participants_by_organisation_type": grouped_rows_in_order(
                org_type,
                "organisation_type",
                ORGANISATION_TYPE_LABELS,
            ),
            "participants_by_language": grouped_rows(language, "language"),
            "participants_by_training_type": grouped_rows(
                event_training_type, "training_type"
            ),
            "participants_by_person_training_tag": grouped_rows_in_order(
                person_training_tag,
                "person_training_tag",
                REFERENCE_TRAINING_TAGS,
            ),
            "participants_by_role": grouped_rows(role, "role"),
            "trainings_by_event_type": event_rows(event_type, "event_type"),
            "trainings_by_location": event_rows(location, "location"),
        },
        "slicers": {
            **{key: sorted(values) for key, values in slicer_values.items()},
            "time": build_time_slicer(time_values),
        },
    }


def build_trainings_facilitator_model(events: list[dict[str, Any]]) -> dict[str, Any]:
    event_rows_data: list[list[Any]] = []
    participant_rows: list[list[Any]] = []
    participant_language_rows: list[list[Any]] = []
    participant_training_tag_rows: list[list[Any]] = []

    participation_index = 0
    for event in events:
        event_id = event.get("event_id")
        event_training_type = event.get("event_tag_name") or event.get("event_tag_name_N")
        event_rows_data.append(
            [
                event_id,
                event.get("event_name"),
                event_training_type,
                event.get("event_type"),
                event.get("event_from"),
                event.get("event_to"),
                event.get("event_venue"),
                event.get("event_organization"),
            ]
        )

        for participant in event.get("participants", []) or []:
            if not isinstance(participant, dict):
                continue
            participation_index += 1
            person_id = participant.get("person_id")
            participation_id = participation_index
            participant_date = (
                participant.get("participant_start")
                or participant.get("participant_end")
                or event.get("event_from")
                or event.get("event_to")
            )
            participant_rows.append(
                [
                    participation_id,
                    event_id,
                    person_id,
                    participant.get("role"),
                    participant_date,
                    participant.get("sex_or_gender"),
                    participant.get("region_label"),
                    participant.get("subregion_label"),
                    sending_organization(participant),
                    organization_type(participant),
                ]
            )

            for language_name in participant.get("language_names", []) or []:
                language_name = clean_group_value(language_name)
                if not language_name:
                    continue
                participant_language_rows.append([participation_id, language_name])

            for training_tag in participant.get("person_training_tags", []) or []:
                training_tag = clean_group_value(training_tag)
                if training_tag not in REFERENCE_TRAINING_TAGS:
                    continue
                participant_training_tag_rows.append([participation_id, training_tag])

    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "description": (
            "Narrow Power BI model tables derived from powerbi_training_events.json. "
            "Use this file for filter-responsive visuals without expanding the large nested JSON."
        ),
        "relationships": [
            {
                "from_table": "participants",
                "from_column": "event_id",
                "to_table": "events",
                "to_column": "event_id",
                "cardinality": "many_to_one",
            },
            {
                "from_table": "participant_languages",
                "from_column": "participation_id",
                "to_table": "participants",
                "to_column": "participation_id",
                "cardinality": "many_to_one",
            },
            {
                "from_table": "participant_training_tags",
                "from_column": "participation_id",
                "to_table": "participants",
                "to_column": "participation_id",
                "cardinality": "many_to_one",
            },
        ],
        "tables": {
            "events": model_table(
                [
                    "event_id",
                    "event_name",
                    "event_training_type",
                    "event_type",
                    "event_from",
                    "event_to",
                    "event_venue",
                    "event_organization",
                ],
                event_rows_data,
            ),
            "participants": model_table(
                [
                    "participation_id",
                    "event_id",
                    "person_id",
                    "role",
                    "participant_date",
                    "sex_or_gender",
                    "region_label",
                    "subregion_label",
                    "sending_organisation",
                    "organisation_type",
                ],
                participant_rows,
            ),
            "participant_languages": model_table(
                ["participation_id", "language_name"],
                participant_language_rows,
            ),
            "participant_training_tags": model_table(
                ["participation_id", "person_training_tag"],
                participant_training_tag_rows,
            ),
            "training_tag_categories": model_table(
                ["person_training_tag"],
                [[tag] for tag in REFERENCE_TRAINING_TAGS],
            ),
            "organisation_type_categories": model_table(
                ["organisation_type"],
                [[label] for label in ORGANISATION_TYPE_LABELS],
            ),
        },
    }


def model_table(columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"columns": columns, "rows": rows}


def model_table_counts(model: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    tables = model.get("tables", {})
    if not isinstance(tables, dict):
        return counts
    for table_name, table in tables.items():
        if isinstance(table, dict) and isinstance(table.get("rows"), list):
            counts[table_name] = len(table["rows"])
        elif isinstance(table, list):
            counts[table_name] = len(table)
    return counts


def grouped_counter() -> dict[str, dict[str, Any]]:
    return defaultdict(lambda: {"participant_links": 0, "people": set()})


def add_participant_group(
    counter: dict[str, dict[str, Any]],
    value: Any,
    person_id: int | None,
) -> None:
    label = clean_group_value(value)
    if label is None:
        return
    counter[label]["participant_links"] += 1
    if person_id is not None:
        counter[label]["people"].add(person_id)


def add_event_group(counter: dict[str, dict[str, Any]], value: Any, event_id: Any) -> None:
    label = clean_group_value(value)
    if label is None:
        return
    counter[label]["event_count"] = counter[label].get("event_count", 0) + 1
    counter[label].setdefault("events", set())
    if event_id not in (None, ""):
        counter[label]["events"].add(event_id)


def grouped_rows(counter: dict[str, dict[str, Any]], field_name: str) -> list[dict[str, Any]]:
    rows = [
        {
            field_name: label,
            "participant_links": values["participant_links"],
            "unique_people": len(values["people"]),
        }
        for label, values in counter.items()
    ]
    return sorted(rows, key=lambda row: (-row["participant_links"], str(row[field_name])))


def grouped_rows_in_order(
    counter: dict[str, dict[str, Any]],
    field_name: str,
    labels: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label in labels:
        values = counter.get(label, {"participant_links": 0, "people": set()})
        rows.append(
            {
                field_name: label,
                "participant_links": values["participant_links"],
                "unique_people": len(values["people"]),
            }
        )
    return rows


def event_rows(counter: dict[str, dict[str, Any]], field_name: str) -> list[dict[str, Any]]:
    rows = [
        {
            field_name: label,
            "event_count": values.get("event_count", 0),
            "unique_events": len(values.get("events", set())),
        }
        for label, values in counter.items()
    ]
    return sorted(rows, key=lambda row: (-row["event_count"], str(row[field_name])))


def clean_group_value(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    text = str(value).strip()
    return text or None


def sending_organization(participant: dict[str, Any]) -> str | None:
    return clean_group_value(
        participant.get("matched_organization_name") or participant.get("national_society_name")
    )


def organization_type(participant: dict[str, Any]) -> str | None:
    if participant.get("national_society_name") or str(
        participant.get("national_society_tag") or ""
    ).startswith("RC."):
        return "National Society"
    organization = str(participant.get("matched_organization_name") or "").strip()
    if organization.upper().startswith("IFRC") or organization.upper() == "IFRC":
        return "IFRC"
    if organization:
        return "Other"
    return "Other"


def build_time_slicer(values: list[str]) -> dict[str, Any]:
    if not values:
        return {"min": None, "max": None, "years": []}
    sorted_values = sorted(values)
    years = sorted({value[:4] for value in values if len(value) >= 4 and value[:4].isdigit()})
    return {"min": sorted_values[0], "max": sorted_values[-1], "years": years}


def as_int_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def write_json_outputs(
    events: list[dict[str, Any]],
    manifest: dict[str, Any],
    model: dict[str, Any] | None = None,
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sparse_events = sparse_json_value(events)
    if model is None:
        model = build_trainings_facilitator_model(events)
    EVENTS_OUTPUT.write_text(
        json.dumps(sparse_events, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    MANIFEST_OUTPUT.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    TRAININGS_FACILITATOR_MODEL_OUTPUT.write_text(
        json.dumps(model, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def sparse_json_value(value: Any) -> Any:
    if isinstance(value, list):
        return [
            sparse_child
            for child in value
            if not is_sparse_empty(sparse_child := sparse_json_value(child))
        ]
    if isinstance(value, dict):
        return {
            key: sparse_child
            for key, child in value.items()
            if not is_sparse_empty(sparse_child := sparse_json_value(child))
        }
    return value


def is_sparse_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
