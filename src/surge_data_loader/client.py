from __future__ import annotations

import json
import time
from collections.abc import Iterator, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from urllib.request import Request, urlopen

from .auth import parse_access_token
from .config import LoaderConfig


JsonObject = dict[str, Any]


class RRMSClientError(RuntimeError):
    """Raised when RRMS/Molnix returns an unusable response."""


class RRMSClient:
    def __init__(self, config: LoaderConfig, verbose: bool = False):
        self.config = config
        self.verbose = verbose
        self._access_token: str | None = None

    @property
    def access_token(self) -> str:
        if not self._access_token:
            self._access_token = self.login()
        return self._access_token

    def login(self) -> str:
        payload = {
            "username": self.config.username,
            "password": self.config.password,
        }
        response = self._request_json(
            "POST",
            self.config.login_url,
            body=payload,
            authorized=False,
        )
        return parse_access_token(response)

    def fetch_organizations(self) -> list[JsonObject]:
        payload = self._request_json("GET", self.config.organizations_url)
        return extract_list_payload(payload)

    def fetch_person_tags(self, person_id: int) -> list[JsonObject]:
        payload = self._request_json("GET", self.people_url(person_id, suffix="tags"))
        return extract_list_payload(payload)

    def fetch_person_detail(self, person_id: int) -> JsonObject:
        payload = self._request_json("GET", self.people_url(person_id))
        if isinstance(payload, Mapping) and isinstance(payload.get("data"), Mapping):
            return dict(payload["data"])
        if isinstance(payload, Mapping):
            return dict(payload)
        return {}

    def people_url(self, person_id: int, *, suffix: str | None = None) -> str:
        path = f"{self.config.site_root}/api/api/people/{person_id}"
        if suffix:
            path += f"/{suffix}"
        return path

    def iter_event_pages(
        self,
        *,
        max_pages: int | None,
        all_pages: bool,
    ) -> Iterator[tuple[int, list[JsonObject]]]:
        page = 1
        pages_fetched = 0
        while True:
            if max_pages is not None and pages_fetched >= max_pages:
                break
            url = with_query_param(self.config.events_api_root, "page", str(page))
            if self.verbose:
                print(f"Fetching events page {page}: {url}", flush=True)
            payload = self._request_json("GET", url)
            events = extract_list_payload(payload)
            if not events:
                break
            yield page, events
            pages_fetched += 1
            if not all_pages and max_pages is None:
                break
            if not all_pages and max_pages is not None and pages_fetched >= max_pages:
                break
            if all_pages and not has_next_page(payload, current_page=page):
                break
            page += 1

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        body: Mapping[str, Any] | None = None,
        authorized: bool = True,
    ) -> Any:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if authorized:
            headers["Authorization"] = f"Bearer {self.access_token}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(url, data=data, headers=headers, method=method)
        raw = self._send_with_retries(request, method, url)

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RRMSClientError(f"{method} {url} did not return valid JSON.") from exc
        return parsed

    def _send_with_retries(self, request: Request, method: str, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.config.request_retries + 1):
            try:
                with urlopen(request, timeout=self.config.request_timeout) as response:
                    return response.read().decode("utf-8")
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                last_error = RRMSClientError(
                    f"{method} {url} failed with HTTP {exc.code}: {detail}"
                )
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= self.config.request_retries:
                    raise last_error from exc
                sleep_seconds = retry_sleep_seconds(exc, attempt)
                if self.verbose:
                    print(
                        f"{method} {url} returned HTTP {exc.code}; retrying in {sleep_seconds:.1f}s.",
                        flush=True,
                    )
                time.sleep(sleep_seconds)
            except URLError as exc:
                last_error = RRMSClientError(f"{method} {url} failed: {exc.reason}")
                if attempt >= self.config.request_retries:
                    raise last_error from exc
                sleep_seconds = float(min(2**attempt, 30))
                if self.verbose:
                    print(f"{method} {url} failed; retrying in {sleep_seconds:.1f}s.", flush=True)
                time.sleep(sleep_seconds)

        raise last_error or RRMSClientError(f"{method} {url} failed.")


def extract_list_payload(payload: Any) -> list[JsonObject]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, Mapping):
        return []
    candidates = [payload.get("data"), payload.get("results"), payload.get("items")]
    for wrapper_key in ("events", "organizations", "people", "tags"):
        wrapper = payload.get(wrapper_key)
        if isinstance(wrapper, Mapping):
            candidates.extend([wrapper.get("data"), wrapper.get("results"), wrapper.get("items")])
        elif isinstance(wrapper, list):
            candidates.append(wrapper)
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def has_next_page(payload: Mapping[str, Any], *, current_page: int) -> bool:
    events = payload.get("events")
    if isinstance(events, Mapping):
        return has_next_page(events, current_page=current_page)

    for key in ("next_page_url", "next"):
        value = payload.get(key)
        if value:
            return True
    last_page = payload.get("last_page")
    if isinstance(last_page, int):
        return current_page < last_page
    meta = payload.get("meta")
    if isinstance(meta, Mapping):
        last_meta_page = meta.get("last_page")
        if isinstance(last_meta_page, int):
            return current_page < last_meta_page
        if meta.get("next") or meta.get("next_page_url"):
            return True
    return False


def with_query_param(url: str, key: str, value: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[key] = value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def retry_sleep_seconds(exc: HTTPError, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), 60.0)
        except ValueError:
            pass
    return float(min(2**attempt, 30))
