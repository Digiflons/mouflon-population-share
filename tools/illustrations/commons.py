"""Small Wikimedia Commons / Wikidata API client (stdlib only).

Runs in GitHub Actions: the development sandbox cannot reach Commons. The User-Agent
is generic, plus an optional contact set by the owner as the WIKIMEDIA_CONTACT
repository secret (masked by GitHub). The contact is never printed or logged.

Busy answers (429, 503 and other 5xx, timeouts, dropped connections) are retried
with backoff, honouring Retry-After, and the pace slows down after each one. If a
request still fails it raises FetchFailed ("retry later"), never a "not found".
"""

from __future__ import annotations

import email.utils
import http.client
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
# Wikimedia asks automated clients for a contact in the User-Agent. The contact is
# a personal detail: it goes only into the request header, never into output.
_CONTACT = os.environ.get("WIKIMEDIA_CONTACT", "").strip()
_BASE_AGENT = "bird-plate-catalogue/0.2 (non-commercial, low volume"
USER_AGENT = _BASE_AGENT + (f"; {_CONTACT})" if _CONTACT else ")")


def public_user_agent() -> str:
    """The User-Agent as it may be printed: the contact, if any, is not shown."""
    return _BASE_AGENT + ("; contact set)" if _CONTACT else ")")


PAUSE_S = 1.0
# Slowest pace between requests after repeated throttling (seconds).
MAX_PAUSE_S = 30.0
# Answers that mean "busy, try again later", never "this file does not exist".
RETRY_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
ATTEMPTS = 6
MAX_BACKOFF_S = 600.0
# A server asking us to wait longer than this gets no more requests from this run.
MAX_RETRY_AFTER_S = 900.0
NETWORK_ERRORS = (
    urllib.error.URLError,
    TimeoutError,
    ConnectionError,
    http.client.HTTPException,
)

# Replaced in tests.
_urlopen = urllib.request.urlopen
_sleep = time.sleep
_now = time.time

# The run's deadline (Unix time, or None) and the current pace between requests.
_state: dict = {"deadline": None, "pause": PAUSE_S}


class FetchFailed(Exception):
    """A request kept failing (throttled, server busy, timeout): retry in a later
    run. Never a sign that the plate does not exist."""


class OutOfTime(Exception):
    """The run's deadline is reached: stop fetching and save what is done."""


def set_deadline(epoch_seconds: float | None) -> None:
    """No request is started, and no retry wait runs, past this time."""
    _state["deadline"] = epoch_seconds


def time_left() -> float:
    deadline = _state["deadline"]
    return float("inf") if deadline is None else deadline - _now()


def _wait(seconds: float) -> None:
    if seconds >= time_left():
        raise OutOfTime
    _sleep(seconds)


def retry_after(value: str | None) -> float | None:
    """Seconds asked by a Retry-After header (a number or an HTTP date)."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - _now())


def backoff(attempt: int, asked: float | None) -> float:
    """Wait before the next attempt: what the server asked, else doubling from 15 s,
    with some jitter so retries do not line up."""
    base = asked if asked is not None else 15.0 * 2**attempt
    return min(MAX_BACKOFF_S, max(5.0, base) * random.uniform(1.0, 1.25))


def _slow_down() -> None:
    _state["pause"] = min(MAX_PAUSE_S, _state["pause"] * 2)


def _speed_up() -> None:
    _state["pause"] = max(PAUSE_S, _state["pause"] * 0.8)


def agent_for(url: str) -> str:
    """The contact goes only to Wikimedia, which asks for it; other hosts get none."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if host.endswith((".wikimedia.org", ".wikidata.org", ".wikipedia.org")):
        return USER_AGENT
    return _BASE_AGENT + ")"


def get(url: str, params: dict) -> dict:
    query = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    return get_json(f"{url}?{query}")


def get_json(full_url: str) -> dict:
    return json.loads(get_bytes(full_url))


def get_bytes(full_url: str, max_bytes: int = 200_000_000) -> bytes:
    """GET at a polite pace, retrying busy answers and network errors with backoff.

    Honours Retry-After. Raises FetchFailed when every attempt was busy or timed
    out, OutOfTime when the deadline would be passed, and the HTTPError itself for
    a definite answer such as 404. Error messages never contain headers.
    """
    request = urllib.request.Request(
        full_url, headers={"User-Agent": agent_for(full_url)}
    )
    reason = "no attempt"
    for attempt in range(ATTEMPTS):
        if time_left() <= 0:
            raise OutOfTime
        asked = None
        try:
            with _urlopen(request, timeout=120) as response:
                data = response.read(max_bytes + 1)
        except urllib.error.HTTPError as error:
            if error.code not in RETRY_CODES:
                raise
            reason = f"HTTP {error.code}"
            headers = error.headers or {}
            asked = retry_after(headers.get("Retry-After"))
            if asked is not None and asked > MAX_RETRY_AFTER_S:
                raise FetchFailed(f"{reason}, asked to wait {asked:.0f} s") from None
            _slow_down()
        except NETWORK_ERRORS as error:
            reason = type(error).__name__
        else:
            if len(data) > max_bytes:
                raise ValueError(f"response larger than {max_bytes} bytes")
            _speed_up()
            _wait(_state["pause"])
            return data
        if attempt < ATTEMPTS - 1:
            _wait(backoff(attempt, asked))
    raise FetchFailed(f"{reason} after {ATTEMPTS} attempts")


def category_members(category: str, kind: str) -> list[str]:
    """Titles of files ("file") or subcategories ("subcat") in a category."""
    titles, params = (
        [],
        {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmtype": kind,
            "cmlimit": "500",
        },
    )
    while True:
        data = get(COMMONS_API, params)
        titles += [m["title"] for m in data["query"]["categorymembers"]]
        if "continue" not in data:
            return titles
        params.update(data["continue"])


def file_info(titles: list[str]) -> dict[str, dict]:
    """URL, size, sha1, licence and description metadata for up to 50 files."""
    data = get(
        COMMONS_API,
        {
            "action": "query",
            "titles": "|".join(titles),
            "prop": "imageinfo|categories|info",
            "iiprop": "url|size|sha1|mime|extmetadata",
            "cllimit": "max",
        },
    )
    result = {}
    for page in data["query"]["pages"]:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        result[page["title"]] = {
            "pageid": page.get("pageid"),
            "url": info.get("url"),
            "descriptionurl": info.get("descriptionurl"),
            "width": info.get("width"),
            "height": info.get("height"),
            "sha1": info.get("sha1"),
            "mime": info.get("mime"),
            "license": meta.get("LicenseShortName", {}).get("value"),
            "usage_terms": meta.get("UsageTerms", {}).get("value"),
            "description": meta.get("ImageDescription", {}).get("value"),
            "categories": [c["title"] for c in page.get("categories", [])],
        }
    return result


def depicts(pageids: list[int]) -> dict[int, list[str]]:
    """Wikidata items in each file's "depicts" (P180) structured data."""
    ids = "|".join(f"M{p}" for p in pageids)
    data = get(COMMONS_API, {"action": "wbgetentities", "ids": ids, "props": "claims"})
    result = {}
    for entity in data.get("entities", {}).values():
        claims = (entity.get("statements") or entity.get("claims") or {}).get(
            "P180", []
        )
        items = [
            c["mainsnak"]["datavalue"]["value"]["id"]
            for c in claims
            if c.get("mainsnak", {}).get("datavalue")
        ]
        result[int(entity["id"][1:])] = items
    return result
