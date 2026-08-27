#!/usr/bin/env python3
"""
IFCgeometry_filter.py  (BIM→BEM Geometry Step 3)

Basic-modules-only.
Goal: From Step 2 traced nodes, FILTER geometry-related entities and FINISH CALCULATIONS here:
- coordinates (world footprint points) when possible
- area, volume, height
- thickness, width, length (if derivable)
- if not available -> omit

Works best for common IFC patterns:
- IfcProductDefinitionShape -> IfcShapeRepresentation -> IfcExtrudedAreaSolid
- Profile = IfcRectangleProfileDef or IfcArbitraryClosedProfileDef (IfcPolyline)

Usage:
  python IFCgeometry_filter.py input.ifc step2_traced.json --out step3_geometry.json
  python IFCgeometry_filter.py input.ifc step2_traced.json --seed "#62" --out step3_62.json
"""

import argparse
import json
import math
import re
from collections import defaultdict, deque
from pathlib import Path

# -----------------------------
# Units
# -----------------------------
# Internal convention (v2): ALL geometry/lengths are in METERS.
# LEN_TO_M is loaded from ifc_units.json (written by Step 1); fallback assumes millimeters.
LEN_TO_M = 0.001

def load_len_to_m(units_path: str):
    global LEN_TO_M
    try:
        p = Path(units_path)
        if p.exists():
            obj = json.loads(p.read_text(encoding='utf-8'))
            v = obj.get('length_to_m')
            if isinstance(v, (int, float)) and v > 0:
                LEN_TO_M = float(v)
                return
    except Exception:
        pass
    # fallback stays 0.001 (mm)



# -----------------------------
# Rounding (global)
# -----------------------------
def _r4(x):
    try:
        return round(float(x), 4)
    except Exception:
        return x

def round_floats(obj):
    """Recursively round all int/float values to 4 decimals (meters-based convention)."""
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return _r4(obj)
    if isinstance(obj, list):
        return [round_floats(v) for v in obj]
    if isinstance(obj, tuple):
        return [round_floats(v) for v in obj]
    if isinstance(obj, dict):
        return {k: round_floats(v) for k, v in obj.items()}
    return obj

# -----------------------------
# STEP parsing (same style as Step 1/2)
# -----------------------------

def strip_block_comments(text: str) -> str:
    out = []
    i = 0
    in_str = False
    while i < len(text):
        c = text[i]
        if c == "'":
            out.append(c)
            if in_str:
                if i + 1 < len(text) and text[i + 1] == "'":  # escaped ''
                    out.append("'")
                    i += 2
                    continue
                in_str = False
            else:
                in_str = True
            i += 1
            continue

        if (not in_str) and c == "/" and i + 1 < len(text) and text[i + 1] == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue

        out.append(c)
        i += 1
    return "".join(out)

def iter_statements_in_data_section(text: str):
    m = re.search(r"\bDATA\s*;\s*(.*?)\bENDSEC\s*;", text, flags=re.IGNORECASE | re.DOTALL)
    data = m.group(1) if m else text
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
                if i + 1 < len(arg_blob) and arg_blob[i + 1] == "'":  # escaped
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
                buf.pop()
                args.append("".join(buf).strip())
                buf = []
        i += 1

    tail = "".join(buf).strip()
    if tail:
        args.append(tail)
    return args

def extract_entity_statement(stmt: str):
    s = stmt.strip()
    m = re.match(r"^(#\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\)\s*;\s*$", s, flags=re.DOTALL)
    if not m:
        return None
    sid = m.group(1)
    ent = m.group(2).upper()
    arg_blob = m.group(3).strip()
    args = split_top_level_args(arg_blob) if arg_blob else []
    return sid, ent, args, s

def unquote_step_string(s: str) -> str:
    s = s.strip()
    if not s or s == "$":
        return ""
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    return ""

def parse_float(tok: str):
    tok = tok.strip()
    if not tok or tok == "$":
        return None
    # STEP can contain e.g. 3.2E-3
    try:
        return float(tok)
    except Exception:
        return None

def parse_ref(tok: str):
    tok = tok.strip()
    return tok if tok.startswith("#") else None


# -----------------------------
# Storey support helpers
# -----------------------------

_REF_RE = re.compile(r"#\d+")

def extract_refs(tok: str):
    """Extract all STEP id references from a token (handles lists like '(#1,#2)')."""
    if not tok or tok == "$":
        return []
    return _REF_RE.findall(tok)

def build_storey_elevation_map(nodes_set, id_to_ent, id_to_args):
    """Return {storey_step_id: elevation_m} for IFCBUILDINGSTOREY nodes."""
    m = {}
    for sid in nodes_set:
        if id_to_ent.get(sid) != "IFCBUILDINGSTOREY":
            continue
        args = id_to_args.get(sid, [])
        # IFCBUILDINGSTOREY(..., Elevation)
        elev = None
        if args:
            elev = parse_float(args[-1])
        if elev is None:
            continue
        m[sid] = float(elev) * LEN_TO_M
    return m

def find_storey_for_space(space_id, nodes_set, id_to_ent, id_to_args):
    """Best-effort find containing storey for an IFCSPACE using common relationships."""
    # 1) IFCRELCONTAINEDINSPATIALSTRUCTURE(RelatedElements, RelatingStructure)
    for sid in nodes_set:
        if id_to_ent.get(sid) != "IFCRELCONTAINEDINSPATIALSTRUCTURE":
            continue
        args = id_to_args.get(sid, [])
        if len(args) < 6:
            continue
        related = extract_refs(args[4])
        if space_id not in related:
            continue
        relating = parse_ref(args[5])
        if relating and id_to_ent.get(relating) == "IFCBUILDINGSTOREY":
            return relating

    # 2) IFCRELAGGREGATES(RelatingObject, RelatedObjects)
    for sid in nodes_set:
        if id_to_ent.get(sid) != "IFCRELAGGREGATES":
            continue
        args = id_to_args.get(sid, [])
        if len(args) < 6:
            continue
        relating = parse_ref(args[4])
        if not (relating and id_to_ent.get(relating) == "IFCBUILDINGSTOREY"):
            continue
        related = extract_refs(args[5])
        if space_id in related:
            return relating

    return None

def find_storey_for_element(element_id, nodes_set, id_to_ent, id_to_args):
    """Best-effort find containing storey for a general IfcProduct occurrence.

    Uses the same two common patterns as spaces:
      1) IfcRelContainedInSpatialStructure: element appears in RelatedElements -> storey in RelatingStructure
      2) IfcRelAggregates: storey in RelatingObject aggregates element in RelatedObjects

    Returns storey StepId (e.g. '#123') or None.
    """
    # 1) IFCRELCONTAINEDINSPATIALSTRUCTURE(RelatedElements, RelatingStructure)
    for sid in nodes_set:
        if id_to_ent.get(sid) != "IFCRELCONTAINEDINSPATIALSTRUCTURE":
            continue
        args = id_to_args.get(sid, [])
        if len(args) < 6:
            continue
        related = extract_refs(args[4])
        if element_id not in related:
            continue
        relating = parse_ref(args[5])
        if relating and id_to_ent.get(relating) == "IFCBUILDINGSTOREY":
            return relating

    # 2) IFCRELAGGREGATES(RelatingObject, RelatedObjects)
    for sid in nodes_set:
        if id_to_ent.get(sid) != "IFCRELAGGREGATES":
            continue
        args = id_to_args.get(sid, [])
        if len(args) < 6:
            continue
        relating = parse_ref(args[4])
        if not (relating and id_to_ent.get(relating) == "IFCBUILDINGSTOREY"):
            continue
        related = extract_refs(args[5])
        if element_id in related:
            return relating

    return None

def _lift_points_z(points, dz):
    if not points or dz is None:
        return points
    out = []
    for p in points:
        if isinstance(p, (list, tuple)) and len(p) >= 3:
            out.append([p[0], p[1], p[2] + dz])
        else:
            out.append(p)
    return out

def parse_ref_list(tok: str):
    """
    Parse something like "(#1,#2,#3)" into ['#1','#2','#3'].
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

def build_ifc_maps(ifc_text: str):
    """
    Returns:
      id_to_ent[#id] = entity
      id_to_args[#id] = args list
    """
    ifc_text = strip_block_comments(ifc_text)
    id_to_ent = {}
    id_to_args = {}
    for stmt in iter_statements_in_data_section(ifc_text):
        parsed = extract_entity_statement(stmt)
        if not parsed:
            continue
        sid, ent, args, raw = parsed
        id_to_ent[sid] = ent
        id_to_args[sid] = args
    return id_to_ent, id_to_args

# -----------------------------
# Basic linear algebra (4x4 transforms)
# -----------------------------

def vec_norm(v):
    n = math.sqrt(sum(x*x for x in v))
    if n == 0:
        return [0.0, 0.0, 0.0], 0.0
    return [x/n for x in v], n

def vec_cross(a, b):
    return [
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0],
    ]

def mat4_mul(A, B):
    # 4x4 multiply
    out = [[0.0]*4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            out[i][j] = sum(A[i][k]*B[k][j] for k in range(4))
    return out

def mat4_apply(M, p):
    # p=[x,y,z,1]
    x = M[0][0]*p[0] + M[0][1]*p[1] + M[0][2]*p[2] + M[0][3]*p[3]
    y = M[1][0]*p[0] + M[1][1]*p[1] + M[1][2]*p[2] + M[1][3]*p[3]
    z = M[2][0]*p[0] + M[2][1]*p[1] + M[2][2]*p[2] + M[2][3]*p[3]
    w = M[3][0]*p[0] + M[3][1]*p[1] + M[3][2]*p[2] + M[3][3]*p[3]
    if w and w != 1.0:
        return [x/w, y/w, z/w]
    return [x, y, z]

def mat4_identity():
    return [
        [1.0,0.0,0.0,0.0],
        [0.0,1.0,0.0,0.0],
        [0.0,0.0,1.0,0.0],
        [0.0,0.0,0.0,1.0],
    ]

def make_axis2placement3d_matrix(location, axis, refdir):
    """
    IFC Axis2Placement3D defines:
      - Location (origin)
      - Axis (Z direction) optional
      - RefDirection (X direction) optional
    Build right-handed basis (X,Y,Z).
    """
    O = location

    # Defaults
    z = axis if axis else [0.0, 0.0, 1.0]
    x = refdir if refdir else [1.0, 0.0, 0.0]

    z, _ = vec_norm(z)
    x, _ = vec_norm(x)

    # Make Y = Z x X
    y = vec_cross(z, x)
    y, yn = vec_norm(y)
    if yn == 0:
        # fallback
        y = [0.0, 1.0, 0.0]

    # Re-orthogonalize X = Y x Z
    x = vec_cross(y, z)
    x, xn = vec_norm(x)
    if xn == 0:
        x = [1.0, 0.0, 0.0]

    M = mat4_identity()
    # columns = basis vectors, last column = translation
    M[0][0], M[1][0], M[2][0] = x[0], x[1], x[2]
    M[0][1], M[1][1], M[2][1] = y[0], y[1], y[2]
    M[0][2], M[1][2], M[2][2] = z[0], z[1], z[2]
    M[0][3], M[1][3], M[2][3] = O[0], O[1], O[2]
    return M

def make_axis2placement2d_matrix(location2d, refdir2d):
    """
    Axis2Placement2D defines origin + X direction in 2D.
    We'll embed in XY plane (z=0).
    """
    ox, oy = location2d
    if refdir2d:
        x = [refdir2d[0], refdir2d[1], 0.0]
        x, _ = vec_norm(x)
    else:
        x = [1.0, 0.0, 0.0]
    z = [0.0, 0.0, 1.0]
    y = vec_cross(z, x)
    y, yn = vec_norm(y)
    if yn == 0:
        y = [0.0, 1.0, 0.0]

    M = mat4_identity()
    M[0][0], M[1][0], M[2][0] = x[0], x[1], x[2]
    M[0][1], M[1][1], M[2][1] = y[0], y[1], y[2]
    M[0][3], M[1][3], M[2][3] = ox, oy, 0.0
    return M

# -----------------------------
# IFC entity interpreters (limited but practical)
# -----------------------------

def get_cartesian_point(sid, id_to_ent, id_to_args):
    # IFCCARTESIANPOINT((x,y,z)) OR ((x,y))
    if id_to_ent.get(sid) != "IFCCARTESIANPOINT":
        return None
    args = id_to_args.get(sid, [])
    if not args:
        return None
    coords_tok = args[0].strip()
    # coords_tok like "(1.0,2.0,0.0)" OR "((1.0,2.0,0.0))" depending exporter
    # We handle both by extracting numbers inside.
    nums = re.findall(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?", coords_tok)
    if not nums:
        return None
    vals = [float(n) for n in nums]
    vals = [v * LEN_TO_M for v in vals]  # scale length unit -> meters
    if len(vals) == 2:
        return [vals[0], vals[1], 0.0]
    return [vals[0], vals[1], vals[2] if len(vals) > 2 else 0.0]

def get_direction(sid, id_to_ent, id_to_args):
    # IFCDIRECTION((x,y,z)) or ((x,y))
    if id_to_ent.get(sid) != "IFCDIRECTION":
        return None
    args = id_to_args.get(sid, [])
    if not args:
        return None
    nums = re.findall(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?", args[0])
    if not nums:
        return None
    vals = [float(n) for n in nums]
    if len(vals) == 2:
        return [vals[0], vals[1], 0.0]
    return [vals[0], vals[1], vals[2] if len(vals) > 2 else 0.0]

def get_axis2placement3d_matrix(sid, id_to_ent, id_to_args):
    if id_to_ent.get(sid) != "IFCAXIS2PLACEMENT3D":
        return None
    args = id_to_args.get(sid, [])
    # (Location, Axis, RefDirection) with optional $
    loc = get_cartesian_point(parse_ref(args[0]) or "", id_to_ent, id_to_args) if len(args) > 0 else None
    axis = get_direction(parse_ref(args[1]) or "", id_to_ent, id_to_args) if len(args) > 1 and args[1] != "$" else None
    refd = get_direction(parse_ref(args[2]) or "", id_to_ent, id_to_args) if len(args) > 2 and args[2] != "$" else None
    if not loc:
        loc = [0.0, 0.0, 0.0]
    return make_axis2placement3d_matrix(loc, axis, refd)

def get_axis2placement2d_matrix(sid, id_to_ent, id_to_args):
    if id_to_ent.get(sid) != "IFCAXIS2PLACEMENT2D":
        return None
    args = id_to_args.get(sid, [])
    # (Location2D as IFCCARTESIANPOINT, RefDirection as IFCDIRECTION optional)
    loc3 = get_cartesian_point(parse_ref(args[0]) or "", id_to_ent, id_to_args) if len(args) > 0 else None
    loc2 = [loc3[0], loc3[1]] if loc3 else [0.0, 0.0]
    refd = get_direction(parse_ref(args[1]) or "", id_to_ent, id_to_args) if len(args) > 1 and args[1] != "$" else None
    ref2 = [refd[0], refd[1]] if refd else None
    return make_axis2placement2d_matrix(loc2, ref2)

def get_local_placement_matrix(sid, id_to_ent, id_to_args, cache):
    """
    IFCLOCALPLACEMENT(PlacementRelTo, RelativePlacement)
    PlacementRelTo: another IfcObjectPlacement (often IfcLocalPlacement) or $
    RelativePlacement: IfcAxis2Placement3D
    Return world matrix by chaining relTo * relative
    """
    if sid in cache:
        return cache[sid]
    if id_to_ent.get(sid) != "IFCLOCALPLACEMENT":
        return None

    args = id_to_args.get(sid, [])
    rel_to = parse_ref(args[0]) if len(args) > 0 and args[0] != "$" else None
    rel_pl = parse_ref(args[1]) if len(args) > 1 and args[1] != "$" else None

    M_rel = get_local_placement_matrix(rel_to, id_to_ent, id_to_args, cache) if rel_to else mat4_identity()
    M_here = get_axis2placement3d_matrix(rel_pl, id_to_ent, id_to_args) if rel_pl else mat4_identity()

    M = mat4_mul(M_rel, M_here)
    cache[sid] = M
    return M


# -----------------------------
# Window/Door "overall dims" rectangle (works when no IfcExtrudedAreaSolid)
# -----------------------------

def get_object_placement_id_from_seed(seed_id, id_to_ent, id_to_args):
    """
    Best-effort: for most IfcProduct subtypes, ObjectPlacement is argument index 5.
    (0-based: args[5]) e.g. IfcWall/IfcWindow/IfcDoor/IfcSpace in IFC2x3/IFC4.
    """
    args = id_to_args.get(seed_id, [])
    if len(args) > 5:
        return parse_ref(args[5])
    return None

def get_overall_dims_for_opening(seed_id, seed_entity, id_to_args):
    """
    For IFCWINDOW and IFCDOOR, OverallHeight/OverallWidth are typically the last two numeric args:
      IfcWindow(..., OverallHeight, OverallWidth)
      IfcDoor  (..., OverallHeight, OverallWidth, OperationType, UserDefinedOperationType, ...)
    In IFC4, IfcDoor has a couple extra trailing attrs; exporters often keep height/width
    in the same slot (8,9) for common Revit-style exports.
    We implement a conservative parse:
      - try schema-typical indices (8,9) first
      - else, scan from the end and pick the last two numeric values (height then width)
        only if they are "reasonable" (positive and not tiny).
    Returns (height, width) or (None, None).
    """
    args = id_to_args.get(seed_id, [])
    height = width = None

    # Typical indices for IfcDoor/IfcWindow in many exports:
    if len(args) >= 10:
        h = parse_float(args[8])
        w = parse_float(args[9])
        if h and h > 0 and w and w > 0:
            return h, w

    # Fallback: last two positive floats
    nums = []
    for tok in reversed(args):
        v = parse_float(tok)
        if v is not None and v > 0:
            nums.append(v)
        if len(nums) >= 2:
            break
    if len(nums) >= 2:
        # reversed scan => nums[0]=last, nums[1]=second-last
        width = nums[0]
        height = nums[1]
    return height, width

def compute_opening_rectangle_world(seed_id, seed_entity, nodes_set, id_to_ent, id_to_args):
    """
    Compute 4 world points for DOOR/WINDOW using:
      - ObjectPlacement chain -> world transform
      - OverallWidth/OverallHeight -> rectangle extents in local X and local Z

    Assumes local origin (0,0,0) corresponds to the rectangle's lower-left-bottom corner
    in the opening plane. This matches many exports (and matched your Test.ifc for #22348/#21869).
    Returns dict with:
      origin_world, x_dir_world, z_dir_world, points_world (4 pts)
    """
    if not (seed_entity.startswith("IFCWINDOW") or seed_entity.startswith("IFCDOOR")):
        return {}

    H, W = get_overall_dims_for_opening(seed_id, seed_entity, id_to_args)
    if H is not None: H = float(H) * LEN_TO_M
    if W is not None: W = float(W) * LEN_TO_M
    if not H or not W:
        return {}

    # Object placement -> world matrix
    placement_cache = {}
    obj_place_id = get_object_placement_id_from_seed(seed_id, id_to_ent, id_to_args)
    if not obj_place_id or id_to_ent.get(obj_place_id) != "IFCLOCALPLACEMENT":
        return {}

    M_obj = get_local_placement_matrix(obj_place_id, id_to_ent, id_to_args, placement_cache) or mat4_identity()

    # World origin of local (0,0,0)
    O = mat4_apply(M_obj, [0.0, 0.0, 0.0, 1.0])

    # Local basis in world from matrix columns (X and Z)
    x_dir = [M_obj[0][0], M_obj[1][0], M_obj[2][0]]
    z_dir = [M_obj[0][2], M_obj[1][2], M_obj[2][2]]

    x_dir, _ = vec_norm(x_dir)
    z_dir, _ = vec_norm(z_dir)

    # 4 corners in world
    P0 = O
    P1 = [O[i] + W * x_dir[i] for i in range(3)]
    P3 = [O[i] + H * z_dir[i] for i in range(3)]
    P2 = [P1[i] + H * z_dir[i] for i in range(3)]

    return {
        "origin_world_m": O,
        "x_dir_world": x_dir,
        "z_dir_world": z_dir,
        "overall_width": W,
        "overall_height": H,
        "opening_rect_world_m": [P0, P1, P2, P3],
    }


# -----------------------------
# WALL polygon (Step 1 logic: centerline + thickness)
# -----------------------------



def get_product_representation_id_from_seed(seed_id, id_to_args):
    """Best-effort: Representation is usually argument index 6 for IfcProduct."""
    args = id_to_args.get(seed_id, [])
    if len(args) > 6:
        return parse_ref(args[6])
    return None

def get_wall_axis_polyline_local_points(rep_sid, id_to_ent, id_to_args):
    """Return Axis polyline points (local coords, already meters) or None."""
    if not rep_sid or id_to_ent.get(rep_sid) != 'IFCPRODUCTDEFINITIONSHAPE':
        return None
    rargs = id_to_args.get(rep_sid, [])
    if len(rargs) < 3:
        return None
    reps = parse_ref_list(rargs[2])
    for rsid in reps:
        if id_to_ent.get(rsid) != 'IFCSHAPEREPRESENTATION':
            continue
        sargs = id_to_args.get(rsid, [])
        if len(sargs) < 4:
            continue
        ident = unquote_step_string(sargs[1]) if len(sargs) > 1 else ''
        if ident.strip().lower() != 'axis':
            continue
        items = parse_ref_list(sargs[3])
        if not items:
            continue
        item = items[0]
        if id_to_ent.get(item) != 'IFCPOLYLINE':
            continue
        pargs = id_to_args.get(item, [])
        if not pargs:
            continue
        pt_ids = parse_ref_list(pargs[0])
        pts = []
        for pid in pt_ids:
            p = get_cartesian_point(pid, id_to_ent, id_to_args)
            if p:
                pts.append(p)
        if len(pts) >= 2:
            return pts
    return None

def compute_wall_axis_world_from_rep(seed_id, id_to_ent, id_to_args):
    """Return (S_world,E_world) for wall axis if Axis rep exists, else None."""
    placement_cache = {}
    obj_place_id = get_object_placement_id_from_seed(seed_id, id_to_ent, id_to_args)
    if not obj_place_id or id_to_ent.get(obj_place_id) != 'IFCLOCALPLACEMENT':
        return None
    M_obj = get_local_placement_matrix(obj_place_id, id_to_ent, id_to_args, placement_cache) or mat4_identity()

    rep_sid = get_product_representation_id_from_seed(seed_id, id_to_args)
    pts_local = get_wall_axis_polyline_local_points(rep_sid, id_to_ent, id_to_args)
    if not pts_local:
        return None

    p1 = pts_local[0]
    p2 = pts_local[-1]
    w1 = mat4_apply(M_obj, [p1[0], p1[1], p1[2], 1.0])
    w2 = mat4_apply(M_obj, [p2[0], p2[1], p2[2], 1.0])
    return (w1, w2)

def compute_wall_polygon_step1(seed_id, geom, id_to_ent, id_to_args):
    """
    Compute a 4-point wall polygon (meters) using "Step 1 logic":
      - Prefer the wall's explicit Axis polyline (IfcShapeRepresentation 'Axis') when available.
        This matches typical "centerline + thickness" expectations from many IFC exports.
      - Fallback: use ObjectPlacement origin + local X direction + computed length (legacy).

    Output:
      wall_polygon_step1_world_m: [P1,P2,P3,P4] where P1..P4 are 3D points [x,y,z] in meters.
    """
    L = geom.get("length")
    t = geom.get("thickness")
    H = geom.get("height") or geom.get("depth")

    if t is None:
        return {}
    t = float(t)

    # --- Preferred: axis polyline from representation ---
    axis_world = compute_wall_axis_world_from_rep(seed_id, id_to_ent, id_to_args)
    if axis_world:
        S, E = axis_world
        dx = E[0] - S[0]
        dy = E[1] - S[1]
        (u2, un) = vec_norm([dx, dy, 0.0])
        if un > 0:
            ux, uy = u2[0], u2[1]
            # perpendicular in XY
            nx, ny = (-uy, ux)
            ht = 0.5 * t
            P1 = [S[0] - ht*nx, S[1] - ht*ny, S[2]]
            P2 = [E[0] - ht*nx, E[1] - ht*ny, E[2]]
            P3 = [E[0] + ht*nx, E[1] + ht*ny, E[2]]
            P4 = [S[0] + ht*nx, S[1] + ht*ny, S[2]]

            out = {
                "starting_point_global_m": S,
                "ending_point_global_m": E,
                "u": [ux, uy, 0.0],
                "n": [nx, ny, 0.0],
                "wall_polygon_step1_world_m": [P1, P2, P3, P4],
                "wall_axis_source": "REPRESENTATION_AXIS",
            }
            if H is not None:
                out["height"] = float(H)
            return out

    # --- Fallback: placement-origin + local X + computed length ---
    if L is None:
        return {}
    L = float(L)

    placement_cache = {}
    obj_place_id = get_object_placement_id_from_seed(seed_id, id_to_ent, id_to_args)
    if not obj_place_id or id_to_ent.get(obj_place_id) != "IFCLOCALPLACEMENT":
        return {}
    M_obj = get_local_placement_matrix(obj_place_id, id_to_ent, id_to_args, placement_cache) or mat4_identity()

    # World origin of local (0,0,0)
    S = mat4_apply(M_obj, [0.0, 0.0, 0.0, 1.0])

    Xd = [M_obj[0][0], M_obj[1][0], M_obj[2][0]]
    u, un = vec_norm(Xd)
    if un == 0:
        return {}

    E = [S[0] + L*u[0], S[1] + L*u[1], S[2] + L*u[2]]

    # perpendicular in XY (fallback assumes wall mostly horizontal in XY)
    (u2, un2) = vec_norm([u[0], u[1], 0.0])
    if un2 == 0:
        return {}
    ux, uy = u2[0], u2[1]
    nx, ny = (-uy, ux)

    ht = 0.5 * t
    P1 = [S[0] - ht*nx, S[1] - ht*ny, S[2]]
    P2 = [E[0] - ht*nx, E[1] - ht*ny, E[2]]
    P3 = [E[0] + ht*nx, E[1] + ht*ny, E[2]]
    P4 = [S[0] + ht*nx, S[1] + ht*ny, S[2]]

    out = {
        "starting_point_global_m": S,
        "ending_point_global_m": E,
        "u": [ux, uy, 0.0],
        "n": [nx, ny, 0.0],
        "wall_polygon_step1_world_m": [P1, P2, P3, P4],
        "wall_axis_source": "PLACEMENT_X_FALLBACK",
    }
    if H is not None:
        out["height"] = float(H)
    return out

# -----------------------------
# Geometry extraction (ExtrudedAreaSolid + profiles)
# -----------------------------

def polygon_area_2d(pts):
    # pts = [(x,y),...], closed or open
    if len(pts) < 3:
        return None
    area = 0.0
    for i in range(len(pts)):
        x1,y1 = pts[i]
        x2,y2 = pts[(i+1) % len(pts)]
        area += x1*y2 - x2*y1
    return abs(area) * 0.5

def extract_profile_points_2d(profile_id, id_to_ent, id_to_args):
    """
    Returns:
      dict with keys:
        type: "RECTANGLE" or "POLYLINE" or "UNKNOWN"
        points_2d: list of (x,y) in profile local space if available
        x_dim, y_dim (for rectangle)
        profile_matrix (Axis2Placement2D if exists) else identity in XY
    """
    ent = id_to_ent.get(profile_id, "")
    args = id_to_args.get(profile_id, [])

    # Default
    profile_matrix = mat4_identity()

    # IFCRECTANGLEPROFILEDEF(ProfileType, ProfileName, Position, XDim, YDim)
    if ent == "IFCRECTANGLEPROFILEDEF":
        # Position may be args[2], XDim args[3], YDim args[4]
        pos_id = parse_ref(args[2]) if len(args) > 2 and args[2] != "$" else None
        if pos_id:
            M2 = get_axis2placement2d_matrix(pos_id, id_to_ent, id_to_args)
            if M2:
                profile_matrix = M2
        x_dim = parse_float(args[3]) if len(args) > 3 else None
        if x_dim is not None: x_dim = float(x_dim) * LEN_TO_M
        y_dim = parse_float(args[4]) if len(args) > 4 else None
        if y_dim is not None: y_dim = float(y_dim) * LEN_TO_M
        if x_dim is None or y_dim is None:
            return {"type":"RECTANGLE", "points_2d": None, "x_dim": x_dim, "y_dim": y_dim, "profile_matrix": profile_matrix}

        # rectangle corners centered at origin in profile local coordinates in IFC
        # Many exporters define rectangle centered at (0,0). We'll use that standard.
        hx = x_dim * 0.5
        hy = y_dim * 0.5
        pts = [(-hx,-hy), (hx,-hy), (hx,hy), (-hx,hy)]
        return {"type":"RECTANGLE", "points_2d": pts, "x_dim": x_dim, "y_dim": y_dim, "profile_matrix": profile_matrix}

    # IFCARBITRARYCLOSEDPROFILEDEF(ProfileType, ProfileName, OuterCurve)
    if ent == "IFCARBITRARYCLOSEDPROFILEDEF":
        # OuterCurve often IfcPolyline or IfcCompositeCurve; we handle polyline.
        outer = parse_ref(args[2]) if len(args) > 2 and args[2] != "$" else None
        if outer and id_to_ent.get(outer) == "IFCPOLYLINE":
            poly_args = id_to_args.get(outer, [])
            pts_ids = parse_ref_list(poly_args[0]) if poly_args else []
            pts2 = []
            for pid in pts_ids:
                p = get_cartesian_point(pid, id_to_ent, id_to_args)
                if p:
                    pts2.append((p[0], p[1]))
            if len(pts2) >= 3:
                return {"type":"POLYLINE", "points_2d": pts2, "x_dim": None, "y_dim": None, "profile_matrix": profile_matrix}
        return {"type":"UNKNOWN", "points_2d": None, "x_dim": None, "y_dim": None, "profile_matrix": profile_matrix}

    # Other profiles not implemented
    return {"type":"UNKNOWN", "points_2d": None, "x_dim": None, "y_dim": None, "profile_matrix": profile_matrix}

def find_first_extruded_solid(nodes_set, id_to_ent):
    """
    Find an IfcExtrudedAreaSolid within traced nodes.
    For now, choose the first one (lowest StepId numeric).
    """
    solids = [sid for sid in nodes_set if id_to_ent.get(sid) == "IFCEXTRUDEDAREASOLID"]
    if not solids:
        return None
    solids.sort(key=lambda x: int(x[1:]))
    return solids[0]

def compute_extruded_geometry(seed_id, seed_entity, nodes_set, id_to_ent, id_to_args):
    """
    Compute:
      - footprint_world (list of 3D points)
      - height (extrusion depth)
      - area, volume (computed)
      - dims: x_dim, y_dim, depth
      - width/length/thickness mapping by entity category
    """
    result = {}

    # --- Multi-storey support (storey elevation)
    # We can lift local (often z=0) footprints/openings to the building-storey base elevation.
    # Mapping:
    #   - IFCBUILDINGSTOREY.Elevation (in IFC length units)
    #   - IFCRELCONTAINEDINSPATIALSTRUCTURE / IFCRELAGGREGATES linking spaces to storeys

    solid_id = find_first_extruded_solid(nodes_set, id_to_ent)
    if not solid_id:
        return result  # cannot compute

    s_args = id_to_args.get(solid_id, [])
    # IFCEXTRUDEDAREASOLID(SweptArea, Position, ExtrudedDirection, Depth)
    swept_area = parse_ref(s_args[0]) if len(s_args) > 0 else None
    pos3d = parse_ref(s_args[1]) if len(s_args) > 1 and s_args[1] != "$" else None
    # extruded direction ignored for footprint; used for height direction. Depth is scalar.
    depth = parse_float(s_args[3]) if len(s_args) > 3 else None
    if depth is not None: depth = float(depth) * LEN_TO_M  # -> meters

    if depth is not None:
        result["height"] = depth

    # Profile points (2D) and profile matrix (2D placement)
    if not swept_area:
        return result

    prof = extract_profile_points_2d(swept_area, id_to_ent, id_to_args)
    if prof.get("x_dim") is not None:
        result["x_dim"] = prof["x_dim"]
    if prof.get("y_dim") is not None:
        result["y_dim"] = prof["y_dim"]
    if depth is not None:
        result["depth"] = depth

    pts2 = prof.get("points_2d")
    if not pts2:
        return result  # can't compute footprint

    # Build transforms:
    # object placement matrix (from seed ObjectPlacement)
    placement_cache = {}
    obj_place_id = None

    # For IfcProduct-like entities, ObjectPlacement is typically arg[5] in IfcSpace/IfcWall/etc.
    # IFCSPACE(GlobalId, OwnerHistory, Name, Description, ObjectType, ObjectPlacement, Representation, LongName, CompositionType, ...)
    # We'll try common slot 5.
    seed_args = id_to_args.get(seed_id, [])
    if len(seed_args) > 5:
        obj_place_id = parse_ref(seed_args[5])

    M_obj = mat4_identity()
    if obj_place_id and id_to_ent.get(obj_place_id) == "IFCLOCALPLACEMENT":
        M_obj = get_local_placement_matrix(obj_place_id, id_to_ent, id_to_args, placement_cache) or mat4_identity()

    # solid position matrix
    M_solid = get_axis2placement3d_matrix(pos3d, id_to_ent, id_to_args) if pos3d else mat4_identity()

    # profile position (2D) embedded matrix
    M_prof = prof.get("profile_matrix") or mat4_identity()

    # total matrix: object * solid * profile
    M_total = mat4_mul(mat4_mul(M_obj, M_solid), M_prof)

    # footprint points in world (z=0 plane of profile)
    footprint_world = []
    for (x,y) in pts2:
        pw = mat4_apply(M_total, [x, y, 0.0, 1.0])
        footprint_world.append(pw)

    result["footprint_world_m"] = footprint_world

    # computed area (in profile local coords)
    area2 = polygon_area_2d(pts2)
    if area2 is not None:
        result["area_computed"] = area2
        if depth is not None:
            result["volume_computed"] = area2 * depth

    # Map thickness/width/length (best-effort by entity family)
    x_dim = prof.get("x_dim")
    y_dim = prof.get("y_dim")

    def set_if(k, v):
        if v is not None:
            result[k] = v

    if x_dim is not None and y_dim is not None:
        a = min(x_dim, y_dim)
        b = max(x_dim, y_dim)

        if seed_entity.startswith("IFCSPACE"):
            # for spaces: width/length from rectangle dims; thickness not relevant
            set_if("width", a)
            set_if("length", b)

        elif seed_entity.startswith("IFCWALL") or seed_entity.startswith("IFCCURTAINWALL"):
            # wall: thickness ~ smaller, length ~ larger, height=depth
            set_if("thickness", a)
            set_if("length", b)

        elif seed_entity.startswith("IFCSLAB") or seed_entity.startswith("IFCROOF") or seed_entity.startswith("IFCCOVERING"):
            # slab/roof/covering: length/width from x/y, thickness from depth
            set_if("width", a)
            set_if("length", b)
            set_if("thickness", depth)

        elif seed_entity.startswith("IFCDOOR") or seed_entity.startswith("IFCWINDOW"):
            # door/window: assume x=width, y=height, depth=thickness (common)
            set_if("width", x_dim)
            set_if("height_opening", y_dim)
            set_if("thickness", depth)

    return result

# -----------------------------
# Quantity extraction (Area/Volume/Height if present)
# -----------------------------

def extract_quantities(nodes_set, id_to_ent, id_to_args):
    """
    Best-effort:
      - find IfcQuantityArea / IfcQuantityVolume / IfcQuantityLength
      - pull Name + value (typically last arg)
    IMPORTANT: IFC stores quantity values in the IFC length unit. We convert to meters-based units:
      - Length  -> * LEN_TO_M
      - Area    -> * (LEN_TO_M ** 2)
      - Volume  -> * (LEN_TO_M ** 3)
    """
    out = {}
    for sid in nodes_set:
        ent = id_to_ent.get(sid, "")
        if ent not in {"IFCQUANTITYAREA", "IFCQUANTITYVOLUME", "IFCQUANTITYLENGTH"}:
            continue
        args = id_to_args.get(sid, [])
        qname = unquote_step_string(args[0]) if len(args) > 0 else ""

        # find first numeric token in args (from the end)
        qval = None
        for tok in reversed(args):
            v = parse_float(tok)
            if v is not None:
                qval = float(v)
                break
        if not qname or qval is None:
            continue

        # scale to meters-based units
        if ent == "IFCQUANTITYLENGTH":
            qval = qval * LEN_TO_M
        elif ent == "IFCQUANTITYAREA":
            qval = qval * (LEN_TO_M ** 2)
        elif ent == "IFCQUANTITYVOLUME":
            qval = qval * (LEN_TO_M ** 3)

        key = qname.strip().lower()
        out[key] = qval

        # also map common targets (normalized keys)
        if ent == "IFCQUANTITYAREA" and "area" not in out:
            out["area"] = qval
        if ent == "IFCQUANTITYVOLUME" and "volume" not in out:
            out["volume"] = qval
        if ent == "IFCQUANTITYLENGTH":
            if "height" in key:
                out["height"] = qval
            if "length" in key and "length" not in out:
                out["length"] = qval
            if "width" in key and "width" not in out:
                out["width"] = qval
            if "thickness" in key and "thickness" not in out:
                out["thickness"] = qval
    return out

# -----------------------------
# Seed category logic
# -----------------------------

def category_from_entity(ent: str):
    if ent.startswith("IFCSPACE"): return "SPACE"
    if ent.startswith("IFCWALL") or ent.startswith("IFCCURTAINWALL"): return "WALL"
    if ent.startswith("IFCWINDOW"): return "WINDOW"
    if ent.startswith("IFCDOOR"): return "DOOR"
    if ent.startswith("IFCROOF"): return "ROOF"
    if ent.startswith("IFCSLAB"): return "SLAB"
    if ent.startswith("IFCCOVERING"): return "COVERING"
    return "OTHER"

# -----------------------------
# Main Step 3 per seed
# -----------------------------

def step3_for_seed(seed_obj, traced_nodes, id_to_ent, id_to_args):
    seed_id = seed_obj["StepId"]
    seed_entity = seed_obj["Entity"].upper()
    nodes_set = set((n.get('StepId') if isinstance(n, dict) else n) for n in traced_nodes if n)

    out = {
        "seed": seed_obj,
        "category": category_from_entity(seed_entity),
        "missing": [],  # reserved if you want to record missing things later
    }



    # Build storey elevation map (within traced closure) and resolve containing storey when possible.
    storey_elev_map = build_storey_elevation_map(nodes_set, id_to_ent, id_to_args)
    storey_id = None
    storey_elev_m = None

    # Entities that commonly participate in containment within a BuildingStorey
    needs_storey = (
        seed_entity.startswith("IFCSPACE")
        or seed_entity.startswith("IFCWALL")
        or seed_entity.startswith("IFCCURTAINWALL")
        or seed_entity.startswith("IFCSLAB")
        or seed_entity.startswith("IFCROOF")
        or seed_entity.startswith("IFCWINDOW")
        or seed_entity.startswith("IFCDOOR")
        or seed_entity.startswith("IFCCOVERING")
    )

    if needs_storey:
        # Prefer storey linkage already captured in Step 1 seeds (if present)
        storey_id = seed_obj.get("StoreyStepId") or seed_obj.get("storey_step_id")
        if storey_id and isinstance(storey_id, str) and not storey_id.startswith("#"):
            storey_id = f"#{storey_id}"  # defensive

        if not storey_id:
            if seed_entity.startswith("IFCSPACE"):
                storey_id = find_storey_for_space(seed_id, nodes_set, id_to_ent, id_to_args)
            else:
                storey_id = find_storey_for_element(seed_id, nodes_set, id_to_ent, id_to_args)

        if storey_id and storey_id in storey_elev_map:
            storey_elev_m = storey_elev_map[storey_id]

        # surface this on the seed for downstream steps (Step 4/5 use it for grouping)
        if storey_id:
            out["seed"]["StoreyStepId"] = storey_id
        if storey_elev_m is not None:
            out["seed"]["StoreyElevation_m"] = storey_elev_m

    # Quantities (if exist)
    q = extract_quantities(nodes_set, id_to_ent, id_to_args)
    if q:
        out["quantities_from_ifc"] = q

    # Geometry/Dimensions:
    # - WALL: compute a 4-point polygon (Step 1 centerline+thickness) and store it.
    if seed_entity.startswith("IFCWALL") or seed_entity.startswith("IFCCURTAINWALL"):
        geom = compute_extruded_geometry(seed_id, seed_entity, nodes_set, id_to_ent, id_to_args)
        if geom:
            wall_step1 = compute_wall_polygon_step1(seed_id, geom, id_to_ent, id_to_args)
            if wall_step1:
                geom.update(wall_step1)
            geom.pop("footprint_world_m", None)
            out["geometry"] = geom
        return out


    # DOOR/WINDOW: even when there is no IfcExtrudedAreaSolid (common: mapped brep),
    # we can still compute a useful 4-corner opening rectangle in world coordinates
    # using OverallWidth/OverallHeight + ObjectPlacement basis.
    if seed_entity.startswith("IFCWINDOW") or seed_entity.startswith("IFCDOOR"):
        rect = compute_opening_rectangle_world(seed_id, seed_entity, nodes_set, id_to_ent, id_to_args)
        if rect:
            out.setdefault("geometry", {}).update(rect)

    # For SPACE and other entities: compute full geometry if possible (ExtrudedAreaSolid patterns)
    geom = compute_extruded_geometry(seed_id, seed_entity, nodes_set, id_to_ent, id_to_args)
    if geom:
        # If this is a SPACE and its footprint is effectively at z≈0, lift it to storey elevation.
        if seed_entity.startswith("IFCSPACE") and storey_elev_m is not None and "footprint_world_m" in geom:
            pts = geom.get("footprint_world_m") or []
            zs = [p[2] for p in pts if isinstance(p, (list, tuple)) and len(p) >= 3 and isinstance(p[2], (int, float))]
            if zs:
                zmin, zmax = min(zs), max(zs)
                # Only lift when footprint is essentially flat at ~0 to avoid double-adding elevation.
                if abs(zmin) < 1e-6 and abs(zmax) < 1e-6 and abs(storey_elev_m) > 1e-9:
                    geom["footprint_world_m"] = _lift_points_z(pts, storey_elev_m)
                    geom["footprint_lifted_by_storey_elevation_m"] = storey_elev_m
        out.setdefault("geometry", {}).update(geom)


    # Final “best” values: prefer IFC quantities if present; else computed
    best = {}
    # area
    if "quantities_from_ifc" in out and "area" in out["quantities_from_ifc"]:
        best["area"] = out["quantities_from_ifc"]["area"]
        best["area_source"] = "IFC"
    elif "geometry" in out and "area_computed" in out["geometry"]:
        best["area"] = out["geometry"]["area_computed"]
        best["area_source"] = "COMPUTED"

    # volume
    if "quantities_from_ifc" in out and "volume" in out["quantities_from_ifc"]:
        best["volume"] = out["quantities_from_ifc"]["volume"]
        best["volume_source"] = "IFC"
    elif "geometry" in out and "volume_computed" in out["geometry"]:
        best["volume"] = out["geometry"]["volume_computed"]
        best["volume_source"] = "COMPUTED"

    # height
    if "quantities_from_ifc" in out and "height" in out["quantities_from_ifc"]:
        best["height"] = out["quantities_from_ifc"]["height"]
        best["height_source"] = "IFC"
    elif "geometry" in out and "height" in out["geometry"]:
        best["height"] = out["geometry"]["height"]
        best["height_source"] = "COMPUTED"
    elif "geometry" in out and "overall_height" in out["geometry"]:
        best["height"] = out["geometry"]["overall_height"]
        best["height_source"] = "ATTR"


    # thickness/width/length
    for k in ["thickness", "width", "length"]:
        if "quantities_from_ifc" in out and k in out["quantities_from_ifc"]:
            best[k] = out["quantities_from_ifc"][k]
            best[f"{k}_source"] = "IFC"
        elif "geometry" in out and k in out["geometry"]:
            best[k] = out["geometry"][k]
            best[f"{k}_source"] = "COMPUTED"
        elif k == "width" and "geometry" in out and "overall_width" in out["geometry"]:
            best["width"] = out["geometry"]["overall_width"]
            best["width_source"] = "ATTR"


    if best:
        out["best"] = best

    return out

# -----------------------------
# CLI
# -----------------------------

def main():
    ap = argparse.ArgumentParser(description="IFC Step 3: filter geometry + finish calculations (basic Python only).")
    ap.add_argument("ifc_path", help="Path to IFC file (.ifc)")
    ap.add_argument("step2_json", help="Path to Step 2 traced JSON (must contain results[seedId].nodes)")
    ap.add_argument("units_json", nargs="?", default="ifc_units.json", help="Units JSON from Step 1 (default: ifc_units.json)")
    ap.add_argument("--out", default="step3_geometry.json", help="Output JSON path")
    ap.add_argument("--seed", default="", help='Optional single seed StepId to process, e.g. "#62"')
    ap.add_argument("--print-json", action="store_true", help="Print full output JSON at end")
    args = ap.parse_args()

    ifc_text = Path(args.ifc_path).read_text(encoding="utf-8", errors="replace")
    step2 = json.loads(Path(args.step2_json).read_text(encoding="utf-8"))
    load_len_to_m(args.units_json)

    id_to_ent, id_to_args = build_ifc_maps(ifc_text)

    results = {}
    step2_results = step2.get("results", {})

    # Optional single-seed filter
    if args.seed.strip():
        sid = args.seed.strip()
        step2_results = {sid: step2_results.get(sid)} if sid in step2_results else {}

    for seed_id, obj in step2_results.items():
        if not obj:
            continue
        seed = obj.get("seed")
        nodes = obj.get("nodes", [])
        if not seed or not nodes:
            continue

        results[seed_id] = step3_for_seed(seed, nodes, id_to_ent, id_to_args)

    out_obj = {
        "meta": {
            "ifc_file": str(args.ifc_path),
            "step2_file": str(args.step2_json),
            "seed_count": len(results),
            "notes": [
                "Step 3 finishes calculations where possible (area/volume/height/width/length/thickness).",
                "If data is not available or not computable with supported patterns, fields are omitted.",
                "Footprint coordinates require ExtrudedAreaSolid + supported profile; otherwise omitted.",
                "Walls: geometry includes a 4-point centerline-based polygon (Step 1 logic).",
            ]
        },
        "results": results
    }

    out_path = Path(args.out)
    out_obj = round_floats(out_obj)

    out_path.write_text(json.dumps(out_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote Step 3 output to: {out_path}")

    if args.print_json:
        print("\n--- JSON RESULT (END) ---")
        print(json.dumps(out_obj, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
