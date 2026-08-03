"""Print a strictly redacted summary of the current-hub API response."""
from __future__ import annotations

import argparse
from getpass import getpass
import importlib.util
from ipaddress import ip_address
import json
from pathlib import Path
import socket
import ssl
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from urllib.parse import urlsplit

_AUTH_HELPER_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "grit_hub"
    / "auth.py"
)
_AUTH_SPEC = importlib.util.spec_from_file_location(
    "_grit_diagnostic_auth",
    _AUTH_HELPER_PATH,
)
if _AUTH_SPEC is None or _AUTH_SPEC.loader is None:
    raise RuntimeError("GRIT authentication helper could not be loaded")
_AUTH = importlib.util.module_from_spec(_AUTH_SPEC)
_AUTH_SPEC.loader.exec_module(_AUTH)
InvalidBearerToken = _AUTH.InvalidBearerToken
bearer_authorization_value = _AUTH.bearer_authorization_value

_KNOWN_WRAPPERS = ("data", "hub", "item", "result")
_MAX_BODY_BYTES = 1_048_576
_SAFE_TOP_LEVEL_KEYS = frozenset((*_KNOWN_WRAPPERS, "id", "ipAddressEthernet"))
_REQUEST_TIMEOUT = 10.0


def _type_name(value: Any) -> str:
    """Return a small JSON-oriented type name without rendering the value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return "other"


def _bounded_key_names(value: Any) -> tuple[list[str], bool]:
    if not isinstance(value, dict):
        return [], False
    names = sorted(
        key
        for key in value
        if isinstance(key, str) and key in _SAFE_TOP_LEVEL_KEYS
    )
    omitted = any(
        not isinstance(key, str) or key not in _SAFE_TOP_LEVEL_KEYS
        for key in value
    )
    return names, omitted


def _candidate_object(payload: Any) -> tuple[dict[str, Any] | None, str | None]:
    if isinstance(payload, dict):
        if "id" in payload or "ipAddressEthernet" in payload:
            return payload, None
        wrapped = [
            key
            for key in _KNOWN_WRAPPERS
            if key in payload and isinstance(payload[key], dict)
        ]
        if len(wrapped) == 1:
            return payload[wrapped[0]], wrapped[0]
    elif (
        isinstance(payload, list)
        and len(payload) == 1
        and isinstance(payload[0], dict)
    ):
        return payload[0], "one_element_list"
    return None, None


def summarize_response(payload: Any, http_status: int) -> dict[str, Any]:
    """Return only the explicitly permitted structural response metadata."""
    keys, keys_truncated = _bounded_key_names(payload)
    candidate, wrapper = _candidate_object(payload)
    candidate = candidate or {}

    hub_id = candidate.get("id")
    ethernet_ip = candidate.get("ipAddressEthernet")
    ip_valid = False
    if isinstance(ethernet_ip, str):
        try:
            ip_address(ethernet_ip.strip())
        except ValueError:
            pass
        else:
            ip_valid = True

    return {
        "http_status": http_status,
        "generic_error_category": None,
        "response_type": _type_name(payload),
        "top_level_key_names": keys,
        "top_level_key_names_truncated": keys_truncated,
        "known_wrapper": wrapper,
        "id_exists": "id" in candidate,
        "id_type": _type_name(hub_id),
        "id_length": len(hub_id) if isinstance(hub_id, str) else None,
        "ipAddressEthernet_exists": "ipAddressEthernet" in candidate,
        "ipAddressEthernet_type": _type_name(ethernet_ip),
        "ipAddressEthernet_syntactically_valid": ip_valid,
    }


def _error_summary(
    category: str,
    *,
    http_status: int | None = None,
) -> dict[str, Any]:
    return {
        "http_status": http_status,
        "generic_error_category": category,
        "response_type": None,
        "top_level_key_names": [],
        "top_level_key_names_truncated": False,
        "known_wrapper": None,
        "id_exists": False,
        "id_type": "null",
        "id_length": None,
        "ipAddressEthernet_exists": False,
        "ipAddressEthernet_type": "null",
        "ipAddressEthernet_syntactically_valid": False,
    }


def _validated_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if (
        len(value) > 2048
        or parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid base URL")
    return value

class _NoRedirectHandler(HTTPRedirectHandler):
    """Fail closed instead of forwarding the bearer header on redirects."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _open_request(
    request: Request,
    *,
    timeout: float,
    context: ssl.SSLContext | None,
) -> Any:
    handlers: list[Any] = [_NoRedirectHandler()]
    if urlsplit(request.full_url).scheme == "https":
        handlers.append(HTTPSHandler(context=context))
    return build_opener(*handlers).open(request, timeout=timeout)


def fetch_summary(
    base_url: str,
    token: str,
    *,
    verify_ssl: bool = True,
) -> dict[str, Any]:
    """Fetch one bounded response without returning or printing raw content."""
    try:
        base_url = _validated_base_url(base_url)
    except ValueError:
        return _error_summary("invalid_base_url")
    try:
        authorization = bearer_authorization_value(token)
    except InvalidBearerToken:
        return _error_summary("invalid_token")

    request = Request(
        f"{base_url}/api/hub/1",
        headers={
            "Authorization": authorization,
            "Accept": "application/json",
        },
        method="GET",
    )
    context = None
    if urlsplit(base_url).scheme == "https" and not verify_ssl:
        context = ssl._create_unverified_context()  # noqa: SLF001

    try:
        with _open_request(
            request,
            timeout=_REQUEST_TIMEOUT,
            context=context,
        ) as response:
            status = response.getcode()
            body = response.read(_MAX_BODY_BYTES + 1)
    except HTTPError as err:
        category = (
            "invalid_auth" if err.code == 401 else "hub_request_failed"
        )
        return _error_summary(category, http_status=err.code)
    except (TimeoutError, socket.timeout):
        return _error_summary("hub_request_timeout")
    except (URLError, ssl.SSLError, OSError):
        return _error_summary("hub_request_failed")

    if len(body) > _MAX_BODY_BYTES:
        return _error_summary("hub_response_too_large", http_status=status)
    if not body:
        return _error_summary("hub_response_missing", http_status=status)
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error_summary("hub_response_invalid", http_status=status)
    return summarize_response(payload, status)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch GET /api/hub/1 and print only allowlisted structural metadata."
        )
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Disable TLS certificate verification for this diagnostic request.",
    )
    args = parser.parse_args()
    token = getpass("GRIT API bearer token (input hidden): ")
    summary = fetch_summary(
        args.base_url,
        token,
        verify_ssl=not args.no_verify_ssl,
    )
    token = ""
    json.dump(summary, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if summary["generic_error_category"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
