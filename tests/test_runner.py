from surge_data_loader.runner import event_changed, merge_events


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
