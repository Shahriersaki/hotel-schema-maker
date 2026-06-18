# Hotel Schema Maker v2 — Complete Documentation

> Generate Google-compliant JSON-LD schema markup and XML sitemaps for hotel websites.
> Features: multi-user RBAC, feed-driven knowledge base, advanced correction engine, one-click export.

---

## Table of Contents

1. [Project Structure](#project-structure)
2. [Quick Start (Local)](#quick-start-local)
3. [Free Cloud Deployment](#free-cloud-deployment)
4. [User Roles & Access Control](#user-roles--access-control)
5. [The Pipeline (Step-by-Step)](#the-pipeline)
6. [Feed System & Knowledge Base](#feed-system--knowledge-base)
7. [Correction Workflow](#correction-workflow)
8. [Instruction DSL Reference](#instruction-dsl-reference)
9. [Multi-Page Patch](#multi-page-patch)
10. [Trend Checker](#trend-checker)
11. [Export Options](#export-options)
12. [Admin Panel](#admin-panel)
13. [API Reference](#api-reference)
14. [Schema Types Generated](#schema-types-generated)
15. [Troubleshooting](#troubleshooting)

---

## Project Structure

```
hotel-schema-maker/
├── app.py                          # Flask entry point
├── requirements.txt
├── Procfile                        # gunicorn start command
├── render.yaml                     # one-click Render deploy
├── .env.example
│
├── backend/
│   ├── auth.py                     # JWT + RBAC (admin/contributor/viewer)
│   ├── database.py                 # SQLite + role/audit/KB/corrections CRUD
│   ├── crawler.py                  # BFS website crawler
│   ├── enrichment.py               # Geocoding + online data fill-in
│   ├── schema_generator.py         # JSON-LD generator (12 page types)
│   │                                 ↳ auto-strips deprecated props at generation
│   ├── sitemap_generator.py        # XML Sitemap 0.9
│   ├── trend_checker.py            # Live schema.org + Google scraper
│   │                                 ↳ builds prioritized digest per user
│   ├── regeneration_engine.py      # Advanced DSL correction engine v2
│   │                                 ↳ 13 auto-fix rules + full DSL
│   ├── schema_routes.py            # /api/schema/* (role-gated)
│   ├── sitemap_routes.py           # /api/sitemap/*
│   ├── feed_routes.py              # /api/feed/* (KB, corrections, trends)
│   └── admin_routes.py             # /api/admin/* (admin only)
│
├── frontend/
│   ├── templates/index.html        # SPA shell
│   └── static/
│       ├── css/app.css             # Full design system
│       ├── js/app.js               # Core SPA logic
│       └── js/enhancements.js      # Admin, preview, export, role UI
│
└── docs/
    └── README.md                   # This file
```

---

## Quick Start (Local)

### Prerequisites
- Python 3.11+
- pip

### Setup

```bash
cd hotel-schema-maker
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` — at minimum set two random secrets:

```bash
# Generate them:
python -c "import secrets; print(secrets.token_hex(32))"
```

```env
SECRET_KEY=<random-64-char-string>
JWT_SECRET=<different-random-64-char-string>
FLASK_ENV=development
```

### Run

```bash
python app.py
```

Visit **http://localhost:5000** — register the first account (auto-promoted to **admin**).

---

## Free Cloud Deployment

### Render (recommended — 750 free hours/month)

1. Push project to GitHub
2. Go to https://render.com → **New Web Service** → connect repo
3. `render.yaml` is auto-detected
4. Set env vars in the Render dashboard:
   - `SECRET_KEY` → random string
   - `JWT_SECRET` → random string
   - `FLASK_ENV` → `production`
5. **Deploy**

> Free tier sleeps after 15 min inactivity. First wake-up request ~30s.

### Railway

```bash
# Install Railway CLI
npm install -g @railway/cli
railway login
railway init
railway up
railway variables set SECRET_KEY=xxx JWT_SECRET=yyy FLASK_ENV=production
```

### Persistent Database

SQLite works out of the box. For production with multiple dynos or persistent storage:

| Option | Free Tier | Setup |
|--------|-----------|-------|
| **Supabase** | 500 MB PostgreSQL | Set `SUPABASE_URL` + `SUPABASE_KEY` |
| **Fly.io volumes** | 3 GB persistent | Mount `/data`, set `SQLITE_PATH=/data/hotel_schema.db` |
| **PlanetScale** | 5 GB MySQL | Set `DATABASE_URL=mysql+pymysql://...` |

---

## User Roles & Access Control

| Role | Who | Permissions |
|------|-----|-------------|
| **admin** | First registered user + anyone promoted | Full access: user management, audit log, all write operations |
| **contributor** | Regular users | Create/edit projects, manage own KB, submit + fix corrections |
| **viewer** | Read-only guests | Browse projects and schemas, download exports — no editing |

### Role Assignment
- **First user** to register is automatically admin
- Admins can change any user's role via **Admin → User Management**
- Users cannot change their own role

### Role in API
The JWT token payload includes `"role"`. All API responses include `403` with a descriptive message if the role is insufficient.

### Inviting Users
Share the deployed URL — users self-register. The admin then upgrades their role if needed.

---

## The Pipeline

### Step 1 — Create Project

Fill in the **New Project** form:

| Field | Required | Notes |
|-------|----------|-------|
| Project Name | ✓ | Internal label |
| Website URL | ✓ | `https://www.hotel.com` |
| Hotel Name | ✓ | Exact name for schema |
| Street, City, Country | ✓ | For PostalAddress |
| Phone, Email, Check-in/out | — | Auto-enriched if blank |
| Amenities | — | Comma-separated; defaults applied if blank |

### Step 2 — Run Pipeline

Either click **⚡ Run Full Pipeline** or step manually:

1. **Crawl** — BFS crawl up to 50 pages, detects page types (home/rooms/dining/…)
2. **Enrich** — Geocodes the address via OpenStreetMap; searches for missing description/phone
3. **Generate Schema** — JSON-LD for each page, trend digest injected, deprecated props stripped
4. **Generate Sitemap** — Full XML Sitemap 0.9 with priorities, change frequencies, image tags

Also available: **↺ Regenerate with KB & Trends** — re-runs generation applying all current KB rules.

### Step 3 — Export & Deploy

- Copy `<script type="application/ld+json">` blocks into each page's `<head>`
- Download `sitemap.xml` and upload to website root
- Submit sitemap to Google Search Console

---

## Feed System & Knowledge Base

The Knowledge Base (KB) is the tool's memory. It stores rules that are **automatically applied** during every schema generation.

### Entry Types

| Type | Purpose | Example |
|------|---------|---------|
| `guideline` | A schema.org or Google rule | "checkinTime must be T-prefixed" |
| `validator_error` | An error from a validator tool | "Missing field 'geo'" |
| `deprecated` | Comma-separated props to remove | `url, sameAs, openingHours` |
| `required` | Comma-separated props to enforce | `geo, checkinTime` |
| `recommended` | Comma-separated props to include | `starRating, image` |
| `example` | Reference JSON-LD snippet | `{"@type":"Rating",...}` |
| `note` | General reminder | "Always use HTTPS URLs" |

### Source Priority

Entries are ranked by source. Higher-priority sources override lower ones in the digest:

| Source keyword | Priority |
|---------------|----------|
| Google / Google Rich Results | 100 |
| Google Search Central | 95 |
| schema.org | 90 |
| schema.org validator | 88 |
| user / manual | 75–80 |
| auto-suggested | 50 |

### Quick Workflow — Paste Validator Errors

1. Run schema through [Google Rich Results Test](https://search.google.com/test/rich-results)
2. Copy the error list
3. Go to **Feed System** → **Paste Validator Output**
4. Click **Parse Errors**
5. Auto-suggested KB entries appear → click **Add to KB**
6. In your project → **↺ Regenerate with KB & Trends**

---

## Correction Workflow

For fixing a specific page's schema after validation:

### Full Workflow

```
1. Validate schema at https://search.google.com/test/rich-results
2. In project view → "Corrections" section → "+ Submit Error"
3. Fill in:
   - Page URL
   - Paste validator error lines
   - (Optional) Instruction commands
4. Click "Submit"
5. Click "Fix →" on the correction card
6. Corrected schema is saved and shown in the Schemas section
```

### What the Fix Engine Does

1. **Strip deprecated** — removes any properties flagged in KB as deprecated
2. **Auto-fix** — 13 built-in rules (see below)
3. **Apply instructions** — your custom DSL commands
4. **Compliance check** — validates against current trend digest
5. **Save** — updates the project's schema for that page

### 13 Auto-Fix Rules

| # | Rule | What It Fixes |
|---|------|---------------|
| 1 | `@context` | Adds missing `https://schema.org` |
| 2 | `checkinTime` | Normalizes to `T14:00:00` ISO format |
| 3 | `starRating` | Wraps plain number in `{"@type":"Rating","ratingValue":"4","bestRating":"5"}` |
| 4 | `address` | Adds `@type: PostalAddress` |
| 5 | `geo` | Adds `@type: GeoCoordinates`, converts lat/lon strings to floats |
| 6 | `image` | Converts string/list to `ImageObject` |
| 7 | `contactPoint` | Adds `@type: ContactPoint` |
| 8 | `priceRange` | Converts non-string to string |
| 9 | `telephone` | Warns if missing `+` E.164 prefix |
| 10 | `url` | Adds `https://` if missing |
| 11 | `amenityFeature` | Adds `@type: LocationFeatureSpecification` and `value: true` |
| 12 | `offers` | Adds `@type: Offer` to bare objects |
| 13 | Empty strings | Removes any `""` property values |

---

## Instruction DSL Reference

Use these commands in the **Instructions** field of a correction, or in **Multi-Page Patch**.

### Core Commands

```
# Add or overwrite a property
ADD checkinTime T14:00:00

# Remove a property
REMOVE openingHours

# Set a nested property (dot notation)
SET starRating.ratingValue 5
SET address.addressCountry GB

# Delete a nested property
UNSET contactPoint.faxNumber

# Push to an array
APPEND amenityFeature {"@type":"LocationFeatureSpecification","name":"Pool","value":true}

# Merge a dict into an existing property
MERGE starRating {"bestRating":"5","worstRating":"1"}

# Change @type
TYPE Hotel
TYPE LodgingBusiness

# Rename a property
RENAME openingHours openingHoursSpecification

# Copy value to another key
COPY name legalName

# Move a nested value
MOVE contactPoint.faxNumber contactPoint.telephone
```

### Advanced Commands

```
# Conditional type change (only changes if current @type matches)
TYPE Hotel IF @type=LodgingBusiness

# Conditional execution
IF MISSING geo THEN ADD geo {"@type":"GeoCoordinates","latitude":48.2,"longitude":16.3}
IF HAS starRating THEN SET starRating.bestRating 5
IF @type=Hotel THEN ADD checkinTime T15:00:00

# String substitution across entire schema
REPLACE "http://" "https://"

# Custom warning (no mutation — shows in compliance report)
WARN All images should be at least 1200x630px for Google rich results
```

### Condition Syntax

```
HAS key              – property exists
MISSING key          – property is absent
@type=Hotel          – @type equals value
key=value            – any property equals value
key CONTAINS string  – property string contains substring
```

### Real-World Examples

**Fix a hotel on Google Rich Results showing "Missing checkinTime":**
```
ADD checkinTime T14:00:00
ADD checkoutTime T12:00:00
```

**Upgrade all schemas from LodgingBusiness to Hotel:**
```
TYPE Hotel IF @type=LodgingBusiness
```

**Fix star rating format:**
```
SET starRating {"@type":"Rating","ratingValue":"4","bestRating":"5"}
```

**Add missing geo coordinates:**
```
ADD geo {"@type":"GeoCoordinates","latitude":48.2082,"longitude":16.3738}
```

**Remove a deprecated property and add replacement:**
```
REMOVE openingHours
APPEND openingHoursSpecification {"@type":"OpeningHoursSpecification","dayOfWeek":["Monday","Tuesday","Wednesday","Thursday","Friday"],"opens":"07:00","closes":"22:00"}
```

---

## Multi-Page Patch

Apply instructions to **multiple pages at once** without rerunning the full pipeline.

1. In project view → **⊞ Patch Pages**
2. Enter instructions (DSL)
3. Optionally filter by `@type` (e.g. `Hotel`) or specific page URLs
4. Click **Preview Ops** to see parsed operations before applying
5. Click **Apply Patch**

**Example — add a pool amenity to all Hotel schemas:**
```
IF @type=Hotel THEN APPEND amenityFeature {"@type":"LocationFeatureSpecification","name":"Swimming Pool","value":true}
```

**Example — update check-in time across all pages:**
```
ADD checkinTime T15:00:00
```

---

## Trend Checker

Navigate to **Trend Checker** in the sidebar.

### What It Fetches

| Source | Data |
|--------|------|
| schema.org/Hotel | Full current property list |
| schema.org/LodgingBusiness | Inherited property list |
| Google Search Central | Required + recommended properties |
| schema.org changelog | Hotel-related release notes |
| Google Rich Results Gallery | All supported rich result types |

### Digest Panel

The dark panel at the top shows the **active digest** — the combined set of rules currently applied to every schema generation:

- **Required Properties** — these must be present (generates warning if missing)
- **Recommended Properties** — these should be present
- **Deprecated Properties** — automatically stripped at generation time
- **Notes** — messages from live trend data + KB entries

### Cache

Trends are cached for 24 hours. Click **↺ Refresh Now** to force a live fetch. Force-refresh available to admin and contributor roles.

---

## Export Options

From any project, click **⬇ Export** to open the export modal.

| Option | Output | Use Case |
|--------|--------|---------|
| **All JSON-LD (HTML)** | `all-schemas.html` | Copy-paste blocks into each page's `<head>` |
| **All Schemas (JSON)** | `schemas.json` | Programmatic use / backup |
| **XML Sitemap** | `sitemap.xml` | Upload to website root + submit to GSC |
| **Full Bundle** | `<name>-bundle.json` | Full project backup / migration |

Individual page export is also available from each schema card — click **↓ Export**.

### Deploying Schema Markup

For each page on your website, paste the corresponding `<script>` block into the `<head>`:

```html
<head>
  <title>Grand Hotel Vienna — Rooms</title>
  <!-- ... other head tags ... -->

  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "Hotel",
    "name": "Grand Hotel Vienna",
    "checkinTime": "T14:00:00",
    "checkoutTime": "T12:00:00",
    ...
  }
  </script>
</head>
```

---

## Admin Panel

Available to admin role only. Navigate via **Admin → User Management**.

### Features

**Stats Dashboard** — live counts of users, projects, KB entries, corrections.

**User Table** — for each user:
- Change role (admin / contributor / viewer) via dropdown
- Enable/disable account
- Reset password

**Audit Log** — every significant action recorded with user, action type, and timestamp. Filter by user.

### Promoted Actions Logged

| Action | Trigger |
|--------|---------|
| `login` | Every login |
| `register` | New account created |
| `add_kb_entry` | KB entry added |
| `submit_correction` | Correction submitted |
| `fix_correction` | Correction applied |
| `patch_pages` | Multi-page patch run |
| `regenerate_all` | Full regeneration with KB |
| `admin_update_user` | Admin changes a user |
| `admin_reset_password` | Admin resets password |

---

## API Reference

All endpoints require `Authorization: Bearer <token>` except `/api/auth/register` and `/api/auth/login`.

### Auth

| Method | Endpoint | Role | Description |
|--------|---------|------|-------------|
| POST | `/api/auth/register` | Public | Register new user |
| POST | `/api/auth/login` | Public | Login, returns JWT |
| GET | `/api/auth/me` | Any | Current user profile |
| PUT | `/api/auth/me/password` | Any | Change own password |
| GET | `/api/auth/verify` | Any | Verify token |

### Admin

| Method | Endpoint | Role | Description |
|--------|---------|------|-------------|
| GET | `/api/admin/stats` | admin | System statistics |
| GET | `/api/admin/users` | admin | List all users |
| PUT | `/api/admin/users/:id` | admin | Update role/status/name |
| POST | `/api/admin/users/:id/reset-password` | admin | Reset password |
| GET | `/api/admin/audit-log` | admin | Audit log |

### Schema Pipeline

| Method | Endpoint | Role | Description |
|--------|---------|------|-------------|
| GET | `/api/schema/projects` | any | List projects |
| POST | `/api/schema/projects` | contributor+ | Create project |
| GET | `/api/schema/projects/:id` | any | Get project |
| PUT | `/api/schema/projects/:id` | contributor+ | Update project |
| DELETE | `/api/schema/projects/:id` | contributor+ | Delete project |
| POST | `/api/schema/projects/:id/crawl` | contributor+ | Crawl website |
| POST | `/api/schema/projects/:id/enrich` | contributor+ | Enrich hotel data |
| POST | `/api/schema/projects/:id/generate` | contributor+ | Generate schemas |
| POST | `/api/schema/projects/:id/run-all` | contributor+ | Full pipeline |

### Sitemap

| Method | Endpoint | Role | Description |
|--------|---------|------|-------------|
| POST | `/api/sitemap/projects/:id/generate` | contributor+ | Generate sitemap |
| GET | `/api/sitemap/projects/:id/download` | any | Download sitemap.xml |

### Feed System

| Method | Endpoint | Role | Description |
|--------|---------|------|-------------|
| GET | `/api/feed/kb` | any | List KB entries (`?type=guideline&sorted=true`) |
| POST | `/api/feed/kb` | contributor+ | Add KB entry |
| DELETE | `/api/feed/kb/:id` | contributor+ | Remove entry |
| POST | `/api/feed/kb/bulk` | contributor+ | Add multiple entries |
| POST | `/api/feed/validate-paste` | any | Parse validator output |
| GET | `/api/feed/trends` | any | Get trends (`?force=true` for live fetch) |
| GET | `/api/feed/trends/digest` | any | Active schema digest |
| GET | `/api/feed/trends/snapshots` | any | Fetch history |
| GET | `/api/feed/projects/:id/corrections` | any | List corrections |
| POST | `/api/feed/projects/:id/corrections` | contributor+ | Submit correction |
| POST | `/api/feed/projects/:id/corrections/:cid/fix` | contributor+ | Apply fix |
| POST | `/api/feed/projects/:id/patch-pages` | contributor+ | Multi-page DSL patch |
| POST | `/api/feed/projects/:id/regenerate` | contributor+ | Regen all with KB |
| POST | `/api/feed/parse-instructions` | any | Parse DSL (dry run) |

---

## Schema Types Generated

| Page Type | Schema Type(s) | Notes |
|-----------|---------------|-------|
| Home | Hotel, WebSite, Organization | Includes SearchAction |
| Rooms | Hotel + Offer | Room type offers if provided |
| Dining | FoodEstablishment | Links to parent Hotel |
| Gallery | ImageGallery | With ImageObject list |
| Attractions | ItemList + TouristAttraction | With distance values |
| Offers | Offer | With price/validity |
| Blog | Blog | With publisher info |
| Contact | Hotel + ContactPage | Full address + geo |
| About | AboutPage | With foundingDate |
| Spa | HealthAndBeautyBusiness | Links to parent Hotel |
| Events | EventVenue | With geo + capacity |
| FAQ | FAQPage | With Q&A pairs |
| Other | WebPage | Generic fallback |

All pages also get a **BreadcrumbList** schema.

---

## Troubleshooting

| Issue | Solution |
|-------|---------|
| Crawl returns 0 pages | Site may block scrapers. Check the URL is publicly accessible and try again. You can also add pages manually via the hotel data. |
| Geocoding fails | Add coordinates manually: in hotel_data add `"geo": {"latitude": X, "longitude": Y}` |
| Schema validation errors | Use Feed System → paste errors → auto-fix. Then regenerate. |
| `400 Write access required` | Your role is Viewer. Ask an admin to change it to Contributor. |
| `403 Admin access required` | You need admin role for that action. |
| JWT expired | Log out and log in again. |
| Render sleeping | First request after 15 min inactivity takes ~30s — normal behavior. |
| SQLite lost on redeploy | Use Supabase or Fly.io persistent volume (see Deployment section). |
| `REPLACE` command not working | Wrap old/new in double quotes: `REPLACE "old text" "new text"` |
| Deprecated props still appearing | Ensure the `deprecated` KB entry uses exact property names, comma-separated. |
