from surge_data_loader.runner import (
    build_dashboard_summary,
    build_trainings_facilitator_model,
    count_participant_links,
    event_changed,
    merge_events,
    sparse_json_value,
)


def test_event_changed_uses_updated_at_when_both_are_available():
    assert event_changed(
        {"id": 1, "updated_at": "2026-07-02T12:01:00Z"},
        {"event_id": 1, "event_updated_at": "2026-07-02T12:00:00Z"},
    )


def test_event_changed_treats_legacy_existing_event_as_unchanged():
    assert not event_changed(
        {"id": 1, "updated_at": "2026-07-02T12:01:00Z"},
        {"event_id": 1},
    )


def test_event_changed_backfills_existing_events_missing_current_fields():
    assert event_changed(
        {"id": 1, "updated_at": "2026-07-02T12:01:00Z"},
        {
            "event_id": 1,
            "event_updated_at": "2026-07-02T12:01:00Z",
            "participants": [{"person_id": 2, "role": "participant"}],
        },
    )


def test_merge_events_replaces_existing_event_and_appends_new_event():
    merged = merge_events(
        [
            {"event_id": 1, "event_name": "old", "event_from": "2024-01-01"},
            {"event_id": 2, "event_name": "same", "event_from": "2024-01-02"},
        ],
        [
            {"event_id": 1, "event_name": "new", "event_from": "2024-01-03"},
            {"event_id": 3, "event_name": "added", "event_from": "2024-01-04"},
        ],
    )

    assert {event["event_id"] for event in merged} == {1, 2, 3}
    assert next(event for event in merged if event["event_id"] == 1)["event_name"] == "new"


def test_count_participant_links_treats_missing_participants_as_empty():
    assert (
        count_participant_links(
            [
                {"event_id": 1, "participants": [{"person_id": 10}]},
                {"event_id": 2},
                {"event_id": 3, "participants": []},
            ]
        )
        == 1
    )


def test_build_dashboard_summary_includes_visuals_and_slicers():
    summary = build_dashboard_summary(
        [
            {
                "event_id": 1,
                "event_tag_name": "MOT",
                "event_tag_name_N": None,
                "event_type": "scheduled",
                "event_venue": "Dubai",
                "participants": [
                    {
                        "person_id": 10,
                        "role": "participant",
                        "participant_start": "2024-01-01T00:00:00Z",
                        "sex_or_gender": "female",
                        "region_label": "Europe Region",
                        "subregion_label": "South Europe",
                        "matched_organization_name": "The Netherlands Red Cross",
                        "national_society_name": "The Netherlands Red Cross",
                        "language_names": ["English"],
                        "person_training_tags": ["TAF"],
                    },
                    {
                        "person_id": 11,
                        "role": "trainer",
                        "participant_start": "2024-01-02T00:00:00Z",
                        "sex_or_gender": "male",
                        "region_label": "Africa Region",
                        "subregion_label": "East Africa",
                        "matched_organization_name": "IFRC Africa",
                        "language_names": ["French"],
                        "person_training_tags": ["Induction"],
                    },
                    {
                        "person_id": 12,
                        "role": "participant",
                        "participant_start": "2024-01-03T00:00:00Z",
                        "sex_or_gender": "other",
                        "language_names": ["Spanish"],
                        "person_training_tags": ["PECT"],
                    },
                ],
            }
        ]
    )

    assert summary["cards"]["trainings"] == 1
    assert summary["cards"]["people_trained"] == 3
    assert summary["visuals"]["participants_by_role"] == [
        {"role": "participant", "participant_links": 2, "unique_people": 2},
        {"role": "trainer", "participant_links": 1, "unique_people": 1},
    ]
    assert summary["visuals"]["participants_by_organisation_type"] == [
        {
            "organisation_type": "National Society",
            "participant_links": 1,
            "unique_people": 1,
        },
        {"organisation_type": "IFRC", "participant_links": 1, "unique_people": 1},
        {"organisation_type": "Other", "participant_links": 1, "unique_people": 1},
    ]
    assert summary["visuals"]["participants_by_language"] == [
        {"language": "English", "participant_links": 1, "unique_people": 1},
        {"language": "French", "participant_links": 1, "unique_people": 1},
        {"language": "Spanish", "participant_links": 1, "unique_people": 1},
    ]
    assert summary["visuals"]["participants_by_person_training_tag"] == [
        {"person_training_tag": "Induction", "participant_links": 1, "unique_people": 1},
        {"person_training_tag": "CAP", "participant_links": 0, "unique_people": 0},
        {"person_training_tag": "ETL", "participant_links": 0, "unique_people": 0},
        {"person_training_tag": "MOT", "participant_links": 0, "unique_people": 0},
        {"person_training_tag": "TAF", "participant_links": 1, "unique_people": 1},
    ]
    assert summary["slicers"]["language"] == ["English", "French", "Spanish"]
    assert summary["slicers"]["event_role"] == ["participant", "trainer"]
    assert summary["slicers"]["time"]["years"] == ["2024"]


def test_build_trainings_facilitator_model_has_filterable_tables():
    model = build_trainings_facilitator_model(
        [
            {
                "event_id": 1,
                "event_name": "MOT - Managing IFRC Operations",
                "event_tag_name": "MOT",
                "event_type": "scheduled",
                "event_from": "2024-01-01T00:00:00Z",
                "participants": [
                    {
                        "person_id": 10,
                        "role": "participant",
                        "participant_start": "2024-01-02T00:00:00Z",
                        "sex_or_gender": "female",
                        "region_label": "Europe Region",
                        "subregion_label": "South Europe",
                        "matched_organization_name": "The Netherlands Red Cross",
                        "national_society_name": "The Netherlands Red Cross",
                        "language_names": ["English", "French"],
                        "person_training_tags": ["TAF", "PECT"],
                    }
                ],
            }
        ]
    )

    assert model["tables"]["events"] == {
        "columns": [
            "event_id",
            "event_name",
            "event_training_type",
            "event_type",
            "event_from",
            "event_to",
            "event_venue",
            "event_organization",
        ],
        "rows": [
            [
                1,
                "MOT - Managing IFRC Operations",
                "MOT",
                "scheduled",
                "2024-01-01T00:00:00Z",
                None,
                None,
                None,
            ]
        ],
    }
    assert model["tables"]["participants"] == {
        "columns": [
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
        "rows": [
            [
                1,
                1,
                10,
                "participant",
                "2024-01-02T00:00:00Z",
                "female",
                "Europe Region",
                "South Europe",
                "The Netherlands Red Cross",
                "National Society",
            ]
        ],
    }
    assert model["tables"]["participant_languages"] == {
        "columns": ["participation_id", "language_name"],
        "rows": [[1, "English"], [1, "French"]],
    }
    assert model["tables"]["participant_training_tags"] == {
        "columns": ["participation_id", "person_training_tag"],
        "rows": [[1, "TAF"]],
    }
    assert model["tables"]["training_tag_categories"] == {
        "columns": ["person_training_tag"],
        "rows": [["Induction"], ["CAP"], ["ETL"], ["MOT"], ["TAF"]],
    }


def test_sparse_json_value_removes_only_empty_values():
    assert sparse_json_value(
        {
            "event_id": 1,
            "event_from": None,
            "event_name": "",
            "event_scale_type": "scheduled",
            "participants": [
                {
                    "person_id": 10,
                    "requested": False,
                    "waitlist": False,
                    "role": "participant",
                    "language_names": [],
                    "subregion_label": None,
                    "person_training_tags": ["TAF"],
                }
            ],
        }
    ) == {
        "event_id": 1,
        "event_scale_type": "scheduled",
        "participants": [
            {
                "person_id": 10,
                "requested": False,
                "waitlist": False,
                "role": "participant",
                "person_training_tags": ["TAF"],
            }
        ],
    }
