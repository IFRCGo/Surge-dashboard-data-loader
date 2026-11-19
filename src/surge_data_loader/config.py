from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_LOGIN_URL = "https://rrms.ifrc.org/api/api/login"
DEFAULT_EVENTS_API_ROOT = "https://rrms.ifrc.org/api/api/events"
DEFAULT_ORGANIZATIONS_URL = "https://rrms.ifrc.org/api/api/system/organizations"
DEFAULT_TRAINING_METRICS_URL = "https://rrms.ifrc.org/api/api/v1/training-metrics"


@dataclass(frozen=True)
class LoaderConfig:
    username: str
    password: str
    site_root: str = "https://rrms.ifrc.org"
    login_url: str = DEFAULT_LOGIN_URL
    events_api_root: str = DEFAULT_EVENTS_API_ROOT
    organizations_url: str = DEFAULT_ORGANIZATIONS_URL
    request_timeout: float = 30.0
    person_workers: int = 4
    request_retries: int = 5


@dataclass(frozen=True)
class TrainingMetricsConfig:
    url: str = DEFAULT_TRAINING_METRICS_URL
    api_token: str = ""
    request_timeout: float = 30.0
    request_retries: int = 5


def load_dotenv(path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE entries from .env without overriding the process env."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def config_from_env() -> LoaderConfig:
    username = os.getenv("RRMS_USERNAME")
    password = os.getenv("RRMS_PASSWORD")
    missing = [
        name
        for name, value in (("RRMS_USERNAME", username), ("RRMS_PASSWORD", password))
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + ". Put them in a local .env file or GitHub repository secrets."
        )

    timeout_raw = os.getenv("RRMS_REQUEST_TIMEOUT", "30")
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:
        raise RuntimeError("RRMS_REQUEST_TIMEOUT must be a number of seconds.") from exc

    workers_raw = os.getenv("RRMS_PERSON_WORKERS", "4")
    try:
        person_workers = int(workers_raw)
    except ValueError as exc:
        raise RuntimeError("RRMS_PERSON_WORKERS must be an integer.") from exc
    if person_workers < 1:
        raise RuntimeError("RRMS_PERSON_WORKERS must be at least 1.")

    retries_raw = os.getenv("RRMS_REQUEST_RETRIES", "5")
    try:
        request_retries = int(retries_raw)
    except ValueError as exc:
        raise RuntimeError("RRMS_REQUEST_RETRIES must be an integer.") from exc
    if request_retries < 0:
        raise RuntimeError("RRMS_REQUEST_RETRIES must be zero or greater.")

    return LoaderConfig(
        username=username or "",
        password=password or "",
        site_root=os.getenv("RRMS_SITE_ROOT", "https://rrms.ifrc.org").rstrip("/"),
        login_url=os.getenv("RRMS_LOGIN_URL", DEFAULT_LOGIN_URL),
        events_api_root=os.getenv("RRMS_EVENTS_API_ROOT", DEFAULT_EVENTS_API_ROOT),
        organizations_url=os.getenv("RRMS_ORGANIZATIONS_URL", DEFAULT_ORGANIZATIONS_URL),
        request_timeout=timeout,
        person_workers=person_workers,
        request_retries=request_retries,
    )


def training_metrics_config_from_env() -> TrainingMetricsConfig:
    api_token = training_metrics_api_token_from_env()
    if not api_token:
        raise RuntimeError(
            "Missing required environment variable: TRAINING_METRICS_API_TOKEN. "
            "Put it in a local .env file or GitHub repository secrets."
        )

    timeout_raw = os.getenv("RRMS_REQUEST_TIMEOUT", "30")
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:
        raise RuntimeError("RRMS_REQUEST_TIMEOUT must be a number of seconds.") from exc

    retries_raw = os.getenv("RRMS_REQUEST_RETRIES", "5")
    try:
        request_retries = int(retries_raw)
    except ValueError as exc:
        raise RuntimeError("RRMS_REQUEST_RETRIES must be an integer.") from exc
    if request_retries < 0:
        raise RuntimeError("RRMS_REQUEST_RETRIES must be zero or greater.")

    return TrainingMetricsConfig(
        url=os.getenv("TRAINING_METRICS_URL", DEFAULT_TRAINING_METRICS_URL),
        api_token=api_token,
        request_timeout=timeout,
        request_retries=request_retries,
    )


def training_metrics_api_token_from_env() -> str:
    for name in ("TRAINING_METRICS_API_TOKEN", "training_metric_api_token"):
        raw_value = os.getenv(name)
        if raw_value:
            return normalize_training_metrics_api_token(raw_value)
    return ""


def normalize_training_metrics_api_token(raw_value: str) -> str:
    return raw_value.strip().strip('"').strip("'").replace("-", "")
