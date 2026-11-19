from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_TRAINING_METRICS_URL = (
    "https://rrms.ifrc.org/api/api/v1/training-metrics"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Probe the training metrics endpoint with the Api-Token "
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually send the requests. Without this, only prints the request plan.",
    )
    parser.add_argument(
        "--preview-bytes",
        type=int,
        default=1200,
        help="Response body preview length for failed or successful metric requests.",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    metrics_url = os.getenv("TRAINING_METRICS_URL", DEFAULT_TRAINING_METRICS_URL)
    api_token = normalize_api_token(os.getenv("TRAINING_METRICS_API_TOKEN", ""))
    timeout = float(os.getenv("RRMS_REQUEST_TIMEOUT", "30"))

    print("Training metrics probe")
    print(f"Metrics URL: {metrics_url}")
    print("Metrics method: GET")
    print("Header: Api-Token: <TRAINING_METRICS_API_TOKEN>")

    if not args.execute:
        print("\nDry run only. Add --execute to send the requests.")
        return 0

    if not api_token:
        print("Missing environment variable: TRAINING_METRICS_API_TOKEN", file=sys.stderr)
        return 2

    print(f"\nGET {metrics_url}")
    print("Trying header: Api-Token: <TRAINING_METRICS_API_TOKEN>")
    try:
        status, response_headers, body = get_json_endpoint(
            url=metrics_url,
            headers={
                "Accept": "application/json",
                "Api-Token": api_token,
            },
            timeout=timeout,
        )
    except RuntimeError as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    print(f"HTTP status: {status}")
    print(f"Content-Type: {response_headers.get('Content-Type', '(missing)')}")
    print(f"Body preview ({min(len(body), args.preview_bytes)} bytes):")
    print(body[: args.preview_bytes])
    if is_json(body):
        print("Response parsed as JSON.")
        return 0
    print("Response was not valid JSON.", file=sys.stderr)
    return 1


def load_dotenv(path: Path = Path(".env")) -> None:
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


def get_json_endpoint(
    *,
    url: str,
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, dict[str, str], str]:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, dict(response.headers.items()), body
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def is_json(body: str) -> bool:
    try:
        json.loads(body)
    except json.JSONDecodeError:
        return False
    return True


def normalize_api_token(raw_value: str) -> str:
    return raw_value.strip().strip('"').strip("'").replace("-", "")


if __name__ == "__main__":
    raise SystemExit(main())
