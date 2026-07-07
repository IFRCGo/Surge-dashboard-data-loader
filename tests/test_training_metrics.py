import json

from surge_data_loader.config import (
    normalize_training_metrics_api_token,
    training_metrics_config_from_env,
)
from surge_data_loader import training_metrics as metrics
from surge_data_loader.config import TrainingMetricsConfig


def test_normalize_training_metrics_api_token_removes_hyphens():
    assert normalize_training_metrics_api_token(" 'abc-def' ") == "abcdef"


def test_training_metrics_config_accepts_lowercase_legacy_env_name(monkeypatch):
    monkeypatch.delenv("TRAINING_METRICS_API_TOKEN", raising=False)
    monkeypatch.setenv("training_metric_api_token", "abc-def")

    config = training_metrics_config_from_env()

    assert config.api_token == "abcdef"


def test_incremental_training_metrics_skips_unchanged_output(monkeypatch, tmp_path):
    output_path = tmp_path / "training_metrics.json"
    manifest_path = tmp_path / "training_metrics_manifest.json"
    payload = {"metrics": {"participants": {"value": 2, "participations": 3}}}

    monkeypatch.setattr(metrics, "TRAINING_METRICS_OUTPUT", output_path)
    monkeypatch.setattr(metrics, "TRAINING_METRICS_MANIFEST_OUTPUT", manifest_path)
    monkeypatch.setattr(metrics, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(metrics, "fetch_training_metrics", lambda config, verbose=False: payload)

    config = TrainingMetricsConfig(url="https://example.test/metrics", api_token="abcdef")
    first_manifest = metrics.run_training_metrics_fetch(config, incremental=True)
    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    second_manifest = metrics.run_training_metrics_fetch(config, incremental=True)

    assert first_manifest["output_written"] is True
    assert saved_manifest["payload_sha256"] == first_manifest["payload_sha256"]
    assert second_manifest["output_written"] is False
    assert second_manifest["unchanged_existing_output"] is True
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == saved_manifest
