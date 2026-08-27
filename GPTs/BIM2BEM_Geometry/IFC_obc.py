#!/usr/bin/env python3
"""IFC_obc.py  (Step 5)

OBC assignment + wall splitting + horizontal slab exposure pairing.

Input:
  step4_idf_geometry.json (from Step 4)
Output:
  step5_obc.json

Key behaviors (v8_grid_like):
- NO unit conversion (Step4 geometry already meters).
- Walls:
    * Derives gap_min from min IFCWALL width (fallback 0.101 m).
    * Splits axis-aligned walls into pieces based on overlaps.
    * Overlapped pieces -> OBC=Surface with mate name.
    * Leftover pieces -> OBC=Adiabatic.
    * Non-axis-aligned walls -> OBC=Outdoors.
- Horizontal surfaces:
    * Rebuilds floors/ceilings/roofs using an XY grid decomposition per storey.
    * Uses storey adjacency (k -> k+1) and slab-thickness / z checks.
    * Produces partial interior pairing and partial exterior roofs / exposed floors:
        - Lowest known storey floors -> Ground
        - Interior ceiling (storey k) <-> floor (storey k+1) -> Surface pairs
        - Top surfaces not covered by any zone above -> Roof (Outdoors)
        - Floors not covered by any zone below (and not lowest storey) -> Floor (Outdoors)
- Fenestration host assignment:
    * Assigns windows/doors to nearest containing wall piece in same storey.
    * Uses a thickness-aware host plane tolerance:
        effective tolerance = max(--host_plane_tol, maximum IFC wall thickness)
      so openings placed on a wall center/reference plane can still match the generated wall face.
    * Removes interior fenestration if host wall OBC=Surface.
- Cleanup:
    * Removes duplicate closure vertex, consecutive duplicates, collinear points.
    * Snaps horizontal Z to mean Z.
    * Adds ConstructionHint.
    * Recursively rounds all numbers to 4 decimals.

Stdlib only.
"""

import argparse
import json
import re
from collections import defaultdict


# -------------------------
# Rounding helpers
# -------------------------

def round4(x):
    if x is None or isinstance(x, bool):
        return x
    if isinstance(x, int):
        # keep json numeric consistency with float formatting rule
        return float(f"{x:.4f}")
    if isinstance(x, float):
        return float(f"{x:.4f}")
    return x


def round_json(obj):
    if isinstance(obj, dict):
        return {k: round_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [round_json(v) for v in obj]
    return round4(obj)


# -------------------------
# Naming helpers
# -------------------------

def safe_name(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    s = s.replace(" ", "_")
    s = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in s)
    while "__" in s:
        s = s.replace("__", "_")
    return s


def parse_space_index(name: str):
    try:
        return int(str(name).strip())
    except Exception:
        return None


_LEVEL_PREFIX_RE = re.compile(r"^\s*(L\d+)[_\-\s]+(.+?)\s*$", re.IGNORECASE)


def split_leading_level_prefix(value: str):
    """Return (level_token, suffix) for values like L1_Unit_5; otherwise None."""
    s = (value or "").strip()
    m = _LEVEL_PREFIX_RE.match(s)
    if m and m.group(2).strip():
        return m.group(1).strip(), m.group(2).strip()
    return None


def strip_leading_level_prefix(value: str) -> str:
    """Remove a leading level token like L1_, L2-, or L10 from a name/tag.

    Examples:
      L1_Unit_5  -> Unit_5
      L10 Unit 5 -> Unit 5
    """
    split = split_leading_level_prefix(value)
    if split:
        return split[1]
    return (value or "").strip()


def starts_with_level_prefix(value: str) -> bool:
    return split_leading_level_prefix(value) is not None


def _same_level_token(a: str, b: str) -> bool:
    return safe_name(a or "").lower() == safe_name(b or "").lower()


def space_naming_target(seed: dict, space_step_id: str, storey_label: str = "") -> str:
    """Choose the stable target part used after '<StoreyLabel>_Zone_'.

    Priority:
    1) Name / Tag / SpaceTag / LongName with a leading L<number> prefix that
       matches the actual StoreyLabel. The matching prefix is removed.
       Example: StoreyLabel=L2 and SpaceTag=L2_Unit_1 -> Unit_1.
    2) Any Name / Tag / SpaceTag / LongName with a leading L<number> prefix.
       The prefix is removed.
       Example: StoreyLabel=L2 and Name=L1_Unit_1 -> Unit_1.
    3) Numeric Name / Tag / SpaceTag / LongName -> integer label.
    4) First non-empty Name / Tag / SpaceTag / LongName.
    5) Space StepId fallback.
    """
    if not isinstance(seed, dict):
        seed = {}

    candidates = []
    for key in ("Name", "Tag", "SpaceTag", "LongName"):
        val = seed.get(key)
        if val not in (None, ""):
            s = str(val).strip()
            if s and s not in candidates:
                candidates.append(s)

    # Prefer the candidate whose leading L<number> matches the actual storey.
    for s in candidates:
        split = split_leading_level_prefix(s)
        if split and _same_level_token(split[0], storey_label):
            return split[1]

    # Otherwise accept any leading L<number> candidate and remove its old level prefix.
    for s in candidates:
        split = split_leading_level_prefix(s)
        if split:
            return split[1]

    for s in candidates:
        idx = parse_space_index(s)
        if idx is not None:
            return str(idx)

    for s in candidates:
        cleaned = strip_leading_level_prefix(s)
        if cleaned:
            return cleaned

    return safe_name(space_step_id) or str(space_step_id).replace("#", "_")


def build_zone_name(storey_label: str, seed: dict, space_step_id: str) -> str:
    storey = safe_name(storey_label or "UNK") or "UNK"
    target = space_naming_target(seed, space_step_id, storey)
    target_safe = safe_name(target) or safe_name(space_step_id) or str(space_step_id).replace("#", "_")
    return f"{storey}_Zone_{target_safe}"



# -------------------------
# Host property helpers (from Step 4 annotations)
# -------------------------

def _get_host_props(surface: dict, key: str):
    try:
        h = surface.get(key) or {}
        if not isinstance(h, dict):
            return {}
        p = h.get("props_m") or {}
        return p if isinstance(p, dict) else {}
    except Exception:
        return {}

def wall_thickness_m(surface: dict, default: float):
    p = _get_host_props(surface, "host_ifc_wall")
    for k in ("thickness", "width"):
        v = p.get(k)
        if isinstance(v, (int, float)) and float(v) > 0:
            return float(v)
    return float(default)

def slab_thickness_m_from_host(host: dict, default: float):
    try:
        if not isinstance(host, dict):
            return float(default)
        p = host.get("props_m") or {}
        if not isinstance(p, dict):
            return float(default)
        for k in ("thickness", "depth"):
            v = p.get(k)
            if isinstance(v, (int, float)) and float(v) > 0:
                return float(v)
    except Exception:
        pass
    return float(default)

def choose_pair_gap(a_thk: float, b_thk: float, fallback: float):
    # expected plane-to-plane gap for two offset walls
    try:
        ta = float(a_thk) if a_thk is not None else None
        tb = float(b_thk) if b_thk is not None else None
        if ta and tb and ta > 0 and tb > 0:
            return 0.5 * (ta + tb)
    except Exception:
        pass
    return float(fallback)
# -------------------------
# Geometry helpers (axis-aligned)
# -------------------------

def axis_fixed(verts, tol=1e-4):
    xs = [p[0] for p in verts]
    ys = [p[1] for p in verts]
    zs = [p[2] for p in verts]
    fx = max(xs) - min(xs) <= tol
    fy = max(ys) - min(ys) <= tol
    fz = max(zs) - min(zs) <= tol
    if fx and not fy and not fz:
        return "X", sum(xs) / len(xs)
    if fy and not fx and not fz:
        return "Y", sum(ys) / len(ys)
    if fz and not fx and not fy:
        return "Z", sum(zs) / len(zs)

    # fallback: pick smallest range if within tol
    ranges = [
        ("X", max(xs) - min(xs), sum(xs) / len(xs)),
        ("Y", max(ys) - min(ys), sum(ys) / len(ys)),
        ("Z", max(zs) - min(zs), sum(zs) / len(zs)),
    ]
    ranges.sort(key=lambda t: t[1])
    if ranges[0][1] <= tol:
        return ranges[0][0], ranges[0][2]
    return None, None


def intervals_for_axis_plane(axis, verts):
    xs = [p[0] for p in verts]
    ys = [p[1] for p in verts]
    zs = [p[2] for p in verts]
    if axis == "X":
        return (min(ys), max(ys), min(zs), max(zs))  # u=Y, v=Z
    if axis == "Y":
        return (min(xs), max(xs), min(zs), max(zs))  # u=X, v=Z
    raise ValueError("axis must be X or Y")


def build_quad_from_cell(axis, fixed, u0, u1, v0, v1):
    if axis == "X":
        x = fixed
        return [[x, u1, v0], [x, u0, v0], [x, u0, v1], [x, u1, v1]]
    if axis == "Y":
        y = fixed
        return [[u0, y, v0], [u1, y, v0], [u1, y, v1], [u0, y, v1]]
    raise ValueError("axis must be X or Y")


def overlap_1d(a0, a1, b0, b1, tol=1e-9):
    lo = max(a0, b0)
    hi = min(a1, b1)
    if hi - lo <= tol:
        return None
    return (lo, hi)


def cell_inside_rect(cell, rect, tol=1e-9):
    u0, u1, v0, v1 = cell
    return (
        u0 >= rect[0] - tol
        and u1 <= rect[1] + tol
        and v0 >= rect[2] - tol
        and v1 <= rect[3] + tol
    )


def rect_contains(rect_big, rect_small, tol=1e-6):
    return (
        rect_small[0] >= rect_big[0] - tol
        and rect_small[1] <= rect_big[1] + tol
        and rect_small[2] >= rect_big[2] - tol
        and rect_small[3] <= rect_big[3] + tol
    )


# -------------------------
# Bounding boxes / areas
# -------------------------

def bbox_xy(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


# -------------------------
# Thickness extraction
# -------------------------

def extract_min_thicknesses(results):
    wall_widths = []
    slab_thks = []
    storey_elev = {}
    for sid, rec in results.items():
        if not isinstance(rec, dict):
            continue
        seed = rec.get("seed", {}) or {}
        ent = (seed.get("Entity") or "").upper()
        q = rec.get("quantities_from_ifc") or {}
        if ent == "IFCWALL":
            w = q.get("width")
            if isinstance(w, (int, float)) and w > 0:
                wall_widths.append(float(w))
        elif ent == "IFCSLAB":
            d = q.get("depth") if isinstance(q.get("depth"), (int, float)) else q.get("thickness")
            if isinstance(d, (int, float)) and d > 0:
                slab_thks.append(float(d))
        elif ent == "IFCBUILDINGSTOREY":
            elev = seed.get("Elevation_m", q.get("elevation"))
            if isinstance(elev, (int, float)):
                storey_elev[sid] = float(elev)
    return (
        min(wall_widths) if wall_widths else None,
        min(slab_thks) if slab_thks else None,
        storey_elev,
    )


# -------------------------
# Surface cleanup
# -------------------------

def almost_equal(a, b, tol=1e-6):
    return abs(a - b) <= tol


def pt_equal(p, q, tol=1e-6):
    return almost_equal(p[0], q[0], tol) and almost_equal(p[1], q[1], tol) and almost_equal(p[2], q[2], tol)


def remove_duplicate_closure(verts, tol=1e-6):
    if not verts or len(verts) < 4:
        return verts
    if pt_equal(verts[0], verts[-1], tol=tol):
        return verts[:-1]
    return verts


def remove_consecutive_duplicates(verts, tol=1e-6):
    if not verts:
        return verts
    out = [verts[0]]
    for p in verts[1:]:
        if not pt_equal(p, out[-1], tol=tol):
            out.append(p)
    return out


def snap_horizontal_z(verts, tol=1e-6):
    if not verts:
        return verts
    zs = [p[2] for p in verts]
    if max(zs) - min(zs) <= tol:
        z = sum(zs) / len(zs)
        return [[p[0], p[1], z] for p in verts]
    return verts


def is_collinear_xy(a, b, c, tol=1e-10):
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) <= tol


def remove_collinear_xy(verts, tol=1e-10):
    if not verts or len(verts) < 4:
        return verts
    out = []
    n = len(verts)
    for i in range(n):
        a = verts[(i - 1) % n]
        b = verts[i]
        c = verts[(i + 1) % n]
        if is_collinear_xy(a, b, c, tol=tol):
            continue
        out.append(b)
    return out if len(out) >= 3 else verts


def cleanup_surface_vertices(surf: dict, kind: str):
    verts = [list(p) for p in (surf.get("vertices_3d") or [])]
    verts = remove_duplicate_closure(verts, tol=1e-6)
    verts = remove_consecutive_duplicates(verts, tol=1e-6)
    if kind in ("floor", "ceiling", "roof"):
        verts = snap_horizontal_z(verts, tol=1e-6)
    verts = remove_collinear_xy(verts, tol=1e-10)
    surf["vertices_3d"] = verts


def set_construction_hint(surface_kind: str, obc: str):
    obc = (obc or "").strip().lower()
    if surface_kind == "wall":
        if obc in ("surface", "adiabatic"):
            return "InteriorWall"
        if obc == "outdoors":
            return "ExteriorWall"
        return "Wall"
    if surface_kind == "floor":
        if obc in ("surface", "adiabatic"):
            return "InteriorFloor"
        if obc == "outdoors":
            return "ExteriorFloor"
        if obc == "ground":
            return "GroundFloor"
        return "Floor"
    if surface_kind == "ceiling":
        if obc in ("surface", "adiabatic"):
            return "InteriorCeiling"
        if obc == "outdoors":
            return "ExteriorCeiling"
        return "Ceiling"
    if surface_kind == "roof":
        if obc == "outdoors":
            return "ExteriorRoof"
        if obc in ("surface", "adiabatic"):
            return "InteriorRoof"
        return "Roof"
    return None


# -------------------------
# 2D point-in-polygon (for slab grid ownership)
# -------------------------

def _pt_on_seg_xy(px, py, ax, ay, bx, by, tol=1e-9):
    if px < min(ax, bx) - tol or px > max(ax, bx) + tol or py < min(ay, by) - tol or py > max(ay, by) + tol:
        return False
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > tol * (abs(bx - ax) + abs(by - ay) + 1.0):
        return False
    return True


def point_in_poly_xy(px, py, poly_xy, tol=1e-9):
    if not poly_xy or len(poly_xy) < 3:
        return False
    inside = False
    n = len(poly_xy)
    for i in range(n):
        ax, ay = poly_xy[i]
        bx, by = poly_xy[(i + 1) % n]

        if _pt_on_seg_xy(px, py, ax, ay, bx, by, tol=tol):
            return True

        cond = (ay > py) != (by > py)
        if cond:
            xint = ax + (py - ay) * (bx - ax) / (by - ay)
            if xint > px:
                inside = not inside
    return inside


def unique_sorted_merge(vals, tol=1e-6):
    vals = sorted(float(v) for v in vals)
    out = []
    for v in vals:
        if not out:
            out.append(v)
        elif abs(v - out[-1]) <= tol:
            out[-1] = (out[-1] + v) / 2.0
        else:
            out.append(v)
    return out


def merge_rects(rects, tol=1e-9):
    if not rects:
        return []

    # Horizontal merge
    rects = sorted(rects, key=lambda r: (r[2], r[3], r[0], r[1]))
    merged = []
    cur = list(rects[0])
    for r in rects[1:]:
        if abs(r[2] - cur[2]) <= tol and abs(r[3] - cur[3]) <= tol and abs(r[0] - cur[1]) <= tol:
            cur[1] = r[1]
        else:
            merged.append(tuple(cur))
            cur = list(r)
    merged.append(tuple(cur))

    # Vertical merge
    merged = sorted(merged, key=lambda r: (r[0], r[1], r[2], r[3]))
    out = []
    cur = list(merged[0])
    for r in merged[1:]:
        if abs(r[0] - cur[0]) <= tol and abs(r[1] - cur[1]) <= tol and abs(r[2] - cur[3]) <= tol:
            cur[3] = r[3]
        else:
            out.append(tuple(cur))
            cur = list(r)
    out.append(tuple(cur))

    return out


def rect_vertices_xy(x0, x1, y0, y1, z):
    return [[x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z]]

def slab_remainder_should_be_adiabatic(rect, wall_gap_min: float) -> bool:
    """Heuristic: if a horizontal 'remainder' rectangle is a wall-thickness artifact, mark Adiabatic.

    Uses BOTH requested rules:
      1) 1.1x rule: min_width <= 1.1 * wall_gap_min
      2) abs difference rule: abs(min_width - wall_gap_min) <= 0.1 * wall_gap_min

    rect: (x0,x1,y0,y1)
    """
    try:
        x0, x1, y0, y1 = rect
        dx = abs(float(x1) - float(x0))
        dy = abs(float(y1) - float(y0))
        min_width = dx if dx < dy else dy
        g = float(wall_gap_min) if wall_gap_min is not None else 0.0
        if g <= 0.0:
            return False
        # Rule A: 1.1x rule
        if min_width <= 1.1 * g:
            return True
        # Rule B: abs difference rule (±10%)
        if abs(min_width - g) <= 0.1 * g:
            return True
        return False
    except Exception:
        return False


def zone_z_floor_top(zone: dict):
    zf = zone.get("_z_floor")
    zt = zone.get("_z_top")
    if zf is None or zt is None:
        zf = zf if zf is not None else 0.0
        zt = zt if zt is not None else zf + 3.0
    return float(zf), float(zt)


def adjacent_slab(lower_zone: dict, upper_zone: dict, slab_thk_min: float, z_tol: float, slab_tol: float):
    zf_u, _ = zone_z_floor_top(upper_zone)
    _, zt_l = zone_z_floor_top(lower_zone)
    dz = zf_u - zt_l
    if abs(dz) <= z_tol:
        return True
    if abs(abs(dz) - slab_thk_min) <= slab_tol:
        return True
    return False


# -------------------------
# Main
# -------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step4_json")
    ap.add_argument("out_json")
    ap.add_argument("--gap_tol", type=float, default=0.01)
    ap.add_argument("--slab_tol", type=float, default=0.20)
    ap.add_argument("--min_overlap_u", type=float, default=0.05)
    ap.add_argument("--min_overlap_v", type=float, default=0.05)
    ap.add_argument("--axis_tol", type=float, default=1e-4)
    ap.add_argument("--z_tol", type=float, default=0.02)
    ap.add_argument("--host_plane_tol", type=float, default=0.15)
    ap.add_argument("--contain_tol", type=float, default=0.02)
    ap.add_argument("--grid_tol", type=float, default=1e-6)
    ap.add_argument("--grid_min_cell", type=float, default=1e-6)
    args = ap.parse_args()

    with open(args.step4_json, "r", encoding="utf-8") as f:
        step4 = json.load(f)
    results = step4.get("results", {}) or {}

    wall_gap_min, slab_thk_min, storey_elev = extract_min_thicknesses(results)
    if wall_gap_min is None:
        wall_gap_min = 0.15
    if slab_thk_min is None:
        slab_thk_min = 0.15

    # -------------------------
    # Build zones from IFCSPACE
    # -------------------------
    zones = []
    zone_by_name = {}
    storey_to_zones = defaultdict(list)

    for sid, rec in results.items():
        if not isinstance(rec, dict):
            continue
        seed = rec.get("seed", {}) or {}
        if (seed.get("Entity") or "").upper() != "IFCSPACE":
            continue

        storey_sid = seed.get("StoreyStepId")
        storey_name = (results.get(storey_sid, {}).get("seed", {}) or {}).get("Name", "")
        storey_lbl = safe_name(storey_name or storey_sid or "UNK") or "UNK"

        space_name_raw = (seed.get("Name") or "").strip()
        zone_name = build_zone_name(storey_lbl, seed, sid)

        idf = rec.get("idf_surfaces", {}) or {}
        idf_walls = idf.get("wall") or idf.get("walls") or []
        idf_floor = idf.get("bottom_slab")
        idf_ceiling = idf.get("ceiling")
        idf_roof = idf.get("top_slab")

        # --- footprint + z planes (from Step4 surfaces) ---
        fp3 = (idf_floor or {}).get("vertices_3d") if isinstance(idf_floor, dict) else None
        if not fp3 and isinstance(idf_floor, list) and idf_floor:
            fp3 = (idf_floor[0] or {}).get("vertices_3d")
        fp3 = fp3 or []
        fp3 = remove_duplicate_closure([list(p) for p in fp3], tol=1e-6)
        fp3 = remove_consecutive_duplicates(fp3, tol=1e-6)

        footprint_xy = [(p[0], p[1]) for p in fp3] if len(fp3) >= 3 else []
        z_floor = (sum(p[2] for p in fp3) / len(fp3)) if fp3 else (storey_elev.get(storey_sid, 0.0) if storey_sid else 0.0)

        top3 = None
        if isinstance(idf_ceiling, dict):
            top3 = idf_ceiling.get("vertices_3d")
        elif isinstance(idf_ceiling, list) and idf_ceiling:
            top3 = (idf_ceiling[0] or {}).get("vertices_3d")
        if top3 is None:
            if isinstance(idf_roof, dict):
                top3 = idf_roof.get("vertices_3d")
            elif isinstance(idf_roof, list) and idf_roof:
                top3 = (idf_roof[0] or {}).get("vertices_3d")
        top3 = top3 or []
        top3 = remove_duplicate_closure([list(p) for p in top3], tol=1e-6)
        z_top = (sum(p[2] for p in top3) / len(top3)) if top3 else (z_floor + 3.0)

        zone = {
            "SpaceStepId": sid,
            "ZoneName": zone_name,
            "StoreyStepId": storey_sid,
            "StoreyLabel": storey_lbl,
            "SpaceName": space_name_raw,
            "footprint_xy": footprint_xy,
            "_bbox_xy": bbox_xy(fp3) if len(fp3) >= 3 else None,
            "_z_floor": float(z_floor),
            "_z_top": float(z_top),
            "surfaces": {"floor": [], "ceiling": [], "roof": [], "wall": []},
            "fenestration": {"door": [], "window": []},
            "unassigned_fenestration": [],
            "removed_interior_fenestration": [],
            "_host_bottom_slab": (idf_floor or {}).get("host_ifc_slab") if isinstance(idf_floor, dict) else {},
            "_host_top_slab": (idf_roof or {}).get("host_ifc_slab") if isinstance(idf_roof, dict) else {},
        }

        # keep Step4 walls (will be split)
        src_walls = idf_walls if isinstance(idf_walls, list) else [idf_walls]
        for s in (src_walls or []):
            ss = dict(s)
            ss.setdefault("OutsideBoundaryCondition", None)
            ss.setdefault("OutsideBoundaryConditionObject", None)
            zone["surfaces"]["wall"].append(ss)

        zones.append(zone)
        zone_by_name[zone_name] = zone
        storey_to_zones[storey_sid or "UNK"].append(zone)

    # -------------------------
    # Wall splitting (axis walls)
    # -------------------------

    class Wall:
        __slots__ = ("wid", "zone", "storey", "axis", "fixed", "u0", "u1", "v0", "v1", "thk", "host")

        def __init__(self, wid, zone, storey, axis, fixed, u0, u1, v0, v1, thk, host):
            self.wid = wid
            self.zone = zone
            self.storey = storey
            self.axis = axis
            self.fixed = fixed
            self.u0 = u0
            self.u1 = u1
            self.v0 = v0
            self.v1 = v1
            self.thk = float(thk) if thk is not None else None
            self.host = host if isinstance(host, dict) else {}

    walls = []
    wid = 0
    for z in zones:
        st = z.get("StoreyStepId") or "UNK"
        for s in z["surfaces"]["wall"]:
            verts = s.get("vertices_3d") or []
            ax, fixed = axis_fixed(verts, tol=args.axis_tol)
            if ax not in ("X", "Y"):
                continue
            u0, u1, v0, v1 = intervals_for_axis_plane(ax, verts)
            wid += 1
            thk = wall_thickness_m(s, wall_gap_min)
            host = s.get("host_ifc_wall") if isinstance(s, dict) else {}
            walls.append(Wall(wid, z["ZoneName"], st, ax, float(fixed), float(u0), float(u1), float(v0), float(v1), thk, host))

    walls_by_key = defaultdict(list)
    for w in walls:
        walls_by_key[(w.storey, w.axis)].append(w)

    overlaps = defaultdict(list)
    ubreak = defaultdict(set)
    vbreak = defaultdict(set)
    for w in walls:
        ubreak[w.wid].update([w.u0, w.u1])
        vbreak[w.wid].update([w.v0, w.v1])

    for (st, ax), lst in walls_by_key.items():
        n = len(lst)
        for i in range(n):
            a = lst[i]
            for j in range(i + 1, n):
                b = lst[j]
                if a.zone == b.zone:
                    continue
                d = abs(a.fixed - b.fixed)
                expected_gap = choose_pair_gap(a.thk, b.thk, wall_gap_min)
                if abs(d - expected_gap) > args.gap_tol:
                    continue
                ou = overlap_1d(a.u0, a.u1, b.u0, b.u1)
                ov = overlap_1d(a.v0, a.v1, b.v0, b.v1)
                if not ou or not ov:
                    continue
                if (ou[1] - ou[0]) < args.min_overlap_u or (ov[1] - ov[0]) < args.min_overlap_v:
                    continue
                rect = (ou[0], ou[1], ov[0], ov[1])
                area = (rect[1] - rect[0]) * (rect[3] - rect[2])
                err = abs(d - wall_gap_min)
                overlaps[a.wid].append((b.wid, rect, err, area))
                overlaps[b.wid].append((a.wid, rect, err, area))
                ubreak[a.wid].update([rect[0], rect[1]])
                vbreak[a.wid].update([rect[2], rect[3]])
                ubreak[b.wid].update([rect[0], rect[1]])
                vbreak[b.wid].update([rect[2], rect[3]])

    wall_by_id = {w.wid: w for w in walls}

    def rkey(x):
        return float(f"{x:.4f}")

    pieces_by_wall = defaultdict(list)
    for w in walls:
        ov = overlaps.get(w.wid, [])
        if not ov:
            pieces_by_wall[w.wid].append({
                "axis": w.axis,
                "fixed": w.fixed,
                "rect": (w.u0, w.u1, w.v0, w.v1),
                "obc": "Outdoors",
                "host": w.host,
                "thk": w.thk,
                "mate": None,
            })
            continue

        us = sorted(set(ubreak[w.wid]))
        vs = sorted(set(vbreak[w.wid]))
        rects = [(other, rect, err, area) for (other, rect, err, area) in ov]

        for ui in range(len(us) - 1):
            u0, u1 = us[ui], us[ui + 1]
            if u1 - u0 <= 1e-9:
                continue
            for vi in range(len(vs) - 1):
                v0, v1 = vs[vi], vs[vi + 1]
                if v1 - v0 <= 1e-9:
                    continue
                cell = (u0, u1, v0, v1)
                cands = []
                for (other, rect, err, area) in rects:
                    if cell_inside_rect(cell, rect):
                        cands.append((err, -area, other))
                if not cands:
                    pieces_by_wall[w.wid].append({
                        "axis": w.axis,
                        "fixed": w.fixed,
                        "rect": (u0, u1, v0, v1),
                        "obc": "Adiabatic",
                        "mate": None,
                    })
                else:
                    cands.sort()
                    pieces_by_wall[w.wid].append({
                        "axis": w.axis,
                        "fixed": w.fixed,
                        "rect": (u0, u1, v0, v1),
                        "obc": "Surface",
                        "mate": cands[0][2],
                        "host": w.host,
                        "thk": w.thk,
                    })

    # Validate one-to-one pairing for identical pieces
    pair_bucket = defaultdict(list)
    for wid, plist in pieces_by_wall.items():
        for p in plist:
            if p["obc"] != "Surface" or p["mate"] is None:
                continue
            a, b = wid, p["mate"]
            lo, hi = (a, b) if a < b else (b, a)
            u0, u1, v0, v1 = p["rect"]
            sig = (p["axis"], rkey(u0), rkey(u1), rkey(v0), rkey(v1))
            pair_bucket[(lo, hi, sig)].append((wid, p))
    valid_pairs = set(k for k, v in pair_bucket.items() if len(v) == 2)

    zone_walls_new = defaultdict(list)

    # preserve non-axis walls as Outdoors
    for z in zones:
        for s in z["surfaces"]["wall"]:
            verts = s.get("vertices_3d") or []
            ax, _ = axis_fixed(verts, tol=args.axis_tol)
            if ax not in ("X", "Y"):
                s["OutsideBoundaryCondition"] = "Outdoors"
                s["OutsideBoundaryConditionObject"] = None
                zone_walls_new[z["ZoneName"]].append(s)

    # rebuild axis walls as pieces
    for wid, plist in pieces_by_wall.items():
        w = wall_by_id[wid]
        for p in plist:
            obc = p["obc"]
            mate = p["mate"]
            u0, u1, v0, v1 = p["rect"]
            if obc == "Surface":
                lo, hi = (wid, mate) if wid < mate else (mate, wid)
                sig = (p["axis"], rkey(u0), rkey(u1), rkey(v0), rkey(v1))
                if (lo, hi, sig) not in valid_pairs:
                    obc = "Adiabatic"
                    mate = None

            zone_walls_new[w.zone].append({
                "name": None,
                "vertices_3d": build_quad_from_cell(p["axis"], p["fixed"], u0, u1, v0, v1),
                "OutsideBoundaryCondition": obc,
                "OutsideBoundaryConditionObject": None,
                "_axis": p["axis"],
                "_fixed": p["fixed"],
                "_rect": (u0, u1, v0, v1),
                "_mate": mate,
                "_thickness_m": w.thk,
                "host_ifc_wall": (p.get("host") if isinstance(p.get("host"), dict) else {}),
            })

    lookup = defaultdict(list)
    wallpieces_by_storey_axis = defaultdict(list)

    wall_thickness_vals = [
        float(w.thk)
        for w in walls
        if w.thk is not None and float(w.thk) > 0
    ]
    max_wall_thickness_m = max(wall_thickness_vals) if wall_thickness_vals else float(wall_gap_min)

    for z in zones:
        wl = zone_walls_new[z["ZoneName"]]
        base = z["ZoneName"] + "_walltmp_"
        for i, s in enumerate(wl, start=1):
            s["name"] = f"{base}{i}"
            if s.get("_axis") in ("X", "Y"):
                u0, u1, v0, v1 = s["_rect"]
                sig = (s["_axis"], rkey(u0), rkey(u1), rkey(v0), rkey(v1))
                lookup[(z["ZoneName"], sig, s.get("_mate"))].append(s)
                area = (u1 - u0) * (v1 - v0)
                st = z.get("StoreyStepId") or "UNK"
                wallpieces_by_storey_axis[(st, s["_axis"])].append({
                    "zone": z["ZoneName"],
                    "name": s["name"],
                    "fixed": s["_fixed"],
                    "rect": (u0, u1, v0, v1),
                    "area": area,
                    "thickness_m": s.get("_thickness_m") if s.get("_thickness_m") is not None else wall_thickness_m(s, wall_gap_min),
                })

        z["surfaces"]["wall"] = wl

    for (lo, hi, sig) in valid_pairs:
        wa = wall_by_id[lo]
        wb = wall_by_id[hi]
        sa_list = lookup.get((wa.zone, sig, hi), [])
        sb_list = lookup.get((wb.zone, sig, lo), [])
        if not sa_list or not sb_list:
            continue
        sa = sa_list.pop(0)
        sb = sb_list.pop(0)
        sa["OutsideBoundaryCondition"] = "Surface"
        sb["OutsideBoundaryCondition"] = "Surface"
        sa["OutsideBoundaryConditionObject"] = sb["name"]
        sb["OutsideBoundaryConditionObject"] = sa["name"]

    # -------------------------
    # Horizontal slabs (grid decomposition)
    # -------------------------

    # storey ordering: ignore UNK unless it is the only storey
    storey_ids = list(storey_to_zones.keys())
    known = [sid for sid in storey_ids if sid != "UNK"]
    if known:
        storey_order = sorted([(sid, storey_elev.get(sid, 0.0)) for sid in known], key=lambda t: t[1])
        storeys = [sid for sid, _ in storey_order]
    else:
        storeys = ["UNK"] if storey_ids else []

    storey_zone_meta = {}
    for st in storeys:
        zl = storey_to_zones.get(st, [])
        meta_list = []
        for z in zl:
            poly = z.get("footprint_xy") or []
            if len(poly) < 3 or z.get("_bbox_xy") is None:
                continue
            bb = z["_bbox_xy"]
            meta_list.append((z, bb, poly))
        storey_zone_meta[st] = meta_list

    def owner_in_storey(st, x, y):
        for z, bb, poly in storey_zone_meta.get(st, []):
            if x < bb[0] - 1e-9 or x > bb[2] + 1e-9 or y < bb[1] - 1e-9 or y > bb[3] + 1e-9:
                continue
            if point_in_poly_xy(x, y, poly, tol=1e-9):
                return z
        return None

    # clear existing horiz surfaces and rebuild
    for z in zones:
        z["surfaces"]["floor"] = []
        z["surfaces"]["ceiling"] = []
        z["surfaces"]["roof"] = []

    horiz_summary = {
        "interior_pairs": 0,
        "roof_pieces": 0,
        "exposed_floor_pieces": 0,
        "ground_floor_pieces": 0,
    }

    # ---- Ground floors (lowest storey) ----
    if storeys:
        st0 = storeys[0]
        xs = []
        ys = []
        for z, _, poly in storey_zone_meta.get(st0, []):
            xs += [p[0] for p in poly]
            ys += [p[1] for p in poly]
        x_lines = unique_sorted_merge(xs, tol=args.grid_tol)
        y_lines = unique_sorted_merge(ys, tol=args.grid_tol)
        ground_rects = defaultdict(list)
        for xi in range(len(x_lines) - 1):
            x0, x1 = x_lines[xi], x_lines[xi + 1]
            if x1 - x0 <= args.grid_min_cell:
                continue
            for yi in range(len(y_lines) - 1):
                y0, y1 = y_lines[yi], y_lines[yi + 1]
                if y1 - y0 <= args.grid_min_cell:
                    continue
                xm = 0.5 * (x0 + x1)
                ym = 0.5 * (y0 + y1)
                z0 = owner_in_storey(st0, xm, ym)
                if not z0:
                    continue
                ground_rects[z0["ZoneName"]].append((x0, x1, y0, y1))

        for zn, rects in ground_rects.items():
            zobj = zone_by_name.get(zn)
            if not zobj:
                continue
            zf, _ = zone_z_floor_top(zobj)
            for r in merge_rects(rects, tol=1e-9):
                name = f"{zn}_floortmp_ground_{len(zobj['surfaces']['floor'])+1}"
                zobj["surfaces"]["floor"].append({
                    "name": name,
                    "vertices_3d": rect_vertices_xy(r[0], r[1], r[2], r[3], zf),
                    "host_ifc_slab": (zobj.get("_host_bottom_slab") if isinstance(zobj.get("_host_bottom_slab"), dict) else {}),
                    "OutsideBoundaryCondition": "Ground",
                    "OutsideBoundaryConditionObject": None,
                })
                horiz_summary["ground_floor_pieces"] += 1

    # ---- Adjacent storey pairs ----
    for i in range(len(storeys) - 1):
        st = storeys[i]
        st2 = storeys[i + 1]
        lower_meta = storey_zone_meta.get(st, [])
        upper_meta = storey_zone_meta.get(st2, [])
        if not lower_meta and not upper_meta:
            continue

        xs = []
        ys = []
        for _, _, poly in lower_meta:
            xs += [p[0] for p in poly]
            ys += [p[1] for p in poly]
        for _, _, poly in upper_meta:
            xs += [p[0] for p in poly]
            ys += [p[1] for p in poly]
        x_lines = unique_sorted_merge(xs, tol=args.grid_tol)
        y_lines = unique_sorted_merge(ys, tol=args.grid_tol)

        interior_rects = defaultdict(list)
        roof_rects = defaultdict(list)
        exp_floor_rects = defaultdict(list)

        for xi in range(len(x_lines) - 1):
            x0, x1 = x_lines[xi], x_lines[xi + 1]
            if x1 - x0 <= args.grid_min_cell:
                continue
            for yi in range(len(y_lines) - 1):
                y0, y1 = y_lines[yi], y_lines[yi + 1]
                if y1 - y0 <= args.grid_min_cell:
                    continue
                xm = 0.5 * (x0 + x1)
                ym = 0.5 * (y0 + y1)
                zl = owner_in_storey(st, xm, ym)
                zu = owner_in_storey(st2, xm, ym)

                if zl and zu:
                    slab_thk_pair = min(
                        slab_thickness_m_from_host(zu.get("_host_bottom_slab"), slab_thk_min),
                        slab_thickness_m_from_host(zl.get("_host_top_slab"), slab_thk_min),
                    )
                    if adjacent_slab(zl, zu, slab_thk_pair, args.z_tol, args.slab_tol):
                        interior_rects[(zl["ZoneName"], zu["ZoneName"])].append((x0, x1, y0, y1))
                elif zl and not zu:
                    roof_rects[zl["ZoneName"]].append((x0, x1, y0, y1))
                elif zu and not zl:
                    exp_floor_rects[zu["ZoneName"]].append((x0, x1, y0, y1))
                elif zl and zu:
                    roof_rects[zl["ZoneName"]].append((x0, x1, y0, y1))
                    exp_floor_rects[zu["ZoneName"]].append((x0, x1, y0, y1))

        for (zl_name, zu_name), rects in interior_rects.items():
            zl = zone_by_name.get(zl_name)
            zu = zone_by_name.get(zu_name)
            if not zl or not zu:
                continue
            zf_u, _ = zone_z_floor_top(zu)
            _, zt_l = zone_z_floor_top(zl)

            for r in merge_rects(rects, tol=1e-9):
                ci = len(zl["surfaces"]["ceiling"]) + 1
                fi = len(zu["surfaces"]["floor"]) + 1
                ceil_name = f"{zl_name}_ceiltmp_pair_{ci}"
                floor_name = f"{zu_name}_floortmp_pair_{fi}"

                zl["surfaces"]["ceiling"].append({
                    "name": ceil_name,
                    "vertices_3d": rect_vertices_xy(r[0], r[1], r[2], r[3], zt_l),
                    "host_ifc_slab": ((zu.get("_host_bottom_slab") if isinstance(zu.get("_host_bottom_slab"), dict) else {}) or (zl.get("_host_top_slab") if isinstance(zl.get("_host_top_slab"), dict) else {})),
                    "OutsideBoundaryCondition": "Surface",
                    "OutsideBoundaryConditionObject": floor_name,
                })

                zu["surfaces"]["floor"].append({
                    "name": floor_name,
                    "vertices_3d": rect_vertices_xy(r[0], r[1], r[2], r[3], zf_u),
                    "OutsideBoundaryCondition": "Surface",
                    "OutsideBoundaryConditionObject": ceil_name,
                })

                horiz_summary["interior_pairs"] += 1

        for zl_name, rects in roof_rects.items():
            zl = zone_by_name.get(zl_name)
            if not zl:
                continue
            _, zt = zone_z_floor_top(zl)
            for r in merge_rects(rects, tol=1e-9):
                ri = len(zl["surfaces"]["roof"]) + 1
                roof_name = f"{zl_name}_rooftmp_ext_{ri}"
                zl["surfaces"]["roof"].append({
                    "name": roof_name,
                    "vertices_3d": rect_vertices_xy(r[0], r[1], r[2], r[3], zt),
                    "host_ifc_slab": (zl.get("_host_top_slab") if isinstance(zl.get("_host_top_slab"), dict) else {}),
                    "OutsideBoundaryCondition": ("Adiabatic" if slab_remainder_should_be_adiabatic(r, wall_gap_min) else "Outdoors"),
                    "OutsideBoundaryConditionObject": None,
                })
                horiz_summary["roof_pieces"] += 1

        for zu_name, rects in exp_floor_rects.items():
            zu = zone_by_name.get(zu_name)
            if not zu:
                continue
            zf, _ = zone_z_floor_top(zu)
            for r in merge_rects(rects, tol=1e-9):
                fi = len(zu["surfaces"]["floor"]) + 1
                floor_name = f"{zu_name}_floortmp_ext_{fi}"
                zu["surfaces"]["floor"].append({
                    "name": floor_name,
                    "vertices_3d": rect_vertices_xy(r[0], r[1], r[2], r[3], zf),
                    "OutsideBoundaryCondition": ("Adiabatic" if slab_remainder_should_be_adiabatic(r, wall_gap_min) else "Outdoors"),
                    "OutsideBoundaryConditionObject": None,
                })
                horiz_summary["exposed_floor_pieces"] += 1

    # ---- Top storey roofs (fill any remaining top areas) ----
    if storeys:
        st_top = storeys[-1]
        xs = []
        ys = []
        for _, _, poly in storey_zone_meta.get(st_top, []):
            xs += [p[0] for p in poly]
            ys += [p[1] for p in poly]
        x_lines = unique_sorted_merge(xs, tol=args.grid_tol)
        y_lines = unique_sorted_merge(ys, tol=args.grid_tol)

        top_roof_rects = defaultdict(list)
        for xi in range(len(x_lines) - 1):
            x0, x1 = x_lines[xi], x_lines[xi + 1]
            if x1 - x0 <= args.grid_min_cell:
                continue
            for yi in range(len(y_lines) - 1):
                y0, y1 = y_lines[yi], y_lines[yi + 1]
                if y1 - y0 <= args.grid_min_cell:
                    continue
                xm = 0.5 * (x0 + x1)
                ym = 0.5 * (y0 + y1)
                zt_owner = owner_in_storey(st_top, xm, ym)
                if not zt_owner:
                    continue
                top_roof_rects[zt_owner["ZoneName"]].append((x0, x1, y0, y1))

        for zn, rects in top_roof_rects.items():
            zobj = zone_by_name.get(zn)
            if not zobj:
                continue
            _, zt = zone_z_floor_top(zobj)
            for r in merge_rects(rects, tol=1e-9):
                ri = len(zobj["surfaces"]["roof"]) + 1
                roof_name = f"{zn}_rooftmp_top_{ri}"
                zobj["surfaces"]["roof"].append({
                    "name": roof_name,
                    "vertices_3d": rect_vertices_xy(r[0], r[1], r[2], r[3], zt),
                    "OutsideBoundaryCondition": ("Adiabatic" if slab_remainder_should_be_adiabatic(r, wall_gap_min) else "Outdoors"),
                    "OutsideBoundaryConditionObject": None,
                })
                horiz_summary["roof_pieces"] += 1

    # Early cleanup of horizontal surfaces
    for z in zones:
        for kind in ("floor", "ceiling", "roof"):
            for s in z["surfaces"][kind]:
                cleanup_surface_vertices(s, kind)

    # -------------------------
    # Fenestration assignment
    # -------------------------

    fen_host_plane_tol = max(float(args.host_plane_tol), float(max_wall_thickness_m))

    def choose_host(storey_sid, fen_axis, fen_fixed, fen_rect):
        cands = wallpieces_by_storey_axis.get((storey_sid or "UNK", fen_axis), [])
        best = None
        for c in cands:
            plane_dist = abs(c["fixed"] - fen_fixed)
            if plane_dist > fen_host_plane_tol + 1e-9:
                continue
            u0, u1, v0, v1 = c["rect"]
            big2 = (u0 - args.contain_tol, u1 + args.contain_tol, v0 - args.contain_tol, v1 + args.contain_tol)
            if not rect_contains(big2, fen_rect, tol=1e-9):
                continue
            score = (plane_dist, c["area"])
            if best is None or score < best[0]:
                best = (score, c)
        return best[1] if best else None

    assigned = 0
    unassigned = 0
    for sid, rec in results.items():
        if not isinstance(rec, dict):
            continue
        seed = rec.get("seed", {}) or {}
        ent = (seed.get("Entity") or "").upper()
        if ent not in ("IFCWINDOW", "IFCDOOR"):
            continue

        opening = (rec.get("geometry", {}) or {}).get("opening_rect_world_m")
        if not opening or not isinstance(opening, list) or len(opening) < 4:
            continue

        opening = remove_consecutive_duplicates([list(p) for p in opening], tol=1e-6)
        ax, fixed = axis_fixed(opening, tol=args.axis_tol)
        if ax not in ("X", "Y"):
            continue
        u0, u1, v0, v1 = intervals_for_axis_plane(ax, opening)
        fen_rect = (float(u0), float(u1), float(v0), float(v1))
        storey_sid = seed.get("StoreyStepId")
        host = choose_host(storey_sid, ax, float(fixed), fen_rect)

        fen_obj = {
            "name": safe_name(seed.get("Name") or sid.replace("#", "_")),
            "ifc_stepid": sid,
            "SurfaceType": "Window" if ent == "IFCWINDOW" else "Door",
            "BuildingSurfaceName": None,
            "vertices_3d": opening,
        }

        if host:
            fen_obj["BuildingSurfaceName"] = host["name"]
            zone_by_name[host["zone"]]["fenestration"]["window" if ent == "IFCWINDOW" else "door"].append(fen_obj)
            assigned += 1
        else:
            zs = [z for z in zones if (z.get("StoreyStepId") or "UNK") == (storey_sid or "UNK")]
            if zs:
                zs[0]["unassigned_fenestration"].append(fen_obj)
            else:
                step4.setdefault("unassigned_fenestration_global", []).append(fen_obj)
            unassigned += 1

    wall_obc = {}
    for z in zones:
        for w in z["surfaces"]["wall"]:
            wall_obc[w["name"]] = w.get("OutsideBoundaryCondition")

    removed = 0
    for z in zones:
        for kind in ("window", "door"):
            kept = []
            for f in z["fenestration"][kind]:
                host = f.get("BuildingSurfaceName")
                if host and wall_obc.get(host) == "Surface":
                    z["removed_interior_fenestration"].append(f)
                    removed += 1
                else:
                    kept.append(f)
            z["fenestration"][kind] = kept

    # -------------------------
    # Renaming pass
    # -------------------------

    surf_rename = {}
    for z in zones:
        zn = z["ZoneName"]
        for i, s in enumerate(z["surfaces"]["wall"], start=1):
            surf_rename[s["name"]] = f"{zn}_Wall_{i}"
        for typ, label in (("floor", "Floor"), ("ceiling", "Ceiling"), ("roof", "Roof")):
            for i, s in enumerate(z["surfaces"][typ], start=1):
                old = s.get("name") or f"{zn}_{label.lower()}tmp_{i}"
                s["name"] = old
                surf_rename[old] = f"{zn}_{label}_{i}"

    for z in zones:
        for typ in ("wall", "floor", "ceiling", "roof"):
            for s in z["surfaces"][typ]:
                s["name"] = surf_rename.get(s["name"], s["name"])

        for typ in ("wall", "floor", "ceiling", "roof"):
            for s in z["surfaces"][typ]:
                if (s.get("OutsideBoundaryCondition") or "").lower() == "surface" and s.get("OutsideBoundaryConditionObject"):
                    s["OutsideBoundaryConditionObject"] = surf_rename.get(
                        s["OutsideBoundaryConditionObject"], s["OutsideBoundaryConditionObject"]
                    )

    for z in zones:
        zn = z["ZoneName"]
        for kind, label in (("window", "Window"), ("door", "Door")):
            for i, f in enumerate(z["fenestration"][kind], start=1):
                f["name"] = f"{zn}_{label}_{i}"
                if f.get("BuildingSurfaceName"):
                    f["BuildingSurfaceName"] = surf_rename.get(f["BuildingSurfaceName"], f["BuildingSurfaceName"])

        for i, f in enumerate(z["removed_interior_fenestration"], start=1):
            lbl = "Window" if f.get("SurfaceType") == "Window" else "Door"
            f["name"] = f"{zn}_RemovedInterior_{lbl}_{i}"
            if f.get("BuildingSurfaceName"):
                f["BuildingSurfaceName"] = surf_rename.get(f["BuildingSurfaceName"], f["BuildingSurfaceName"])

        for f in z["unassigned_fenestration"]:
            if f.get("BuildingSurfaceName"):
                f["BuildingSurfaceName"] = surf_rename.get(f["BuildingSurfaceName"], f["BuildingSurfaceName"])

    # -------------------------
    # Final cleanup + ConstructionHint
    # -------------------------

    for z in zones:
        for kind in ("floor", "ceiling", "roof", "wall"):
            for s in z["surfaces"][kind]:
                cleanup_surface_vertices(s, kind)
                s["ConstructionHint"] = set_construction_hint(kind, s.get("OutsideBoundaryCondition"))

        for kind in ("window", "door"):
            for f in z["fenestration"][kind]:
                f["vertices_3d"] = remove_consecutive_duplicates([list(p) for p in (f.get("vertices_3d") or [])], tol=1e-6)

        for f in z["removed_interior_fenestration"]:
            f["vertices_3d"] = remove_consecutive_duplicates([list(p) for p in (f.get("vertices_3d") or [])], tol=1e-6)

    out = {
        "meta": step4.get("meta", {}),
        "step": "step5_obc_v8_grid_like",
        "derived_thickness": {
            "wall_gap_min": wall_gap_min,
            "wall_thickness_max": max_wall_thickness_m,
            "slab_thk_min": slab_thk_min,
        },
        "derived_tolerances": {
            "fenestration_host_plane_tol": fen_host_plane_tol,
        },
        "horiz_summary": horiz_summary,
        "fenestration_summary": {
            "assigned_before_filter": assigned,
            "unassigned": unassigned,
            "removed_interior": removed,
            "kept_after_filter": assigned - removed,
        },
        "zones": zones,
    }

    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(round_json(out), f, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())