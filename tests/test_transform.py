from surge_data_loader.transform import (
    best_event_tag_name,
    build_organization_lookup,
    collect_person_ids,
    enrich_person,
    event_tag_name_from_name,
    extract_sex_or_gender,
    transform_event,
)


def test_event_transform_keeps_participants_nested_and_uses_pivot():
    event = {
        "id": 7412,
        "name": "PECT training",
        "type": "course",
        "updated_at": "2026-07-02T12:00:00.000000Z",
        "tags": [
            {
                "id": 3555,
                "name": "PECT",
                "description": "Practical Cash Transfers in Emergencies (PECT) Training",
            }
        ],
        "person": [
            {
                "id": 5603,
                "pivot": {
                    "person_id": 5603,
                    "role": "participant",
                    "requested": False,
                    "start": None,
                    "end": None,
                    "result": None,
                    "waitlist": False,
                },
            }
        ],
    }

    output = transform_event(
        event,
        person_enrichment={
            5603: {
                "sex_or_gender": "female",
                "region_tag": "EURO",
                "region_label": "Europe Region",
                "subregion_tag": "EU-SE",
                "subregion_label": "South Europe",
                "language_codes": ["L-ENG"],
                "language_names": ["English"],
                "person_training_tags": ["Induction"],
                "national_society_tag": "RC.NL",
                "national_society_name": "The Netherlands Red Cross",
                "matched_organization_id": 124,
                "matched_organization_name": "The Netherlands Red Cross",
                "organization_match_method": "person_tag_to_organization_tag",
            }
        },
    )

    assert output["event_id"] == 7412
    assert output["event_updated_at"] == "2026-07-02T12:00:00.000000Z"
    assert output["event_tag_name"] == "PECT"
    assert output["event_tag_name_N"] is None
    assert "event_tags" not in output
    assert output["participants"] == [
        {
            "person_id": 5603,
            "role": "participant",
            "requested": False,
            "participant_start": None,
            "participant_end": None,
            "result": None,
            "waitlist": False,
            "sex_or_gender": "female",
            "region_tag": "EURO",
            "region_label": "Europe Region",
            "subregion_tag": "EU-SE",
            "subregion_label": "South Europe",
            "language_codes": ["L-ENG"],
            "language_names": ["English"],
            "person_training_tags": ["Induction"],
            "national_society_tag": "RC.NL",
            "national_society_name": "The Netherlands Red Cross",
            "matched_organization_id": 124,
            "matched_organization_name": "The Netherlands Red Cross",
        }
    ]


def test_collect_person_ids_from_pivot():
    events = [{"person": [{"id": 1, "pivot": {"person_id": "42"}}]}]
    assert collect_person_ids(events) == {42}


def test_enrich_person_extracts_region_ns_and_prefers_rc_org_match():
    organizations = [
        {"id": 10, "name": "Europe Office", "tags": [{"id": 1, "name": "EURO"}]},
        {
            "id": 124,
            "name": "The Netherlands Red Cross",
            "tags": [{"id": 2, "name": "RC.NL"}],
        },
    ]
    lookup = build_organization_lookup(organizations)

    enriched = enrich_person(
        person_tags=[
            {"id": 1, "name": "EURO", "groups": ["REGION"]},
            {"id": 2, "name": "RC.NL", "groups": ["NATIONAL SOCIETIES"]},
        ],
        person_detail={"gender": {"name": "female"}, "email": "ignored@example.org"},
        organization_lookup=lookup,
    )

    assert enriched["region_tag"] == "EURO"
    assert enriched["region_label"] == "Europe Region"
    assert enriched["national_society_tag"] == "RC.NL"
    assert enriched["national_society_name"] == "The Netherlands Red Cross"
    assert enriched["matched_organization_id"] == 124
    assert enriched["sex_or_gender"] == "female"


def test_enrich_person_extracts_tag_groups_languages_and_training_tags():
    lookup = build_organization_lookup([])

    enriched = enrich_person(
        person_tags=[
            {
                "id": 1,
                "name": "AP-Pacific",
                "description": "ASIAP Sub-region: Pacific",
                "groups": ["SUB-REGION"],
            },
            {"id": 2, "name": "L-ENG", "description": "English", "groups": ["LANGUAGE"]},
            {"id": 3, "name": "L-FRA", "description": "French", "groups": ["LANGUAGE"]},
            {
                "id": 4,
                "name": "TAF",
                "description": "Train. Assess. Facilitate. (TAF) Training",
                "groups": ["training", "Surge Trainings"],
            },
        ],
        person_languages=[
            {"language": "English", "language_id": 1},
            {"language": {"name": "French"}, "language_id": 2},
        ],
        person_detail={},
        organization_lookup=lookup,
    )

    assert enriched["subregion_tag"] == "AP-Pacific"
    assert enriched["subregion_label"] == "Pacific"
    assert enriched["language_codes"] == ["L-ENG", "L-FRA"]
    assert enriched["language_names"] == ["English", "French"]
    assert enriched["person_training_tags"] == ["TAF"]


def test_extract_sex_or_gender_uses_only_allowed_fields():
    assert extract_sex_or_gender({"sex": "male", "fullname": "Should Not Matter"}) == "male"


def test_best_event_tag_name_matches_description_inside_event_name():
    assert (
        best_event_tag_name(
            "MOT- Managing IFRC Operations",
            [
                {"name": "AVAIL", "description": "Available For Deployment"},
                {"name": "MOT", "description": "Managing IFRC Operations"},
            ],
        )
        == "MOT"
    )


def test_best_event_tag_name_uses_tag_name_in_event_name():
    assert (
        best_event_tag_name(
            "PECT training",
            [
                {"name": "AVAIL", "description": "Available For Deployment"},
                {"name": "PECT", "description": "Practical Cash Transfers in Emergencies"},
            ],
        )
        == "PECT"
    )


def test_best_event_tag_name_does_not_fall_back_to_unmatched_first_tag():
    assert (
        best_event_tag_name(
            "PECT training",
            [
                {"name": "AVAIL", "description": "Available For Deployment"},
                {"name": "CVA", "description": "Cash & Voucher Assistance"},
            ],
        )
        is None
    )


def test_best_event_tag_name_fuzzy_matches_similar_description():
    assert (
        best_event_tag_name(
            "Practical Emergency Cash Transfer (PECT) training, Jakarta",
            [
                {"name": "AVAIL", "description": "Available For Deployment"},
                {"name": "PECT", "description": "Practical Cash Transfers in Emergencies"},
            ],
        )
        == "PECT"
    )


def test_best_event_tag_name_fuzzy_ignores_generic_tags():
    assert (
        best_event_tag_name(
            "Asia Pacific leadership training",
            [
                {"name": "ASIAP", "description": "Asia Pacific Region"},
                {"name": "AVAIL", "description": "Available For Deployment"},
            ],
        )
        is None
    )


def test_event_tag_name_from_name_extracts_leading_code():
    assert event_tag_name_from_name("MOT - Managing IFRC Operations") == "MOT"


def test_event_tag_name_from_name_extracts_parenthetical_code():
    assert event_tag_name_from_name("Emergency Team Leader (ETL) training 2023") == "ETL"


def test_event_tag_name_from_name_ignores_plain_titles():
    assert event_tag_name_from_name("Emergency WASH Training, Fiji") is None


def test_event_tag_name_from_name_ignores_language_prefixes():
    assert event_tag_name_from_name("Spanish - Emergency response training") is None
