from __future__ import annotations

import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import TrainingMetricsConfig
from .pii import validate_no_forbidden_fields


OUTPUT_DIR = Path("data/powerbi")
TRAINING_METRICS_OUTPUT = OUTPUT_DIR / "training_metrics.json"
TRAINING_METRICS_MANIFEST_OUTPUT = OUTPUT_DIR / "training_metrics_manifest.json"


class TrainingMetricsError(RuntimeError):
    """Raised when the training metrics endpoint returns an unusable response."""


AUTH_HEADER_VARIANTS = (
    ("Authorization", lambda token: f"Bearer {token}"),
    ("Authorization", lambda token: f"Token {token}"),
    ("Api-Token", lambda token: token),
)


def fetch_training_metrics(
    config: TrainingMetricsConfig,
    *,
    access_token: str,
    verbose: bool = False,
) -> Any:
    last_error: Exception | None = None
    for header_name, header_value_factory in AUTH_HEADER_VARIANTS:
        headers = {
            "Accept": "application/json",
            header_name: header_value_factory(access_token),
        }
        request = Request(config.url, headers=headers, method="GET")
        try:
            raw = send_with_retries(
                request,
                method="GET",
                url=config.url,
                timeout=config.request_timeout,
                retries=config.request_retries,
                verbose=verbose,
            )
            return json.loads(raw)
        except (TrainingMetricsError, json.JSONDecodeError) as exc:
            last_error = exc
            if verbose:
                print(f"Training metrics auth variant {header_name} failed: {exc}")

    if isinstance(last_error, json.JSONDecodeError):
        raise TrainingMetricsError(f"GET {config.url} did not return valid JSON.") from last_error
    raise TrainingMetricsError(
        f"GET {config.url} failed for all auth header variants using the RRMS login token."
    ) from last_error


def run_training_metrics_fetch(
    config: TrainingMetricsConfig,
    *,
    access_token: str,
    verbose: bool = False,
) -> dict[str, Any]:
    started_at = now_utc()
    payload = fetch_training_metrics(config, access_token=access_token, verbose=verbose)
    validate_no_forbidden_fields(payload)

    manifest = {
        "started_at": started_at,
        "finished_at": now_utc(),
        "endpoint": config.url,
        "output_file": str(TRAINING_METRICS_OUTPUT).replace("\\", "/"),
        "top_level_type": type(payload).__name__,
        "top_level_count": top_level_count(payload),
        "personal_fields_saved": False,
        "errors": [],
    }
    validate_no_forbidden_fields(manifest)
    write_training_metrics_outputs(payload, manifest)
    return manifest


def write_training_metrics_outputs(payload: Any, manifest: Mapping[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TRAINING_METRICS_OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    TRAINING_METRICS_MANIFEST_OUTPUT.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def send_with_retries(
    request: Request,
    *,
    method: str,
    url: str,
    timeout: float,
    retries: int,
    verbose: bool,
) -> str:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = TrainingMetricsError(
                f"{method} {url} failed with HTTP {exc.code}: {detail}"
            )
            if exc.code not in {429, 500, 502, 503, 504} or attempt >= retries:
                raise last_error from exc
            sleep_seconds = retry_sleep_seconds(exc, attempt)
            if verbose:
                print(f"{method} {url} returned HTTP {exc.code}; retrying in {sleep_seconds:.1f}s.")
            time.sleep(sleep_seconds)
        except URLError as exc:
            last_error = TrainingMetricsError(f"{method} {url} failed: {exc.reason}")
            if attempt >= retries:
                raise last_error from exc
            sleep_seconds = float(min(2**attempt, 30))
            if verbose:
                print(f"{method} {url} failed; retrying in {sleep_seconds:.1f}s.")
            time.sleep(sleep_seconds)

    raise last_error or TrainingMetricsError(f"{method} {url} failed.")


def retry_sleep_seconds(exc: HTTPError, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), 60.0)
        except ValueError:
            pass
    return float(min(2**attempt, 30))


def top_level_count(payload: Any) -> int | None:
    if isinstance(payload, (list, tuple)):
        return len(payload)
    if isinstance(payload, Mapping):
        for key in ("data", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        return len(payload)
    return None


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
