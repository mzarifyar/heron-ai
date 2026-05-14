"""API routes for external data pullers and scheduler control.

"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ...core import get_settings
from ...integrations import jira as jira_api
from ...services.pullers.scheduler import puller_manager
from ...store.local_db import local_state_db

router = APIRouter(prefix="/pullers", tags=["pullers"])
ui_router = APIRouter(tags=["pullers-ui"])
TICKETS_PAGE_SIZE = 100

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "ui" / "templates"
try:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
except AssertionError:
    templates = None


def _load_yaml(path: Path) -> dict:
    """Loads YAML document and returns a dict payload."""
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _alert_config_roots() -> list[Path]:
    """Returns configured alert definition roots from HERON_ALERT_CONFIG_ROOT."""
    root_override = (os.getenv("HERON_ALERT_CONFIG_ROOT") or "").strip()
    if not root_override:
        return []
    base = Path(root_override).expanduser()
    return [base / "alarms", base]


def _collect_alarm_category_paths() -> set[str]:
    """Collects category paths from configured alert definition folders."""
    out: set[str] = set()
    for root in _alert_config_roots():
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_dir():
                continue
            try:
                rel = path.relative_to(root).as_posix().strip("/")
            except Exception:
                continue
            if not rel:
                continue
            parts = [part for part in rel.split("/") if part]
            if not parts:
                continue
            out.add(parts[0].lower())
            if len(parts) >= 2:
                out.add(f"{parts[0].lower()}/{parts[1].lower()}")
    return out


def _load_runbook_ref_to_id() -> dict[str, str]:
    """Loads runbook-ref -> runbook-id mapping from catalog."""
    path = Path(__file__).resolve().parents[2] / "mitigations" / "catalog" / "alarm_runbook_map.yaml"
    payload = _load_yaml(path)
    mapping = payload.get("runbook_ref_to_runbook") if isinstance(payload.get("runbook_ref_to_runbook"), dict) else {}
    out: dict[str, str] = {}
    for key, value in mapping.items():
        ref = str(key or "").strip().strip("/").lower()
        rid = str(value or "").strip().lower()
        if ref and rid:
            out[ref] = rid
    return out


def _invert_runbook_ref_map(runbook_ref_to_id: dict[str, str]) -> dict[str, list[str]]:
    """Builds runbook-id -> list[runbook-ref] index."""
    out: dict[str, list[str]] = {}
    for ref, rid in runbook_ref_to_id.items():
        out.setdefault(rid, []).append(ref)
    return out


_ALARM_CATEGORY_PATHS = _collect_alarm_category_paths()
_RUNBOOK_REF_TO_ID = _load_runbook_ref_to_id()
_RUNBOOK_ID_TO_REFS = _invert_runbook_ref_map(_RUNBOOK_REF_TO_ID)


def _normalize_category_text(text: str) -> str:
    """Formats category path for display."""
    token = (text or "").strip().strip("/")
    if not token:
        return ""
    parts = [part.replace("_", " ").strip() for part in token.split("/") if part.strip()]
    return " / ".join(parts)


def _extract_candidate_runbook_refs(item: dict) -> list[str]:
    """Extracts candidate runbook refs from ticket context."""
    context = item.get("context") if isinstance(item.get("context"), dict) else {}
    enrichment = context.get("enrichment") if isinstance(context.get("enrichment"), dict) else {}
    resolution = enrichment.get("runbook_resolution") if isinstance(enrichment.get("runbook_resolution"), dict) else {}
    refs: list[str] = []
    direct = str(resolution.get("runbook_ref_path") or "").strip().strip("/").lower()
    if direct:
        refs.append(direct)
    rid = str(enrichment.get("runbook_id") or "").strip().lower()
    if rid:
        refs.extend(_RUNBOOK_ID_TO_REFS.get(rid, []))
    out: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if ref and ref not in seen:
            out.append(ref)
            seen.add(ref)
    return out


def _derive_alarm_category(item: dict) -> str:
    """Derives t2 alarm category path from runbook resolution metadata."""
    refs = _extract_candidate_runbook_refs(item)
    if not refs:
        return ""
    candidates = sorted(_ALARM_CATEGORY_PATHS, key=lambda x: (-x.count("/"), -len(x), x))
    for ref in refs:
        ref_l = ref.lower()
        for cat in candidates:
            if ref_l == cat or ref_l.startswith(cat + "/"):
                return _normalize_category_text(cat)
    # fallback to best-effort first segment from runbook ref
    token = refs[0].split("/", 2)
    if len(token) >= 2:
        return _normalize_category_text(f"{token[0]}/{token[1]}")
    if token:
        return _normalize_category_text(token[0])
    return ""


def _apply_group_display(item: dict) -> None:
    """Sets display group value for UI when DB group is empty/unmapped."""
    current = str(item.get("group") or "").strip()
    if current and current.lower() != "unmapped":
        return
    derived = _derive_alarm_category(item)
    if derived:
        item["group"] = derived
    else:
        item["group"] = "unmapped"


def _jira_browse_base_url() -> str:
    """Builds jira browse base url using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    return get_settings().jira_browser_auth_url.rstrip("/")


def _jira_issue_url(ticket_key: str | None) -> str | None:
    """Builds jira issue url using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    key = (ticket_key or "").strip()
    if not key:
        return None
    return f"{_jira_browse_base_url()}/browse/{key}"


def _effective_ticket_status(item: dict) -> str:
    """Builds effective ticket status using cached enrichment values."""
    context = item.get("context") if isinstance(item.get("context"), dict) else {}
    enrichment = context.get("enrichment") if isinstance(context.get("enrichment"), dict) else {}
    jira = enrichment.get("jira") if isinstance(enrichment.get("jira"), dict) else {}
    status = str(jira.get("status") or enrichment.get("status_after") or enrichment.get("status_before") or "").strip()
    status_category = str(jira.get("status_category") or "").strip().lower()
    resolution = str(jira.get("resolution") or "").strip()
    resolution_date = str(jira.get("resolution_date_utc") or "").strip()
    normalized = status.lower()
    if resolution or resolution_date or normalized in {"resolved", "closed", "done"} or status_category in {"done", "complete", "completed"}:
        return "Resolved"
    return status or "Unknown"


def _jira_status_from_fields(fields: dict) -> str:
    """Derives normalized status from Jira issue fields."""
    status_obj = fields.get("status") if isinstance(fields.get("status"), dict) else {}
    status_name = str(status_obj.get("name") or "").strip()
    status_category = ""
    if isinstance(status_obj.get("statusCategory"), dict):
        status_category = str((status_obj.get("statusCategory") or {}).get("name") or "").strip().lower()
    resolution_obj = fields.get("resolution") if isinstance(fields.get("resolution"), dict) else {}
    resolution_name = str(resolution_obj.get("name") or "").strip()
    resolution_date = str(fields.get("resolutiondate") or "").strip()
    normalized = status_name.lower()
    if resolution_name or resolution_date or normalized in {"resolved", "closed", "done"} or status_category in {"done", "complete", "completed"}:
        return "Resolved"
    return status_name or "Unknown"


def _refresh_ticket_statuses(items: list[dict]) -> None:
    """Refreshes ticket status in batch from Jira and updates items in-place."""
    keys = [str(item.get("ticket_key") or "").strip() for item in items if str(item.get("ticket_key") or "").strip()]
    if not keys:
        return
    uniq_keys: list[str] = []
    seen: set[str] = set()
    for key in keys:
        up = key.upper()
        if up in seen:
            continue
        seen.add(up)
        uniq_keys.append(up)
    quoted_keys = ",".join(f'"{key}"' for key in uniq_keys)
    issues = jira_api.search_issues(
        jql=f"key in ({quoted_keys})",
        fields="key,status,resolution,resolutiondate,updated",
        max_results=max(100, len(uniq_keys) + 10),
    )
    live: dict[str, str] = {}

    batch_error = bool(issues and isinstance(issues[0], dict) and issues[0].get("error"))
    for issue in ([] if batch_error else issues):
        if not isinstance(issue, dict):
            continue
        key = str(issue.get("key") or "").strip().upper()
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        live[key] = _jira_status_from_fields(fields)

    # Fallback to per-ticket lookup for missing keys or if batch search failed.
    missing = [key for key in uniq_keys if key not in live]
    for key in missing:
        payload = jira_api.get_issue_full(key)
        if not isinstance(payload, dict) or payload.get("error"):
            continue
        fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        live[key] = _jira_status_from_fields(fields)

    for item in items:
        key = str(item.get("ticket_key") or "").strip().upper()
        if key in live:
            item["ticket_status"] = live[key]
        else:
            item["ticket_status"] = _effective_ticket_status(item)


def _sort_tickets(items: list[dict], *, sort_by: str, sort_dir: str) -> list[dict]:
    """Sorts ticket rows using UI-compatible sort keys."""
    key_name = (sort_by or "last_seen_at").strip().lower()
    reverse = (sort_dir or "desc").strip().lower() != "asc"

    def _ticket_number(item: dict) -> int:
        key = str(item.get("ticket_key") or "")
        if "-" not in key:
            return -1
        try:
            return int(key.split("-", 1)[1])
        except Exception:
            return -1

    def _sort_key(item: dict):
        if key_name == "ticket_key":
            return str(item.get("ticket_key") or "")
        if key_name == "ticket_number":
            return _ticket_number(item)
        if key_name == "last_seen_at":
            return str(item.get("last_seen_at") or "")
        if key_name == "group":
            return str(item.get("group") or "")
        if key_name == "summary":
            return str(item.get("summary") or "")
        if key_name == "ticket_status":
            return str(item.get("ticket_status") or "")
        return str(item.get("last_seen_at") or "")

    return sorted(items, key=_sort_key, reverse=reverse)


def _load_live_heron_tickets(*, q: str | None, page: int, page_size: int, sort_by: str, sort_dir: str) -> tuple[list[dict], int]:
    """Loads Heron-generated tickets directly from Jira."""
    extra_filter = ""
    q_token = (q or "").strip()
    if q_token:
        safe = q_token.replace('"', '\\"')
        extra_filter = f' AND (summary ~ "{safe}" OR key = "{safe}")'
    jql = (
        'project in ("ODA","CDA") AND issuetype = Incident '
        'AND (summary ~ "HERON" OR labels = heron_rollup)'
        f"{extra_filter} ORDER BY updated DESC"
    )
    issues = jira_api.search_issues(
        jql=jql,
        fields=(
            "key,summary,labels,status,created,updated,description,"
            "assignee,reporter,priority,issuetype,project,resolution,resolutiondate"
        ),
        max_results=500,
    )
    if issues and isinstance(issues[0], dict) and issues[0].get("error"):
        return [], 0

    items: list[dict] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        key = str(issue.get("key") or "").strip()
        if not key:
            continue
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        status_obj = fields.get("status") if isinstance(fields.get("status"), dict) else {}
        jira_status = str(status_obj.get("name") or "").strip()
        ticket_status = _jira_status_from_fields(fields)
        summary = str(fields.get("summary") or "").strip()
        context = {
            "message": summary,
            "enrichment": {
                "status_before": jira_status,
                "status_after": jira_status,
                "jira": {
                    "status": jira_status,
                    "status_category": str((status_obj.get("statusCategory") or {}).get("name") or "")
                    if isinstance(status_obj.get("statusCategory"), dict)
                    else "",
                    "assignee": str((fields.get("assignee") or {}).get("displayName") or "")
                    if isinstance(fields.get("assignee"), dict)
                    else "",
                    "reporter": str((fields.get("reporter") or {}).get("displayName") or "")
                    if isinstance(fields.get("reporter"), dict)
                    else "",
                    "priority": str((fields.get("priority") or {}).get("name") or "")
                    if isinstance(fields.get("priority"), dict)
                    else "",
                    "issue_type": str((fields.get("issuetype") or {}).get("name") or "")
                    if isinstance(fields.get("issuetype"), dict)
                    else "",
                    "project_key": str((fields.get("project") or {}).get("key") or "")
                    if isinstance(fields.get("project"), dict)
                    else "",
                    "project_name": str((fields.get("project") or {}).get("name") or "")
                    if isinstance(fields.get("project"), dict)
                    else "",
                    "resolution": str((fields.get("resolution") or {}).get("name") or "")
                    if isinstance(fields.get("resolution"), dict)
                    else "",
                    "resolution_date_utc": fields.get("resolutiondate"),
                    "updated_utc": fields.get("updated"),
                },
            },
        }
        items.append(
            {
                "ticket_key": key,
                "summary": summary,
                "labels": fields.get("labels") or [],
                "group": "heron_generated",
                "context": context,
                "ingest_status": "live_jira",
                "first_seen_at": fields.get("created"),
                "last_seen_at": fields.get("updated"),
                "ticket_status": ticket_status,
                "jira_url": _jira_issue_url(key),
            }
        )

    items = _sort_tickets(items, sort_by=sort_by, sort_dir=sort_dir)
    total = len(items)
    offset = max(0, (max(1, int(page)) - 1) * page_size)
    paged = items[offset : offset + page_size]
    return paged, total


@router.post("/run-now", status_code=status.HTTP_202_ACCEPTED)
def run_pullers_now(
    source: str = Query(default="jira", description="Puller source name or 'all'"),
) -> dict:
    """Runs pullers now using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        return puller_manager.run_now(source=source)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/status")
def get_pullers_status() -> dict:
    """Gets pullers status using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return puller_manager.status()


@router.get("/cursors")
def get_puller_cursors() -> dict:
    """Gets puller cursors using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return puller_manager.cursors()


@router.get("/runs")
def list_puller_runs(
    limit: int = Query(default=50, ge=1, le=500),
    source: str | None = Query(default=None),
) -> dict:
    """Lists puller runs using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    items = local_state_db.list_puller_runs(limit=limit, source=source)
    return {"count": len(items), "items": items, "limit": limit, "source": source}


@router.get("/tickets")
def list_ingested_jira_tickets(
    page: int = Query(default=1, ge=1),
    q: str | None = Query(default=None),
    project: str | None = Query(default=None, description="Ticket source tab: ODA, CDA, or HERON"),
    sort_by: str = Query(default="last_seen_at"),
    sort_dir: str = Query(default="desc"),
) -> dict:
    """Lists ingested jira tickets using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    page_size = TICKETS_PAGE_SIZE
    project_key = (project or "").strip().upper()
    if project_key == "HERON":
        items, total = _load_live_heron_tickets(
            q=q,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    else:
        offset = (page - 1) * page_size
        items, total = local_state_db.list_jira_tickets(
            limit=page_size,
            offset=offset,
            query=q,
            project=project_key if project_key in {"ODA", "CDA"} else None,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        _refresh_ticket_statuses(items)
        for item in items:
            item["jira_url"] = _jira_issue_url(item.get("ticket_key"))
    for item in items:
        _apply_group_display(item)
    total_pages = (total + page_size - 1) // page_size if total else 1
    return {
        "count": len(items),
        "items": items,
        "query": q,
        "project": project,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }


@router.get("/cluster-hygiene/runs")
def list_cluster_hygiene_runs(
    limit: int = Query(default=25, ge=1, le=200),
) -> dict:
    """Lists cluster hygiene runs using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    items = local_state_db.list_cluster_hygiene_runs(limit=limit)
    return {"count": len(items), "items": items, "limit": limit}


@router.get("/cluster-hygiene/findings")
def list_cluster_hygiene_findings(
    run_id: int = Query(..., ge=1),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict:
    """Lists cluster hygiene findings using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    items = local_state_db.list_cluster_hygiene_findings(run_id=run_id, limit=limit)
    return {"count": len(items), "items": items, "run_id": run_id, "limit": limit}


@router.get("/cluster-hygiene/latest")
def latest_cluster_hygiene_report() -> dict:
    """Builds latest cluster hygiene report using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    runs = local_state_db.list_cluster_hygiene_runs(limit=1)
    if not runs:
        return {"run": None, "findings": []}
    run = runs[0]
    findings = local_state_db.list_cluster_hygiene_findings(run_id=int(run["id"]), limit=500)
    return {"run": run, "findings": findings}


@ui_router.get("/pullers", response_class=HTMLResponse, include_in_schema=False)
def pullers_dashboard(request: Request) -> HTMLResponse:
    """Builds pullers dashboard using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    base_url = f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"
    context = {
        "request": request,
        "base_url": base_url,
        "jira_browse_base_url": _jira_browse_base_url(),
        "status_url": "/api/v1/pullers/status",
        "cursors_url": "/api/v1/pullers/cursors",
        "runs_url": "/api/v1/pullers/runs?limit=25",
        "tickets_url": "/api/v1/pullers/tickets",
        "cluster_hygiene_latest_url": "/api/v1/pullers/cluster-hygiene/latest",
        "docs_url": "/docs",
    }
    if templates is None:
        html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Heron Pullers Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {{
      --bg: #ffffff;
      --panel: #f8f9fa;
      --muted: #6c757d;
      --text: #000000;
      --link: #007bff;
      --border: #dee2e6;
    }}
    html, body {{
      height: 100%;
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
    }}
    a {{ color: var(--link); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .container {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
    .row {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
    .grow {{ flex: 1 1 auto; }}
    .muted {{ color: var(--muted); }}
    .small {{ font-size: 12px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }}
    .stack {{ display: grid; gap: 12px; }}
    .grid {{ width: 100%; border-collapse: collapse; }}
    .grid th, .grid td {{ border-bottom: 1px solid var(--border); text-align: left; padding: 8px 10px; font-size: 13px; vertical-align: top; }}
    .grid th {{ color: var(--muted); font-weight: 600; }}
    .code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; background: #eef2f7; border: 1px solid var(--border); border-radius: 6px; padding: 2px 6px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="panel stack" style="margin-top: 12px;">
      <div class="row">
        <div class="grow">
          <h3 style="margin: 0;">Pullers Dashboard</h3>
        </div>
        <a href="{context["docs_url"]}">Docs</a>
      </div>
      <div class="row">
        <button id="refresh-btn" type="button">Refresh</button>
        <button id="run-jira-btn" type="button">Run Jira Now</button>
      </div>
      <div class="row">
        <div class="panel grow">
          <details>
            <summary><strong>Scheduler</strong></summary>
            <pre id="status-json" class="code" style="display:block;white-space:pre-wrap; padding:8px; margin-top:8px;"></pre>
          </details>
        </div>
        <div class="panel grow">
          <details>
            <summary><strong>Cursors</strong></summary>
            <pre id="cursors-json" class="code" style="display:block;white-space:pre-wrap; padding:8px; margin-top:8px;"></pre>
          </details>
        </div>
      </div>
      <details>
        <summary><strong>Recent Puller Runs</strong></summary>
        <div style="margin-top:8px;">
          <table class="grid">
            <thead><tr><th>When</th><th>Source</th><th>Status</th><th>Reason</th><th>Duration</th><th>Summary</th></tr></thead>
            <tbody id="runs-body"></tbody>
          </table>
        </div>
      </details>
      <div>
        <h4 style="margin-bottom: 8px;">Ingested Jira Tickets</h4>
        <div class="row" style="margin-bottom:8px;">
          <button id="tickets-tab-oda" type="button">ODA</button>
          <button id="tickets-tab-cda" type="button">CDA</button>
          <button id="tickets-tab-heron" type="button">Heron</button>
        </div>
        <table class="grid">
          <thead><tr><th>#</th><th></th><th><button type="button" data-sort-by="ticket_number">Ticket</button></th><th>Ticket Status</th><th><button type="button" data-sort-by="last_seen_at">Last Seen</button></th><th><button type="button" data-sort-by="group">Group</button></th><th><button type="button" data-sort-by="summary">Summary</button></th></tr></thead>
          <tbody id="tickets-body"></tbody>
        </table>
        <div class="row" style="margin-top:8px;">
          <button id="tickets-prev-btn" type="button">Prev</button>
          <button id="tickets-next-btn" type="button">Next</button>
          <span id="tickets-page-label" class="small muted">Page 1 / 1</span>
        </div>
      </div>
    </div>
  </div>
  <script>
    const statusUrl = "{context["status_url"]}";
    const cursorsUrl = "{context["cursors_url"]}";
    const runsUrl = "{context["runs_url"]}";
    const ticketsUrl = "{context["tickets_url"]}";
    const jiraBrowseBaseUrl = "{context["jira_browse_base_url"]}";
    const pretty = (value) => JSON.stringify(value, null, 2);
    let ticketsPage = 1;
    let ticketsTotalPages = 1;
    let ticketsProject = "ODA";
    let ticketsSortBy = "last_seen_at";
    let ticketsSortDir = "desc";
    function updateProjectTabState() {{
      const odaBtn = document.getElementById("tickets-tab-oda");
      const cdaBtn = document.getElementById("tickets-tab-cda");
      const heronBtn = document.getElementById("tickets-tab-heron");
      if (odaBtn) odaBtn.disabled = ticketsProject === "ODA";
      if (cdaBtn) cdaBtn.disabled = ticketsProject === "CDA";
      if (heronBtn) heronBtn.disabled = ticketsProject === "HERON";
    }}
    async function getJson(url, options) {{
      const response = await fetch(url, options || {{}});
      if (!response.ok) throw new Error(`${{url}} failed (${{response.status}})`);
      return response.json();
    }}
    function renderRuns(items) {{
      const body = document.getElementById("runs-body");
      body.innerHTML = "";
      for (const row of items || []) {{
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${{row.completed_at || ""}}</td><td>${{row.source || ""}}</td><td>${{row.status || ""}}</td><td>${{row.reason || ""}}</td><td>${{row.duration_ms || 0}}ms</td><td><span class="code">${{pretty(row.summary || {{}})}}</span></td>`;
        body.appendChild(tr);
      }}
    }}
    function compactTicket(row, issueUrl) {{
      const context = row.context || {{}};
      const enrichment = context.enrichment || {{}};
      const jira = enrichment.jira || {{}};
      return {{
        ticket_key: row.ticket_key || "",
        jira_url: issueUrl || "",
        ingest_status: row.ingest_status || "",
        group: row.group || "unmapped",
        summary: row.summary || "",
        location: {{
          airport_code: context.airport_code || "",
          realm: context.realm || "",
          environment: context.environment || "",
          cluster: context.cluster || "",
        }},
        message: context.message || "",
        jira: {{
          status: row.ticket_status || jira.status || enrichment.status_before || "",
          status_category: jira.status_category || "",
          priority: jira.priority || "",
          assignee: jira.assignee || "",
          reporter: jira.reporter || "",
          project_key: jira.project_key || "",
          issue_type: jira.issue_type || "",
          created_utc: enrichment.created_utc || "",
          updated_utc: jira.updated_utc || "",
        }},
        alert_mitigation: {{
          title: (enrichment.alert_specific_mitigation || {{}}).title || "",
          intent: (enrichment.alert_specific_mitigation || {{}}).intent || "",
          steps: (enrichment.alert_specific_mitigation || {{}}).steps || [],
          source: (enrichment.alert_specific_mitigation || {{}}).source || "",
        }},
        alarm: {{
          alarm_region: enrichment.alarm_region || "",
          alarm_id: enrichment.alarm_id || "",
          alarm_status: enrichment.alarm_status || "",
          alarm_status_since: enrichment.alarm_status_since || null,
        }},
      }};
    }}
    function renderTickets(items, page) {{
      const body = document.getElementById("tickets-body");
      body.innerHTML = "";
      let idx = (Math.max(page, 1) - 1) * {TICKETS_PAGE_SIZE};
      for (const row of items || []) {{
        idx += 1;
        const tr = document.createElement("tr");
        const key = row.ticket_key || "";
        const issueUrl = row.jira_url || (key ? `${{jiraBrowseBaseUrl}}/browse/${{key}}` : "");
        const ticketCell = issueUrl ? `<a href="${{issueUrl}}" target="_blank" rel="noopener noreferrer">${{key}}</a>` : key;
        const detailsPayload = pretty({{
          ticket_key: row.ticket_key || "",
          jira_url: issueUrl || "",
          ingest_status: row.ingest_status || "",
          group: row.group || "unmapped",
          labels: row.labels || [],
          context: row.context || {{}},
          first_seen_at: row.first_seen_at || "",
          last_seen_at: row.last_seen_at || "",
        }});
        const compact = compactTicket(row, issueUrl);
        const compactPayload = pretty(compact);
        const ticketStatus = (compact.jira || {{}}).status || "n/a";
        tr.innerHTML = `<td>${{idx}}</td><td style="position:relative; width:34px; min-width:34px;"><details style="position:relative;"><summary title="Toggle details" style="cursor:pointer;"></summary><div class="panel" style="position:absolute; left:18px; top:-4px; z-index:50; width:min(760px, calc(100vw - 120px)); max-height:60vh; overflow:auto; padding:8px;"><pre class="code" style="display:block;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word; padding:8px; margin:0;">${{compactPayload}}</pre><details style="margin-top:8px;"><summary>Raw payload</summary><pre class="code" style="display:block;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word; padding:8px; margin-top:8px;">${{detailsPayload}}</pre></details></div></details></td><td>${{ticketCell}}</td><td>${{ticketStatus}}</td><td>${{row.last_seen_at || ""}}</td><td>${{row.group || "unmapped"}}</td><td style="overflow-wrap:anywhere;word-break:break-word;">${{row.summary || ""}}</td>`;
        body.appendChild(tr);
      }}
    }}
    function updateSortHeaderState() {{
      document.querySelectorAll("button[data-sort-by]").forEach((btn) => {{
        const key = btn.getAttribute("data-sort-by");
        const marker = key === ticketsSortBy ? (ticketsSortDir === "asc" ? " ↑" : " ↓") : "";
        btn.textContent = btn.textContent.replace(/ [↑↓]$/, "") + marker;
      }});
    }}
    async function loadTickets(page) {{
      const current = Math.max(1, page || 1);
      const payload = await getJson(`${{ticketsUrl}}?page=${{current}}&project=${{encodeURIComponent(ticketsProject)}}&sort_by=${{encodeURIComponent(ticketsSortBy)}}&sort_dir=${{encodeURIComponent(ticketsSortDir)}}`);
      ticketsPage = payload.page || current;
      ticketsTotalPages = payload.total_pages || 1;
      renderTickets(payload.items, ticketsPage);
      updateSortHeaderState();
      updateProjectTabState();
      const label = document.getElementById("tickets-page-label");
      if (label) label.textContent = `${{ticketsProject}} • Page ${{ticketsPage}} / ${{ticketsTotalPages}}`;
      const prev = document.getElementById("tickets-prev-btn");
      const next = document.getElementById("tickets-next-btn");
      if (prev) prev.disabled = ticketsPage <= 1;
      if (next) next.disabled = ticketsPage >= ticketsTotalPages;
    }}
    async function refresh() {{
      try {{
        const [status, cursors, runs] = await Promise.all([getJson(statusUrl), getJson(cursorsUrl), getJson(runsUrl)]);
        document.getElementById("status-json").textContent = pretty(status);
        document.getElementById("cursors-json").textContent = pretty(cursors);
        renderRuns(runs.items);
        await loadTickets(ticketsPage);
      }} catch (error) {{
        document.getElementById("status-json").textContent = String(error);
      }}
    }}
    document.getElementById("refresh-btn").addEventListener("click", refresh);
    document.getElementById("run-jira-btn").addEventListener("click", async () => {{
      await getJson("/api/v1/pullers/run-now?source=jira", {{ method: "POST" }});
      await refresh();
    }});
    document.getElementById("tickets-prev-btn").addEventListener("click", async () => {{
      if (ticketsPage > 1) await loadTickets(ticketsPage - 1);
    }});
    document.getElementById("tickets-next-btn").addEventListener("click", async () => {{
      if (ticketsPage < ticketsTotalPages) await loadTickets(ticketsPage + 1);
    }});
    document.getElementById("tickets-tab-oda").addEventListener("click", async () => {{
      ticketsProject = "ODA";
      ticketsPage = 1;
      await loadTickets(1);
    }});
    document.getElementById("tickets-tab-cda").addEventListener("click", async () => {{
      ticketsProject = "CDA";
      ticketsPage = 1;
      await loadTickets(1);
    }});
    document.getElementById("tickets-tab-heron").addEventListener("click", async () => {{
      ticketsProject = "HERON";
      ticketsPage = 1;
      await loadTickets(1);
    }});
    document.querySelectorAll("button[data-sort-by]").forEach((btn) => {{
      btn.addEventListener("click", async () => {{
        const requested = btn.getAttribute("data-sort-by") || "last_seen_at";
        if (ticketsSortBy === requested) {{
          ticketsSortDir = ticketsSortDir === "asc" ? "desc" : "asc";
        }} else {{
          ticketsSortBy = requested;
          ticketsSortDir = requested === "ticket_number" ? "desc" : "asc";
        }}
        ticketsPage = 1;
        await loadTickets(1);
      }});
    }});
    refresh();
  </script>
</body>
</html>"""
        return HTMLResponse(content=html)
    return templates.TemplateResponse("pullers.html", context)
