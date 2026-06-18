"""
Regeneration Engine v2 — advanced correction instructions, nested properties,
multi-page schemas, conditional logic, deprecated-property stripping.

Instruction DSL (one command per line):
  ADD     key value                   – set top-level property (JSON value ok)
  REMOVE  key                         – delete top-level property
  SET     path.to.nested value        – dot-notation nested write
  UNSET   path.to.nested              – dot-notation nested delete
  APPEND  key value                   – push value onto array property
  MERGE   key {"a":1}                 – shallow-merge dict into property
  TYPE    NewType                     – change @type
  TYPE    NewType IF @type=OldType    – conditional type change
  REPLACE "old string" "new string"   – regex-safe string substitution
  RENAME  old_key new_key             – rename a property
  COPY    src_key dest_key            – copy one property to another
  MOVE    src.path dest.path          – move nested value to new path
  REQUIRE key                         – add to required-field check list
  WARN    message                     – emit a custom warning (no mutation)
  IF      condition THEN instruction  – conditional execution
"""

import re
import json
import copy
from datetime import datetime, timezone
from typing import Any
from backend.trend_checker import build_trend_digest, get_compliance_warnings


# ─── Value Parser ─────────────────────────────────────────────────────────────

def _parse_value(raw: str) -> Any:
    """JSON parse → fallback to string. Handles quoted strings."""
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _parse_quoted_pair(text: str) -> tuple[str, str] | None:
    """Extract two quoted strings from: "old" "new" """
    m = re.match(r'"((?:[^"\\]|\\.)*)"\s+"((?:[^"\\]|\\.)*)"', text)
    if m:
        return m.group(1), m.group(2)
    # Fallback: unquoted space-split
    parts = text.split(None, 1)
    return (parts[0], parts[1]) if len(parts) == 2 else None


# ─── Condition Evaluator ──────────────────────────────────────────────────────

def _eval_condition(schema: dict, condition: str) -> bool:
    """
    Evaluate a simple condition string against a schema dict.

    Supported:
      @type=Hotel                  – type equality
      key=value                    – property equality
      HAS key                      – property exists
      MISSING key                  – property absent
      key CONTAINS substring       – string contains check
    """
    condition = condition.strip()

    # HAS key
    m = re.match(r"HAS\s+(\S+)", condition, re.I)
    if m:
        return _get_nested(schema, m.group(1)) is not None

    # MISSING key
    m = re.match(r"MISSING\s+(\S+)", condition, re.I)
    if m:
        return _get_nested(schema, m.group(1)) is None

    # key CONTAINS substring
    m = re.match(r"(\S+)\s+CONTAINS\s+(.+)", condition, re.I)
    if m:
        val = str(_get_nested(schema, m.group(1)) or "")
        return m.group(2).strip().strip('"') in val

    # key=value (dot-notation key supported)
    m = re.match(r"(\S+)\s*=\s*(.+)", condition)
    if m:
        actual = _get_nested(schema, m.group(1))
        expected = _parse_value(m.group(2))
        return str(actual) == str(expected)

    return False


# ─── Nested Path Helpers ──────────────────────────────────────────────────────

def _get_nested(obj: dict, path: str) -> Any:
    """Get value at dot-notation path."""
    if not isinstance(obj, dict):
        return None
    keys = path.split(".")
    current = obj
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _set_nested(obj: dict, path: str, value: Any) -> dict:
    """Set value at dot-notation path, creating intermediate dicts."""
    keys = path.split(".")
    current = obj
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value
    return obj


def _del_nested(obj: dict, path: str) -> dict:
    """Delete key at dot-notation path."""
    keys = path.split(".")
    current = obj
    for key in keys[:-1]:
        current = current.get(key, {})
        if not isinstance(current, dict):
            return obj
    current.pop(keys[-1], None)
    return obj


def _move_nested(obj: dict, src: str, dest: str) -> dict:
    """Move a value from src path to dest path."""
    val = _get_nested(obj, src)
    if val is not None:
        _del_nested(obj, src)
        _set_nested(obj, dest, val)
    return obj


# ─── Instruction Parser ───────────────────────────────────────────────────────

def parse_instructions(instructions: str) -> list[dict]:
    """
    Parse the full instruction DSL into a list of operation dicts.
    Handles: ADD, REMOVE, SET, UNSET, APPEND, MERGE, TYPE, REPLACE,
             RENAME, COPY, MOVE, REQUIRE, WARN, IF...THEN
    """
    ops = []
    lines = [ln.strip() for ln in instructions.strip().splitlines()
             if ln.strip() and not ln.strip().startswith("#")]

    for line in lines:
        parts = line.split(None, 1)
        if not parts:
            continue
        verb = parts[0].upper()
        rest = parts[1].strip() if len(parts) > 1 else ""

        # ── IF condition THEN instruction ─────────────────────────────────
        if verb == "IF":
            m = re.match(r"(.+?)\s+THEN\s+(.+)", rest, re.I)
            if m:
                inner_ops = parse_instructions(m.group(2))
                ops.append({"op": "if", "condition": m.group(1).strip(),
                             "then": inner_ops})
                continue
            ops.append({"op": "note", "text": line})
            continue

        # ── ADD key value ─────────────────────────────────────────────────
        if verb == "ADD":
            kv = rest.split(None, 1)
            if len(kv) == 2:
                ops.append({"op": "add", "key": kv[0], "value": _parse_value(kv[1])})
            continue

        # ── REMOVE key ────────────────────────────────────────────────────
        if verb == "REMOVE":
            ops.append({"op": "remove", "key": rest.split()[0] if rest else ""})
            continue

        # ── SET path value ────────────────────────────────────────────────
        if verb == "SET":
            kv = rest.split(None, 1)
            if len(kv) == 2:
                ops.append({"op": "set", "path": kv[0], "value": _parse_value(kv[1])})
            continue

        # ── UNSET path ────────────────────────────────────────────────────
        if verb == "UNSET":
            ops.append({"op": "unset", "path": rest.strip()})
            continue

        # ── APPEND key value ──────────────────────────────────────────────
        if verb == "APPEND":
            kv = rest.split(None, 1)
            if len(kv) == 2:
                ops.append({"op": "append", "key": kv[0], "value": _parse_value(kv[1])})
            continue

        # ── MERGE key dict ────────────────────────────────────────────────
        if verb == "MERGE":
            kv = rest.split(None, 1)
            if len(kv) == 2:
                try:
                    val = json.loads(kv[1])
                    ops.append({"op": "merge", "key": kv[0], "value": val})
                except Exception:
                    ops.append({"op": "note", "text": f"MERGE parse error: {line}"})
            continue

        # ── TYPE NewType [IF condition] ────────────────────────────────────
        if verb == "TYPE":
            m = re.match(r"(\S+)\s+IF\s+(.+)", rest, re.I)
            if m:
                ops.append({"op": "type", "value": m.group(1), "condition": m.group(2).strip()})
            else:
                ops.append({"op": "type", "value": rest.strip()})
            continue

        # ── REPLACE "old" "new" ───────────────────────────────────────────
        if verb == "REPLACE":
            pair = _parse_quoted_pair(rest)
            if pair:
                ops.append({"op": "replace", "old": pair[0], "new": pair[1]})
            else:
                parts2 = rest.split(None, 1)
                if len(parts2) == 2:
                    ops.append({"op": "replace", "old": parts2[0], "new": parts2[1]})
            continue

        # ── RENAME old_key new_key ────────────────────────────────────────
        if verb == "RENAME":
            kv = rest.split(None, 1)
            if len(kv) == 2:
                ops.append({"op": "rename", "from": kv[0], "to": kv[1].strip()})
            continue

        # ── COPY src dest ─────────────────────────────────────────────────
        if verb == "COPY":
            kv = rest.split(None, 1)
            if len(kv) == 2:
                ops.append({"op": "copy", "from": kv[0], "to": kv[1].strip()})
            continue

        # ── MOVE src dest ─────────────────────────────────────────────────
        if verb == "MOVE":
            kv = rest.split(None, 1)
            if len(kv) == 2:
                ops.append({"op": "move", "from": kv[0], "to": kv[1].strip()})
            continue

        # ── REQUIRE key ───────────────────────────────────────────────────
        if verb == "REQUIRE":
            ops.append({"op": "require", "key": rest.strip()})
            continue

        # ── WARN message ──────────────────────────────────────────────────
        if verb == "WARN":
            ops.append({"op": "warn", "message": rest})
            continue

        # Unrecognised
        ops.append({"op": "note", "text": line})

    return ops


# ─── Operation Applicator ─────────────────────────────────────────────────────

def _apply_single_op(schema: dict, op: dict, extra_warnings: list) -> dict:
    """Apply one operation to one schema dict. Mutates in place. Returns schema."""
    verb = op.get("op")

    if verb == "note":
        return schema

    if verb == "warn":
        extra_warnings.append(f"USER WARNING: {op.get('message', '')}")
        return schema

    if verb == "require":
        key = op.get("key", "")
        if key and not schema.get(key):
            extra_warnings.append(f"REQUIRED MISSING: '{key}' is marked required but absent.")
        return schema

    if verb == "add":
        schema[op["key"]] = op["value"]

    elif verb == "remove":
        schema.pop(op.get("key", ""), None)

    elif verb == "set":
        _set_nested(schema, op["path"], op["value"])

    elif verb == "unset":
        _del_nested(schema, op["path"])

    elif verb == "append":
        key = op["key"]
        existing = schema.get(key)
        if isinstance(existing, list):
            existing.append(op["value"])
        elif existing is None:
            schema[key] = [op["value"]]
        else:
            schema[key] = [existing, op["value"]]

    elif verb == "merge":
        key = op["key"]
        existing = schema.get(key, {})
        if isinstance(existing, dict) and isinstance(op["value"], dict):
            schema[key] = {**existing, **op["value"]}
        else:
            schema[key] = op["value"]

    elif verb == "type":
        condition = op.get("condition")
        if condition:
            if _eval_condition(schema, condition):
                schema["@type"] = op["value"]
        else:
            schema["@type"] = op["value"]

    elif verb == "replace":
        try:
            s = json.dumps(schema)
            s = s.replace(json.dumps(op["old"]).strip('"'), op["new"])
            schema.update(json.loads(s))
        except Exception:
            pass

    elif verb == "rename":
        if op["from"] in schema:
            schema[op["to"]] = schema.pop(op["from"])

    elif verb == "copy":
        val = _get_nested(schema, op["from"])
        if val is not None:
            _set_nested(schema, op["to"], copy.deepcopy(val))

    elif verb == "move":
        _move_nested(schema, op["from"], op["to"])

    elif verb == "if":
        if _eval_condition(schema, op.get("condition", "")):
            for inner_op in op.get("then", []):
                _apply_single_op(schema, inner_op, extra_warnings)

    return schema


def apply_operations(schema_list: list, ops: list[dict],
                     target_type: str = None) -> tuple[list, list]:
    """
    Apply operations to all schemas (or only those matching target_type).
    Returns (modified_schema_list, list_of_warnings).
    """
    result = copy.deepcopy(schema_list)
    warnings = []

    for schema in result:
        # Skip if target_type filter set and schema doesn't match
        schema_type = schema.get("@type", "")
        if target_type:
            types = schema_type if isinstance(schema_type, list) else [schema_type]
            if target_type not in types:
                continue
        for op in ops:
            _apply_single_op(schema, op, warnings)

    return result, warnings


# ─── Deprecated Property Stripper ─────────────────────────────────────────────

def strip_deprecated_properties(schemas: list, deprecated: list[str]) -> tuple[list, list]:
    """Remove any deprecated properties found in the schemas."""
    result = copy.deepcopy(schemas)
    stripped = []
    for schema in result:
        for prop in deprecated:
            if prop in schema:
                del schema[prop]
                stripped.append(prop)
    return result, list(set(stripped))


# ─── Auto-Fix Engine ─────────────────────────────────────────────────────────

# Each fix: (pattern_fn, fix_fn, description_template)
_AUTO_FIX_RULES = []


def _register_fix(fn):
    _AUTO_FIX_RULES.append(fn)
    return fn


@_register_fix
def _fix_context(schema: dict, errors: str) -> list[str]:
    if "@context" not in schema:
        schema["@context"] = "https://schema.org"
        return ["Added missing @context"]
    return []


@_register_fix
def _fix_checkin_format(schema: dict, errors: str) -> list[str]:
    fixes = []
    for key in ("checkinTime", "checkoutTime"):
        val = schema.get(key, "")
        if val and isinstance(val, str):
            # Remove any existing T prefix to normalize first
            val_clean = val.lstrip("T").rstrip("Z")
            # Accept HH:MM or HH:MM:SS
            if re.match(r"^\d{2}:\d{2}(:\d{2})?$", val_clean):
                formatted = f"T{val_clean}" if ":" in val_clean else f"T{val_clean}:00"
                if not formatted.endswith(":00"):
                    formatted += ":00"
                schema[key] = formatted
                fixes.append(f"Normalized {key} → {formatted}")
    return fixes


@_register_fix
def _fix_star_rating(schema: dict, errors: str) -> list[str]:
    sr = schema.get("starRating")
    if sr is None:
        return []
    if isinstance(sr, (int, float)):
        schema["starRating"] = {"@type": "Rating", "ratingValue": str(int(sr)), "bestRating": "5"}
        return [f"Wrapped starRating {sr} in Rating object"]
    if isinstance(sr, str) and sr.isdigit():
        schema["starRating"] = {"@type": "Rating", "ratingValue": sr, "bestRating": "5"}
        return ["Wrapped starRating string in Rating object"]
    if isinstance(sr, dict):
        sr.setdefault("@type", "Rating")
        sr.setdefault("bestRating", "5")
        if "ratingValue" in sr and not isinstance(sr["ratingValue"], str):
            sr["ratingValue"] = str(sr["ratingValue"])
        return ["Completed starRating object fields"]
    return []


@_register_fix
def _fix_address_type(schema: dict, errors: str) -> list[str]:
    addr = schema.get("address")
    if isinstance(addr, dict) and "@type" not in addr:
        addr["@type"] = "PostalAddress"
        return ["Added @type PostalAddress to address"]
    return []


@_register_fix
def _fix_geo_type(schema: dict, errors: str) -> list[str]:
    geo = schema.get("geo")
    if isinstance(geo, dict) and "@type" not in geo:
        geo["@type"] = "GeoCoordinates"
        return ["Added @type GeoCoordinates to geo"]
    if isinstance(geo, dict):
        # Ensure lat/lon are floats, not strings
        for coord in ("latitude", "longitude"):
            if coord in geo and isinstance(geo[coord], str):
                try:
                    geo[coord] = float(geo[coord])
                    return [f"Converted geo.{coord} to float"]
                except ValueError:
                    pass
    return []


@_register_fix
def _fix_image_type(schema: dict, errors: str) -> list[str]:
    if "image" not in schema:
        return []
    img = schema["image"]
    if isinstance(img, str):
        schema["image"] = {"@type": "ImageObject", "url": img}
        return ["Converted image string to ImageObject"]
    if isinstance(img, list):
        fixed = []
        changed = False
        for item in img:
            if isinstance(item, str):
                fixed.append({"@type": "ImageObject", "url": item})
                changed = True
            elif isinstance(item, dict) and "@type" not in item:
                item["@type"] = "ImageObject"
                fixed.append(item)
                changed = True
            else:
                fixed.append(item)
        if changed:
            schema["image"] = fixed
            return ["Converted image list items to ImageObject"]
    return []


@_register_fix
def _fix_contact_point(schema: dict, errors: str) -> list[str]:
    cp = schema.get("contactPoint")
    if isinstance(cp, dict) and "@type" not in cp:
        cp["@type"] = "ContactPoint"
        return ["Added @type ContactPoint"]
    return []


@_register_fix
def _fix_price_range(schema: dict, errors: str) -> list[str]:
    if "priceRange" in schema and not isinstance(schema["priceRange"], str):
        schema["priceRange"] = str(schema["priceRange"])
        return ["Converted priceRange to string"]
    return []


@_register_fix
def _fix_offers_type(schema: dict, errors: str) -> list[str]:
    offers = schema.get("offers")
    if isinstance(offers, dict) and "@type" not in offers:
        offers["@type"] = "Offer"
        return ["Added @type Offer to offers"]
    if isinstance(offers, list):
        changed = []
        for o in offers:
            if isinstance(o, dict) and "@type" not in o:
                o["@type"] = "Offer"
                changed.append(o)
        if changed:
            return [f"Added @type Offer to {len(changed)} offer(s)"]
    return []


@_register_fix
def _fix_empty_strings(schema: dict, errors: str) -> list[str]:
    skip = {"@context", "@type", "@id"}
    empty_keys = [k for k, v in list(schema.items()) if v == "" and k not in skip]
    for k in empty_keys:
        del schema[k]
    return [f"Removed empty properties: {', '.join(empty_keys)}"] if empty_keys else []


@_register_fix
def _fix_url_format(schema: dict, errors: str) -> list[str]:
    fixes = []
    for key in ("url", "sameAs"):
        val = schema.get(key)
        if val and isinstance(val, str) and not val.startswith(("http://", "https://")):
            schema[key] = "https://" + val
            fixes.append(f"Added https:// prefix to {key}")
    return fixes


@_register_fix
def _fix_amenity_features(schema: dict, errors: str) -> list[str]:
    """Ensure amenityFeature entries are LocationFeatureSpecification."""
    features = schema.get("amenityFeature")
    if not isinstance(features, list):
        return []
    changed = False
    for f in features:
        if isinstance(f, dict) and "@type" not in f:
            f["@type"] = "LocationFeatureSpecification"
            changed = True
        if isinstance(f, dict) and "value" not in f:
            f["value"] = True
            changed = True
    return ["Completed amenityFeature objects"] if changed else []


def auto_fix_from_errors(schemas: list, errors: list[str]) -> tuple[list, list]:
    """Run all registered auto-fix rules against schemas."""
    fixed = copy.deepcopy(schemas)
    all_fixes = []
    error_text = " ".join(errors).lower()

    for schema in fixed:
        for rule in _AUTO_FIX_RULES:
            try:
                fixes = rule(schema, error_text)
                all_fixes.extend(fixes)
            except Exception as e:
                all_fixes.append(f"Fix rule error ({rule.__name__}): {e}")

    return fixed, list(dict.fromkeys(all_fixes))  # deduplicate preserving order


# ─── Multi-Page Schema Patcher ────────────────────────────────────────────────

def patch_multi_page_schemas(
    all_schemas: dict,
    page_urls: list[str],
    ops: list[dict],
    target_type: str = None
) -> tuple[dict, dict]:
    """
    Apply operations to multiple pages' schemas at once.

    Args:
        all_schemas: project's full schemas_generated dict
        page_urls: list of page URLs to patch (empty = all pages)
        ops: parsed operation list
        target_type: only apply to schemas with this @type

    Returns: (updated_all_schemas, per_page_summary)
    """
    result = copy.deepcopy(all_schemas)
    summary = {}

    urls_to_patch = page_urls if page_urls else list(result.keys())

    for url in urls_to_patch:
        page_data = result.get(url)
        if not page_data:
            summary[url] = {"status": "skipped", "reason": "not found"}
            continue

        schemas = page_data.get("schemas", [])
        patched, warnings = apply_operations(schemas, ops, target_type)

        # Re-emit HTML
        script_tags = []
        for s in patched:
            script_tags.append(
                f'<script type="application/ld+json">\n{json.dumps(s, indent=2, ensure_ascii=False)}\n</script>'
            )

        page_data["schemas"] = patched
        page_data["json_ld_html"] = "\n\n".join(script_tags)
        page_data["multi_patch_warnings"] = warnings
        page_data["multi_patched_at"] = datetime.now(timezone.utc).isoformat()
        result[url] = page_data

        summary[url] = {
            "status": "patched",
            "schema_count": len(patched),
            "warnings": warnings
        }

    return result, summary


# ─── Main Single-Page Correction ─────────────────────────────────────────────

def regenerate_corrected_schema(
    original_schemas: list,
    validator_errors: list,
    instructions: str,
    hotel_data: dict,
    page: dict,
    user_id: int = None
) -> dict:
    """
    Full correction pipeline for a single page:
      1. Strip deprecated properties (from KB digest)
      2. Auto-fix common errors from validator output
      3. Apply user instructions (advanced DSL)
      4. Run compliance check against trend digest
      5. Re-emit JSON-LD HTML

    Returns comprehensive result dict.
    """
    # Step 0: Load digest & deprecated list
    digest = build_trend_digest(user_id=user_id)
    deprecated = digest.get("deprecated_properties", [])

    # Step 1: Strip deprecated
    schemas, stripped = strip_deprecated_properties(original_schemas, deprecated)
    deprecation_fixes = [f"Stripped deprecated property: {p}" for p in stripped]

    # Step 2: Auto-fix
    schemas, auto_fixes = auto_fix_from_errors(schemas, validator_errors)

    # Step 2b: Apply global guidelines from digest if any
    guideline_warnings = []
    user_guidelines = digest.get("user_guidelines", [])
    guideline_ops = []
    for gl in user_guidelines:
        content = gl.get("content", "")
        if content.strip():
            try:
                ops = parse_instructions(content)
                guideline_ops.extend(ops)
            except Exception as e:
                print(f"[Schema Correction] Guideline parse skip: {e}")
    if guideline_ops:
        schemas, guideline_warnings = apply_operations(schemas, guideline_ops)

    # Step 3: Parse and apply instructions
    instruction_fixes = []
    instruction_warnings = []
    if instructions.strip():
        ops = parse_instructions(instructions)
        schemas, instruction_warnings = apply_operations(schemas, ops)
        instruction_fixes = [
            _describe_op(op) for op in ops if op.get("op") not in ("note", "warn")
        ]

    # Step 3b: Align with example schemas from digest
    example_schemas = digest.get("example_schemas", [])
    if example_schemas:
        from backend.schema_generator import align_with_example_structure
        aligned_schemas = []
        for schema in schemas:
            matched_example = None
            for ex in example_schemas:
                if ex.get("@type") == schema.get("@type"):
                    matched_example = ex
                    break
            if matched_example:
                aligned_schema = align_with_example_structure(schema, matched_example, hotel_data)
                aligned_schemas.append(aligned_schema)
            else:
                aligned_schemas.append(schema)
        schemas = aligned_schemas

    # Step 4: Compliance check
    compliance_warnings = []
    for schema in schemas:
        compliance_warnings.extend(get_compliance_warnings(schema, digest))

    # Step 5: Emit JSON-LD HTML
    script_tags = [
        f'<script type="application/ld+json">\n{json.dumps(s, indent=2, ensure_ascii=False)}\n</script>'
        for s in schemas
    ]
    json_ld_html = "\n\n".join(script_tags)

    all_fixes = deprecation_fixes + auto_fixes + instruction_fixes
    all_warnings = guideline_warnings + instruction_warnings + compliance_warnings

    return {
        "corrected_schemas": schemas,
        "json_ld_html": json_ld_html,
        "schema_count": len(schemas),
        "deprecation_fixes": deprecation_fixes,
        "auto_fixes": auto_fixes,
        "instruction_fixes": instruction_fixes,
        "all_fixes": all_fixes,
        "compliance_warnings": all_warnings,
        "digest_notes": digest.get("notes", []),
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


def _describe_op(op: dict) -> str:
    verb = op.get("op", "?")
    if verb == "add":
        return f"ADD {op.get('key')} = {json.dumps(op.get('value'))[:60]}"
    if verb == "remove":
        return f"REMOVE {op.get('key')}"
    if verb == "set":
        return f"SET {op.get('path')} = {json.dumps(op.get('value'))[:50]}"
    if verb == "unset":
        return f"UNSET {op.get('path')}"
    if verb == "append":
        return f"APPEND to {op.get('key')}"
    if verb == "merge":
        return f"MERGE into {op.get('key')}"
    if verb == "type":
        cond = f" IF {op['condition']}" if op.get("condition") else ""
        return f"TYPE → {op.get('value')}{cond}"
    if verb == "replace":
        return f"REPLACE '{op.get('old')}' → '{op.get('new')}'"
    if verb == "rename":
        return f"RENAME {op.get('from')} → {op.get('to')}"
    if verb == "copy":
        return f"COPY {op.get('from')} → {op.get('to')}"
    if verb == "move":
        return f"MOVE {op.get('from')} → {op.get('to')}"
    if verb == "if":
        return f"IF {op.get('condition')} THEN ..."
    return f"{verb} ..."


# ─── Batch Regeneration with Full KB + Deprecation ────────────────────────────

def regenerate_all_schemas_with_kb(hotel_data: dict, pages: list, user_id: int) -> dict:
    """
    Re-generate all page schemas applying:
    - KB-prioritized digest
    - Deprecated property stripping
    - Auto-fixes
    """
    from backend.schema_generator import generate_all_schemas

    digest = build_trend_digest(user_id=user_id)
    deprecated = digest.get("deprecated_properties", [])

    hotel_data = copy.deepcopy(hotel_data)
    hotel_data["_trend_digest"] = digest

    all_schemas = generate_all_schemas(hotel_data, pages, user_id=user_id)

    for url, page_data in all_schemas.items():
        schemas = page_data.get("schemas", [])

        # Strip deprecated
        schemas, stripped = strip_deprecated_properties(schemas, deprecated)

        # Auto-fix
        schemas, fixes = auto_fix_from_errors(schemas, [])

        page_data["schemas"] = schemas
        page_data["deprecation_stripped"] = stripped
        page_data["auto_fixes"] = fixes

        # Re-emit
        page_data["json_ld_html"] = "\n\n".join(
            f'<script type="application/ld+json">\n{json.dumps(s, indent=2, ensure_ascii=False)}\n</script>'
            for s in schemas
        )

    return all_schemas
