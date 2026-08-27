#!/usr/bin/env python3
"""
IFC Step 2 tracing (basic Python only).

Goal:
- For each seed StepId, collect a closure of related entities:
  * Forward traversal: follow #refs recursively
  * Restricted inverse traversal: include ONLY relationship entities that reference the seed

Fix in this version:
- Relationship pruning:
  When traversing forward FROM a relationship entity (IfcRel*), do NOT follow
  the big "RelatedObjects/RelatedElements" lists (this causes explosion).
  Instead, follow only the "Relating..." side + relevant geometry/property pointers.
"""

import argparse
import json
import re
from collections import defaultdict, deque
from pathlib import Path

# -----------------------------
# IFC parsing helpers
# -----------------------------

def strip_block_comments(text: str) -> str:
    # Remove /* ... */ comments
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

def iter_statements_in_data_section(text: str):
    """
    Yield full IFC statements inside DATA; ... ENDSEC; each ending with ';'.
    Handles multi-line statements and semicolons inside strings.
    """
    m = re.search(r"\bDATA\s*;\s*(.*?)\bENDSEC\s*;", text, flags=re.IGNORECASE | re.DOTALL)
    data = m.group(1) if m else text  # fallback

    stmt = []
    in_str = False
    for idx, c in enumerate(data):
        stmt.append(c)

        if c == "'":
            if in_str:
                if idx + 1 < len(data) and data[idx + 1] == "'":  # escaped
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
    """Split arg list by top-level commas, respecting nesting and strings."""
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
                if i + 1 < len(arg_blob) and arg_blob[i + 1] == "'":  # escaped quote
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
                buf.pop()  # remove comma
                args.append("".join(buf).strip())
                buf = []

        i += 1

    tail = "".join(buf).strip()
    if tail:
        args.append(tail)
    return args

def extract_entity_statement(stmt: str):
    """
    Parse: #152= IFCWALL(...);
    Return (step_id, entity, args_list, raw_stmt) or None.
    """
    s = stmt.strip()
    m = re.match(r"^(#\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\)\s*;\s*$", s, flags=re.DOTALL)
    if not m:
        return None
    step_id = m.group(1)
    entity = m.group(2).upper()
    arg_blob = m.group(3).strip()
    args = split_top_level_args(arg_blob) if arg_blob else []
    return step_id, entity, args, s

def find_refs_outside_strings(text: str):
    """
    Find all #<digits> tokens in text, ignoring occurrences inside single-quoted strings.
    Returns list like ['#62', '#152', ...].
    """
    refs = []
    i = 0
    in_str = False

    while i < len(text):
        c = text[i]

        if c == "'":
            if in_str:
                if i + 1 < len(text) and text[i + 1] == "'":  # escaped
                    i += 2
                    continue
                in_str = False
            else:
                in_str = True
            i += 1
            continue

        if not in_str and c == "#":
            j = i + 1
            while j < len(text) and text[j].isdigit():
                j += 1
            if j > i + 1:
                refs.append(text[i:j])
                i = j
                continue

        i += 1

    return refs

def parse_ref(tok: str):
    tok = tok.strip()
    return tok if tok.startswith("#") else None

def parse_ref_list(tok: str):
    """
    Parse "(#1,#2,#3)" into ['#1','#2','#3'].
    Best-effort; ignores non-refs.
    """
    tok = tok.strip()
    if not tok.startswith("(") or not tok.endswith(")"):
        return []
    inner = tok[1:-1].strip()
    if not inner:
        return []
    parts = split_top_level_args(inner)
    out = []
    for p in parts:
        r = parse_ref(p)
        if r:
            out.append(r)
    return out

def refs_from_token(tok: str):
    """
    Return list of refs for a single token which may be:
      - "#123"
      - "(#1,#2,#3)"
      - "$"
      - others
    """
    tok = tok.strip()
    if not tok or tok == "$":
        return []
    if tok.startswith("(") and tok.endswith(")"):
        return parse_ref_list(tok)
    r = parse_ref(tok)
    return [r] if r else []

# -----------------------------
# Traversal policy
# -----------------------------

# Only relationship entities are allowed for inverse expansion (avoid explosion)
REL_WHITELIST = {
    "IFCRELAGGREGATES",
    "IFCRELCONTAINEDINSPATIALSTRUCTURE",
    "IFCRELDEFINESBYPROPERTIES",
    "IFCRELDEFINESBYTYPE",
    "IFCRELASSOCIATESMATERIAL",
    "IFCRELVOIDSELEMENT",
    "IFCRELFILLSELEMENT",
    "IFCRELCONNECTSELEMENTS",
    "IFCRELCONNECTSPATHELEMENTS",
    "IFCRELCONNECTSWITHREALIZINGELEMENTS",
    "IFCRELSPACEBOUNDARY",
    "IFCRELSPACEBOUNDARY1STLEVEL",
    "IFCRELSPACEBOUNDARY2NDLEVEL",
}

# Relationship forward pruning rules:
# For each IfcRel*, define which argument indices we are allowed to traverse forward into.
# IMPORTANT: We intentionally DO NOT follow big "RelatedObjects/RelatedElements" lists.
REL_FORWARD_ARGS = {
    # IfcRelContainedInSpatialStructure(GlobalId,OwnerHistory,Name,Description,RelatedElements,RelatingStructure)
    "IFCRELCONTAINEDINSPATIALSTRUCTURE": [5],  # RelatingStructure only

    # IfcRelAggregates(GlobalId,OwnerHistory,Name,Description,RelatingObject,RelatedObjects)
    "IFCRELAGGREGATES": [4],  # RelatingObject only

    # IfcRelDefinesByProperties(GlobalId,OwnerHistory,Name,Description,RelatedObjects,RelatingPropertyDefinition)
    "IFCRELDEFINESBYPROPERTIES": [5],  # RelatingPropertyDefinition only

    # IfcRelDefinesByType(GlobalId,OwnerHistory,Name,Description,RelatedObjects,RelatingType)
    "IFCRELDEFINESBYTYPE": [5],  # RelatingType only (often *TYPE; Step 3/summary can ignore if needed)

    # IfcRelAssociatesMaterial(GlobalId,OwnerHistory,Name,Description,RelatedObjects,RelatingMaterial)
    "IFCRELASSOCIATESMATERIAL": [5],  # RelatingMaterial only

    # IfcRelVoidsElement(GlobalId,OwnerHistory,Name,Description,RelatingBuildingElement,RelatedOpeningElement)
    "IFCRELVOIDSELEMENT": [5],  # opening only (prevents walking back out into other elements)

    # IfcRelFillsElement(GlobalId,OwnerHistory,Name,Description,RelatingOpeningElement,RelatedBuildingElement)
    "IFCRELFILLSELEMENT": [4],  # opening only (keeps it tight)

    # IfcRelConnectsElements(GlobalId,OwnerHistory,Name,Description,ConnectionGeometry,RelatingElement,RelatedElement)
    "IFCRELCONNECTSELEMENTS": [4, 5, 6],  # connection geometry + the two elements

    # Variants: keep conservative; if unknown ordering in some exports, fallback will be out_refs.
    "IFCRELCONNECTSPATHELEMENTS": [4, 5, 6],
    "IFCRELCONNECTSWITHREALIZINGELEMENTS": [4, 5, 6],

    # IfcRelSpaceBoundary* (if present):
    # Commonly includes (RelatingSpace, RelatedBuildingElement, ConnectionGeometry, ...) in later args.
    # We keep last 3-ish refs by index is unreliable, so leave it to fallback unless you add schema-specific parsing.
}

def get_forward_neighbors(cur_id: str, id_to_entity: dict, id_to_args: dict, out_refs: dict):
    """
    Return forward neighbors for traversal.
    - For relationship entities in REL_FORWARD_ARGS: only follow allowed indices
    - Otherwise: follow all out_refs
    """
    ent = id_to_entity.get(cur_id, "")
    if ent in REL_FORWARD_ARGS:
        args = id_to_args.get(cur_id, [])
        nbrs = []
        for idx in REL_FORWARD_ARGS[ent]:
            if 0 <= idx < len(args):
                nbrs.extend(refs_from_token(args[idx]))
        return nbrs
    return list(out_refs.get(cur_id, set()))

# -----------------------------
# Index build
# -----------------------------

def parse_ifc_index(ifc_text: str):
    """
    Build:
      id_to_entity[#id] = ENTITY
      id_to_args[#id]   = args list (top-level)
      out_refs[#id]     = set of referenced #ids (forward, raw/all)
      in_refs[#id]      = set of #ids that reference it (reverse index)
    """
    ifc_text = strip_block_comments(ifc_text)

    id_to_entity = {}
    id_to_args = {}
    out_refs = defaultdict(set)
    in_refs = defaultdict(set)

    for stmt in iter_statements_in_data_section(ifc_text):
        parsed = extract_entity_statement(stmt)
        if not parsed:
            continue
        sid, ent, args, raw = parsed
        id_to_entity[sid] = ent
        id_to_args[sid] = args

        refs = find_refs_outside_strings(raw)
        for r in refs:
            out_refs[sid].add(r)
            in_refs[r].add(sid)

    return id_to_entity, id_to_args, out_refs, in_refs

# -----------------------------
# Step 2 tracing per seed
# -----------------------------

def sort_step_ids(step_ids):
    def step_num(x: str):
        try:
            return int(x[1:])
        except Exception:
            return 10**12
    return sorted(step_ids, key=step_num)

def trace_seed(seed_id: str,
               id_to_entity: dict,
               id_to_args: dict,
               out_refs: dict,
               in_refs: dict,
               max_nodes: int = 200000):
    """
    Returns:
      ids_sorted, missing_ids_sorted
    """
    visited = set([seed_id])
    missing = set()
    q = deque([seed_id])

    # Restricted inverse: only relationships that directly reference the seed
    for ref_by in in_refs.get(seed_id, set()):
        if id_to_entity.get(ref_by, "") in REL_WHITELIST and ref_by not in visited:
            visited.add(ref_by)
            q.append(ref_by)

    # Forward closure
    while q:
        if len(visited) > max_nodes:
            break

        cur = q.popleft()
        for nxt in get_forward_neighbors(cur, id_to_entity, id_to_args, out_refs):
            if nxt in visited:
                continue

            if nxt not in id_to_entity:
                missing.add(nxt)
                visited.add(nxt)  # mark as visited to stop repeated chasing
                continue

            visited.add(nxt)
            q.append(nxt)

    ids_sorted = sort_step_ids(visited)
    missing_sorted = sort_step_ids(missing)
    return ids_sorted, missing_sorted

def build_output_for_seed(seed_obj: dict,
                          id_to_entity: dict,
                          id_to_args: dict,
                          out_refs: dict,
                          in_refs: dict,
                          max_nodes: int, include_entities: bool = False):
    seed_id = seed_obj.get("StepId", "")
    if not seed_id or seed_id not in id_to_entity:
        return {
            "seed": seed_obj,
            "count": 0,
            "nodes": ([{"StepId": seed_id, "Entity": "MISSING"}] if include_entities else ([seed_id] if seed_id else [])),
            "missing_ids": [seed_id] if seed_id else [],
        }

    ids, missing_ids = trace_seed(seed_id, id_to_entity, id_to_args, out_refs, in_refs, max_nodes=max_nodes)
    if include_entities:
        nodes = [{"StepId": sid, "Entity": id_to_entity.get(sid, "MISSING")} for sid in ids]
    else:
        # Compact: only StepIds (much smaller JSON; Step 3 can rebuild entity info from IFC)
        nodes = list(ids)

    return {
        "seed": seed_obj,
        "count": len(nodes),
        "nodes": nodes,
        "missing_ids": missing_ids,
    }

# -----------------------------
# CLI
# -----------------------------

def main():
    ap = argparse.ArgumentParser(description="IFC Step 2 tracing (basic Python only) with relationship pruning.")
    ap.add_argument("ifc_path", help="Path to IFC file (.ifc)")
    ap.add_argument("seeds_json", help="Path to Step 1 seeds JSON")
    ap.add_argument("--include-entities", action="store_true", help="Include Entity names per node (larger output). Default is compact StepId-only nodes.")
    ap.add_argument("--out", default="step2_traced.json", help="Output JSON path")
    ap.add_argument("--seed", default="", help='Optional single seed StepId to trace, e.g. "#62"')
    ap.add_argument("--max-nodes", type=int, default=200000, help="Safety cap per seed")
    ap.add_argument("--print-json", action="store_true", help="Print full output JSON at end")
    args = ap.parse_args()

    ifc_text = Path(args.ifc_path).read_text(encoding="utf-8", errors="replace")
    seeds = json.loads(Path(args.seeds_json).read_text(encoding="utf-8", errors="replace"))

    id_to_entity, id_to_args, out_refs, in_refs = parse_ifc_index(ifc_text)

    # Optional single seed mode
    if args.seed:
        seeds = [s for s in seeds if s.get("StepId") == args.seed]

    results = {}
    for seed_obj in seeds:
        sid = seed_obj.get("StepId", "")
        results[sid] = build_output_for_seed(seed_obj, id_to_entity, id_to_args, out_refs, in_refs, args.max_nodes)

    out_obj = {"results": results}
    Path(args.out).write_text(json.dumps(out_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote traced JSON to: {args.out}")

    if args.print_json:
        print("\n--- JSON RESULT (END) ---")
        print(json.dumps(out_obj, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()