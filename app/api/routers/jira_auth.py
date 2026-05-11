"""Browser-friendly Jira token management routes.

"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from ...core import get_settings
from ...store.jira_auth_store import jira_auth_store

router = APIRouter(prefix="/jira-auth", tags=["jira-auth"])
ui_router = APIRouter(tags=["jira-auth-ui"])

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "ui" / "templates"
try:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
except AssertionError:
    templates = None


class JiraTokenPayload(BaseModel):
    """Provides JiraTokenPayload behavior using local state or integrations and exposes structured outputs for callers."""
    token: str = Field(min_length=1)


@router.get("/status")
def jira_auth_status() -> dict:
    """Builds jira auth status using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    settings = get_settings()
    payload = jira_auth_store.status()
    payload["browser_auth_url"] = settings.jira_browser_auth_url
    payload["env_token_present"] = bool(os.environ.get("JIRA_BEARER_TOKEN"))
    return payload


@router.post("/token")
def save_jira_token(payload: JiraTokenPayload) -> dict:
    """Saves jira token using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        meta = jira_auth_store.save_token(payload.token, source="ui")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"saved": True, **meta}


@router.delete("/token")
def clear_jira_token() -> dict:
    """Clears jira token using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    jira_auth_store.clear()
    return {"cleared": True}


@ui_router.get("/jira-auth", response_class=HTMLResponse, include_in_schema=False)
def jira_auth_page(request: Request) -> HTMLResponse:
    """Builds jira auth page using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    settings = get_settings()
    context = {
        "request": request,
        "base_url": f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}",
        "browser_auth_url": settings.jira_browser_auth_url,
        "status_url": "/api/v1/jira-auth/status",
        "save_url": "/api/v1/jira-auth/token",
        "clear_url": "/api/v1/jira-auth/token",
    }
    if templates is not None:
        return templates.TemplateResponse("jira_auth.html", context)

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jira Auth</title></head><body style="font-family:sans-serif;padding:24px;">
<h3>Jira Auth</h3>
<p>1) Open Jira and authenticate in browser. 2) Generate or copy bearer token/PAT. 3) Paste token below to persist locally.</p>
<p><a href="{context["browser_auth_url"]}" target="_blank" rel="noreferrer">Open Jira</a></p>
<p><input id="token" type="password" placeholder="Paste Jira token" style="width:480px;max-width:100%;"></p>
<p><button id="save">Save Token</button> <button id="clear">Clear Token</button></p>
<pre id="status"></pre>
<script>
async function loadStatus() {{
  const r = await fetch("{context["status_url"]}");
  document.getElementById("status").textContent = JSON.stringify(await r.json(), null, 2);
}}
document.getElementById("save").onclick = async () => {{
  const token = document.getElementById("token").value;
  const r = await fetch("{context["save_url"]}", {{method:"POST", headers:{{"Content-Type":"application/json"}}, body: JSON.stringify({{token}})}});
  if (!r.ok) alert("Failed to save token");
  await loadStatus();
}};
document.getElementById("clear").onclick = async () => {{
  await fetch("{context["clear_url"]}", {{method:"DELETE"}});
  await loadStatus();
}};
loadStatus();
</script></body></html>"""
    return HTMLResponse(content=html)