#!/usr/bin/env python3
"""Step 4: IDF geometry preparation (EnergyPlus vertices) - V2 (host IFC mapping).

Input:  step3_geometry.json  (ALL lengths/coords already in meters)
Output: step4_idf_geometry.json  (adds idf_surfaces)

What this script does:
- No unit conversion (already meters).
- Recursively rounds JSON numeric fields to 4 decimals.
- Builds EnergyPlus-style surface vertices for each IFCSPACE using the SPACE footprint + height:
    - idf_surfaces.bottom_slab.vertices_3d   (was: floor)
    - idf_surfaces.top_slab.vertices_3d      (was: ceiling/roof; ALWAYS generated here)
    - idf_surfaces.walls[i].vertices_3d      (vertical quads)

Why "bottom_slab" / "top_slab":
- Step 4 only creates clean zone solids from spaces.
- Step 5 will decide whether a top_slab becomes an interior Ceiling (Surface/Adiabatic)
  or an exterior Roof (Outdoors).

Slab thickness hints (for Step 5 horizontal pairing):
- Step 4 collects IFCSLAB thicknesses per building storey (best-effort) and attaches:
    - slab_thickness_m
    - slab_storey_stepid
    - ifc_slab_stepids (candidate slab ids used for the thickness estimate)
  onto each generated bottom_slab / top_slab surface.

Storey metadata:
- Prefers IFCBUILDINGSTOREY seeds (StepId/Name/Elevation_m).
- Fallback to unique SPACE.seed.StoreyElevation_m values.
- Writes results["storeys"] = {num_storeys, items:[...]}.

Also:
- Infers StoreyStepId for fenestration (IFCWINDOW/IFCDOOR) when missing,
  using opening_rect_world_m Z location and storey elevation bands.
- Infers StoreyStepId for IFCSLAB when missing, using nearest storey elevation.

Stdlib only.
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path


# -----------------------------
# Rounding helpers (global)
# -----------------------------

def round_floats(obj, ndigits=4):
    """Recursively round floats/ints inside dict/list structures."""
    if isinstance(obj, dict):
        return {k: round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [round_floats(v, ndigits) for v in obj]
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, (int, float)):
        x = float(obj)
        xr = round(x, ndigits)
        # preserve ints where safe
        if isinstance(obj, int) and abs(xr - int(xr)) < 10 ** (-ndigits):
            return int(xr)
        return xr
    return obj


def _r4(x):
    try:
        return round(float(x), 4)
    except Exception:
        return x


def round_point_m(pt):
    if not isinstance(pt, (list, tuple)) or len(pt) < 3:
        return pt
    return [_r4(pt[0]), _r4(pt[1]), _r4(pt[2])]


# -----------------------------
# Geometry helpers
# -----------------------------

def ensure_closed_ring_xy(pts):
    """Ensure footprint ring is closed in XY. (Z may differ, but spaces are assumed flat.)"""
    if not pts:
        return pts
    if len(pts) >= 2 and (pts[0][0], pts[0][1]) == (pts[-1][0], pts[-1][1]):
        return pts
    return pts + [pts[0]]


def infer_z0_from_footprint(footprint_world_m):
    """Return z0 as min(z) of footprint (flat assumption)."""
    try:
        return float(min(p[2] for p in footprint_world_m))
    except Exception:
        return 0.0


def infer_height_m(rec):
    """Best-effort space height inference (meters)."""
    geom = rec.get("geometry", {}) if isinstance(rec.get("geometry"), dict) else {}
    best = rec.get("best", {}) if isinstance(rec.get("best"), dict) else {}
    q = rec.get("quantities_from_ifc", {}) if isinstance(rec.get("quantities_from_ifc"), dict) else {}

    for key in ("height", "depth"):
        v = geom.get(key)
        if v not in (None, "", 0, 0.0):
            try:
                return float(v)
            except Exception:
                pass

    for key in ("height", "depth"):
        v = best.get(key)
        if v not in (None, "", 0, 0.0):
            try:
                return float(v)
            except Exception:
                pass

    # derive from volume/area if present
    try:
        vol = q.get("NetVolume") or q.get("GrossVolume") or q.get("Volume")
        area = q.get("NetFloorArea") or q.get("GrossFloorArea") or q.get("Area")
        if vol and area:
            vol = float(vol)
            area = float(area)
            if area > 0:
                h = vol / area
                if h > 0:
                    return h
    except Exception:
        pass

    return 3.0


def build_idf_surfaces_from_footprint_m(
    footprint_world_m,
    z0_m,
    height_m,
    zone_name,
    *,
    bottom_meta=None,
    top_meta=None,
):
    """Create bottom_slab + top_slab + wall quads from a footprint ring."""
    if not footprint_world_m or len(footprint_world_m) < 3:
        return {}

    ring = ensure_closed_ring_xy([list(p) for p in footprint_world_m])
    z0 = float(z0_m)
    H = float(height_m)
    z_top = z0 + H

    bottom_pts = [round_point_m([p[0], p[1], z0]) for p in ring[:-1]]
    top_pts = [round_point_m([p[0], p[1], z_top]) for p in ring[:-1]]

    walls = []
    for i in range(len(ring) - 1):
        p1 = ring[i]
        p2 = ring[i + 1]
        wall_vertices = [
            round_point_m([p1[0], p1[1], z0]),
            round_point_m([p2[0], p2[1], z0]),
            round_point_m([p2[0], p2[1], z_top]),
            round_point_m([p1[0], p1[1], z_top]),
        ]
        walls.append({"name": f"{zone_name}_WALL_{i+1}", "vertices_3d": wall_vertices})

    bottom = {"name": f"{zone_name}_BOTTOM_SLAB", "vertices_3d": bottom_pts}
    top = {"name": f"{zone_name}_TOP_SLAB", "vertices_3d": top_pts}
    if isinstance(bottom_meta, dict):
        bottom.update(bottom_meta)
    if isinstance(top_meta, dict):
        top.update(top_meta)

    return {
        "bottom_slab": bottom,
        "top_slab": top,
        "walls": walls,
    }


# -----------------------------
# Rounding within blocks
# -----------------------------

def round_geometry_block(geom: dict) -> dict:
    if not isinstance(geom, dict):
        return geom
    out = dict(geom)

    # Round point lists
    if "footprint_world_m" in out and isinstance(out["footprint_world_m"], list):
        out["footprint_world_m"] = [round_point_m(p) for p in out["footprint_world_m"]]

    for k in ("origin_world_m",):
        if k in out and isinstance(out[k], list):
            out[k] = round_point_m(out[k])

    if "opening_rect_world_m" in out and isinstance(out["opening_rect_world_m"], list):
        out["opening_rect_world_m"] = [round_point_m(p) for p in out["opening_rect_world_m"]]

    # Round direction vectors (unitless)
    for dk in ("x_dir_world", "y_dir_world", "z_dir_world"):
        if dk in out and isinstance(out[dk], list) and len(out[dk]) >= 3:
            out[dk] = [_r4(out[dk][0]), _r4(out[dk][1]), _r4(out[dk][2])]

    # Round scalar meter-based geometry fields if present
    scalar_keys = {
        "height",
        "depth",
        "x_dim",
        "y_dim",
        "width",
        "length",
        "thickness",
        "height_opening",
        "overall_width",
        "overall_height",
        "area_computed",
        "volume_computed",
    }
    for k in list(out.keys()):
        if k in scalar_keys and isinstance(out[k], (int, float)):
            out[k] = _r4(out[k])

    return out


def round_quantities_block(q: dict) -> dict:
    if not isinstance(q, dict):
        return q
    out = dict(q)
    for k, v in list(out.items()):
        if isinstance(v, (int, float)):
            out[k] = _r4(v)
    return out


# -----------------------------
# Storey derivation
# -----------------------------

def derive_storeys(results: dict):
    """Derive storey list and helpers.

    Prefer IFCBUILDINGSTOREY seeds (StepId/Name/Elevation_m).
    Fallback to unique SPACE.seed.StoreyElevation_m if no storeys exist.

    Returns:
      storeys_items: list of dicts with StoreyIndex, StoreyStepId (or None), StoreyLabel, StoreyElevation_m
      stepid_to_index: dict StoreyStepId -> StoreyIndex
      elevs_sorted: list of elevations (float) aligned with storeys_items
    """
    storey_recs = []
    for sid, rec in results.items():
        seed = rec.get("seed") if isinstance(rec.get("seed"), dict) else {}
        if seed.get("Entity") == "IFCBUILDINGSTOREY":
            elev = seed.get("Elevation_m")
            if isinstance(elev, (int, float)):
                storey_recs.append({
                    "StoreyStepId": seed.get("StepId", sid),
                    "StoreyLabel": (seed.get("Name") or "").strip() or None,
                    "StoreyElevation_m": float(elev),
                })

    storeys_items = []
    if storey_recs:
        storey_recs.sort(key=lambda d: (round(d["StoreyElevation_m"], 6), str(d.get("StoreyStepId"))))
        for idx, s in enumerate(storey_recs, start=1):
            label = s["StoreyLabel"] or f"L{idx}"
            storeys_items.append({
                "StoreyIndex": idx,
                "StoreyStepId": s.get("StoreyStepId"),
                "StoreyLabel": label,
                "StoreyElevation_m": _r4(s["StoreyElevation_m"]),
            })
    else:
        elevs = []
        for sid, rec in results.items():
            if rec.get("category") != "SPACE":
                continue
            seed = rec.get("seed") if isinstance(rec.get("seed"), dict) else {}
            elev = seed.get("StoreyElevation_m")
            if isinstance(elev, (int, float)):
                elevs.append(float(elev))
        uniq = sorted({round(e, 4) for e in elevs}) or [0.0]
        for idx, e in enumerate(uniq, start=1):
            storeys_items.append({
                "StoreyIndex": idx,
                "StoreyStepId": None,
                "StoreyLabel": f"L{idx}",
                "StoreyElevation_m": _r4(e),
            })

    stepid_to_index = {}
    elevs_sorted = []
    for s in storeys_items:
        elevs_sorted.append(float(s["StoreyElevation_m"]))
        if s.get("StoreyStepId"):
            stepid_to_index[str(s["StoreyStepId"])] = int(s["StoreyIndex"])
    return storeys_items, stepid_to_index, elevs_sorted


def infer_storey_stepid_for_z_band(z_m: float, storeys_items: list, elevs_sorted: list):
    """Map a Z value to a StoreyStepId using storey elevation bands.

    Band rule:
      - storey i covers [elev_i, elev_{i+1}] (inclusive of upper boundary)
      - last storey covers [elev_last, +inf)

    This is appropriate for windows/doors.
    """
    if not storeys_items:
        return None
    try:
        import bisect
        j = bisect.bisect_left(elevs_sorted, float(z_m)) - 1
        if j < 0:
            j = 0
        if j >= len(storeys_items):
            j = len(storeys_items) - 1
        return storeys_items[j].get("StoreyStepId") or None
    except Exception:
        return storeys_items[0].get("StoreyStepId") or None


def infer_storey_stepid_nearest_elevation(z_m: float, storeys_items: list):
    """Infer StoreyStepId by nearest storey elevation.

    This is more appropriate for horizontal elements (slabs) where Z often equals the storey level.
    """
    best = None
    for s in storeys_items:
        stid = s.get("StoreyStepId")
        elev = s.get("StoreyElevation_m")
        if stid is None or elev is None:
            continue
        try:
            d = abs(float(z_m) - float(elev))
        except Exception:
            continue
        if best is None or d < best[0]:
            best = (d, stid)
    return best[1] if best else None



# -----------------------------
# Host IFC element matching (additive metadata only) - V2
# -----------------------------

def _bbox_from_pts_xy(pts):
    xs=[p[0] for p in pts] if pts else []
    ys=[p[1] for p in pts] if pts else []
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))

def _bbox_overlap_area(a, b):
    if not a or not b:
        return 0.0
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ox0=max(ax0, bx0); oy0=max(ay0, by0)
    ox1=min(ax1, bx1); oy1=min(ay1, by1)
    if ox1 <= ox0 or oy1 <= oy0:
        return 0.0
    return float((ox1-ox0)*(oy1-oy0))

def _bbox_area(a):
    if not a:
        return 0.0
    return float(max(0.0, a[2]-a[0]) * max(0.0, a[3]-a[1]))

def _seg_len_xy(a, b):
    dx=b[0]-a[0]; dy=b[1]-a[1]
    return (dx*dx+dy*dy) ** 0.5

def _unit_xy(dx, dy):
    L=(dx*dx+dy*dy) ** 0.5
    if L <= 1e-12:
        return (0.0, 0.0, 0.0)
    return (dx/L, dy/L, L)

def _angle_deg_between_xy(u1, u2):
    # u1,u2 are (ux,uy) unit
    import math
    dotv = max(-1.0, min(1.0, u1[0]*u2[0] + u1[1]*u2[1]))
    return abs(math.degrees(math.acos(dotv)))

def _dist_point_to_line_xy(px, py, ax, ay, bx, by):
    # distance from point P to infinite line AB in XY
    import math
    dx=bx-ax; dy=by-ay
    den = math.hypot(dx, dy)
    if den <= 1e-12:
        return math.hypot(px-ax, py-ay)
    return abs(dy*px - dx*py + bx*ay - by*ax) / den

def _proj_scalar_on_u(px, py, ox, oy, ux, uy):
    return (px-ox)*ux + (py-oy)*uy

def _overlap_1d_len(a0, a1, b0, b1):
    lo=max(a0, b0); hi=min(a1, b1)
    return max(0.0, hi-lo)

def extract_host_props_m(host_rec, entity_upper):
    """Extract key meter-based physical properties from a Step-3 record (already meters)."""
    if not isinstance(host_rec, dict):
        return {}
    q = host_rec.get("quantities_from_ifc") if isinstance(host_rec.get("quantities_from_ifc"), dict) else {}
    g = host_rec.get("geometry") if isinstance(host_rec.get("geometry"), dict) else {}
    b = host_rec.get("best") if isinstance(host_rec.get("best"), dict) else {}

    def pick(*keys):
        for k in keys:
            v = q.get(k)
            if isinstance(v, (int, float)) and float(v) > 0:
                return float(v)
        for k in keys:
            v = g.get(k)
            if isinstance(v, (int, float)) and float(v) > 0:
                return float(v)
        for k in keys:
            v = b.get(k)
            if isinstance(v, (int, float)) and float(v) > 0:
                return float(v)
        return None

    ent = (entity_upper or "").upper()
    props = {}

    if ent.startswith("IFCWALL") or ent.startswith("IFCCURTAINWALL"):
        thk = pick("width", "thickness", "depth")
        if thk is not None: props["thickness"] = _r4(thk)
        h = pick("height")
        if h is not None: props["height"] = _r4(h)
        L = pick("length")
        if L is not None: props["length"] = _r4(L)

    elif ent.startswith("IFCSLAB") or ent.startswith("IFCROOF"):
        thk = pick("depth", "thickness")
        if thk is not None: props["thickness"] = _r4(thk)

    elif ent in ("IFCWINDOW","IFCDOOR"):
        # openings: include overall dims + thickness if present
        ow = pick("overall_width", "width")
        oh = pick("overall_height", "height")
        if ow is not None: props["overall_width"] = _r4(ow)
        if oh is not None: props["overall_height"] = _r4(oh)
        thk = pick("thickness", "depth")
        if thk is not None: props["thickness"] = _r4(thk)

    else:
        # generic fallback
        thk = pick("thickness", "depth", "width")
        if thk is not None: props["thickness"] = _r4(thk)

    return props

def build_candidates_by_entity(results):
    """Pre-index Step-3 results by entity type for host matching.

    Returns:
      walls: list of (sid, rec) for IFCWALL/IFCCURTAINWALL with axis endpoints
      slabs: list of (sid, rec) for IFCSLAB with footprint
      roofs: list of (sid, rec) for IFCROOF with footprint (when available)
    """
    walls=[]
    slabs=[]
    roofs=[]
    for sid, rec in (results or {}).items():
        if not isinstance(rec, dict):
            continue
        seed = rec.get("seed") if isinstance(rec.get("seed"), dict) else {}
        ent = (seed.get("Entity") or "").upper()
        if ent.startswith("IFCWALL") or ent.startswith("IFCCURTAINWALL"):
            g = rec.get("geometry") if isinstance(rec.get("geometry"), dict) else {}
            sp = g.get("starting_point_global_m")
            ep = g.get("ending_point_global_m")
            if isinstance(sp, list) and len(sp) >= 2 and isinstance(ep, list) and len(ep) >= 2:
                walls.append((sid, rec))
        elif ent.startswith("IFCSLAB"):
            g = rec.get("geometry") if isinstance(rec.get("geometry"), dict) else {}
            fp = g.get("footprint_world_m")
            if isinstance(fp, list) and len(fp) >= 3:
                slabs.append((sid, rec))
        elif ent.startswith("IFCROOF"):
            g = rec.get("geometry") if isinstance(rec.get("geometry"), dict) else {}
            fp = g.get("footprint_world_m")
            if isinstance(fp, list) and len(fp) >= 3:
                roofs.append((sid, rec))
    return walls, slabs, roofs

def match_wall_surface_to_ifc_wall(surface, zone_storey_stepid, wall_candidates, results, dist_tol_m=1.0):
    """Match a Step-4 wall quad to an IFCWALL axis segment using XY metrics."""
    verts = surface.get("vertices_3d") or []
    if len(verts) < 2:
        return None

    # base segment from first two vertices at z0
    a = verts[0]; b = verts[1]
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    ux, uy, segL = _unit_xy(bx-ax, by-ay)
    if segL <= 1e-9:
        return None
    mx, my = (ax+bx)/2.0, (ay+by)/2.0

    best = None
    for sid, rec in wall_candidates:
        seed = rec.get("seed") if isinstance(rec.get("seed"), dict) else {}
        if zone_storey_stepid and seed.get("StoreyStepId") and str(seed.get("StoreyStepId")) != str(zone_storey_stepid):
            continue
        g = rec.get("geometry") if isinstance(rec.get("geometry"), dict) else {}
        sp = g.get("starting_point_global_m"); ep = g.get("ending_point_global_m")
        if not (isinstance(sp, list) and isinstance(ep, list)):
            continue
        wx0, wy0 = float(sp[0]), float(sp[1])
        wx1, wy1 = float(ep[0]), float(ep[1])
        wux, wuy, wL = _unit_xy(wx1-wx0, wy1-wy0)
        if wL <= 1e-9:
            continue

        # angle diff (0..90)
        ang = _angle_deg_between_xy((ux,uy),(wux,wuy))
        ang = min(ang, 180.0-ang)

        # distance from wall segment midpoint to IFC wall axis line
        dist = _dist_point_to_line_xy(mx, my, wx0, wy0, wx1, wy1)
        if dist > dist_tol_m:
            continue

        # overlap length along the surface direction (project both segments on surface axis)
        s0 = 0.0
        s1 = segL
        # project IFC endpoints onto surface axis (origin at a)
        p0 = _proj_scalar_on_u(wx0, wy0, ax, ay, ux, uy)
        p1 = _proj_scalar_on_u(wx1, wy1, ax, ay, ux, uy)
        ov = _overlap_1d_len(min(p0,p1), max(p0,p1), s0, s1)
        if ov <= 1e-6:
            continue
        ov_ratio = ov / segL if segL > 0 else 0.0

        # score: prioritize overlap_ratio, then lower dist, then lower angle
        score = (ov_ratio, -dist, -ang, ov)
        if best is None or score > best[0]:
            host_seed = seed
            host_rec = rec
            best = (score, sid, host_seed, host_rec, {"overlap_m": _r4(ov), "overlap_ratio": _r4(min(1.0, ov_ratio)), "dist_m": _r4(dist), "angle_deg": _r4(ang)})

    if best is None:
        return None
    _, sid, host_seed, host_rec, match = best
    ent = (host_seed.get("Entity") or "").upper()
    return {
        "step_id": sid,
        "entity": host_seed.get("Entity"),
        "global_id": host_seed.get("GlobalId"),
        "storey_stepid": host_seed.get("StoreyStepId"),
        "props_m": extract_host_props_m(host_rec, ent),
        "match": match,
    }

def match_slab_by_xy_and_z(surf_poly_pts, target_z, slab_candidates, zone_storey_stepid, allow_storeys=None, z_band=(0.25, 0.6), prefer_roof=False):
    """Return best slab host and candidates. Uses bbox overlap + Z band around target_z.
    z_band = (below, above) allowance in meters around target_z (asymmetric).
    """
    if not surf_poly_pts or len(surf_poly_pts) < 3:
        return None, []
    sbbox = _bbox_from_pts_xy(surf_poly_pts)
    sarea = _bbox_area(sbbox)
    if sarea <= 1e-12:
        return None, []
    below, above = z_band
    cand_list=[]
    for sid, rec in slab_candidates:
        seed = rec.get("seed") if isinstance(rec.get("seed"), dict) else {}
        stid = seed.get("StoreyStepId")
        if allow_storeys is not None:
            if stid not in allow_storeys:
                continue
        elif zone_storey_stepid and stid and str(stid) != str(zone_storey_stepid):
            continue

        g = rec.get("geometry") if isinstance(rec.get("geometry"), dict) else {}
        fp = g.get("footprint_world_m")
        if not isinstance(fp, list) or len(fp) < 3:
            continue
        # z of slab from footprint
        try:
            zmean = sum(float(p[2]) for p in fp) / len(fp)
        except Exception:
            zmean = None
        if zmean is None:
            continue
        if not (target_z - below <= zmean <= target_z + above):
            continue

        bb = _bbox_from_pts_xy(fp)
        ovA = _bbox_overlap_area(sbbox, bb)
        if ovA <= 1e-9:
            continue
        ov_ratio = ovA / sarea
        dist = abs(zmean - target_z)
        roof_bonus = 1.0 if (prefer_roof and (seed.get("Entity") or "").upper().startswith("IFCROOF")) else 0.0
        cand_list.append((roof_bonus, ov_ratio, -dist, sid, rec, zmean, ovA))

    cand_list.sort(reverse=True)
    out=[]
    for _roofb, ov_ratio, _negdist, sid, rec, zmean, ovA in cand_list[:10]:
        seed = rec.get("seed") if isinstance(rec.get("seed"), dict) else {}
        ent = (seed.get("Entity") or "").upper()
        out.append({
            "step_id": sid,
            "entity": seed.get("Entity"),
            "global_id": seed.get("GlobalId"),
            "storey_stepid": seed.get("StoreyStepId"),
            "props_m": extract_host_props_m(rec, ent),
            "match": {
                "overlap_area_m2": _r4(ovA),
                "overlap_ratio_bbox": _r4(min(1.0, float(ov_ratio))),
                "z_mean_m": _r4(zmean),
                "z_dist_m": _r4(abs(zmean - target_z)),
            }
        })
    best = out[0] if out else None
    return best, out

# -----------------------------
# Slab thickness extraction
# -----------------------------

def extract_slab_thickness_m(rec: dict):
    """Best-effort slab thickness in meters from a Step-3 record."""
    q = rec.get("quantities_from_ifc") if isinstance(rec.get("quantities_from_ifc"), dict) else {}
    g = rec.get("geometry") if isinstance(rec.get("geometry"), dict) else {}

    for key in ("depth", "thickness", "Depth", "Thickness"):
        v = q.get(key)
        if isinstance(v, (int, float)) and float(v) > 0:
            return float(v)

    for key in ("depth", "thickness", "height"):
        v = g.get(key)
        if isinstance(v, (int, float)) and float(v) > 0:
            return float(v)

    return None


def build_slab_thickness_maps(results: dict, storeys_items: list):
    """Collect IFCSLAB thickness by storey and return (default_thk, thk_by_storey, slab_ids_by_storey)."""
    thk_all = []
    thk_by_storey = defaultdict(list)
    slab_ids_by_storey = defaultdict(list)

    # quick map for StoreyStepId -> elevation
    stepid_to_elev = {str(s.get("StoreyStepId")): s.get("StoreyElevation_m") for s in storeys_items if s.get("StoreyStepId")}

    for sid, rec in results.items():
        if not isinstance(rec, dict):
            continue
        seed = rec.get("seed") if isinstance(rec.get("seed"), dict) else {}
        ent = (seed.get("Entity") or "").upper()
        if not ent.startswith("IFCSLAB"):
            continue

        # infer storey for slab when missing (nearest elevation)
        stid = seed.get("StoreyStepId")
        if not stid:
            geom = rec.get("geometry") if isinstance(rec.get("geometry"), dict) else {}
            fp = geom.get("footprint_world_m")
            z_guess = None
            if isinstance(fp, list) and fp and isinstance(fp[0], (list, tuple)) and len(fp[0]) >= 3:
                try:
                    z_guess = sum(float(p[2]) for p in fp) / float(len(fp))
                except Exception:
                    try:
                        z_guess = float(fp[0][2])
                    except Exception:
                        z_guess = None
            if z_guess is not None:
                stid = infer_storey_stepid_nearest_elevation(z_guess, storeys_items)
                if stid:
                    seed["StoreyStepId"] = stid
                    elev = stepid_to_elev.get(str(stid))
                    if isinstance(elev, (int, float)):
                        seed["StoreyElevation_m"] = elev
                    rec["seed"] = seed

        thk = extract_slab_thickness_m(rec)
        if isinstance(thk, (int, float)) and float(thk) > 0:
            thk = float(thk)
            thk_all.append(thk)
            if stid:
                thk_by_storey[str(stid)].append(thk)
                slab_ids_by_storey[str(stid)].append(sid)

    default_thk = statistics.median(thk_all) if thk_all else None
    thk_storey_med = {k: statistics.median(v) for k, v in thk_by_storey.items() if v}

    return default_thk, thk_storey_med, slab_ids_by_storey


# -----------------------------
# Main
# -----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step3_json", help="Input step3_geometry.json")
    ap.add_argument("--out", default="step4_idf_geometry.json", help="Output JSON")
    args = ap.parse_args()

    data = json.loads(Path(args.step3_json).read_text(encoding="utf-8"))
    results = data.get("results", {})

    # Derive storey info and store it under results (not meta)
    storeys_items, stepid_to_index, elevs_sorted = derive_storeys(results)
    num_storeys = len(storeys_items)

    # V2: pre-index IFC candidates for host mapping
    wall_candidates, slab_candidates, roof_candidates = build_candidates_by_entity(results)
    storey_order = [s.get("StoreyStepId") for s in storeys_items]

    # Keep meta metadata-only
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    meta.pop("num_storeys", None)
    meta.pop("storeys", None)
    data["meta"] = meta

    # Attach storeys payload under results to match desired output schema
    results["storeys"] = {
        "num_storeys": num_storeys,
        "items": storeys_items,
    }

    # Collect slab thickness hints per storey
    default_slab_thk, slab_thk_by_storey, slab_ids_by_storey = build_slab_thickness_maps(results, storeys_items)

    # quick mapping storey_stepid -> elevation
    storey_elev_by_stepid = {str(s.get("StoreyStepId")): float(s.get("StoreyElevation_m")) for s in storeys_items if s.get("StoreyStepId") and isinstance(s.get("StoreyElevation_m"), (int, float))}

    # Round blocks + generate idf_surfaces for spaces
    for sid, rec in results.items():
        if "quantities_from_ifc" in rec:
            rec["quantities_from_ifc"] = round_quantities_block(rec["quantities_from_ifc"])
        if "best" in rec:
            rec["best"] = round_quantities_block(rec["best"])

        geom = rec.get("geometry")
        if isinstance(geom, dict):
            rec["geometry"] = round_geometry_block(geom)

        if rec.get("category") == "SPACE" and isinstance(rec.get("geometry"), dict) and "footprint_world_m" in rec["geometry"]:
            seed = rec.get("seed") if isinstance(rec.get("seed"), dict) else {}

            # Determine storey index for this space (prefer StoreyStepId when present)
            storey_index = 1
            sid_storey = seed.get("StoreyStepId")
            if sid_storey and str(sid_storey) in stepid_to_index:
                storey_index = int(stepid_to_index[str(sid_storey)])
            else:
                elev = seed.get("StoreyElevation_m")
                elev_key = round(float(elev), 4) if isinstance(elev, (int, float)) else (elevs_sorted[0] if elevs_sorted else 0.0)
                if elevs_sorted:
                    nearest = min(elevs_sorted, key=lambda x: abs(x - elev_key))
                    storey_index = elevs_sorted.index(nearest) + 1

            # next storey (by building storey list)
            next_storey_stepid = None
            if 1 <= storey_index < num_storeys:
                next_storey_stepid = storeys_items[storey_index].get("StoreyStepId")  # storey_index is 1-based

            # zone name for Step4 surface naming only (Step5 defines final ZoneName)
            zone_name = seed.get("Name", sid) or sid
            zone_name = str(zone_name).strip() or sid
            zone_name = zone_name.replace(" ", "_")

            z0_m = infer_z0_from_footprint(rec["geometry"]["footprint_world_m"])
            h_m = infer_height_m(rec)

            # bottom slab thickness from SAME storey
            bottom_storey_key = str(sid_storey) if sid_storey else None
            bottom_thk = slab_thk_by_storey.get(bottom_storey_key) if bottom_storey_key else None
            if bottom_thk is None:
                bottom_thk = default_slab_thk
            bottom_ids = slab_ids_by_storey.get(bottom_storey_key, []) if bottom_storey_key else []

            # top slab thickness from NEXT storey (Revit typical: floor slab assigned to level above)
            top_storey_key = str(next_storey_stepid) if next_storey_stepid else bottom_storey_key
            top_thk = slab_thk_by_storey.get(top_storey_key) if top_storey_key else None
            if top_thk is None:
                top_thk = default_slab_thk
            top_ids = slab_ids_by_storey.get(top_storey_key, []) if top_storey_key else []

            bottom_meta = {}
            if isinstance(bottom_thk, (int, float)):
                bottom_meta["slab_thickness_m"] = _r4(bottom_thk)
            if sid_storey:
                bottom_meta["slab_storey_stepid"] = sid_storey
            if bottom_ids:
                bottom_meta["ifc_slab_stepids"] = bottom_ids

            top_meta = {}
            if isinstance(top_thk, (int, float)):
                top_meta["slab_thickness_m"] = _r4(top_thk)
            if next_storey_stepid:
                top_meta["slab_storey_stepid"] = next_storey_stepid
            elif sid_storey:
                top_meta["slab_storey_stepid"] = sid_storey
            if top_ids:
                top_meta["ifc_slab_stepids"] = top_ids

            # also store the vertical gap to the next storey elevation when available (useful for debugging)
            try:
                if next_storey_stepid and str(next_storey_stepid) in storey_elev_by_stepid:
                    z_top = float(z0_m) + float(h_m)
                    gap = float(storey_elev_by_stepid[str(next_storey_stepid)]) - float(z_top)
                    top_meta["z_gap_to_next_storey_elev_m"] = _r4(gap)
            except Exception:
                pass

            rec["idf_surfaces"] = build_idf_surfaces_from_footprint_m(
                rec["geometry"]["footprint_world_m"],
                z0_m,
                h_m,
                zone_name,
                bottom_meta=bottom_meta,
                top_meta=top_meta,
            )


            # -------------------------
            # V2: host IFC mapping (metadata only; does NOT modify geometry)
            # -------------------------
            try:
                storey_sid = seed.get("StoreyStepId")
                idf = rec.get("idf_surfaces") or {}
                # Walls
                wlist = idf.get("walls") or []
                for ws in wlist:
                    ws["host_ifc_wall"] = match_wall_surface_to_ifc_wall(
                        ws, storey_sid, wall_candidates, results, dist_tol_m=1.0
                    )

                # Bottom slab host (same storey)
                bslab = idf.get("bottom_slab") if isinstance(idf.get("bottom_slab"), dict) else None
                if bslab and isinstance(bslab.get("vertices_3d"), list):
                    z0_tgt = float(z0_m)
                    best, cands = match_slab_by_xy_and_z(
                        bslab.get("vertices_3d"),
                        z0_tgt,
                        slab_candidates,
                        storey_sid,
                        allow_storeys=None,
                        z_band=(0.35, 0.35),
                    )
                    bslab["host_ifc_slab"] = (best or (cands[0] if cands else {}))

                # Top slab host (consider same storey + next storey; use synthetic top z as anchor)
                tslab = idf.get("top_slab") if isinstance(idf.get("top_slab"), dict) else None
                if tslab and isinstance(tslab.get("vertices_3d"), list):
                    ztop_tgt = float(z0_m) + float(h_m)
                    # allow same storey and next storey (if known)
                    allow = set()
                    has_next_storey = False
                    if storey_sid:
                        allow.add(storey_sid)
                        try:
                            i = stepid_to_index.get(str(storey_sid))
                            if i is not None and 1 <= int(i) < len(storey_order):
                                nxt = storey_order[int(i)]  # StoreyIndex is 1-based; list is 0-based
                                if nxt:
                                    allow.add(nxt)
                                    has_next_storey = True
                        except Exception:
                            pass
                    prefer_roof = not has_next_storey
                    # thickness hint
                    thk_hint = None
                    try:
                        thk_hint = top_meta.get("slab_thickness_m") if isinstance(top_meta, dict) else None
                    except Exception:
                        thk_hint = None
                    try:
                        thk_hint = float(thk_hint) if thk_hint not in (None, "", 0, 0.0) else None
                    except Exception:
                        thk_hint = None
                    above = 0.6 + (thk_hint or 0.3)
                    best, cands = match_slab_by_xy_and_z(
                        tslab.get("vertices_3d"),
                        ztop_tgt,
                        (slab_candidates + roof_candidates),
                        storey_sid,
                        allow_storeys=allow if allow else None,
                        z_band=(0.50, above),
                        prefer_roof=prefer_roof,
                    )
                    tslab["host_ifc_slab"] = (best or (cands[0] if cands else {}))
            except Exception:
                pass

    # Infer StoreyStepId for fenestration (IFCWINDOW/IFCDOOR) when missing,
    # using opening_rect_world_m Z location and storey elevation bands.
    for sid, rec in results.items():
        if sid == "storeys":
            continue
        seed = rec.get("seed") if isinstance(rec.get("seed"), dict) else {}
        ent = seed.get("Entity")
        if ent not in ("IFCWINDOW", "IFCDOOR"):
            continue
        if seed.get("StoreyStepId"):
            continue
        geom = rec.get("geometry") if isinstance(rec.get("geometry"), dict) else {}
        rect = geom.get("opening_rect_world_m")
        if not (isinstance(rect, list) and rect and isinstance(rect[0], (list, tuple)) and len(rect[0]) >= 3):
            continue
        try:
            zc = sum(float(p[2]) for p in rect) / float(len(rect))
        except Exception:
            continue
        stid = infer_storey_stepid_for_z_band(zc, storeys_items, elevs_sorted)
        if stid:
            seed["StoreyStepId"] = stid
            # store elevation for convenience
            for s in storeys_items:
                if s.get("StoreyStepId") == stid:
                    seed["StoreyElevation_m"] = s.get("StoreyElevation_m")
                    break
            rec["seed"] = seed

    data["results"] = results
    data = round_floats(data, 4)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {args.out}")


if __name__ == "__main__":
    main()
