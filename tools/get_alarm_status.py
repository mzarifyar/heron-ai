#!/usr/bin/env python3
"""Fetch AWS T2 alarm status (borrowed from max-ops/JIRA).

"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict

import requests


DEFAULT_REGION = "ap-chuncheon-2"
DEFAULT_CA_BUNDLE_CANDIDATES = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
)


def _usage() -> None:
    """Builds usage using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    print("Usage: python get_alarm_status.py <ALARM_ID|ALARM_UI_URL> [REGION]", file=sys.stderr)


def _get_token() -> str:
    """Gets token using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    token = os.getenv("OPERATOR_ACCESS_TOKEN") or os.getenv("HERON_OPERATOR_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("OPERATOR_ACCESS_TOKEN or HERON_OPERATOR_ACCESS_TOKEN must be set")
    return token


def _requests_verify() -> Any:
    """Builds requests verify using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    bundle = (os.getenv("REQUESTS_CA_BUNDLE") or "").strip()
    if bundle and os.path.exists(bundle):
        return bundle
    for candidate in DEFAULT_CA_BUNDLE_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return True


def _parse_input(arg: str, region_override: str | None) -> tuple[str, str]:
    """Parses input using local writes or integration calls and returns a tuple result (e.g., ()), may raise ValueError for bad input while dependency errors may bubble."""
    if arg.startswith("http"):
        match = re.search(r"/alarms/([^/]+)/([^/]+)", arg)
        if not match:
            raise ValueError(f"Could not parse REGION and ALARM_ID from URL: {arg}")
        region, alarm_id = match.groups()
        return region, alarm_id
    return region_override or DEFAULT_REGION, arg


def _fetch_alarm_details(base_url: str, alarm_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """Fetches alarm details using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    response = requests.get(
        f"{base_url}/v2/alarms/{alarm_id}",
        headers=headers,
        timeout=30,
        verify=_requests_verify(),
    )
    response.raise_for_status()
    return response.json()


def _fetch_alarm_status(base_url: str, account_id: str, alarm_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """Fetches alarm status using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    page_token = None
    while True:
        params = {"accountId": account_id}
        if page_token:
            params["page"] = page_token
        response = requests.get(
            f"{base_url}/v2/alarms/status",
            headers=headers,
            params=params,
            timeout=30,
            verify=_requests_verify(),
        )
        response.raise_for_status()
        status_list = response.json()
        for item in status_list:
            if item.get("id") == alarm_id:
                return item
        page_token = response.headers.get("opc-next-page")
        if not page_token:
            break
    raise RuntimeError("Alarm status not found")


def main() -> None:
    """Builds main using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    if len(sys.argv) < 2:
        _usage()
        sys.exit(2)

    input_arg = sys.argv[1]
    region = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_REGION

    try:
        token = _get_token()
    except RuntimeError as exc:
        print(json.dumps({"status": "Unknown", "timestampTriggered": None, "error": str(exc)}))
        sys.exit(1)

    try:
        region, alarm_id = _parse_input(input_arg, region)
    except ValueError as exc:
        print(json.dumps({"status": "Unknown", "timestampTriggered": None, "error": str(exc)}))
        sys.exit(2)

    base_url = f"https://devops.aws.amazoncorp.com/api/t2/{region}"
    headers = {"Authorization": f"bearer {token}", "Content-Type": "application/json"}

    try:
        details = _fetch_alarm_details(base_url, alarm_id, headers)
    except requests.RequestException:
        print(json.dumps({"status": "Unknown", "timestampTriggered": None}))
        sys.exit(1)

    account_id = details.get("accountId")
    if not account_id:
        print(json.dumps({"status": "Unknown", "timestampTriggered": None}))
        sys.exit(1)

    try:
        alarm_data = _fetch_alarm_status(base_url, account_id, alarm_id, headers)
    except (requests.RequestException, RuntimeError):
        print(json.dumps({"status": "Unknown", "timestampTriggered": None}))
        sys.exit(1)

    status = alarm_data.get("status")
    timestamp_triggered = alarm_data.get("timestampTriggered")
    print(json.dumps({"status": status, "timestampTriggered": timestamp_triggered}))


if __name__ == "__main__":
    main()