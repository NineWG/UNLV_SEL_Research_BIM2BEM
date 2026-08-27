#!/usr/bin/env python3
"""
IFC BIM→BEM Geometry Step 1 (Basic Modules Only)

Goal:
- Extract geometry seed objects from an IFC (STEP text) file without IFC libraries.
- Output JSON records:
  [{"StepId":"#152","Entity":"IFCWALL","Name":"...","GlobalId":"..."}]
- Exclude *TYPE entities (e.g., IFCWALLTYPE, IFCSPACETYPE) from output and summary.
- Print the JSON result at the end of the run.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path


def _r4(x):
    try:
        return round(float(x), 4)
    except Exception:
        return x

# -----------------------------
# STEP/IFC text parsing helpers
# -----------------------------

def strip_block_comments(text: str) -> str:
    """
    Remove /* ... */ block comments, but keep anything inside single-quoted strings.
    STEP strings use single quotes; escaped quote is doubled ''.
    """
    out = []
    i = 0
    in_str = False
    while i < len(text):
        c = text[i]

        if c == "'":
            out.append(c)
            if in_str:
                # Escaped quote
                if i + 1 < len(text) and text[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                in_str = False
            else:
                in_str = True
            i += 1
            continue

        # Block comments only when not in string
        if (not in_str) and c == "/" and i + 1 < len(text) and text[i + 1] == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2  # skip closing */
            continue

        out.append(c)
        i += 1

    return "".join(out)

def iter_statements_in_data_section(text: str):
    """
    Yield full IFC statements inside DATA; ... ENDSEC; as strings, each ending with ';'.
    Handles multi-line statements and semicolons inside strings.
    """
    m = re.search(r"\bDATA\s*;\s*(.*?)\bENDSEC\s*;", text, flags=re.IGNORECASE | re.DOTALL)
    data = m.group(1) if m else text  # fallback: parse whole file

    stmt = []
    in_str = False
    for idx, c in enumerate(data):
        stmt.append(c)

        if c == "'":
            if in_str:
                # Escaped quote '' => stay in string
                if idx + 1 < len(data) and data[idx + 1] == "'":
                    continue
                in_str = False
            else:
                in_str = True

        if c == ";" and not in_str:
            s = "".join(stmt).strip()
            if s:
                yield s
            stmt = []

def split_top_level_args(arg_blob: str):
    """
    Split a STEP argument list (inside parentheses) by top-level commas.
    Respects nested parentheses and STEP strings with escaped quotes.
    """
    args = []
    buf = []
    depth = 0
    in_str = False
    i = 0

    while i < len(arg_blob):
        c = arg_blob[i]
        buf.append(c)

        if c == "'":
            if in_str:
                # Escaped quote
                if i + 1 < len(arg_blob) and arg_blob[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_str = False
            else:
                in_str = True
            i += 1
            continue

        if not in_str:
            if c == "(":
                depth += 1
            elif c == ")":
                depth = max(0, depth - 1)
            elif c == "," and depth == 0:
                # End of arg at top-level
                buf.pop()  # remove comma
                args.append("".join(buf).strip())
                buf = []

        i += 1

    tail = "".join(buf).strip()
    if tail:
        args.append(tail)

    return args

def unquote_step_string(s: str) -> str:
    """
    Convert STEP string token like 'ABC''DEF' into ABC'DEF.
    Return "" for $ or non-quoted tokens.
    """
    s = s.strip()
    if not s or s == "$":
        return ""
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        inner = s[1:-1]
        return inner.replace("''", "'")
    return ""

def extract_entity_statement(stmt: str):
    """
    Parse statement of form:
      #152= IFCWALL(...);

    Return (step_id, entity, args_list) or None if not matched.
    """
    s = stmt.strip()
    m = re.match(r"^(#\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\)\s*;\s*$", s, flags=re.DOTALL)
    if not m:
        return None
    step_id = m.group(1)
    entity = m.group(2).upper()
    arg_blob = m.group(3).strip()
    args = split_top_level_args(arg_blob) if arg_blob else []
    return step_id, entity, args

# -----------------------------
# Seed selection + field extraction
# -----------------------------

# Keep this list flexible; prefix matching catches subtypes like IFCWALLSTANDARDCASE
# Keep this list flexible; prefix matching catches subtypes like IFCWALLSTANDARDCASE
# NOTE: Doors/Windows are handled STRICTLY in is_target_entity() (only IFCDOOR / IFCWINDOW occurrences),
# so they are intentionally NOT included in this prefix list.
TARGET_PREFIXES = (
    "IFCSPACE",
    "IFCWALL",
    "IFCCURTAINWALL",
    "IFCROOF",
    "IFCSLAB",
    "IFCCOVERING",
    "IFCBUILDINGSTOREY",
)

def is_target_entity(entity: str) -> bool:
    """Return True if this entity should be included as a *seed*.

    Rules (BIM→BEM Geometry Step 1):
    - Exclude *TYPE (handled separately via is_type_entity)
    - Exclude *PROPERTIES (no direct geometry; prevents counting IFCDOORLININGPROPERTIES, etc.)
    - Doors/Windows: include only occurrence entities (IFCDOOR / IFCWINDOW), not their property objects.
    - Others use prefix matching to keep subtypes (e.g., IFCWALLSTANDARDCASE).
    """
    e = entity.upper()

    # Exclude property-definition entities (no direct geometry for BEM)
    if e.endswith("PROPERTIES"):
        return False

    # Doors/Windows: occurrences only (strict)
    if e in ("IFCDOOR", "IFCWINDOW"):
        return True

    # Everything else: prefix match
    return any(e.startswith(p) for p in TARGET_PREFIXES)

def is_type_entity(entity: str) -> bool:
    # Exclude type definitions from seeds (no direct geometry)
    return entity.upper().endswith("TYPE")

def extract_name_and_globalid(args: list):
    """
    Best-effort IfcRoot heuristic:
      args[0] = GlobalId
      args[2] = Name

    If missing or not quoted, returns "".
    """
    globalid = unquote_step_string(args[0]) if len(args) > 0 else ""
    name = unquote_step_string(args[2]) if len(args) > 2 else ""
    return name, globalid


def _as_float(token: str):
    """Parse a STEP numeric token into float.

    Returns None for '$', '*', or non-numeric tokens.
    """
    t = (token or "").strip()
    if not t or t in ("$", "*"):
        return None
    try:
        return float(t)
    except Exception:
        return None


def parse_building_storeys(ifc_text: str, length_to_m: float):
    """Extract IfcBuildingStorey elevations (in meters).

    Uses IfcBuildingStorey.Elevation (commonly arg index 9):
      IfcBuildingStorey(GlobalId, OwnerHistory, Name, Description, ObjectType,
      ObjectPlacement, Representation, LongName, CompositionType, Elevation)
    """
    txt = strip_block_comments(ifc_text)
    storey_info = {}
    for stmt in iter_statements_in_data_section(txt):
        parsed = extract_entity_statement(stmt)
        if not parsed:
            continue
        sid, ent, args = parsed
        if ent != "IFCBUILDINGSTOREY":
            continue
        name, gid = extract_name_and_globalid(args)
        elev_raw = _as_float(args[9]) if len(args) > 9 else None
        elev_m = _r4(elev_raw * float(length_to_m)) if elev_raw is not None else ""
        storey_info[sid] = {"Name": name, "GlobalId": gid, "Elevation_m": elev_m}
    return storey_info


def parse_elem_to_storey_map(ifc_text: str):
    """Map elements/spaces to their containing IfcBuildingStorey StepId.

    We use two common patterns:
    1) IfcRelAggregates: RelatingObject (storey) -> RelatedObjects (spaces)
       (..., RelatingObject, RelatedObjects)
    2) IfcRelContainedInSpatialStructure: RelatingStructure (storey) contains RelatedElements
       (..., RelatedElements, RelatingStructure)
    """
    txt = strip_block_comments(ifc_text)
    m = {}
    for stmt in iter_statements_in_data_section(txt):
        parsed = extract_entity_statement(stmt)
        if not parsed:
            continue
        _sid, ent, args = parsed

        if ent == "IFCRELAGGREGATES" and len(args) >= 6:
            relating = args[4].strip()
            related = args[5].strip()
            if not relating.startswith("#"):
                continue
            related_ids = []
            if related.startswith("(") and related.endswith(")"):
                inner = related[1:-1].strip()
                if inner:
                    related_ids = [t.strip() for t in split_top_level_args(inner)]
            elif related.startswith("#"):
                related_ids = [related]
            for rid in related_ids:
                if rid.startswith("#"):
                    m[rid] = relating

        elif ent == "IFCRELCONTAINEDINSPATIALSTRUCTURE" and len(args) >= 6:
            related = args[4].strip()
            relating = args[5].strip()
            if not relating.startswith("#"):
                continue
            related_ids = []
            if related.startswith("(") and related.endswith(")"):
                inner = related[1:-1].strip()
                if inner:
                    related_ids = [t.strip() for t in split_top_level_args(inner)]
            elif related.startswith("#"):
                related_ids = [related]
            for rid in related_ids:
                if rid.startswith("#"):
                    m[rid] = relating

    return m

def extract_seeds(ifc_text: str, *, storey_info=None, elem_to_storey=None):
    """Extract seed entities.

    Optional enrichment (multi-storey support):
    - IFCBUILDINGSTOREY: include Elevation_m (from storey_info)
    - IFCSPACE: include StoreyStepId and StoreyElevation_m (via elem_to_storey)
    """
    ifc_text = strip_block_comments(ifc_text)

    seeds = []
    summary = Counter()

    for stmt in iter_statements_in_data_section(ifc_text):
        parsed = extract_entity_statement(stmt)
        if not parsed:
            continue

        step_id, entity, args = parsed

        if not is_target_entity(entity):
            continue

        if is_type_entity(entity):
            continue  # drop *TYPE objects entirely

        name, globalid = extract_name_and_globalid(args)

        rec = {
            "StepId": step_id,
            "Entity": entity,
            "Name": name,
            "GlobalId": globalid,
        }

        # Space naming support for Step 5:
        # In IFCSPACE, arg[7] is commonly LongName. Some BIM/UI tools expose this
        # as a space tag/label, so keep it as both LongName and SpaceTag when present.
        if entity.startswith("IFCSPACE"):
            long_name = unquote_step_string(args[7]) if len(args) > 7 else ""
            if long_name:
                rec["LongName"] = long_name
                rec["SpaceTag"] = long_name

        if entity == "IFCBUILDINGSTOREY" and storey_info and step_id in storey_info:
            rec["Elevation_m"] = storey_info[step_id].get("Elevation_m", "")

        if entity.startswith("IFCSPACE") and elem_to_storey:
            st = elem_to_storey.get(step_id)
            if st and isinstance(st, str) and st.startswith("#"):
                rec["StoreyStepId"] = st
                if storey_info and st in storey_info:
                    rec["StoreyElevation_m"] = storey_info[st].get("Elevation_m", "")

        seeds.append(rec)

        # Summary by major groups (simple & robust)
        if entity.startswith("IFCSPACE"):
            summary["SPACE"] += 1
        elif entity.startswith("IFCWALL") or entity.startswith("IFCCURTAINWALL"):
            summary["WALL"] += 1
        elif entity == "IFCWINDOW":
            summary["WINDOW"] += 1
        elif entity == "IFCDOOR":
            summary["DOOR"] += 1
        elif entity.startswith("IFCROOF"):
            summary["ROOF"] += 1
        elif entity.startswith("IFCSLAB"):
            # best-effort: treat slab as FLOOR/ROOF if tokens exist, else FLOOR (or SLAB)
            joined = " ".join(a.upper() for a in args)
            if ".ROOF." in joined:
                summary["ROOF"] += 1
            else:
                summary["FLOOR"] += 1
        elif entity.startswith("IFCCOVERING"):
            joined = " ".join(a.upper() for a in args)
            if ".CEILING." in joined:
                summary["CEILING"] += 1
            else:
                summary["CEILING"] += 1  # still count as ceiling-ish for BEM step-1
        else:
            summary["OTHER"] += 1

    # Sort by numeric StepId
    def step_num(r):
        try:
            return int(r["StepId"][1:])
        except Exception:
            return 10**12

    seeds.sort(key=step_num)
    return seeds, summary

# -----------------------------
# CLI
# -----------------------------

# -----------------------------
# Unit detection (length -> meters)
# -----------------------------

_SI_PREFIX_TO_SCALE = {
    "$": 1.0,
    ".MILLI.": 0.001,
    ".CENTI.": 0.01,
    ".DECI.": 0.1,
    ".DEKA.": 10.0,
    ".HECTO.": 100.0,
    ".KILO.": 1000.0,
}

def detect_length_to_m(ifc_text: str):
    """Best-effort: detect LENGTHUNIT scale factor to meters.

    Supports common metric patterns:
      - IFCSIUNIT(.LENGTHUNIT., .MILLI., .METRE.)  -> millimeters (0.001)
      - IFCSIUNIT(.LENGTHUNIT., $, .METRE.)        -> meters (1.0)

    Returns: (length_to_m: float, note: str)
    """
    txt = strip_block_comments(ifc_text)
    for stmt in iter_statements_in_data_section(txt):
        parsed = extract_entity_statement(stmt)
        if not parsed:
            continue
        sid, ent, args = parsed
        if ent != "IFCSIUNIT" or len(args) < 3:
            continue
        unit_type = args[0].strip().upper()
        prefix = args[1].strip().upper()
        name = args[2].strip().upper()
        if unit_type != ".LENGTHUNIT.":
            continue
        # Most exporters encode mm as (LENGTHUNIT, MILLI, METRE)
        if name == ".METRE.":
            scale = _SI_PREFIX_TO_SCALE.get(prefix, 1.0)
            if prefix == "$":
                return scale, "Detected SI length unit: METRE"
            return scale, f"Detected SI length unit: {prefix} METRE"
    # fallback: assume millimeters (common for Revit exports)
    return 0.001, "No explicit LENGTHUNIT detected; assumed millimeters (MILLI*METRE)"

def main():
    ap = argparse.ArgumentParser(
        description="IFC Step 1 seed extraction (basic Python only): output JSON [StepId, Entity, Name, GlobalId], exclude *TYPE."
    )
    ap.add_argument("ifc_path", help="Path to IFC file (.ifc)")
    ap.add_argument("--out", default="seeds.json", help="Output JSON path (default: seeds.json)")
    ap.add_argument("--units-out", default="ifc_units.json", help="Output units JSON (default: ifc_units.json)")
    ap.add_argument("--print-json", action="store_true",
                    help="Print the full JSON result at the end (default: True)")
    ap.add_argument("--no-print-json", action="store_true",
                    help="Do not print JSON at end (overrides --print-json)")
    args = ap.parse_args()

    text = Path(args.ifc_path).read_text(encoding="utf-8", errors="replace")
    length_to_m, units_note = detect_length_to_m(text)
    storey_info = parse_building_storeys(text, length_to_m=length_to_m)
    elem_to_storey = parse_elem_to_storey_map(text)
    seeds, summary = extract_seeds(text, storey_info=storey_info, elem_to_storey=elem_to_storey)
    units_out_path = Path(args.units_out)
    # If user passed a bare filename, write next to seeds.json by default
    if not units_out_path.is_absolute() and units_out_path.parent == Path('.'):
        units_out_path = Path(args.out).resolve().parent / units_out_path
    units_out_path.write_text(json.dumps({"length_to_m": _r4(length_to_m), "note": units_note}, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write JSON file
    out_path = Path(args.out)
    out_path.write_text(json.dumps(seeds, ensure_ascii=False, indent=2), encoding="utf-8")

    # Print summary (no TYPE included because we exclude them earlier)
    total = len(seeds)
    print(f"Wrote {total} seed records to: {out_path}")
    print(f"Wrote units JSON to: {units_out_path}  (length_to_m={length_to_m})")
    
    print("Summary (non-TYPE only):")
    for k in ["SPACE","WALL","WINDOW","DOOR","FLOOR","CEILING","ROOF","OTHER"]:
        print(f"  {k}: {summary.get(k, 0)}")


    # Print full JSON at end (as requested)
    should_print_json = True
    if args.no_print_json:
        should_print_json = False
    if args.print_json:
        should_print_json = True

    if should_print_json:
        print("\n--- JSON RESULT (END) ---")
        print(json.dumps(seeds, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()