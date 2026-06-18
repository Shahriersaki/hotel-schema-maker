/* ── Hotel Schema Maker — Frontend JS ──────────────────
   Pure vanilla JS, no dependencies needed.
──────────────────────────────────────────────────────── */

const API = "";  // Empty = same origin; change for separate backend

// ─── State ────────────────────────────────────────────
let token = localStorage.getItem("hsm_token") || null;
let currentUser = null;
let currentProjectId = null;
let projectsCache = [];

// ─── Init ─────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  if (token) {
    verifyAndLoadApp();
  } else {
    showScreen("auth");
  }
});

async function verifyAndLoadApp() {
  try {
    const res = await apiFetch("/api/auth/verify");
    if (res.valid) {
      currentUser = res.user;
      await loadApp();
    } else {
      logout();
    }
  } catch {
    logout();
  }
}

async function loadApp() {
  // Set user info in sidebar
  document.getElementById("user-name").textContent = currentUser.email?.split("@")[0] || "User";
  document.getElementById("user-email").textContent = currentUser.email || "";
  document.getElementById("user-avatar").textContent =
    (currentUser.email || "U")[0].toUpperCase();

  showScreen("app");
  await loadDashboard();
}

// ─── Auth Handlers ────────────────────────────────────
async function handleLogin() {
  const email    = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;
  const errorEl  = document.getElementById("login-error");
  hideEl(errorEl);

  if (!email || !password) {
    return showError(errorEl, "Please enter your email and password.");
  }

  showLoading("Signing in…");
  try {
    const res = await apiFetch("/api/auth/login", "POST", { email, password });
    token = res.token;
    currentUser = res.user;
    localStorage.setItem("hsm_token", token);
    hideLoading();
    await loadApp();
  } catch (err) {
    hideLoading();
    showError(errorEl, err.message || "Login failed. Please try again.");
  }
}

async function handleRegister() {
  const name     = document.getElementById("reg-name").value.trim();
  const email    = document.getElementById("reg-email").value.trim();
  const password = document.getElementById("reg-password").value;
  const errorEl  = document.getElementById("reg-error");
  hideEl(errorEl);

  if (!name || !email || !password) {
    return showError(errorEl, "All fields are required.");
  }

  showLoading("Creating account…");
  try {
    const res = await apiFetch("/api/auth/register", "POST", { name, email, password });
    token = res.token;
    currentUser = res.user;
    localStorage.setItem("hsm_token", token);
    hideLoading();
    await loadApp();
  } catch (err) {
    hideLoading();
    showError(errorEl, err.message || "Registration failed.");
  }
}

function handleLogout() {
  logout();
}

function logout() {
  token = null;
  currentUser = null;
  localStorage.removeItem("hsm_token");
  showScreen("auth");
}

function switchAuth(panel) {
  document.querySelectorAll(".auth-panel").forEach(p => p.classList.remove("active"));
  document.getElementById(`${panel}-panel`).classList.add("active");
  // Clear errors
  document.getElementById("login-error").classList.add("hidden");
  document.getElementById("reg-error").classList.add("hidden");
}

// ─── Dashboard ────────────────────────────────────────
async function loadDashboard() {
  try {
    const res = await apiFetch("/api/schema/projects");
    projectsCache = res.projects || [];
    renderDashboard(projectsCache);
    renderSidebarProjects(projectsCache);
  } catch (err) {
    console.error("Dashboard load failed:", err);
  }
}

function renderDashboard(projects) {
  const grid   = document.getElementById("projects-grid");
  const noProj = document.getElementById("no-projects");

  if (!projects.length) {
    grid.innerHTML = "";
    noProj.classList.remove("hidden");
    return;
  }

  noProj.classList.add("hidden");
  grid.innerHTML = projects.map(p => {
    const pagesCount   = (p.pages_found || []).length;
    const schemasCount = Object.keys(p.schemas_generated || {}).length;
    const hasSitemap   = !!p.sitemap_xml;
    return `
    <div class="project-card" onclick="openProject(${p.id})">
      <div class="card-badge">${new Date(p.created_at).toLocaleDateString()}</div>
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
    </div>`;
  }).join("");
}

function renderSidebarProjects(projects) {
  const list = document.getElementById("sidebar-project-list");
  list.innerHTML = projects.slice(0, 8).map(p =>
    `<button class="sidebar-proj-item ${p.id === currentProjectId ? 'active' : ''}"
       onclick="openProject(${p.id})">${esc(p.name)}</button>`
  ).join("") || '<div style="padding:8px 12px;font-size:11px;color:rgba(255,255,255,0.2)">No projects</div>';
}

// ─── New Project ──────────────────────────────────────
async function createProject() {
  const errorEl = document.getElementById("new-proj-error");
  hideEl(errorEl);

  const name = document.getElementById("proj-name").value.trim();
  const websiteUrl = document.getElementById("proj-url").value.trim();
  const hotelName = document.getElementById("hotel-name").value.trim();
  const street = document.getElementById("addr-street").value.trim();
  const city = document.getElementById("addr-city").value.trim();
  const country = document.getElementById("addr-country").value.trim().toUpperCase();

  if (!name) return showError(errorEl, "Project name is required.");
  if (!websiteUrl) return showError(errorEl, "Website URL is required.");
  if (!hotelName) return showError(errorEl, "Hotel name is required.");
  if (!street || !city || !country) return showError(errorEl, "Street address, city, and country are required.");

  const amenitiesRaw = document.getElementById("hotel-amenities").value.trim();
  const amenities = amenitiesRaw ? amenitiesRaw.split(",").map(s => s.trim()).filter(Boolean) : [];

  const hotelData = {
    name: hotelName,
    description: document.getElementById("hotel-desc").value.trim(),
    starRating: document.getElementById("hotel-stars").value || null,
    priceRange: document.getElementById("hotel-price").value || "",
    telephone: document.getElementById("hotel-phone").value.trim(),
    email: document.getElementById("hotel-email").value.trim(),
    checkinTime: document.getElementById("hotel-checkin").value || "14:00",
    checkoutTime: document.getElementById("hotel-checkout").value || "12:00",
    bookingUrl: document.getElementById("hotel-booking").value.trim(),
    amenities,
    address: {
      streetAddress: street,
      addressLocality: city,
      addressRegion: document.getElementById("addr-region").value.trim(),
      postalCode: document.getElementById("addr-postal").value.trim(),
      addressCountry: country,
    }
  };

  showLoading("Creating project…");
  try {
    const res = await apiFetch("/api/schema/projects", "POST", {
      name, website_url: websiteUrl, hotel_data: hotelData
    });
    hideLoading();
    toast("Project created!", "success");
    projectsCache.unshift(res.project);
    renderSidebarProjects(projectsCache);
    openProject(res.project.id);
  } catch (err) {
    hideLoading();
    showError(errorEl, err.message || "Failed to create project.");
  }
}

// ─── Project View ─────────────────────────────────────
async function openProject(projectId) {
  currentProjectId = projectId;

  // Find project in cache or fetch
  let project = projectsCache.find(p => p.id === projectId);
  if (!project) {
    try {
      const res = await apiFetch(`/api/schema/projects/${projectId}`);
      project = res.project;
    } catch {
      toast("Failed to load project.", "error");
      return;
    }
  }

  // Update nav
  document.querySelectorAll(".sidebar-proj-item").forEach(el => {
    el.classList.toggle("active", el.textContent === project.name);
  });
  document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));

  // Update header
  document.getElementById("project-title").textContent = project.name;
  document.getElementById("project-subtitle").textContent = project.website_url;

  // Delete button
  document.getElementById("delete-project-btn").onclick = () => deleteProject(projectId);

  // Restore pipeline state from project data
  restorePipelineState(project);

  switchView("project");
}

function restorePipelineState(project) {
  const pages = project.pages_found || [];
  const schemas = project.schemas_generated || {};
  const sitemap = project.sitemap_xml || "";

  // Reset
  ["crawl","enrich","schema","sitemap"].forEach(s => {
    const step = document.getElementById(`step-${s}`);
    if (step) step.classList.remove("done","active");
  });
  ["crawl-result","enrich-result","schema-result","sitemap-result"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = "";
  });

  // Pages
  if (pages.length) {
    document.getElementById("step-crawl").classList.add("done");
    document.getElementById("crawl-result").textContent = `${pages.length} pages found`;
    renderPagesSection(pages);
  }

  // Enrichment log
  const log = project.hotel_data?.enrichment_log;
  if (log?.length) {
    document.getElementById("step-enrich").classList.add("done");
    document.getElementById("enrich-result").textContent = `${log.length} enrichments`;
    renderEnrichSection(log);
  }

  // Schemas
  if (Object.keys(schemas).length) {
    document.getElementById("step-schema").classList.add("done");
    document.getElementById("schema-result").textContent = `${Object.keys(schemas).length} schemas`;
    renderSchemasSection(schemas);
  }

  // Sitemap
  if (sitemap) {
    document.getElementById("step-sitemap").classList.add("done");
    document.getElementById("sitemap-result").textContent = "Generated ✓";
    renderSitemapSection(sitemap);
  }
}

// ─── Pipeline Steps ───────────────────────────────────
async function runCrawl() {
  if (!currentProjectId) return;
  disableAllButtons();
  showLoading("Crawling website… This may take 30–90 seconds.");

  try {
    const res = await apiFetch(`/api/schema/projects/${currentProjectId}/crawl`, "POST", {max_pages: 50});
    updateProjectCache(currentProjectId, { pages_found: res.pages });

    document.getElementById("step-crawl").classList.add("done");
    document.getElementById("crawl-result").textContent = `${res.page_count} pages found`;
    renderPagesSection(res.pages);
    toast(`Crawl complete! Found ${res.page_count} pages.`, "success");
  } catch (err) {
    toast("Crawl failed: " + (err.message || "Unknown error"), "error");
  } finally {
    hideLoading();
    enableAllButtons();
  }
}

async function runEnrich() {
  if (!currentProjectId) return;
  disableAllButtons();
  showLoading("Enriching hotel data from online sources…");

  try {
    const res = await apiFetch(`/api/schema/projects/${currentProjectId}/enrich`, "POST");
    updateProjectCache(currentProjectId, { hotel_data: res.hotel_data });

    document.getElementById("step-enrich").classList.add("done");
    document.getElementById("enrich-result").textContent = `${res.enrichment_log.length} enrichments`;
    renderEnrichSection(res.enrichment_log);
    toast("Data enrichment complete!", "success");
  } catch (err) {
    toast("Enrichment failed: " + (err.message || "Unknown error"), "error");
  } finally {
    hideLoading();
    enableAllButtons();
  }
}

async function runSchemas() {
  if (!currentProjectId) return;
  disableAllButtons();
  showLoading("Generating JSON-LD schemas for all pages…");

  try {
    const res = await apiFetch(`/api/schema/projects/${currentProjectId}/generate`, "POST");
    updateProjectCache(currentProjectId, { schemas_generated: res.schemas });

    document.getElementById("step-schema").classList.add("done");
    document.getElementById("schema-result").textContent = `${res.page_count} schemas`;
    renderSchemasSection(res.schemas);
    toast(`Generated schemas for ${res.page_count} pages!`, "success");
  } catch (err) {
    toast("Schema generation failed: " + (err.message || "Unknown error"), "error");
  } finally {
    hideLoading();
    enableAllButtons();
  }
}

async function runSitemap() {
  if (!currentProjectId) return;
  disableAllButtons();
  showLoading("Generating XML sitemap…");

  try {
    const res = await apiFetch(`/api/sitemap/projects/${currentProjectId}/generate`, "POST");
    updateProjectCache(currentProjectId, { sitemap_xml: res.sitemap_xml });

    document.getElementById("step-sitemap").classList.add("done");
    document.getElementById("sitemap-result").textContent = `${res.stats.total_urls} URLs ✓`;
    renderSitemapSection(res.sitemap_xml);
    toast(`Sitemap generated with ${res.stats.total_urls} URLs!`, "success");
  } catch (err) {
    toast("Sitemap generation failed: " + (err.message || "Unknown error"), "error");
  } finally {
    hideLoading();
    enableAllButtons();
  }
}

async function runAll() {
  if (!currentProjectId) return;
  disableAllButtons();
  showLoading("Running full pipeline: crawl → enrich → schema → sitemap…");

  try {
    const res = await apiFetch(`/api/schema/projects/${currentProjectId}/run-all`, "POST");
    const project = res.project;
    updateProjectCache(currentProjectId, {
      pages_found: project.pages_found,
      hotel_data: project.hotel_data,
      schemas_generated: project.schemas_generated,
      sitemap_xml: project.sitemap_xml
    });

    restorePipelineState(project);

    // Also generate sitemap if schemas exist
    if (Object.keys(project.schemas_generated || {}).length && !project.sitemap_xml) {
      await runSitemap();
    }

    toast("Full pipeline complete! 🎉", "success");
  } catch (err) {
    toast("Pipeline failed: " + (err.message || "Unknown error"), "error");
  } finally {
    hideLoading();
    enableAllButtons();
  }
}

async function deleteProject(projectId) {
  if (!confirm("Delete this project? This cannot be undone.")) return;

  showLoading("Deleting project…");
  try {
    await apiFetch(`/api/schema/projects/${projectId}`, "DELETE");
    projectsCache = projectsCache.filter(p => p.id !== projectId);
    renderSidebarProjects(projectsCache);
    toast("Project deleted.", "success");
    switchView("dashboard");
    renderDashboard(projectsCache);
  } catch (err) {
    toast("Delete failed: " + (err.message || "Unknown error"), "error");
  } finally {
    hideLoading();
  }
}

// ─── Render Helpers ───────────────────────────────────
function renderPagesSection(pages) {
  const section = document.getElementById("pages-section");
  section.classList.remove("hidden");
  document.getElementById("pages-count").textContent = pages.length;

  const typeColors = {
    home: "#b8960c", rooms: "#1a3a5c", dining: "#c0392b",
    gallery: "#7d3c98", attractions: "#1e8449", offers: "#d35400",
    blog: "#2980b9", contact: "#27ae60", spa: "#a04000",
    events: "#8e44ad", faq: "#17a589", about: "#566573"
  };

  document.getElementById("pages-list").innerHTML = pages.map(p => {
    const isSelected = p.selected !== false;
    return `
    <div class="page-item" style="display:flex;align-items:center;gap:10px">
      <input type="checkbox" class="page-select-checkbox" ${isSelected ? 'checked' : ''} onchange="togglePageSelection('${escJs(p.url)}', this.checked)" style="width:16px;height:16px;cursor:pointer">
      <span class="page-type-badge" style="background:${typeColors[p.page_type] || '#888'}22;color:${typeColors[p.page_type] || '#888'}">${p.page_type}</span>
      <span class="page-url" title="${esc(p.url)}" style="flex:1">${esc(p.url.replace(/^https?:\/\/[^\/]+/, ''))  || '/'}</span>
    </div>`;
  }).join("");
}

function renderEnrichSection(log) {
  const section = document.getElementById("enrich-section");
  section.classList.remove("hidden");
  document.getElementById("enrich-log").innerHTML = log.map(item =>
    `<div class="log-item">${esc(item)}</div>`
  ).join("");
}

function renderSchemasSection(schemas) {
  const section = document.getElementById("schemas-section");
  section.classList.remove("hidden");
  document.getElementById("schemas-count").textContent = Object.keys(schemas).length;

  document.getElementById("schemas-list").innerHTML = Object.entries(schemas).map(([url, data]) => `
    <div class="schema-item">
      <div class="schema-item-header" onclick="toggleSchema(this)">
        <span class="page-type-badge">${esc(data.page_type || "page")}</span>
        <span class="schema-item-url">${esc(url)}</span>
        <span class="schema-item-toggle">▾ ${data.schema_count} schema${data.schema_count !== 1 ? 's' : ''}</span>
      </div>
      <div class="schema-item-body">
        <pre class="code-block">${esc(data.json_ld_html || JSON.stringify(data.schemas, null, 2))}</pre>
        <div style="padding:8px 12px;background:var(--cream-2);display:flex;gap:8px;">
          <button class="btn-xs" onclick="copySingleSchemaHtml('${escJs(url)}')">Copy HTML</button>
          <button class="btn-xs" onclick="copySingleSchemaJson('${escJs(url)}')">Copy JSON</button>
        </div>
      </div>
    </div>`).join("");
}

function renderSitemapSection(xml) {
  const section = document.getElementById("sitemap-section");
  section.classList.remove("hidden");
  document.getElementById("sitemap-preview").textContent = xml.substring(0, 3000) +
    (xml.length > 3000 ? "\n\n… (truncated for preview)" : "");
}

function toggleSchema(headerEl) {
  const body = headerEl.nextElementSibling;
  const isOpen = body.classList.toggle("open");
  headerEl.querySelector(".schema-item-toggle").textContent =
    (isOpen ? "▴" : "▾") + " " + headerEl.querySelector(".schema-item-toggle").textContent.slice(2);
}

// ─── Download / Copy ──────────────────────────────────
function copySingleSchemaHtml(url) {
  const project = projectsCache.find(p => p.id === currentProjectId);
  const data = project?.schemas_generated?.[url];
  if (!data || !data.json_ld_html) {
    toast("No schema HTML to copy.", "error");
    return;
  }
  copyText(data.json_ld_html);
  toast("Copied HTML schema!", "success");
}

function copySingleSchemaJson(url) {
  const project = projectsCache.find(p => p.id === currentProjectId);
  const data = project?.schemas_generated?.[url];
  if (!data || !data.schemas) {
    toast("No schema JSON to copy.", "error");
    return;
  }
  copyText(JSON.stringify(data.schemas, null, 2));
  toast("Copied JSON schema!", "success");
}

function copyAllSchemas() {
  const schemas = projectsCache.find(p => p.id === currentProjectId)?.schemas_generated || {};
  const allHtml = Object.values(schemas).map(s => s.json_ld_html).join("\n\n\n");
  copyText(allHtml);
  toast("All schemas copied to clipboard!", "success");
}

function copySitemap() {
  const project = projectsCache.find(p => p.id === currentProjectId);
  if (project?.sitemap_xml) {
    copyText(project.sitemap_xml);
    toast("Sitemap XML copied!", "success");
  }
}

async function downloadSitemap() {
  if (!currentProjectId) return;
  const url = `/api/sitemap/projects/${currentProjectId}/download`;
  const a = document.createElement("a");
  a.href = url;
  a.download = "sitemap.xml";
  // Add auth header via fetch + blob
  try {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error("Download failed");
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    a.href = blobUrl;
    a.click();
    URL.revokeObjectURL(blobUrl);
    toast("Sitemap downloaded!", "success");
  } catch {
    toast("Download failed.", "error");
  }
}

function copyText(text) {
  navigator.clipboard.writeText(text).then(() => {
    toast("Copied to clipboard!", "success");
  }).catch(() => {
    // Fallback
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    toast("Copied!", "success");
  });
}

// ─── UI Helpers ───────────────────────────────────────
function switchView(viewName) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.getElementById(`view-${viewName}`).classList.add("active");

  // Update nav
  document.querySelectorAll(".nav-item").forEach(el => {
    el.classList.toggle("active", el.dataset.view === viewName);
  });

  if (viewName === "dashboard") {
    loadDashboard();
  }
}

function showScreen(name) {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  document.getElementById(`${name}-screen`).classList.add("active");
}

function showLoading(msg = "Processing…") {
  document.getElementById("loading-msg").textContent = msg;
  document.getElementById("loading-overlay").classList.remove("hidden");
}

function hideLoading() {
  document.getElementById("loading-overlay").classList.add("hidden");
}

function toast(msg, type = "info") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = `toast ${type}`;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 3500);
}

function showError(el, msg) {
  el.textContent = msg;
  el.classList.remove("hidden");
}

function hideEl(el) { el.classList.add("hidden"); }

function disableAllButtons() {
  document.querySelectorAll(".btn-step, .btn-run-all").forEach(b => b.disabled = true);
}

function enableAllButtons() {
  document.querySelectorAll(".btn-step, .btn-run-all").forEach(b => b.disabled = false);
}

function updateProjectCache(projectId, updates) {
  const idx = projectsCache.findIndex(p => p.id === projectId);
  if (idx >= 0) Object.assign(projectsCache[idx], updates);
}

// ─── API Fetch ────────────────────────────────────────
async function apiFetch(path, method = "GET", body = null) {
  const opts = {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }
  };
  if (body) opts.body = JSON.stringify(body);

  const res = await fetch(API + path, opts);
  const data = await res.json();

  if (!res.ok) {
    throw new Error(data.error || data.message || `HTTP ${res.status}`);
  }
  return data;
}

// ─── XSS Helpers ─────────────────────────────────────
function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escJs(str) {
  return String(str)
    .replace(/\\/g, "\\\\")
    .replace(/`/g, "\\`")
    .replace(/\$/g, "\\$");
}

// ─── Keyboard shortcuts ───────────────────────────────
document.addEventListener("keydown", e => {
  if (e.key === "Enter") {
    const loginPanel = document.getElementById("login-panel");
    const regPanel = document.getElementById("register-panel");
    if (loginPanel.classList.contains("active")) handleLogin();
    else if (regPanel.classList.contains("active")) handleRegister();
  }
});

// ═══════════════════════════════════════════════════════
//  FEED SYSTEM
// ═══════════════════════════════════════════════════════

// ─── Knowledge Base ───────────────────────────────────
async function loadKBEntries() {
  const filter = document.getElementById("kb-filter")?.value || "";
  const url = "/api/feed/kb" + (filter ? `?type=${filter}` : "");

  try {
    const res = await apiFetch(url);
    renderKBEntries(res.entries);
  } catch (err) {
    toast("Failed to load knowledge base: " + err.message, "error");
  }
}

function renderKBEntries(entries) {
  const list  = document.getElementById("kb-entries-list");
  const empty = document.getElementById("kb-empty");
  const count = document.getElementById("kb-count");

  if (count) count.textContent = entries.length;

  if (!entries.length) {
    if (list) list.innerHTML = "";
    if (empty) empty.classList.remove("hidden");
    return;
  }
  if (empty) empty.classList.add("hidden");

  list.innerHTML = entries.map(e => `
    <div class="kb-entry">
      <span class="kb-entry-type ${esc(e.entry_type)}">${esc(e.entry_type)}</span>
      <div class="kb-entry-body">
        <div class="kb-entry-title">${esc(e.title)}</div>
        <div class="kb-entry-content">${esc(e.content)}</div>
        ${e.source ? `<div class="kb-entry-source">↗ ${esc(e.source)}</div>` : ""}
      </div>
      <button class="kb-entry-del" onclick="deleteKBEntry(${e.id})" title="Remove">✕</button>
    </div>`).join("");
}

async function deleteKBEntry(entryId) {
  if (!confirm("Remove this knowledge base entry?")) return;
  try {
    await apiFetch(`/api/feed/kb/${entryId}`, "DELETE");
    toast("Entry removed.", "success");
    loadKBEntries();
  } catch (err) {
    toast("Delete failed: " + err.message, "error");
  }
}

// ─── KB Modal ─────────────────────────────────────────
function openAddKBModal(type = "") {
  document.getElementById("kb-title").value = "";
  document.getElementById("kb-content").value = "";
  document.getElementById("kb-source").value = "";
  document.getElementById("kb-error").classList.add("hidden");
  if (type) document.getElementById("kb-type").value = type;
  openModal("kb-modal");
}

async function submitKBModal() {
  const title   = document.getElementById("kb-title").value.trim();
  const content = document.getElementById("kb-content").value.trim();
  const type    = document.getElementById("kb-type").value;
  const source  = document.getElementById("kb-source").value.trim();
  const errorEl = document.getElementById("kb-error");

  if (!title) return showError(errorEl, "Title is required.");
  if (!content) return showError(errorEl, "Content is required.");

  try {
    await apiFetch("/api/feed/kb", "POST", {
      entry_type: type, title, content, source
    });
    closeModal("kb-modal");
    toast("Entry added to knowledge base!", "success");
    loadKBEntries();
  } catch (err) {
    showError(errorEl, err.message || "Failed to save entry.");
  }
}

// ─── Validator Paste Parser ────────────────────────────
async function parseValidatorPaste() {
  const paste = document.getElementById("validator-paste").value.trim();
  const resultEl = document.getElementById("paste-result");
  if (!paste) { toast("Paste some validator output first.", "error"); return; }

  try {
    const res = await apiFetch("/api/feed/validate-paste", "POST", { paste });
    resultEl.classList.remove("hidden");

    let html = `<div style="margin-bottom:8px;font-weight:500">${res.error_count} error(s) parsed</div>`;
    for (const e of res.structured_errors.slice(0, 12)) {
      const cls = e.severity === "ERROR" ? "err-item" : e.severity === "WARNING" ? "warn-item" : "info-item";
      html += `<div class="${cls}">[${e.severity}] ${esc(e.message)}</div>`;
    }

    if (res.suggestions.length) {
      html += `<div style="margin-top:10px;font-weight:500;color:var(--green)">${res.suggestions.length} KB suggestion(s):</div>`;
      for (const s of res.suggestions) {
        html += `<div class="sugg-item">→ ${esc(s.title)}
          <button class="btn-xs" style="margin-left:6px;font-size:10px" onclick='addSuggestedKB(${JSON.stringify(s).replace(/'/g,"&#39;")})'>Add to KB</button></div>`;
      }
    }
    resultEl.innerHTML = html;
    toast(`Parsed ${res.error_count} errors.`, "success");
  } catch (err) {
    toast("Parse failed: " + err.message, "error");
  }
}

async function addSuggestedKB(suggestion) {
  try {
    await apiFetch("/api/feed/kb", "POST", {
      entry_type: suggestion.entry_type,
      title: suggestion.title,
      content: suggestion.content,
      source: suggestion.source || "Auto-suggested"
    });
    toast("Suggestion added to KB!", "success");
    loadKBEntries();
  } catch (err) {
    toast("Failed: " + err.message, "error");
  }
}

// ═══════════════════════════════════════════════════════
//  TREND CHECKER
// ═══════════════════════════════════════════════════════

async function fetchTrends(force = false) {
  const btn = document.getElementById("btn-refresh-trends");
  if (btn) btn.disabled = true;
  showLoading(force ? "Fetching latest from schema.org and Google…" : "Loading cached trends…");

  try {
    const url = "/api/feed/trends" + (force ? "?force=true" : "");
    const res = await apiFetch(url);
    renderTrendSources(res.trends);
    if (force) toast("Trends refreshed from live sources!", "success");
  } catch (err) {
    toast("Trend fetch failed: " + err.message, "error");
  } finally {
    hideLoading();
    if (btn) btn.disabled = false;
  }
}

async function loadTrendDigest() {
  const panel = document.getElementById("digest-panel");
  if (!panel) return;

  try {
    const res = await apiFetch("/api/feed/trends/digest");
    const d = res.digest;
    panel.innerHTML = `
      <div class="digest-grid">
        <div>
          <div class="digest-col-title">Required Properties</div>
          <div class="digest-prop-list">
            ${(d.required_properties || []).map(p => `<div class="digest-prop">${esc(p)}</div>`).join("")}
          </div>
        </div>
        <div>
          <div class="digest-col-title">Recommended Properties</div>
          <div class="digest-prop-list">
            ${(d.recommended_properties || []).map(p => `<div class="digest-prop">${esc(p)}</div>`).join("")}
          </div>
        </div>
        <div>
          <div class="digest-col-title">Trend Notes & KB</div>
          <div class="digest-prop-list">
            ${(d.notes || []).map(n => `<div class="digest-note">${esc(n)}</div>`).join("") || '<div class="digest-note" style="color:var(--stone)">No notes yet</div>'}
          </div>
          ${(d.deprecated_properties || []).length ? `
            <div class="digest-col-title" style="margin-top:12px;color:#c0392b">Deprecated</div>
            ${d.deprecated_properties.map(p => `<div class="digest-prop" style="color:#c0392b">${esc(p)}</div>`).join("")}
          ` : ""}
        </div>
      </div>`;
  } catch (err) {
    if (panel) panel.innerHTML = `<div class="digest-loading">Digest unavailable: ${esc(err.message)}</div>`;
  }
}

function renderTrendSources(trends) {
  const grid = document.getElementById("trend-sources-grid");
  if (!grid) return;
  grid.innerHTML = "";

  const sourceMap = {
    "schema_org_hotel":        { label: "schema.org/Hotel",       key: "schema_org_hotel" },
    "google_docs":             { label: "Google Search Central",  key: "google_docs" },
    "schema_org_changelog":    { label: "schema.org Changelog",   key: "schema_org_changelog" },
    "google_rich_results_gallery": { label: "Google Rich Results", key: "google_rich_results_gallery" },
  };

  let rendered = 0;
  for (const [key, cfg] of Object.entries(sourceMap)) {
    const data = trends[key] || trends[key.replace(/_/g, "")] || null;
    if (!data) continue;
    rendered++;

    const fetchedAt = data.fetched_at
      ? new Date(data.fetched_at).toLocaleString()
      : (trends.fetched_at ? new Date(trends.fetched_at).toLocaleString() : "cached");

    let bodyHtml = "";

    if (key === "schema_org_hotel" && data.properties?.length) {
      bodyHtml = data.properties.slice(0, 20).map(p => `
        <div class="trend-prop-item">
          <span class="trend-prop-name">${esc(p.name)}</span>
          ${p.description ? `<div class="trend-prop-desc">${esc(p.description.slice(0,80))}</div>` : ""}
        </div>`).join("");
      bodyHtml += `<div style="color:var(--stone);font-size:11px;padding-top:6px">+${data.properties.length - 20} more properties</div>`;
    } else if (key === "google_docs") {
      const req = data.required_properties || [];
      const rec = data.recommended_properties || [];
      bodyHtml = req.length ? `<div style="font-size:10px;color:var(--green);font-family:var(--mono);margin-bottom:6px">REQUIRED (${req.length})</div>` +
        req.map(r => `<div class="trend-prop-item"><span class="trend-prop-name">${esc(r.slice(0,80))}</span></div>`).join("") : "";
      bodyHtml += rec.length ? `<div style="font-size:10px;color:var(--gold);font-family:var(--mono);margin:8px 0 6px">RECOMMENDED (${rec.length})</div>` +
        rec.slice(0,8).map(r => `<div class="trend-prop-item"><span class="trend-prop-name">${esc(r.slice(0,80))}</span></div>`).join("") : "";
      if (!bodyHtml) bodyHtml = `<div style="color:var(--stone);font-size:12px">No property data fetched (site may block scrapers)</div>`;
    } else if (key === "schema_org_changelog") {
      const changes = data.hotel_related_changes || [];
      bodyHtml = changes.length
        ? changes.map(c => `<div class="trend-prop-item"><span class="trend-prop-name">${esc(c.version)}</span><div class="trend-prop-desc">${esc((c.content||"").slice(0,100))}</div></div>`).join("")
        : `<div style="color:var(--stone);font-size:12px">No recent Hotel-related changelog entries found.</div>`;
    } else if (key === "google_rich_results_gallery") {
      const types = data.supported_types || [];
      bodyHtml = types.slice(0,15).map(t =>
        `<div class="trend-prop-item"><span class="trend-prop-name">${esc(t.name)}</span></div>`
      ).join("") + (types.length > 15 ? `<div style="color:var(--stone);font-size:11px;padding-top:4px">+${types.length-15} more</div>` : "");
    }

    if (data.error) {
      bodyHtml = `<div style="color:var(--red);font-size:12px;font-family:var(--mono)">Fetch error: ${esc(data.error)}</div>`;
    }

    grid.innerHTML += `
      <div class="trend-source-card">
        <div class="trend-source-head">
          <div class="trend-source-name">${esc(cfg.label)}</div>
          <div class="trend-source-time">${esc(fetchedAt)}</div>
        </div>
        <div class="trend-source-body">${bodyHtml || '<div style="color:var(--stone);font-size:12px">No data</div>'}</div>
      </div>`;
  }

  if (!rendered) {
    grid.innerHTML = `<div style="color:var(--stone);font-size:13px;padding:20px">No trend data yet. Click "Refresh Now" to fetch.</div>`;
  }
}

async function loadTrendSnapshots() {
  const list = document.getElementById("trend-snapshots-list");
  if (!list) return;
  try {
    const res = await apiFetch("/api/feed/trends/snapshots");
    if (!res.snapshots.length) {
      list.innerHTML = `<div style="color:var(--stone);font-size:12px">No snapshots yet. Run a trend refresh first.</div>`;
      return;
    }
    list.innerHTML = res.snapshots.map(s => `
      <div class="snapshot-item">
        <span class="snapshot-source">${esc(s.source)}</span>
        <span class="snapshot-summary">${esc(s.summary)}</span>
        <span class="snapshot-time">${new Date(s.fetched_at).toLocaleString()}</span>
      </div>`).join("");
  } catch (err) {
    list.innerHTML = `<div style="color:var(--red);font-size:12px">${esc(err.message)}</div>`;
  }
}

// ═══════════════════════════════════════════════════════
//  CORRECTIONS
// ═══════════════════════════════════════════════════════

function openSubmitCorrection() {
  // Populate project select
  const sel = document.getElementById("corr-project-select");
  sel.innerHTML = projectsCache.map(p =>
    `<option value="${p.id}" ${p.id === currentProjectId ? "selected" : ""}>${esc(p.name)}</option>`
  ).join("");

  document.getElementById("corr-page-url").value = "";
  document.getElementById("corr-errors").value = "";
  document.getElementById("corr-instructions").value = "";
  document.getElementById("corr-schema").value = "";
  document.getElementById("corr-error").classList.add("hidden");
  openModal("correction-modal");
}

async function submitCorrectionModal() {
  const projectId  = document.getElementById("corr-project-select").value;
  const pageUrl    = document.getElementById("corr-page-url").value.trim();
  const errorsRaw  = document.getElementById("corr-errors").value.trim();
  const instructions = document.getElementById("corr-instructions").value.trim();
  const schemaRaw  = document.getElementById("corr-schema").value.trim();
  const errorEl    = document.getElementById("corr-error");

  if (!pageUrl) return showError(errorEl, "Page URL is required.");
  if (!errorsRaw && !instructions) return showError(errorEl, "Provide errors or instructions.");

  let originalSchema;
  if (schemaRaw) {
    try {
      const cleanResult = cleanAndParseJSONLD(schemaRaw);
      originalSchema = cleanResult.parsed;
    }
    catch (err) {
      return showError(errorEl, "Invalid JSON in schema field: " + err.message);
    }
  } else {
    // Try to use existing schema from project cache
    const proj = projectsCache.find(p => p.id == projectId);
    const existing = proj?.schemas_generated?.[pageUrl];
    originalSchema = existing?.schemas || [];
  }

  const validatorErrors = errorsRaw.split("\n").map(s => s.trim()).filter(Boolean);

  try {
    const res = await apiFetch(`/api/feed/projects/${projectId}/corrections`, "POST", {
      page_url: pageUrl,
      original_schema: originalSchema,
      validator_errors: validatorErrors,
      instructions
    });
    closeModal("correction-modal");
    toast("Correction submitted!", "success");

    // Show corrections section if on same project
    if (parseInt(projectId) === currentProjectId) {
      loadProjectCorrections(currentProjectId);
    }
  } catch (err) {
    showError(errorEl, err.message || "Submission failed.");
  }
}

async function loadProjectCorrections(projectId) {
  try {
    const res = await apiFetch(`/api/feed/projects/${projectId}/corrections`);
    if (res.count === 0) return;

    const section = document.getElementById("corrections-section");
    section.classList.remove("hidden");
    document.getElementById("corrections-count").textContent = res.count;

    document.getElementById("corrections-list").innerHTML = res.corrections.map(c => `
      <div class="correction-card">
        <div class="correction-head">
          <span class="correction-status ${c.status}">${c.status}</span>
          <span class="correction-url">${esc(c.page_url)}</span>
          ${c.status === "pending"
            ? `<button class="btn-fix" onclick="fixCorrection(${c.id})">Fix →</button>`
            : `<span style="font-size:10px;color:var(--green);font-family:var(--mono)">✓ Fixed</span>`}
        </div>
        <div class="correction-body">
          <div class="correction-errors">
            ${c.validator_errors.slice(0,3).map(e => `⚠ ${esc(e)}`).join("<br>")}
          </div>
          ${c.instructions ? `<div style="font-size:11px;font-family:var(--mono);color:var(--stone);margin-top:4px">Instructions: ${esc(c.instructions)}</div>` : ""}
        </div>
      </div>`).join("");
  } catch (err) {
    console.warn("Could not load corrections:", err.message);
  }
}

async function fixCorrection(corrId) {
  if (!currentProjectId) return;
  showLoading("Applying corrections and regenerating schema…");
  try {
    const res = await apiFetch(`/api/feed/projects/${currentProjectId}/corrections/${corrId}/fix`, "POST");
    hideLoading();

    // Update local schema display
    const r = res.result;
    const fixes = r.all_fixes || [];
    const warnings = r.compliance_warnings || [];

    toast(`Schema corrected! ${fixes.length} fix(es) applied.`, "success");

    // Refresh project view
    const proj = await apiFetch(`/api/schema/projects/${currentProjectId}`);
    const idx = projectsCache.findIndex(p => p.id === currentProjectId);
    if (idx >= 0) projectsCache[idx] = proj.project;
    restorePipelineState(proj.project);
    loadProjectCorrections(currentProjectId);

    if (warnings.length) {
      setTimeout(() => toast(`⚠ ${warnings.length} compliance warning(s) remain.`, "error"), 2000);
    }
  } catch (err) {
    hideLoading();
    toast("Fix failed: " + err.message, "error");
  }
}

// ─── Regenerate All with KB ────────────────────────────
async function regenerateWithKB(projectId) {
  showLoading("Regenerating all schemas with latest KB + trends…");
  try {
    const res = await apiFetch(`/api/feed/projects/${projectId}/regenerate`, "POST");
    hideLoading();
    toast(`Regenerated ${res.page_count} schemas with KB context!`, "success");
    const proj = await apiFetch(`/api/schema/projects/${projectId}`);
    const idx = projectsCache.findIndex(p => p.id === projectId);
    if (idx >= 0) projectsCache[idx] = proj.project;
    if (projectId === currentProjectId) restorePipelineState(proj.project);
  } catch (err) {
    hideLoading();
    toast("Regeneration failed: " + err.message, "error");
  }
}

// ═══════════════════════════════════════════════════════
//  MODAL HELPERS
// ═══════════════════════════════════════════════════════

function openModal(id) {
  document.getElementById(id).classList.remove("hidden");
}

function closeModal(id) {
  document.getElementById(id).classList.add("hidden");
}

// Close modal on backdrop click
document.addEventListener("click", e => {
  if (e.target.classList.contains("modal-overlay")) {
    e.target.classList.add("hidden");
  }
});

// ═══════════════════════════════════════════════════════
//  PATCH: switchView to load Feed/Trends data
// ═══════════════════════════════════════════════════════

const _origSwitchView = switchView;
window.switchView = function(viewName) {
  _origSwitchView(viewName);

  if (viewName === "feed") {
    loadKBEntries();
  } else if (viewName === "trends") {
    loadTrendDigest();
    loadTrendSnapshots();
    // Render cached trends
    apiFetch("/api/feed/trends").then(res => renderTrendSources(res.trends)).catch(() => {});
  } else if (viewName === "project" || viewName === "dashboard") {
    // handled by existing code
  }
};

// Patch openProject to also load corrections
const _origOpenProject = openProject;
window.openProject = async function(projectId) {
  await _origOpenProject(projectId);
  await loadProjectCorrections(projectId);

  // Add Regenerate with KB button if not present
  const allBtn = document.querySelector(".pipeline-all");
  if (allBtn && !document.getElementById("btn-regen-kb")) {
    const regenBtn = document.createElement("button");
    regenBtn.id = "btn-regen-kb";
    regenBtn.className = "btn-secondary";
    regenBtn.style.cssText = "margin-top:8px;display:block;margin-left:auto;margin-right:auto;";
    regenBtn.textContent = "↺ Regenerate with KB & Trends";
    regenBtn.onclick = () => regenerateWithKB(currentProjectId);
    allBtn.appendChild(regenBtn);
  }
};

// ─── Interactive Page Selection & Custom Page Addition ───
async function togglePageSelection(url, isSelected) {
  if (!currentProjectId) return;
  const project = projectsCache.find(p => p.id === currentProjectId);
  if (!project) return;

  const pages = project.pages_found || [];
  const targetPage = pages.find(p => p.url === url);
  if (targetPage) {
    targetPage.selected = isSelected;
  }

  try {
    const res = await apiFetch(`/api/schema/projects/${currentProjectId}/pages`, "POST", { pages });
    updateProjectCache(currentProjectId, { pages_found: res.pages });
    toast(isSelected ? "Page selected" : "Page deselected", "success");
  } catch (err) {
    toast("Failed to update page selection: " + err.message, "error");
    renderPagesSection(pages);
  }
}

async function toggleAllPages(isSelected) {
  if (!currentProjectId) return;
  const project = projectsCache.find(p => p.id === currentProjectId);
  if (!project) return;

  const pages = project.pages_found || [];
  pages.forEach(p => p.selected = isSelected);

  showLoading("Updating pages...");
  try {
    const res = await apiFetch(`/api/schema/projects/${currentProjectId}/pages`, "POST", { pages });
    updateProjectCache(currentProjectId, { pages_found: res.pages });
    hideLoading();
    renderPagesSection(res.pages);
    toast(isSelected ? "All pages selected" : "All pages deselected", "success");
  } catch (err) {
    hideLoading();
    toast("Failed to update page selection: " + err.message, "error");
    renderPagesSection(pages);
  }
}

function openAddSinglePageModal() {
  document.getElementById("add-page-url").value = "";
  document.getElementById("add-page-title").value = "";
  document.getElementById("add-page-type").value = "other";
  document.getElementById("add-page-error").classList.add("hidden");
  openModal("add-single-page-modal");
}

async function submitAddSinglePage() {
  if (!currentProjectId) return;
  const url = document.getElementById("add-page-url").value.trim();
  const type = document.getElementById("add-page-type").value;
  const title = document.getElementById("add-page-title").value.trim();
  const errorEl = document.getElementById("add-page-error");

  if (!url) {
    showError(errorEl, "Page URL is required.");
    return;
  }

  const project = projectsCache.find(p => p.id === currentProjectId);
  if (!project) return;

  const pages = [...(project.pages_found || [])];
  if (pages.some(p => p.url.toLowerCase() === url.toLowerCase())) {
    showError(errorEl, "This URL is already in the list.");
    return;
  }

  const newPage = {
    url,
    page_type: type,
    title: title || "",
    selected: true
  };
  pages.push(newPage);

  showLoading("Adding custom page...");
  try {
    const res = await apiFetch(`/api/schema/projects/${currentProjectId}/pages`, "POST", { pages });
    updateProjectCache(currentProjectId, { pages_found: res.pages });
    hideLoading();
    closeModal("add-single-page-modal");
    renderPagesSection(res.pages);
    toast("Custom page added successfully!", "success");
  } catch (err) {
    hideLoading();
    showError(errorEl, err.message || "Failed to add page.");
  }
}

// ─── Quick KB Feeding Option ───
function cleanAndParseJSONLD(raw) {
  let cleaned = raw.trim();
  
  // 1. Remove HTML script tags if present
  const scriptMatch = cleaned.match(/<script\b[^>]*>([\s\S]*?)<\/script>/i);
  if (scriptMatch) {
    cleaned = scriptMatch[1].trim();
  } else {
    cleaned = cleaned.replace(/^<script[^>]*>/i, "").replace(/<\/script>$/i, "").trim();
  }
  
  // 2. Remove comments
  // Strip block comments /* ... */
  cleaned = cleaned.replace(/\/\*[\s\S]*?\*\//g, "");
  // Strip single-line comments // ... but not URL schemes (http://, https://)
  cleaned = cleaned.split("\n").map(line => {
    const commentIdx = line.indexOf("//");
    if (commentIdx !== -1) {
      const before = line.substring(0, commentIdx);
      if (!before.endsWith("http:") && !before.endsWith("https:")) {
        return before;
      }
    }
    return line;
  }).join("\n");

  // 3. Strip trailing commas before closing braces/brackets
  cleaned = cleaned.replace(/,\s*([}\]])/g, '$1');
  
  // Try parsing
  return {
    parsed: JSON.parse(cleaned),
    cleanedStr: cleaned
  };
}

async function submitFeedSchema() {
  const title = document.getElementById("feed-schema-title").value.trim();
  const rawContent = document.getElementById("feed-schema-content").value.trim();

  if (!title || !rawContent) {
    toast("Title and schema content are required.", "warning");
    return;
  }

  let cleanedContent = rawContent;
  try {
    const result = cleanAndParseJSONLD(rawContent);
    cleanedContent = JSON.stringify(result.parsed, null, 2);
  } catch (err) {
    toast("Invalid JSON-LD schema syntax: " + err.message, "error");
    return;
  }

  showLoading("Feeding reference schema...");
  try {
    await apiFetch("/api/feed/kb", "POST", {
      entry_type: "example",
      title,
      content: cleanedContent,
      source: "Quick Feed"
    });
    hideLoading();
    document.getElementById("feed-schema-title").value = "";
    document.getElementById("feed-schema-content").value = "";
    toast("Reference schema fed to Knowledge Base!", "success");
    if (document.getElementById("view-feed").classList.contains("active")) {
      loadKBEntries();
    }
  } catch (err) {
    hideLoading();
    toast("Failed to feed schema: " + err.message, "error");
  }
}

async function submitFeedNews() {
  const title = document.getElementById("feed-news-title").value.trim();
  const content = document.getElementById("feed-news-content").value.trim();

  if (!title || !content) {
    toast("Title and news content are required.", "warning");
    return;
  }

  showLoading("Feeding news update...");
  try {
    await apiFetch("/api/feed/kb", "POST", {
      entry_type: "news",
      title,
      content,
      source: "Quick Feed"
    });
    hideLoading();
    document.getElementById("feed-news-title").value = "";
    document.getElementById("feed-news-content").value = "";
    toast("News/updates fed to Knowledge Base!", "success");
    if (document.getElementById("view-feed").classList.contains("active")) {
      loadKBEntries();
    }
  } catch (err) {
    hideLoading();
    toast("Failed to feed news: " + err.message, "error");
  }
}

