(function () {
  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll("\"", "&quot;")
      .replaceAll("'", "&#39;");
  }

  async function getJson(url, options) {
    const opts = options ? { ...options } : {};
    const method = String(opts.method || "GET").toUpperCase();
    const isLocalHost = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    const isOpsWrite = String(url || "").startsWith("/api/v1/ops/") && !["GET", "HEAD", "OPTIONS"].includes(method);
    if (isLocalHost && isOpsWrite) {
      const role = (window.localStorage && window.localStorage.getItem("cortex-role")) || "admin";
      const headers = new Headers(opts.headers || {});
      if (!headers.has("x-cortex-role")) {
        headers.set("x-cortex-role", role);
      }
      opts.headers = headers;
    }
    const response = await fetch(url, opts);
    const raw = await response.text();
    let payload = {};
    if (raw) {
      try {
        payload = JSON.parse(raw);
      } catch (_) {
        payload = { detail: raw };
      }
    }
    if (!response.ok) {
      throw new Error(payload.detail || url + " failed (" + response.status + ")");
    }
    return payload;
  }

  function renderKeyValueRows(targetId, rows) {
    const body = document.getElementById(targetId);
    if (!body) return;
    body.innerHTML = "";
    for (const [label, value] of rows || []) {
      const tr = document.createElement("tr");
      tr.innerHTML = "<th>" + escapeHtml(label) + "</th><td>" + escapeHtml(value) + "</td>";
      body.appendChild(tr);
    }
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function runButtonAction(button, action, options) {
    const opts = options || {};
    if (!button) return action();
    if (button.dataset.busy === "1") return undefined;

    const originalText = button.textContent;
    const pendingText = opts.pendingText || "Working...";
    const successText = opts.successText || "Done";
    const errorText = opts.errorText || "Failed";

    button.dataset.busy = "1";
    button.disabled = true;
    button.classList.remove("btn-success", "btn-error");
    button.classList.add("btn-running");
    button.textContent = pendingText;

    try {
      const result = await action();
      button.classList.remove("btn-running");
      button.classList.add("btn-success");
      button.textContent = successText;
      await sleep(opts.successMs || 700);
      return result;
    } catch (error) {
      button.classList.remove("btn-running");
      button.classList.add("btn-error");
      button.textContent = errorText;
      await sleep(opts.errorMs || 1000);
      throw error;
    } finally {
      button.dataset.busy = "0";
      button.disabled = false;
      button.classList.remove("btn-running", "btn-success", "btn-error");
      button.textContent = originalText;
    }
  }

  window.CortexUI = {
    escapeHtml,
    getJson,
    renderKeyValueRows,
    runButtonAction,
  };
})();
