"""

"""

from typing import Dict, Any, List, Optional
import logging
import os
import requests
from datetime import datetime, timezone
from utils.settings import get_jira_base_url, get_jira_timeout_seconds, is_passive_mode
from app.integrations.telemetry import log_jira_api_call
from app.store.jira_auth_store import jira_auth_store
from . import secret_service
from utils.logging_mode import get_activity_logger, redact_payload

__all__ = [
    "BASE_URL",
    "get_bearer_headers",
    "get_issue_labels",
    "get_issue_full",
    "get_issue_description",
    "get_fields_map",
    "add_comment",
    "add_label",
    "get_transitions",
    "transition_issue",
    "transition_issue_by_name",
    "link_issues",
    "create_issue",
    "search_issues",
]

# Generic Jira REST utilities usable by any codebase.

BASE_URL = get_jira_base_url()
LOGGER = logging.getLogger(__name__)

JIRA_LABEL_MAX_LENGTH = 255
JIRA_LABEL_MAX_COUNT = 50
CUSTOMFIELD_COMPONENT_ITEM = "customfield_10107"
DEFAULT_CA_BUNDLE_CANDIDATES = (
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
    "/etc/ssl/certs/ca-certificates.crt",
)
_VERIFY_WARNING_EMITTED = False


def _normalize_token(value: Optional[str]) -> str:
    """Normalizes token using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    token = (value or "").strip()
    if not token:
        return ""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        token = token[1:-1].strip()
    return token


def _requests_verify() -> Any:
    """Builds requests verify using local writes or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    global _VERIFY_WARNING_EMITTED
    bundle = (os.getenv("REQUESTS_CA_BUNDLE") or "").strip()
    if bundle:
        if os.path.exists(bundle):
            return bundle
        if not _VERIFY_WARNING_EMITTED:
            LOGGER.warning(
                "REQUESTS_CA_BUNDLE path not found in runtime (%s); falling back to system CA bundle",
                bundle,
            )
            _VERIFY_WARNING_EMITTED = True

    for candidate in DEFAULT_CA_BUNDLE_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return True


def _sanitize_labels(labels: Optional[List[str]]) -> Optional[List[str]]:
    """Builds sanitize labels using local state or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
    if not labels:
        return None
    valid: List[str] = []
    for raw in labels:
        if not isinstance(raw, str):
            LOGGER.warning("Dropping non-string Jira label value: %r", raw)
            continue
        label = raw.strip()
        if not label:
            LOGGER.warning("Dropping empty Jira label derived from %r", raw)
            continue
        if len(label) > JIRA_LABEL_MAX_LENGTH:
            LOGGER.warning(
                "Jira label '%s' exceeds %d characters; dropping to avoid API rejection",
                label,
                JIRA_LABEL_MAX_LENGTH,
            )
            continue
        valid.append(label)

    if not valid:
        return None

    if len(valid) > JIRA_LABEL_MAX_COUNT:
        LOGGER.warning(
            "Truncating Jira labels from %d to %d entries to satisfy API limits",
            len(valid),
            JIRA_LABEL_MAX_COUNT,
        )
        valid = valid[:JIRA_LABEL_MAX_COUNT]

    # Deduplicate while preserving order
    deduped: List[str] = []
    seen = set()
    for label in valid:
        if label not in seen:
            deduped.append(label)
            seen.add(label)
    return deduped


def get_jira_bearer_token() -> str:
    """Gets jira bearer token using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    env_token = _normalize_token(os.environ.get("JIRA_BEARER_TOKEN"))
    if env_token:
        return env_token

    stored = _normalize_token(jira_auth_store.get_token())
    if stored:
        return stored

    try:
        client = secret_service.get_secret_client()
        token = _normalize_token(client.get_plain_secret("cortex-jira-sd-token"))
        if token:
            return token
    except Exception as e:
        raise RuntimeError(
            f"Failed to get JIRA bearer token from secret service: {e}. "
            "Set JIRA_BEARER_TOKEN or save a token in /jira-auth."
        ) from e
    raise RuntimeError("Failed to get JIRA bearer token: empty token returned by secret service.")


def get_bearer_headers() -> Dict[str, str]:
    """Gets bearer headers using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    token = get_jira_bearer_token()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def get_issue_labels(issue_key: str) -> List[str]:
    """Gets issue labels using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
    headers = get_bearer_headers()
    try:
        resp = requests.get(
            f"{BASE_URL}/issue/{issue_key}",
            headers=headers,
            params={"fields": "labels"},
            timeout=get_jira_timeout_seconds(),
            verify=_requests_verify(),
        )
        log_jira_api_call("get_issue_labels")
        resp.raise_for_status()
        data = resp.json()
        return data.get("fields", {}).get("labels", []) or []
    except Exception:
        return []


def get_issue_full(issue_key: str) -> Dict[str, Any]:
    """Gets issue full using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        headers = get_bearer_headers()
    except RuntimeError as e:
        return {"error": str(e)}
    try:
        resp = requests.get(
            f"{BASE_URL}/issue/{issue_key}",
            headers=headers,
            timeout=get_jira_timeout_seconds(),
            verify=_requests_verify(),
        )
        log_jira_api_call("get_issue_full")
        if 200 <= resp.status_code < 300:
            return resp.json()
        else:
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text
            return {"error": f"HTTP {resp.status_code}: {err_body}"}
    except Exception as e:
        return {"error": str(e)}


def get_issue_description(issue_key: str) -> str:
    """Gets issue description using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        headers = get_bearer_headers()
    except RuntimeError:
        return ""
    try:
        resp = requests.get(
            f"{BASE_URL}/issue/{issue_key}",
            headers=headers,
            params={"fields": "description"},
            timeout=get_jira_timeout_seconds(),
            verify=_requests_verify(),
        )
        log_jira_api_call("get_issue_description")
        resp.raise_for_status()
        data = resp.json()
        desc = data.get("fields", {}).get("description")
        if isinstance(desc, str):
            return desc
        try:
            return str(desc) if desc is not None else ""
        except Exception:
            return ""
    except Exception:
        return ""


PASSIVE_ALLOWED_KEYS = {"issue_key", "project_key", "label"}


def _sanitize_value(value: Any) -> Any:
    """Builds sanitize value using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if isinstance(value, dict):
        return _sanitize_dict(value)
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(item) for item in value]
    return value


def _sanitize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Builds sanitize dict using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return {key: _sanitize_value(val) for key, val in data.items()}


def _sanitize_passive_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Builds sanitize passive payload using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    sanitized: Dict[str, Any] = {}
    for key in PASSIVE_ALLOWED_KEYS:
        if key in payload:
            sanitized[key] = _sanitize_value(payload[key])
    if "issue_key" not in sanitized and "project_key" not in sanitized:
        # Keep only minimal indicator to avoid leaking arbitrary user fields.
        return {"info": "omitted"}
    return sanitized


def _log_passive_action(action: str, payload: Dict[str, Any]) -> None:
    """Builds log passive action using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    try:
        logger = get_activity_logger()
    except Exception:
        logger = None
    if logger:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "cortex",
            "mode": "passive",
            "action": action,
            "payload": redact_payload(_sanitize_passive_payload(payload)),
        }
        logger.append(record)


def _passive_result(action: str, payload: Dict[str, Any], response: Dict[str, Any]) -> Dict[str, Any]:
    """Builds passive result using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    target = payload.get("issue_key") or payload.get("project_key") or ""
    suffix = f" for {target}" if target else ""
    print(f"[mode] Passive mode active; skipping Jira action '{action}'{suffix}")
    _log_passive_action(action, payload)
    result = response.copy()
    result["passive"] = True
    return result


def add_comment(issue_key: str, body: str) -> Dict[str, Any]:
    """Builds add comment using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if is_passive_mode():
        return _passive_result(
            "add_comment",
            {"issue_key": issue_key, "body": body},
            {"key": issue_key, "result": "passive_mode_comment_logged"},
        )
    headers = get_bearer_headers()
    payload = {"body": body}
    try:
        resp = requests.post(
            f"{BASE_URL}/issue/{issue_key}/comment",
            headers=headers,
            json=payload,
            timeout=get_jira_timeout_seconds(),
            verify=_requests_verify(),
        )
        log_jira_api_call("add_comment")
        if 200 <= resp.status_code < 300:
            data = resp.json()
            return {"key": issue_key, "comment_id": data.get("id")}
        else:
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text
            return {"key": issue_key, "error": f"HTTP {resp.status_code}: {err_body}"}
    except Exception as e:
        return {"key": issue_key, "error": str(e)}

def add_label(issue_key: str, label: str) -> Dict[str, Any]:
    """Builds add label using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if is_passive_mode():
        return _passive_result(
            "add_label",
            {"issue_key": issue_key, "label": label},
            {"key": issue_key, "result": f"passive_mode_label_{label}_planned"},
        )
    headers = get_bearer_headers()
    payload = {"update": {"labels": [{"add": label}]}}
    try:
        resp = requests.put(
            f"{BASE_URL}/issue/{issue_key}",
            headers=headers,
            json=payload,
            timeout=get_jira_timeout_seconds(),
            verify=_requests_verify(),
        )
        log_jira_api_call("add_label")
        if 200 <= resp.status_code < 300:
            return {"key": issue_key, "result": f"label_{label}_added"}
        else:
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text
            return {"key": issue_key, "error": f"HTTP {resp.status_code}: {err_body}"}
    except Exception as e:
        return {"key": issue_key, "error": str(e)}


def get_transitions(issue_key: str) -> Dict[str, Any]:
    """Gets transitions using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if is_passive_mode():
        return _passive_result(
            "get_transitions",
            {"issue_key": issue_key},
            {"key": issue_key, "transitions": []},
        )
    headers = get_bearer_headers()
    try:
        resp = requests.get(
            f"{BASE_URL}/issue/{issue_key}/transitions",
            headers=headers,
            timeout=get_jira_timeout_seconds(),
            verify=_requests_verify(),
        )
        log_jira_api_call("get_transitions")
        if 200 <= resp.status_code < 300:
            payload = resp.json() or {}
            transitions = payload.get("transitions")
            return {"key": issue_key, "transitions": transitions if isinstance(transitions, list) else []}
        try:
            err_body = resp.json()
        except Exception:
            err_body = resp.text
        return {"key": issue_key, "error": f"HTTP {resp.status_code}: {err_body}"}
    except Exception as e:
        return {"key": issue_key, "error": str(e)}


def transition_issue(issue_key: str, transition_id: str) -> Dict[str, Any]:
    """Builds transition issue using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    tid = str(transition_id or "").strip()
    if not tid:
        return {"key": issue_key, "error": "missing_transition_id"}
    if is_passive_mode():
        return _passive_result(
            "transition_issue",
            {"issue_key": issue_key, "transition_id": tid},
            {"key": issue_key, "result": f"passive_mode_transition_{tid}_planned"},
        )
    headers = get_bearer_headers()
    payload = {"transition": {"id": tid}}
    try:
        resp = requests.post(
            f"{BASE_URL}/issue/{issue_key}/transitions",
            headers=headers,
            json=payload,
            timeout=get_jira_timeout_seconds(),
            verify=_requests_verify(),
        )
        log_jira_api_call("transition_issue")
        if 200 <= resp.status_code < 300:
            return {"key": issue_key, "result": "transitioned", "transition_id": tid}
        try:
            err_body = resp.json()
        except Exception:
            err_body = resp.text
        return {"key": issue_key, "error": f"HTTP {resp.status_code}: {err_body}", "transition_id": tid}
    except Exception as e:
        return {"key": issue_key, "error": str(e), "transition_id": tid}


def transition_issue_by_name(issue_key: str, transition_name: str) -> Dict[str, Any]:
    """Builds transition issue by name using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    target = str(transition_name or "").strip()
    if not target:
        return {"key": issue_key, "error": "missing_transition_name"}
    transitions_payload = get_transitions(issue_key)
    if transitions_payload.get("error"):
        return {"key": issue_key, "error": transitions_payload["error"], "transition_name": target}
    transitions = transitions_payload.get("transitions") or []
    for item in transitions:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name.lower() == target.lower():
            return transition_issue(issue_key, str(item.get("id") or ""))
    return {"key": issue_key, "error": f"transition_not_found:{target}", "transition_name": target}


def get_fields_map() -> Dict[str, Any]:
    """Gets fields map using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        headers = get_bearer_headers()
    except RuntimeError as e:
        return {"error": str(e)}  # type: ignore

    try:
        resp = requests.get(
            f"{BASE_URL}/field",
            headers=headers,
            timeout=get_jira_timeout_seconds(),
            verify=_requests_verify(),
        )
        log_jira_api_call("get_fields_map")
        if 200 <= resp.status_code < 300:
            fields = resp.json() or []
            result: Dict[str, str] = {}
            for f in fields:
                name = f.get("name")
                fid = f.get("id")
                if isinstance(name, str) and isinstance(fid, str):
                    result[name] = fid
            return result
        else:
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text
            return {"error": f"HTTP {resp.status_code}: {err_body}"}  # type: ignore
    except Exception as e:
        return {"error": str(e)}  # type: ignore


def create_issue(
    project_key: str,
    summary: str,
    description: str,
    issue_type_name: str = "Incident",
    component_name: Optional[str] = None,
    custom_fields: Optional[Dict[str, Any]] = None,
    labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Creates issue using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if not isinstance(project_key, str) or not project_key.strip():
        return {"error": "invalid_project_key", "details": {"project_key": project_key}}

    summary_text = (summary or "").strip()
    if not summary_text:
        return {"error": "invalid_summary"}

    description_text = (description or "").strip()
    if not description_text:
        return {"error": "invalid_description"}

    if is_passive_mode():
        return _passive_result(
            "create_issue",
            {
                "project_key": project_key,
                "summary": summary_text,
                "issue_type_name": issue_type_name,
                "component_name": component_name,
            },
            {
                "key": f"{project_key}-SIMULATED",
                "id": None,
                "result": "passive_mode_issue_not_created",
            },
        )
    try:
        headers = get_bearer_headers()
    except RuntimeError as e:
        return {"error": str(e)}


def link_issues(source_issue_key: str, target_issue_key: str, link_type_name: str = "Relates") -> Dict[str, Any]:
    """Links issues using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    source = str(source_issue_key or "").strip()
    target = str(target_issue_key or "").strip()
    link_type = str(link_type_name or "Relates").strip() or "Relates"
    if not source or not target:
        return {"error": "missing_issue_key", "source_issue_key": source, "target_issue_key": target}
    if source == target:
        return {"error": "source_and_target_same", "source_issue_key": source}

    if is_passive_mode():
        return _passive_result(
            "link_issues",
            {"issue_key": source, "target_issue_key": target},
            {"source_issue_key": source, "target_issue_key": target, "result": "passive_mode_issue_link_planned"},
        )

    try:
        headers = get_bearer_headers()
    except RuntimeError as e:
        return {"error": str(e), "source_issue_key": source, "target_issue_key": target}

    payload = {
        "type": {"name": link_type},
        "inwardIssue": {"key": source},
        "outwardIssue": {"key": target},
    }
    try:
        resp = requests.post(
            f"{BASE_URL}/issueLink",
            headers=headers,
            json=payload,
            timeout=get_jira_timeout_seconds(),
            verify=_requests_verify(),
        )
        log_jira_api_call("link_issues")
        if 200 <= resp.status_code < 300:
            return {"source_issue_key": source, "target_issue_key": target, "result": "linked", "link_type": link_type}
        try:
            err_body = resp.json()
        except Exception:
            err_body = resp.text
        return {
            "source_issue_key": source,
            "target_issue_key": target,
            "error": f"HTTP {resp.status_code}: {err_body}",
            "link_type": link_type,
        }
    except Exception as e:
        return {"source_issue_key": source, "target_issue_key": target, "error": str(e), "link_type": link_type}

    fields: Dict[str, Any] = {
        "project": {"key": project_key.strip()},
        "summary": summary_text,
        "description": description_text,
        "issuetype": {"name": issue_type_name},
    }

    # Retain existing behavior for Component / Item custom field.
    if component_name and CUSTOMFIELD_COMPONENT_ITEM not in (custom_fields or {}):
        fields[CUSTOMFIELD_COMPONENT_ITEM] = {"id": "28283"}

    if isinstance(custom_fields, dict) and custom_fields:
        for k, v in custom_fields.items():
            fields[k] = v

    sanitized_labels = _sanitize_labels(labels)
    if sanitized_labels:
        fields["labels"] = sanitized_labels

    payload = {"fields": fields}

    try:
        resp = requests.post(
            f"{BASE_URL}/issue",
            headers=headers,
            json=payload,
            timeout=get_jira_timeout_seconds(),
            verify=_requests_verify(),
        )
        log_jira_api_call("create_issue")
        if 200 <= resp.status_code < 300:
            data = resp.json()
            return {"key": data.get("key"), "id": data.get("id")}
        else:
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text

            err_details = err_body if isinstance(err_body, dict) else {"message": err_body}
            if resp.status_code == 404:
                return {
                    "error": "project_not_found",
                    "details": {"project_key": project_key, "response": err_details},
                }
            if resp.status_code == 400:
                return {
                    "error": "invalid_issue_payload",
                    "details": {"project_key": project_key, "response": err_details},
                }
            return {"error": f"HTTP {resp.status_code}", "details": err_details}
    except Exception as e:
        return {"error": str(e)}


def search_issues(
    jql: str,
    fields: Optional[str] = "key,summary",
    max_results: int = 100,
) -> List[Dict[str, Any]]:
    """Builds search issues using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        headers = get_bearer_headers()
    except RuntimeError as e:
        return [{"error": str(e)}]

    try:
        params: Dict[str, str] = {"jql": jql, "maxResults": str(max_results)}
        if fields:
            params["fields"] = fields

        resp = requests.get(
            f"{BASE_URL}/search",
            headers=headers,
            params=params,
            timeout=get_jira_timeout_seconds(),
            verify=_requests_verify(),
        )
        log_jira_api_call("search_issues")
        resp.raise_for_status()
        data = resp.json()
        return data.get("issues", [])
    except Exception as e:
        return [{"error": str(e)}]
