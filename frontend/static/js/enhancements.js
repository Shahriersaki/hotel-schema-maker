/* ═══════════════════════════════════════════════════════════════════════
   Hotel Schema Maker — Enhancement Layer
   Covers: Admin panel, Schema preview, One-click export,
           Multi-page patch, Role UI, Polished notifications
   ═══════════════════════════════════════════════════════════════════════ */

// ─── State ────────────────────────────────────────────────────────────────────
let previewData = {};          // current schema open in preview modal
let adminUsersCache = [];      // cached user list for admin panel

// ═══════════════════════════════════════════════════════════════════════════════
//  ENHANCED TOAST SYSTEM
// ═══════════════════════════════════════════════════════════════════════════════

const TOAST_ICONS = { success: "✓", error: "✕", info: "ℹ", warning: "⚠" };
let toastQueue = [];
let toastTimer = null;

function toast(msg, type = "info", detail = "") {
  toastQueue.push({ msg, type, detail });
  if (!toastTimer) drainToast();
}

function drainToast() {
  if (!toastQueue.length) { toastTimer = null; return; }
  const { msg, type, detail } = toastQueue.shift();
  const el = document.getElementById("toast");
  if (!el) return;

  const icon = TOAST_ICONS[type] || "ℹ";
  el.className = `toast ${type}`;
  el.innerHTML = detail
    ? `<div class="toast-icon">${icon}</div>
       <div class="toast-body">
         <div class="toast-title">${esc(msg)}</div>
         <div class="toast-msg">${esc(detail)}</div>
       </div>`
    : `<div class="toast-icon">${icon}</div>
       <div class="toast-body"><div class="toast-title">${esc(msg)}</div></div>`;

  el.classList.remove("hidden");
  toastTimer = setTimeout(() => {
    el.classList.add("hidden");
    setTimeout(drainToast, 200);
  }, type === "error" ? 5000 : 3200);
}

// Override the base toast defined in app.js
window.toast = toast;

// ═══════════════════════════════════════════════════════════════════════════════
//  ROLE-BASED UI
// ═══════════════════════════════════════════════════════════════════════════════

function applyRoleUI(role) {
  // Show admin nav items
  document.querySelectorAll(".admin-only").forEach(el => {
    el.classList.toggle("hidden", role !== "admin");
  });

  // Role badge in sidebar
  const badge = document.getElementById("role-badge");
  if (badge) {
    badge.textContent = role;
    badge.className = `role-badge ${role}`;
  }

  // Show viewer notice on write-heavy views
  const notice = document.getElementById("viewer-notice");
  if (notice) {
    notice.classList.toggle("show", role === "viewer");
  }

  // Disable write buttons for viewers
  if (role === "viewer") {
    document.querySelectorAll(
      ".btn-step, .btn-run-all, #btn-regen-kb, .btn-fix"
    ).forEach(btn => {
      btn.disabled = true;
      btn.title = "Read-only access — contact an admin to enable editing";
    });
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  SCHEMA PREVIEW MODAL
// ═══════════════════════════════════════════════════════════════════════════════
function openSchemaPreview(url, pageData = null) {
  if (!pageData) {
    const project = projectsCache.find(p => p.id === currentProjectId);
    pageData = project?.schemas_generated?.[url];
  }
  if (!pageData) {
    toast("No schema data found for this page.", "error");
    return;
  }
  previewData = { url, pageData };

  document.getElementById("preview-modal-title").textContent =
    (pageData.page_type || "Page") + " — Schema Preview";
  document.getElementById("preview-modal-url").textContent = url;

  // HTML tab
  document.getElementById("preview-html-code").textContent =
    pageData.json_ld_html || "No schema generated yet.";

  // JSON tab
  document.getElementById("preview-json-code").textContent =
    JSON.stringify(pageData.schemas || [], null, 2);

  // Warnings tab
  const warns = [
    ...(pageData.compliance_warnings || []),
    ...(pageData.multi_patch_warnings || []),
    ...(pageData.correction_fixes || []).map(f => "✓ FIX: " + f),
    ...(pageData.deprecation_stripped || []).map(p => "✓ STRIPPED deprecated: " + p),
    ...(pageData.auto_fixes || []).map(f => "✓ AUTO-FIX: " + f),
  ];

  const warnBadge = document.getElementById("preview-warn-badge");
  const warnList  = document.getElementById("preview-warnings-list");
  const errCount  = warns.filter(w => w.startsWith("MISSING") || w.startsWith("INVALID")).length;

  if (warnBadge) warnBadge.textContent = warns.length || "";
  if (warnList) {
    warnList.innerHTML = warns.length
      ? warns.map(w => {
          const cls = w.startsWith("✓") ? "color:var(--green)"
            : (w.startsWith("MISSING") || w.startsWith("INVALID")) ? "color:var(--red)"
            : "color:#c07000";
          return `<div style="${cls};margin-bottom:5px">${esc(w)}</div>`;
        }).join("")
      : `<div style="color:var(--stone)">No warnings — schema looks clean ✓</div>`;
  }

  // Reset to HTML tab
  switchPreviewTab("html");
  openModal("schema-preview-modal");
}

function switchPreviewTab(tab) {
  document.querySelectorAll(".preview-tab").forEach(t =>
    t.classList.toggle("active", t.getAttribute("onclick").includes(`'${tab}'`)));
  document.querySelectorAll(".preview-tab-content").forEach(c =>
    c.classList.remove("active"));
  const panel = document.getElementById(`preview-tab-${tab}`);
  if (panel) panel.classList.add("active");
}

function copyPreviewContent(type) {
  const el = document.getElementById(
    type === "html" ? "preview-html-code" : "preview-json-code"
  );
  if (el) {
    copyText(el.textContent);
    toast(`${type.toUpperCase()} copied to clipboard!`, "success");
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  ONE-CLICK EXPORT ENGINE
// ═══════════════════════════════════════════════════════════════════════════════

function openExportModal() {
  if (!currentProjectId) {
    toast("Open a project first.", "error");
    return;
  }
  openModal("export-modal");
}

function exportAction(type) {
  const project = projectsCache.find(p => p.id === currentProjectId);
  if (!project) { toast("Project not found.", "error"); return; }

  switch (type) {
    case "all-jsonld":    exportAllJsonLD(project);   break;
    case "schemas-json":  exportSchemasJSON(project); break;
    case "sitemap":       downloadSitemap();           break;
    case "full-bundle":   exportFullBundle(project);  break;
  }
  closeModal("export-modal");
}

function exportAllJsonLD(project) {
  const schemas = project.schemas_generated || {};
  if (!Object.keys(schemas).length) {
    toast("No schemas generated yet.", "error");
    return;
  }

  // Build one HTML file per page with embed-ready script tags
  let combinedHtml = `<!DOCTYPE html>
<!-- Hotel Schema Maker — JSON-LD Export
     Project: ${project.name}
     Website: ${project.website_url}
     Generated: ${new Date().toISOString()}
     
     HOW TO USE:
     Copy each page's <script> block into the <head> of that specific page.
-->
`;

  for (const [url, data] of Object.entries(schemas)) {
    combinedHtml += `\n\n<!-- ═══ ${url} [${data.page_type || "page"}] ═══ -->\n`;
    combinedHtml += data.json_ld_html || "";
  }

  downloadBlob(combinedHtml, "all-schemas.html", "text/html");
  toast("Exported!", "success", `${Object.keys(schemas).length} pages → all-schemas.html`);
}

function exportSchemasJSON(project) {
  const schemas = project.schemas_generated || {};
  if (!Object.keys(schemas).length) {
    toast("No schemas generated yet.", "error");
    return;
  }

  // Clean export — strip internal metadata fields
  const clean = {};
  for (const [url, data] of Object.entries(schemas)) {
    clean[url] = {
      page_type:  data.page_type,
      page_title: data.page_title,
      url:        data.page_url || url,
      schemas:    data.schemas || [],
      generated_at: data.generated_at
    };
  }

  downloadBlob(JSON.stringify(clean, null, 2), "schemas.json", "application/json");
  toast("Exported!", "success", `schemas.json — ${Object.keys(clean).length} pages`);
}

async function downloadSitemap() {
  if (!currentProjectId) return;
  try {
    const res = await fetch(`/api/sitemap/projects/${currentProjectId}/download`,
      { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error("No sitemap generated yet");
    const blob  = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl; a.download = "sitemap.xml"; a.click();
    URL.revokeObjectURL(blobUrl);
    toast("sitemap.xml downloaded!", "success");
  } catch (err) {
    toast("Download failed", "error", err.message);
  }
}

function exportFullBundle(project) {
  const bundle = {
    meta: {
      tool:        "Hotel Schema Maker",
      version:     "2.0",
      exported_at: new Date().toISOString(),
      project_id:  project.id,
      project_name: project.name,
    },
    website_url:       project.website_url,
    hotel_data:        project.hotel_data,
    pages_found:       project.pages_found || [],
    schemas_generated: project.schemas_generated || {},
    sitemap_xml:       project.sitemap_xml || "",
  };
  downloadBlob(JSON.stringify(bundle, null, 2), `${slugify(project.name)}-bundle.json`, "application/json");
  toast("Full bundle exported!", "success", `${slugify(project.name)}-bundle.json`);
}

function downloadBlob(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function slugify(str) {
  return (str || "export").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

// ═══════════════════════════════════════════════════════════════════════════════
//  MULTI-PAGE PATCH MODAL
// ═══════════════════════════════════════════════════════════════════════════════

function openMultiPatchModal() {
  if (!currentProjectId) { toast("Open a project first.", "error"); return; }
  document.getElementById("patch-instructions").value = "";
  document.getElementById("patch-target-type").value = "";
  document.getElementById("patch-page-urls").value = "";
  document.getElementById("patch-preview").classList.add("hidden");
  document.getElementById("patch-error").classList.add("hidden");
  openModal("multipatch-modal");
}

async function previewPatchInstructions() {
  const instructions = document.getElementById("patch-instructions").value.trim();
  const previewEl    = document.getElementById("patch-preview");
  if (!instructions) return;

  try {
    const res = await apiFetch("/api/feed/parse-instructions", "POST", { instructions });
    previewEl.classList.remove("hidden");

    const ops = res.ops || [];
    const validOps = ops.filter(o => o.op !== "note");
    const notes    = ops.filter(o => o.op === "note");

    let html = `<div style="font-weight:500;margin-bottom:6px">${validOps.length} operation(s) parsed</div>`;
    for (const op of validOps) {
      const label = _opLabel(op);
      html += `<div style="color:var(--green)">✓ ${esc(label)}</div>`;
    }
    for (const n of notes) {
      html += `<div style="color:var(--stone)">⚠ Unrecognized: ${esc(n.text)}</div>`;
    }
    if (res.warnings?.length) {
      for (const w of res.warnings) {
        html += `<div style="color:#c07000">⚠ ${esc(w)}</div>`;
      }
    }
    previewEl.innerHTML = html;
  } catch (err) {
    document.getElementById("patch-error").textContent = err.message;
    document.getElementById("patch-error").classList.remove("hidden");
  }
}

function _opLabel(op) {
  const v = op.op;
  if (v === "add")    return `ADD ${op.key} = ${JSON.stringify(op.value || "").slice(0,40)}`;
  if (v === "remove") return `REMOVE ${op.key}`;
  if (v === "set")    return `SET ${op.path} = ${JSON.stringify(op.value || "").slice(0,40)}`;
  if (v === "unset")  return `UNSET ${op.path}`;
  if (v === "append") return `APPEND to ${op.key}`;
  if (v === "merge")  return `MERGE into ${op.key}`;
  if (v === "type")   return `TYPE → ${op.value}${op.condition ? ` (IF ${op.condition})` : ""}`;
  if (v === "replace")return `REPLACE "${op.old}" → "${op.new}"`;
  if (v === "rename") return `RENAME ${op.from} → ${op.to}`;
  if (v === "copy")   return `COPY ${op.from} → ${op.to}`;
  if (v === "move")   return `MOVE ${op.from} → ${op.to}`;
  if (v === "if")     return `IF ${op.condition} THEN ...`;
  if (v === "warn")   return `WARN: ${op.message}`;
  return `${v}`;
}

async function submitMultiPatch() {
  const instructions = document.getElementById("patch-instructions").value.trim();
  const targetType   = document.getElementById("patch-target-type").value.trim();
  const urlsRaw      = document.getElementById("patch-page-urls").value.trim();
  const errorEl      = document.getElementById("patch-error");

  if (!instructions) {
    errorEl.textContent = "Instructions are required.";
    errorEl.classList.remove("hidden");
    return;
  }

  const pageUrls = urlsRaw
    ? urlsRaw.split("\n").map(s => s.trim()).filter(Boolean)
    : [];

  showLoading(`Patching ${pageUrls.length || "all"} pages…`);
  try {
    const res = await apiFetch(`/api/feed/projects/${currentProjectId}/patch-pages`, "POST", {
      instructions,
      target_type: targetType || null,
      page_urls:   pageUrls
    });
    hideLoading();
    closeModal("multipatch-modal");

    // Update cache
    const proj = await apiFetch(`/api/schema/projects/${currentProjectId}`);
    updateProjectCache(currentProjectId, proj.project);
    restorePipelineState(proj.project);

    const patched = Object.values(res.summary || {}).filter(s => s.status === "patched").length;
    toast("Multi-page patch applied!", "success",
      `${patched} page(s) updated · ${res.ops_applied} operation(s)`);
  } catch (err) {
    hideLoading();
    errorEl.textContent = err.message;
    errorEl.classList.remove("hidden");
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  ADMIN PANEL
// ═══════════════════════════════════════════════════════════════════════════════

async function loadAdminData() {
  await Promise.all([loadAdminStats(), loadAdminUsers(), loadAuditLog()]);
}

async function loadAdminStats() {
  try {
    const res = await apiFetch("/api/admin/stats");
    const s   = res.stats || {};
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val ?? "—"; };
    set("stat-users",       s.users);
    set("stat-projects",    s.projects);
    set("stat-kb",          s.knowledge_base);
    set("stat-corrections", s.schema_corrections);
  } catch (err) {
    console.warn("Admin stats unavailable:", err.message);
  }
}

async function loadAdminUsers() {
  try {
    const res = await apiFetch("/api/admin/users");
    adminUsersCache = res.users || [];
    renderAdminUserTable(adminUsersCache);
    populateAuditUserFilter(adminUsersCache);
  } catch (err) {
    const el = document.getElementById("admin-user-table");
    if (el) el.innerHTML = `<div style="padding:20px;color:var(--red);font-size:13px">Failed to load users: ${esc(err.message)}</div>`;
  }
}

function renderAdminUserTable(users) {
  const el = document.getElementById("admin-user-table");
  if (!el) return;

  if (!users.length) {
    el.innerHTML = `<div style="padding:20px;color:var(--stone);font-size:13px">No users found.</div>`;
    return;
  }

  el.innerHTML = `
    <table class="user-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Email</th>
          <th>Role</th>
          <th>Status</th>
          <th>Last Login</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        ${users.map(u => {
          const isMe = u.id === (currentUser?.user_id || 0);
          const lastLogin = u.last_login
            ? new Date(u.last_login).toLocaleDateString()
            : "Never";
          return `
          <tr>
            <td><strong>${esc(u.name)}</strong>${isMe ? ' <span style="font-size:10px;color:var(--gold)">(you)</span>' : ""}</td>
            <td style="font-family:var(--mono);font-size:12px">${esc(u.email)}</td>
            <td>
              <select class="user-role-select"
                onchange="adminUpdateUser(${u.id}, {role: this.value})"
                ${isMe ? "disabled" : ""}>
                <option value="admin"       ${u.role==="admin"       ? "selected" : ""}>admin</option>
                <option value="contributor" ${u.role==="contributor" ? "selected" : ""}>contributor</option>
                <option value="viewer"      ${u.role==="viewer"      ? "selected" : ""}>viewer</option>
              </select>
            </td>
            <td>
              <button class="user-status-toggle ${u.is_active ? "active" : "inactive"}"
                onclick="adminToggleActive(${u.id}, ${u.is_active ? 0 : 1})"
                ${isMe ? "disabled" : ""}>
                ${u.is_active ? "Active" : "Disabled"}
              </button>
            </td>
            <td style="font-size:12px;color:var(--stone)">${lastLogin}</td>
            <td>
              <button class="btn-table-action"
                onclick="openAdminResetPassword(${u.id}, '${esc(u.name)}')">
                Reset PW
              </button>
            </td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

function populateAuditUserFilter(users) {
  const sel = document.getElementById("audit-user-filter");
  if (!sel) return;
  const existing = sel.innerHTML;
  sel.innerHTML = '<option value="">All users</option>' +
    users.map(u => `<option value="${u.id}">${esc(u.name)} (${esc(u.email)})</option>`).join("");
}

async function adminUpdateUser(userId, updates) {
  try {
    await apiFetch(`/api/admin/users/${userId}`, "PUT", updates);
    toast("User updated.", "success");
    await loadAdminUsers();
    log_audit("admin_update_user");
  } catch (err) {
    toast("Update failed", "error", err.message);
    await loadAdminUsers(); // revert display
  }
}

async function adminToggleActive(userId, newState) {
  try {
    await apiFetch(`/api/admin/users/${userId}`, "PUT", { is_active: newState });
    toast(newState ? "User activated." : "User disabled.", "success");
    await loadAdminUsers();
  } catch (err) {
    toast("Status change failed", "error", err.message);
    await loadAdminUsers();
  }
}

let _resetTargetId = null;
function openAdminResetPassword(userId, name) {
  _resetTargetId = userId;
  const modal = document.createElement("div");
  modal.id    = "admin-pw-modal";
  modal.className = "modal-overlay";
  modal.innerHTML = `
    <div class="modal-box" style="max-width:380px">
      <div class="modal-header">
        <h3>Reset Password — ${esc(name)}</h3>
        <button onclick="document.getElementById('admin-pw-modal').remove()" class="modal-close">✕</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label>New Password <span class="label-hint">(min 8 chars)</span></label>
          <input type="password" id="admin-new-pw" placeholder="••••••••">
        </div>
        <div id="admin-pw-error" class="form-error hidden"></div>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="document.getElementById('admin-pw-modal').remove()">Cancel</button>
        <button class="btn-primary" onclick="submitAdminResetPW()" style="width:auto;padding:10px 20px">Reset →</button>
      </div>
    </div>`;
  document.body.appendChild(modal);
}

async function submitAdminResetPW() {
  const pw      = document.getElementById("admin-new-pw")?.value || "";
  const errorEl = document.getElementById("admin-pw-error");
  if (pw.length < 8) {
    if (errorEl) { errorEl.textContent = "Min 8 characters."; errorEl.classList.remove("hidden"); }
    return;
  }
  try {
    await apiFetch(`/api/admin/users/${_resetTargetId}/reset-password`, "POST",
                   { new_password: pw });
    document.getElementById("admin-pw-modal")?.remove();
    toast("Password reset successfully.", "success");
  } catch (err) {
    if (errorEl) { errorEl.textContent = err.message; errorEl.classList.remove("hidden"); }
  }
}

async function loadAuditLog() {
  const userFilter = document.getElementById("audit-user-filter")?.value;
  const listEl     = document.getElementById("audit-log-list");
  if (!listEl) return;

  try {
    const url = "/api/admin/audit-log?limit=60" + (userFilter ? `&user_id=${userFilter}` : "");
    const res = await apiFetch(url);
    const logs = res.logs || [];

    if (!logs.length) {
      listEl.innerHTML = `<div style="color:var(--stone);font-size:12px">No activity logged yet.</div>`;
      return;
    }

    const ACTION_ICONS = {
      login:              "→",
      register:           "★",
      admin_update_user:  "⚙",
      add_kb_entry:       "⬡",
      delete_kb_entry:    "✕",
      bulk_kb:            "⬡",
      submit_correction:  "⚠",
      fix_correction:     "✓",
      patch_pages:        "⊞",
      regenerate_all:     "↺",
      change_password:    "🔑",
      crawl:              "◎",
      generate_schemas:   "{ }",
    };

    listEl.innerHTML = logs.map(l => {
      const icon    = ACTION_ICONS[l.action] || "·";
      const timeStr = new Date(l.created_at).toLocaleString();
      const who     = l.email ? `${esc(l.name || l.email)}` : `User #${l.user_id}`;
      return `
        <div class="snapshot-item">
          <span class="snapshot-source" style="width:130px">${icon} ${esc(l.action)}</span>
          <span class="snapshot-summary">${who}${l.detail ? ` — ${esc(l.detail.slice(0,80))}` : ""}</span>
          <span class="snapshot-time">${timeStr}</span>
        </div>`;
    }).join("");
  } catch (err) {
    listEl.innerHTML = `<div style="color:var(--red);font-size:12px">Failed to load: ${esc(err.message)}</div>`;
  }
}

function log_audit(action) {
  // Client-side no-op; actual logging happens server-side
}

// ═══════════════════════════════════════════════════════════════════════════════
//  CHANGE PASSWORD (own account)
// ═══════════════════════════════════════════════════════════════════════════════

function openPasswordModal() {
  document.getElementById("pw-current").value = "";
  document.getElementById("pw-new").value = "";
  document.getElementById("pw-confirm").value = "";
  document.getElementById("pw-error").classList.add("hidden");
  openModal("password-modal");
}

async function submitPasswordChange() {
  const current  = document.getElementById("pw-current").value;
  const newPw    = document.getElementById("pw-new").value;
  const confirm  = document.getElementById("pw-confirm").value;
  const errorEl  = document.getElementById("pw-error");

  if (!current)        return showError(errorEl, "Current password is required.");
  if (newPw.length < 8) return showError(errorEl, "New password must be at least 8 characters.");
  if (newPw !== confirm) return showError(errorEl, "Passwords do not match.");

  try {
    await apiFetch("/api/auth/me/password", "PUT", {
      current_password: current,
      new_password:     newPw
    });
    closeModal("password-modal");
    toast("Password changed successfully.", "success");
  } catch (err) {
    showError(errorEl, err.message || "Failed to change password.");
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  ENHANCED SCHEMA ITEMS (preview button + per-page export)
// ═══════════════════════════════════════════════════════════════════════════════

function renderSchemasSection(schemas) {
  const section = document.getElementById("schemas-section");
  if (!section) return;
  section.classList.remove("hidden");

  const countEl = document.getElementById("schemas-count");
  if (countEl) countEl.textContent = Object.keys(schemas).length;

  const list = document.getElementById("schemas-list");
  if (!list) return;

  const TYPE_COLORS = {
    home: "#b8960c", rooms: "#1a3a5c", dining: "#c0392b",
    gallery: "#7d3c98", attractions: "#1e8449", offers: "#d35400",
    blog: "#2980b9", contact: "#27ae60", spa: "#a04000",
    events: "#8e44ad", faq: "#17a589", about: "#566573"
  };

  list.innerHTML = Object.entries(schemas).map(([url, data]) => {
    const color   = TYPE_COLORS[data.page_type] || "#888";
    const warns   = (data.compliance_warnings || []).length;
    const fixes   = (data.auto_fixes || []).length + (data.deprecation_stripped || []).length;
    const corrected = data.corrected ? "✓ corrected" : "";

    return `
    <div class="schema-item">
      <div class="schema-item-header" onclick="toggleSchema(this)">
        <span class="page-type-badge"
          style="background:${color}22;color:${color}">${esc(data.page_type || "page")}</span>
        <span class="schema-item-url">${esc(url)}</span>
        <div style="display:flex;align-items:center;gap:8px;flex-shrink:0">
          ${warns  ? `<span style="color:var(--red);font-size:10px;font-family:var(--mono)">⚠${warns}</span>` : ""}
          ${fixes  ? `<span style="color:var(--green);font-size:10px;font-family:var(--mono)">✓${fixes}</span>` : ""}
          ${corrected ? `<span style="color:var(--gold);font-size:10px;font-family:var(--mono)">${corrected}</span>` : ""}
        </div>
        <span class="schema-item-toggle">▾ ${data.schema_count} schema${data.schema_count !== 1 ? "s" : ""}</span>
      </div>
      <div class="schema-item-body">
        <pre class="code-block">${esc((data.json_ld_html || "").slice(0, 2000))}${(data.json_ld_html || "").length > 2000 ? "\n… (truncated — use Preview for full view)" : ""}</pre>
        <div class="schema-item-actions" style="margin-bottom:12px">
          <button class="btn-xs" onclick="openSchemaPreview('${escJs(url)}')">
            ⊡ Preview
          </button>
          <button class="btn-xs" onclick="copySingleSchemaHtml('${escJs(url)}')">
            Copy HTML
          </button>
          <button class="btn-xs" onclick="copySingleSchemaJson('${escJs(url)}')">
            Copy JSON
          </button>
          <button class="btn-xs" onclick="exportSinglePage('${escJs(url)}')">
            ↓ Export
          </button>
        </div>
        <div class="schema-error-fixer-inline" style="display:flex;gap:8px;padding:8px 12px;background:var(--cream-2);border-top:1px solid rgba(0,0,0,0.05)">
          <input type="text" id="error-input-${escJs(url)}" placeholder="Found an error? Paste it here (e.g. Missing image URL)..." style="flex:1;font-size:12px;padding:6px 10px;border:1px solid rgba(0,0,0,0.15);border-radius:4px;background:#fff">
          <button class="btn-primary-sm" onclick="fixPageErrorOnTheSpot('${escJs(url)}')" style="font-size:11px;padding:6px 12px;cursor:pointer">Fix & Rewrite</button>
        </div>
      </div>
    </div>`;
  }).join("");
}

function escJsonAttr(obj) {
  // Safe inline JSON for onclick handlers
  return JSON.stringify(JSON.stringify(obj)).slice(1, -1).replace(/'/g, "&#39;");
}

function exportSinglePage(url) {
  const project = projectsCache.find(p => p.id === currentProjectId);
  const data    = project?.schemas_generated?.[url];
  if (!data) { toast("Schema not found.", "error"); return; }

  const slug = slugify(url.replace(/^https?:\/\/[^/]+/, "") || "page");
  downloadBlob(data.json_ld_html || "", `schema-${slug}.html`, "text/html");
  toast("Page schema exported.", "success", `schema-${slug}.html`);
}

// ═══════════════════════════════════════════════════════════════════════════════
//  ENHANCED PROJECT CARDS (export button)
// ═══════════════════════════════════════════════════════════════════════════════

function renderDashboard(projects) {
  const grid   = document.getElementById("projects-grid");
  const noProj = document.getElementById("no-projects");
  if (!grid) return;

  if (!projects.length) {
    grid.innerHTML = "";
    if (noProj) noProj.classList.remove("hidden");
    return;
  }
  if (noProj) noProj.classList.add("hidden");

  grid.innerHTML = projects.map(p => {
    const pagesCount   = (p.pages_found || []).length;
    const schemasCount = Object.keys(p.schemas_generated || {}).length;
    const hasSitemap   = !!p.sitemap_xml;
    const dateStr      = new Date(p.created_at).toLocaleDateString();

    return `
    <div class="project-card" onclick="openProject(${p.id})">
      <div class="card-badge">${dateStr}</div>
      <div class="card-title">${esc(p.name)}</div>
      <div class="card-url">${esc(p.website_url)}</div>
      <div class="card-stats">
        <div class="card-stat">
          <div class="card-stat-val">${pagesCount}</div>
          <div class="card-stat-label">Pages</div>
        </div>
        <div class="card-stat">
          <div class="card-stat-val">${schemasCount}</div>
          <div class="card-stat-label">Schemas</div>
        </div>
        <div class="card-stat">
          <div class="card-stat-val">${hasSitemap ? "✓" : "—"}</div>
          <div class="card-stat-label">Sitemap</div>
        </div>
      </div>
      <div class="card-actions" onclick="event.stopPropagation()">
        <button class="btn-xs" onclick="openProject(${p.id})">Open →</button>
        ${schemasCount ? `<button class="btn-xs" onclick="quickExport(${p.id})">⬇ Export</button>` : ""}
      </div>
    </div>`;
  }).join("");
}

async function quickExport(projectId) {
  let project = projectsCache.find(p => p.id === projectId);
  if (!project?.schemas_generated || !Object.keys(project.schemas_generated).length) {
    // Fetch fresh
    try {
      const res = await apiFetch(`/api/schema/projects/${projectId}`);
      project = res.project;
      updateProjectCache(projectId, project);
    } catch { toast("Export failed — project not found.", "error"); return; }
  }
  currentProjectId = projectId;
  exportAllJsonLD(project);
}

// ═══════════════════════════════════════════════════════════════════════════════
//  ENHANCED PROJECT VIEW HEADER ACTIONS
// ═══════════════════════════════════════════════════════════════════════════════

function injectProjectActions() {
  // Add Export and Multi-Patch buttons to project view header if not present
  const headerActions = document.querySelector("#view-project .header-actions");
  if (!headerActions || document.getElementById("btn-export-project")) return;

  const exportBtn = document.createElement("button");
  exportBtn.id    = "btn-export-project";
  exportBtn.className = "btn-secondary";
  exportBtn.textContent = "⬇ Export";
  exportBtn.onclick = () => openExportModal();

  const patchBtn = document.createElement("button");
  patchBtn.id    = "btn-multi-patch";
  patchBtn.className = "btn-secondary";
  patchBtn.textContent = "⊞ Patch Pages";
  patchBtn.onclick = () => openMultiPatchModal();

  // Insert before the delete button
  const deleteBtn = document.getElementById("delete-project-btn");
  if (deleteBtn) {
    headerActions.insertBefore(exportBtn, deleteBtn);
    headerActions.insertBefore(patchBtn, deleteBtn);
  } else {
    headerActions.appendChild(exportBtn);
    headerActions.appendChild(patchBtn);
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  VIEWER NOTICE BANNER
// ═══════════════════════════════════════════════════════════════════════════════

function ensureViewerNotice() {
  if (document.getElementById("viewer-notice")) return;
  const notice = document.createElement("div");
  notice.id        = "viewer-notice";
  notice.className = "viewer-notice";
  notice.innerHTML = "👁 Read-only mode — you have Viewer access. Contact an Admin to get write access.";
  const mainContent = document.querySelector(".main-content");
  if (mainContent) mainContent.insertBefore(notice, mainContent.firstChild);
}

// ═══════════════════════════════════════════════════════════════════════════════
//  SIDEBAR FOOTER — Change Password & Role Badge
// ═══════════════════════════════════════════════════════════════════════════════

function enhanceSidebarFooter() {
  const footer = document.querySelector(".sidebar-footer");
  if (!footer || document.getElementById("btn-change-pw")) return;

  const pwBtn = document.createElement("button");
  pwBtn.id        = "btn-change-pw";
  pwBtn.className = "btn-logout";
  pwBtn.title     = "Change password";
  pwBtn.textContent = "🔑";
  pwBtn.onclick = openPasswordModal;
  footer.insertBefore(pwBtn, footer.querySelector(".btn-logout"));
}

// ═══════════════════════════════════════════════════════════════════════════════
//  HOOK INTO APP LIFECYCLE
// ═══════════════════════════════════════════════════════════════════════════════

// Override loadApp to apply role UI after login
const _baseLoadApp = window.loadApp;
window.loadApp = async function() {
  await _baseLoadApp?.();
  ensureViewerNotice();
  enhanceSidebarFooter();
};

// Override verifyAndLoadApp to pass role
const _baseVerify = window.verifyAndLoadApp;
window.verifyAndLoadApp = async function() {
  try {
    const res = await apiFetch("/api/auth/verify");
    if (res.valid) {
      currentUser = res.user;
      // Patch name display with full user object
      const user = await apiFetch("/api/auth/me").then(r => r.user).catch(() => res.user);
      document.getElementById("user-name").textContent  = user.name || user.email?.split("@")[0] || "User";
      document.getElementById("user-email").textContent = user.email || "";
      document.getElementById("user-avatar").textContent = (user.name || user.email || "U")[0].toUpperCase();

      await (window._origLoadApp || loadApp)?.();
      applyRoleUI(user.role || res.user.role || "contributor");
      ensureViewerNotice();
      enhanceSidebarFooter();
    } else {
      logout();
    }
  } catch {
    logout();
  }
};

// Override switchView to load admin data
const _eSwitchView = window.switchView;
window.switchView = function(viewName) {
  _eSwitchView?.(viewName);
  if (viewName === "admin") loadAdminData();
  if (viewName === "project") {
    setTimeout(injectProjectActions, 50);
  }
};

// Override openProject to inject action buttons
const _eOpenProject = window.openProject;
window.openProject = async function(projectId) {
  await _eOpenProject?.(projectId);
  injectProjectActions();
};

// ═══════════════════════════════════════════════════════════════════════════════
//  INSTRUCTION HELP TOOLTIP (inline in correction modal)
// ═══════════════════════════════════════════════════════════════════════════════

function injectInstructionHelp(textareaId, containerId) {
  const container = document.getElementById(containerId);
  if (!container || document.getElementById(`help-${containerId}`)) return;

  const helpEl = document.createElement("div");
  helpEl.id    = `help-${containerId}`;
  helpEl.className = "instruction-help";
  helpEl.innerHTML = `
    <b>Command Reference:</b><br>
    <b>ADD</b> key value &nbsp;|&nbsp;
    <b>REMOVE</b> key &nbsp;|&nbsp;
    <b>SET</b> path.nested value<br>
    <b>UNSET</b> path.nested &nbsp;|&nbsp;
    <b>APPEND</b> key value &nbsp;|&nbsp;
    <b>RENAME</b> old new<br>
    <b>TYPE</b> NewType [IF @type=OldType] &nbsp;|&nbsp;
    <b>REPLACE</b> "old" "new"<br>
    <b>MOVE</b> src dest &nbsp;|&nbsp;
    <b>COPY</b> src dest &nbsp;|&nbsp;
    <b>IF</b> condition <b>THEN</b> command<br>
    <span style="color:var(--stone)">Values: strings, numbers, or JSON objects</span>`;

  const ta = document.getElementById(textareaId);
  if (ta && ta.parentNode) {
    ta.parentNode.insertBefore(helpEl, ta.nextSibling);
  }
}

// Inject help on correction modal open
const _origOpenSubmit = window.openSubmitCorrection;
window.openSubmitCorrection = function() {
  _origOpenSubmit?.();
  setTimeout(() => injectInstructionHelp("corr-instructions", "corr-instructions"), 100);
};

// ═══════════════════════════════════════════════════════════════════════════════
//  UTILITY: copy all schemas as combined HTML
// ═══════════════════════════════════════════════════════════════════════════════

function copyAllSchemas() {
  const project = projectsCache.find(p => p.id === currentProjectId);
  const schemas = project?.schemas_generated || {};
  const allHtml = Object.values(schemas).map(s => s.json_ld_html).filter(Boolean).join("\n\n\n");
  if (!allHtml) { toast("No schemas to copy.", "warning"); return; }
  copyText(allHtml);
  toast("All schemas copied!", "success", `${Object.keys(schemas).length} pages`);
}

async function fixPageErrorOnTheSpot(url) {
  const inputEl = document.getElementById(`error-input-${url}`);
  const errorText = inputEl?.value.trim();
  if (!errorText) {
    toast("Please enter an error message first.", "warning");
    return;
  }

  showLoading("Parsing error and rewriting schema for page…");
  try {
    const res = await apiFetch(`/api/feed/projects/${currentProjectId}/fix-page-error`, "POST", {
      page_url: url,
      error_text: errorText
    });
    hideLoading();
    if (inputEl) inputEl.value = "";

    toast("Schema corrected & rewritten successfully!", "success");

    // Refresh project in cache
    const proj = await apiFetch(`/api/schema/projects/${currentProjectId}`);
    const idx = projectsCache.findIndex(p => p.id === currentProjectId);
    if (idx >= 0) projectsCache[idx] = proj.project;
    restorePipelineState(proj.project);
  } catch (err) {
    hideLoading();
    toast("Correction failed: " + err.message, "error");
  }
}

function openManagePagesModal() {
  if (!currentProjectId) return;
  const project = projectsCache.find(p => p.id === currentProjectId);
  if (!project) return;

  const pages = project.pages_found || [];
  const urls = pages.map(p => p.url).join("\n");
  document.getElementById("manage-urls-input").value = urls;
  document.getElementById("manage-pages-error").classList.add("hidden");
  openModal("manage-pages-modal");
}

async function submitManualPages() {
  const urlsRaw = document.getElementById("manage-urls-input").value.trim();
  const errorEl = document.getElementById("manage-pages-error");
  errorEl.classList.add("hidden");

  const urls = urlsRaw
    ? urlsRaw.split("\n").map(u => u.trim()).filter(Boolean)
    : [];

  showLoading("Updating pages manually…");
  try {
    await apiFetch(`/api/schema/projects/${currentProjectId}/pages`, "POST", { pages: urls });
    hideLoading();
    closeModal("manage-pages-modal");
    toast("Pages list updated manually!", "success");

    // Refresh project in cache
    const proj = await apiFetch(`/api/schema/projects/${currentProjectId}`);
    const idx = projectsCache.findIndex(p => p.id === currentProjectId);
    if (idx >= 0) projectsCache[idx] = proj.project;
    restorePipelineState(proj.project);
  } catch (err) {
    hideLoading();
    errorEl.textContent = err.message;
    errorEl.classList.remove("hidden");
  }
}
