"""
Typed HTTP client for all six battleship routes.
Mints a fresh JWT for every request. Points at BASE_URL env var
(default: real server). When BASE_URL is a localhost URL, auth is skipped
so the simulator works without credentials.
"""

import os
from typing import Any

import urllib.request
import urllib.error
import json as _json

BASE_URL = os.environ.get(
    "BASE_URL", "https://intern-battleship-game-server.vercel.app"
).rstrip("/")

COMP_ID = os.environ.get(
    "COMP_ID",
    "295cccc9137b5335cc581d67d655d6fa3b41dac6610dad0e7ed201625523ad8c",
)

_USE_AUTH = "localhost" not in BASE_URL and "127.0.0.1" not in BASE_URL


def _get_auth_header(capability: str) -> dict:
    if not _USE_AUTH:
        return {}
    from auth import auth_header, get_agent_id
    return auth_header(get_agent_id(), capability)


def _request(method: str, path: str, capability: str, body: Any = None) -> dict:
    url = f"{BASE_URL}{path}"
    data = _json.dumps(body).encode() if body is not None else None
    headers = {
        "Accept": "application/json",
        **_get_auth_header(capability),
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return _json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code} {e.reason} — {body_text}") from e


# ── Six capability routes ──────────────────────────────────────────────────────

def get_rules() -> dict:
    return _request("GET", f"/competitions/{COMP_ID}/rules", "getCompetitionRules")


def create_attempt() -> dict:
    return _request("POST", f"/competitions/{COMP_ID}/attempts", "createAttempt")


def get_current_attempt() -> dict:
    return _request("GET", f"/competitions/{COMP_ID}/attempts/current", "getCurrentAttempt")


def place_ships(placements: list[dict]) -> dict:
    return _request(
        "POST",
        f"/competitions/{COMP_ID}/attempts/current/placements",
        "placeShips",
        {"placements": placements},
    )


def submit_shot(row: int, col: int) -> dict:
    return _request(
        "POST",
        f"/competitions/{COMP_ID}/attempts/current/shots",
        "submitShot",
        {"row": row, "col": col},
    )


def abandon_attempt() -> dict:
    return _request(
        "DELETE",
        f"/competitions/{COMP_ID}/attempts/current",
        "abandonAttempt",
    )
