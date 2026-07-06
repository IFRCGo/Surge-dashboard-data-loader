from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Any


REGION_LABELS = {
    "AFRICA": "Africa Region",
    "AMER": "Americas Region",
    "AMERICAS": "Americas Region",
    "ASIAP": "Asia Pacific Region",
    "EURO": "Europe Region",
    "MENA": "Middle East and North Africa Region",
}

LANGUAGE_CODE_PREFIX = "L-"

EVENT_TAG_STOPWORDS = {
    "A",
    "AN",
    "AND",
    "ARE",
    "AT",
    "FOR",
    "FROM",
    "IFRC",
    "IN",
    "OF",
    "ON",
    "OR",
    "RED",
    "THE",
    "TO",
    "TRAINING",
    "WITH",
}

GENERIC_FUZZY_EVENT_TAGS = {
    "AFRICA",
    "AMER",
    "AMERICAS",
    "ASIAP",
    "AVAIL",
    "EURO",
    "MENA",
    "MEMBER",
}

GENERIC_EVENT_NAME_PREFIXES = GENERIC_FUZZY_EVENT_TAGS | {
    "ARABIC",
    "ENGLISH",
    "FRENCH",
    "JAPANESE",
    "LITHUANIAN",
    "MYANMAR",
    "OLD",
    "PORTUGUESE",
    "RUSSIAN",
    "SPANISH",
    "SWEDISH",
    "TARGETED",
    "UKRAINIAN",
    "WEBINAR",
    "WORKSHOP",
}


@dataclass
class OrganizationLookup:
    by_tag_id: dict[int, dict[str, Any]] = field(default_factory=dict)
    by_tag_name: dict[str, dict[str, Any]] = field(default_factory=dict)


def build_organization_lookup(organizations: list[dict[str, Any]]) -> OrganizationLookup:
    lookup = OrganizationLookup()
    for organization in organizations:
        org_id = organization.get("id") or organization.get("organization_id")
        org_name = (
            organization.get("name")
            or organization.get("title")
            or organization.get("organization_name")
        )
        for tag in extract_tags(organization):
            tag_id = as_int(tag.get("id") or tag.get("tag_id"))
            tag_name = normalize_tag_name(tag)
            entry = {
                "organization_id": org_id,
                "organization_name": org_name,
                "tag_id": tag_id,
                "tag_name": tag_name,
            }
            if tag_id is not None:
                lookup.by_tag_id[tag_id] = entry
            if tag_name:
                lookup.by_tag_name[tag_name] = entry
    return lookup


def transform_event(
    event: Mapping[str, Any],
    *,
    person_enrichment: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    event_id = event.get("id") or event.get("event_id")
    event_name = display_value(event.get("name") or event.get("title") or event.get("event_name"))
    event_tags = extract_tags(event)
    return {
        "event_id": event_id,
        "event_name": event_name,
        "event_tag_name": best_event_tag_name(event_name, event_tags),
        "event_tag_name_N": event_tag_name_from_name(event_name),
        "event_type": display_value(event.get("type") or event.get("event_type")),
        "event_scale_type": display_value(event.get("scale_type") or event.get("event_scale_type")),
        "event_from": display_value(event.get("from") or event.get("event_from") or event.get("start")),
        "event_to": display_value(event.get("to") or event.get("event_to") or event.get("end")),
        "event_updated_at": display_value(event.get("updated_at") or event.get("event_updated_at")),
        "event_venue": display_value(event.get("venue") or event.get("location") or event.get("event_venue")),
        "event_organization": display_value(event.get("organization") or event.get("event_organization")),
        "participants": [
            transform_participant(person, event_id=event_id, person_enrichment=person_enrichment)
            for person in event.get("person", []) or []
            if isinstance(person, Mapping)
        ],
    }


def transform_participant(
    person: Mapping[str, Any],
    *,
    event_id: Any,
    person_enrichment: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    pivot = person.get("pivot") if isinstance(person.get("pivot"), Mapping) else {}
    person_id = as_int(pivot.get("person_id") or person.get("id") or person.get("person_id"))
    enrichment = person_enrichment.get(person_id or -1, {})
    participant = {
        "person_id": person_id,
        "role": pivot.get("role"),
        "requested": pivot.get("requested"),
        "participant_start": pivot.get("start"),
        "participant_end": pivot.get("end"),
        "result": pivot.get("result"),
        "waitlist": pivot.get("waitlist"),
        "sex_or_gender": enrichment.get("sex_or_gender"),
        "region_tag": enrichment.get("region_tag"),
        "region_label": enrichment.get("region_label"),
        "subregion_tag": enrichment.get("subregion_tag"),
        "subregion_label": enrichment.get("subregion_label"),
        "language_codes": enrichment.get("language_codes", []),
        "language_names": enrichment.get("language_names", []),
        "person_training_tags": enrichment.get("person_training_tags", []),
        "national_society_tag": enrichment.get("national_society_tag"),
        "national_society_name": enrichment.get("national_society_name"),
        "matched_organization_id": enrichment.get("matched_organization_id"),
        "matched_organization_name": enrichment.get("matched_organization_name"),
    }
    return participant


def collect_person_ids(events: list[dict[str, Any]]) -> set[int]:
    person_ids: set[int] = set()
    for event in events:
        for person in event.get("person", []) or []:
            if not isinstance(person, Mapping):
                continue
            pivot = person.get("pivot") if isinstance(person.get("pivot"), Mapping) else {}
            person_id = as_int(pivot.get("person_id") or person.get("id") or person.get("person_id"))
            if person_id is not None:
                person_ids.add(person_id)
    return person_ids


def enrich_person(
    *,
    person_tags: list[dict[str, Any]],
    person_detail: Mapping[str, Any] | None,
    person_languages: list[dict[str, Any]] | None = None,
    organization_lookup: OrganizationLookup,
) -> dict[str, Any]:
    region_tag = first_tag_name_in_group(person_tags, "REGION", allowed_values=set(REGION_LABELS))
    if region_tag is None:
        tag_names = [normalize_tag_name(tag) for tag in person_tags]
        region_tag = next((tag for tag in tag_names if tag in REGION_LABELS), None)

    subregion_tag_obj = first_tag_in_group(person_tags, "SUB-REGION")
    subregion_tag = tag_display_name(subregion_tag_obj)
    subregion_label = subregion_label_from_tag(subregion_tag_obj)

    ns_tag = first_tag_name_in_group(person_tags, "NATIONAL SOCIETIES", prefix="RC.")
    if ns_tag is None:
        tag_names = [normalize_tag_name(tag) for tag in person_tags]
        ns_tag = next((tag for tag in tag_names if tag.startswith("RC.")), None)

    language_codes, tag_language_names = extract_language_tags(person_tags)
    language_names = unique_nonblank(
        [
            *extract_language_names(person_languages or []),
            *tag_language_names,
        ]
    )
    person_training_tags = extract_person_training_tags(person_tags)
    org_match, match_method = match_organization(person_tags, organization_lookup)
    return {
        "sex_or_gender": extract_sex_or_gender(person_detail or {}),
        "region_tag": region_tag,
        "region_label": REGION_LABELS.get(region_tag) if region_tag else None,
        "subregion_tag": subregion_tag,
        "subregion_label": subregion_label,
        "language_codes": language_codes,
        "language_names": language_names,
        "person_training_tags": person_training_tags,
        "national_society_tag": ns_tag,
        "national_society_name": org_match.get("organization_name") if ns_tag and org_match else None,
        "matched_organization_id": org_match.get("organization_id") if org_match else None,
        "matched_organization_name": org_match.get("organization_name") if org_match else None,
        "organization_match_method": match_method,
    }


def match_organization(
    person_tags: list[dict[str, Any]],
    organization_lookup: OrganizationLookup,
) -> tuple[dict[str, Any] | None, str | None]:
    tag_id_matches: list[dict[str, Any]] = []
    tag_name_matches: list[dict[str, Any]] = []
    for tag in person_tags:
        tag_id = as_int(tag.get("id") or tag.get("tag_id"))
        tag_name = normalize_tag_name(tag)
        if tag_id is not None and tag_id in organization_lookup.by_tag_id:
            tag_id_matches.append(organization_lookup.by_tag_id[tag_id])
        if tag_name and tag_name in organization_lookup.by_tag_name:
            tag_name_matches.append(organization_lookup.by_tag_name[tag_name])

    if tag_id_matches:
        return prefer_national_society(tag_id_matches), "person_tag_id_to_organization_tag"
    if tag_name_matches:
        return prefer_national_society(tag_name_matches), "person_tag_to_organization_tag"
    return None, None


def prefer_national_society(matches: list[dict[str, Any]]) -> dict[str, Any]:
    for match in matches:
        tag_name = match.get("tag_name")
        if isinstance(tag_name, str) and tag_name.startswith("RC."):
            return match
    return matches[0]


def extract_sex_or_gender(person_detail: Mapping[str, Any]) -> Any:
    value = person_detail.get("sex")
    if value in (None, ""):
        value = person_detail.get("gender")
    if isinstance(value, Mapping):
        return value.get("name") or value.get("label") or value.get("value")
    return value


def first_tag_in_group(
    tags: list[dict[str, Any]],
    group_name: str,
    *,
    allowed_values: set[str] | None = None,
    prefix: str | None = None,
) -> dict[str, Any] | None:
    for tag in tags:
        tag_name = normalize_tag_name(tag)
        if not tag_name:
            continue
        if not tag_has_group(tag, group_name):
            continue
        if allowed_values is not None and tag_name not in allowed_values:
            continue
        if prefix is not None and not tag_name.startswith(prefix):
            continue
        return tag
    return None


def first_tag_name_in_group(
    tags: list[dict[str, Any]],
    group_name: str,
    *,
    allowed_values: set[str] | None = None,
    prefix: str | None = None,
) -> str | None:
    tag = first_tag_in_group(tags, group_name, allowed_values=allowed_values, prefix=prefix)
    return normalize_tag_name(tag) if tag else None


def tag_has_group(tag: Mapping[str, Any], group_name: str) -> bool:
    expected = normalize_group_name(group_name)
    return any(normalize_group_name(group) == expected for group in tag_groups(tag))


def tag_groups(tag: Mapping[str, Any]) -> list[str]:
    groups = tag.get("groups") or tag.get("group")
    if isinstance(groups, str):
        return [groups]
    if isinstance(groups, Mapping):
        return [str(display_value(groups) or "")]
    if not isinstance(groups, list):
        return []
    output: list[str] = []
    for group in groups:
        if isinstance(group, Mapping):
            value = display_value(group)
            if value:
                output.append(str(value))
        elif group not in (None, ""):
            output.append(str(group))
    return output


def normalize_group_name(value: Any) -> str:
    return normalize_text(value).replace("_", "-")


def subregion_label_from_tag(tag: Mapping[str, Any] | None) -> str | None:
    if tag is None:
        return None
    description = display_value(tag.get("description"))
    if isinstance(description, str) and description.strip():
        if ":" in description:
            return description.split(":", 1)[1].strip() or None
        return description.strip()
    tag_name = normalize_tag_name(tag)
    return tag_name or None


def tag_display_name(tag: Mapping[str, Any] | None) -> str | None:
    if tag is None:
        return None
    value = display_value(tag.get("name") or tag.get("label") or tag.get("tag_name"))
    if value in (None, ""):
        return None
    return str(value).strip()


def extract_language_tags(tags: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    codes: list[str] = []
    names: list[str] = []
    for tag in tags:
        tag_name = normalize_tag_name(tag)
        if not tag_name:
            continue
        if not tag_has_group(tag, "LANGUAGE") and not tag_name.startswith(LANGUAGE_CODE_PREFIX):
            continue
        codes.append(tag_name)
        description = display_value(tag.get("description"))
        if description:
            names.append(str(description).strip())
    return unique_nonblank(codes), unique_nonblank(names)


def extract_language_names(languages: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for language in languages:
        value = language.get("language")
        if isinstance(value, Mapping):
            label = display_value(value)
        else:
            label = display_value(value)
        if label:
            names.append(str(label).strip())
    return unique_nonblank(names)


def extract_person_training_tags(tags: list[dict[str, Any]]) -> list[str]:
    training_tags: list[str] = []
    for tag in tags:
        if not (tag_has_group(tag, "training") or tag_has_group(tag, "Surge Trainings")):
            continue
        tag_name = display_value(tag.get("name") or tag.get("label") or tag.get("tag_name"))
        if tag_name:
            training_tags.append(str(tag_name).strip())
    return unique_nonblank(training_tags)


def unique_nonblank(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in (None, ""):
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def display_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        for key in ("name", "title", "label", "value", "code", "id"):
            candidate = value.get(key)
            if candidate not in (None, "") and not isinstance(candidate, (Mapping, list)):
                return candidate
        return None
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if not isinstance(item, (Mapping, list)))
    return value


def extract_tags(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    tags = value.get("tags") or value.get("tag") or []
    if isinstance(tags, Mapping):
        tags = tags.get("data") or tags.get("items") or []
    if not isinstance(tags, list):
        return []
    return [tag for tag in tags if isinstance(tag, dict)]


def best_event_tag_name(event_name: Any, tags: list[dict[str, Any]]) -> str | None:
    if not tags:
        return None

    normalized_event_name = normalize_text(event_name)
    if normalized_event_name:
        for tag in tags:
            tag_name = normalize_tag_name(tag)
            tag_description = normalize_text(tag.get("description"))
            if tag_description and tag_description in normalized_event_name:
                return tag_name or None
            if tag_name and re.search(rf"\b{re.escape(tag_name)}\b", normalized_event_name):
                return tag_name

    return best_fuzzy_event_tag_name(normalized_event_name, tags)


def event_tag_name_from_name(event_name: Any) -> str | None:
    text = normalize_text(event_name)
    if not text:
        return None

    leading_match = re.match(r"^([A-Z][A-Z0-9/-]{1,14})\s*(?:-|–|—|:)\s+\S+", text)
    if leading_match:
        candidate = leading_match.group(1).strip("/-")
        if is_likely_event_code(candidate):
            return candidate

    parenthetical_matches = re.findall(r"\(([A-Z][A-Z0-9/-]{1,14})\)", text)
    for candidate in parenthetical_matches:
        if is_likely_event_code(candidate):
            return candidate

    return None


def is_likely_event_code(candidate: str) -> bool:
    if not candidate or candidate in GENERIC_EVENT_NAME_PREFIXES:
        return False
    if candidate in EVENT_TAG_STOPWORDS:
        return False
    if len(candidate) > 8 and "/" not in candidate and "-" not in candidate:
        return False
    return bool(re.search(r"[A-Z]", candidate))


def best_fuzzy_event_tag_name(normalized_event_name: str, tags: list[dict[str, Any]]) -> str | None:
    event_tokens = tokenize_for_tag_match(normalized_event_name)
    if len(event_tokens) < 2:
        return None

    best_name: str | None = None
    best_score = 0.0
    best_overlap = 0
    for tag in tags:
        tag_name = normalize_tag_name(tag)
        if not tag_name or tag_name in GENERIC_FUZZY_EVENT_TAGS:
            continue

        description_tokens = tokenize_for_tag_match(tag.get("description"))
        if not description_tokens:
            continue
        overlap = len(event_tokens & description_tokens)
        if overlap < 2:
            continue

        coverage = overlap / len(description_tokens)
        precision = overlap / len(event_tokens)
        score = (coverage * 0.7) + (precision * 0.3)
        if score > best_score:
            best_name = tag_name
            best_score = score
            best_overlap = overlap

    if best_name and best_overlap >= 2 and best_score >= 0.42:
        return best_name
    return None


def tokenize_for_tag_match(value: Any) -> set[str]:
    text = normalize_text(value)
    tokens = set()
    for token in re.findall(r"[A-Z0-9]+", text):
        if token in EVENT_TAG_STOPWORDS or len(token) < 3:
            continue
        tokens.add(singularize_token(token))
    return tokens


def singularize_token(token: str) -> str:
    if token.endswith("IES") and len(token) > 4:
        return token[:-3] + "Y"
    if token.endswith("S") and not token.endswith("SS") and len(token) > 3:
        return token[:-1]
    return token


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().upper())


def normalize_tag_name(tag: Mapping[str, Any]) -> str:
    value = tag.get("name") or tag.get("tag_name") or tag.get("tag")
    if value is None:
        return ""
    return str(value).strip().upper()


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
