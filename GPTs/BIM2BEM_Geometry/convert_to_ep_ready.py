"""convert_to_ep_ready.py  (Step 6)

Input:
  step5_obc.json
Output:
  step6_ep_ready.json

Responsibilities:
- NO unit conversion (geometry already meters).
- Remove repeated closing vertex if last ~= first.
- Enforce EnergyPlus-facing vertex ordering:
    * Floors: outside normal = -Z
    * Ceilings/Roofs: outside normal = +Z
    * Walls: outside normal = outward from the zone footprint (robust for concave footprints)
    * Fenestration: match host wall normal
- Rotate vertices so Vertex1 is the **UpperLeftCorner** from the outside view.
- For every Surface<->Surface pair (walls + slabs): ensure opposite normals by flipping mate if needed.
- Recursively round all numeric values to 4 decimals.

Stdlib only.
"""

import argparse
import json
import math
from typing import Any, Dict, List, Optional, Tuple

Vec = Tuple[float, float, float]
Pt = Tuple[float, float, float]


# -------------------------
# Rounding
# -------------------------

def round4(x):
    if x is None or isinstance(x, bool):
        return x
    if isinstance(x, int):
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
# Basic vector math
# -------------------------

def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def mul(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def norm(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec) -> Vec:
    n = norm(a)
    if n <= 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


# -------------------------
# Geometry helpers
# -------------------------

def remove_closing_vertex(pts: List[Pt], tol: float = 1e-6) -> List[Pt]:
    if len(pts) >= 4:
        a = pts[0]
        b = pts[-1]
        if abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol and abs(a[2] - b[2]) <= tol:
            return pts[:-1]
    return pts


def plane_from_pts(pts: List[Pt]) -> Tuple[Vec, float]:
    """Return (unit normal, d) for plane n·x = d."""
    if len(pts) < 3:
        return (0.0, 0.0, 1.0), 0.0
    p0 = pts[0]
    # find non-collinear triplet
    for i in range(1, len(pts) - 1):
        v1 = sub(pts[i], p0)
        v2 = sub(pts[i + 1], p0)
        n = cross(v1, v2)
        if norm(n) > 1e-12:
            n = unit(n)
            d = dot(n, p0)
            return n, d
    return (0.0, 0.0, 1.0), dot((0.0, 0.0, 1.0), pts[0])


def polygon_area_2d_xy(pts: List[Tuple[float, float]]) -> float:
    if len(pts) < 3:
        return 0.0
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return 0.5 * a


def make_view_basis_from_normal(out_n: Vec) -> Tuple[Vec, Vec]:
    """Build deterministic orthonormal basis (u,v) for a view plane.

    u: "right" in the outside view, v: "up" in the outside view.
    """
    n = unit(out_n)
    up = (0.0, 0.0, 1.0)
    if abs(dot(up, n)) > 0.95:
        up = (0.0, 1.0, 0.0)
    u = unit(cross(up, n))
    v = unit(cross(n, u))
    return u, v


def upper_left_index(pts: List[Pt], out_n: Vec) -> int:
    """Return index of vertex that is upper-left in the outside view."""
    u, v = make_view_basis_from_normal(out_n)
    origin = pts[0]
    best_i = 0
    best_key = None
    for i, p in enumerate(pts):
        d = sub(p, origin)
        x_u = dot(d, u)
        y_v = dot(d, v)
        # upper-left => maximize y, then maximize -x
        key = (y_v, -x_u)
        if best_key is None or key > best_key:
            best_key = key
            best_i = i
    return best_i


def rotate_to_index(pts: List[Pt], i0: int) -> List[Pt]:
    if not pts:
        return pts
    i0 = i0 % len(pts)
    return pts[i0:] + pts[:i0]


def enforce_ccw_and_upperleft(pts: List[Pt], desired_out: Vec) -> List[Pt]:
    """Ensure polygon is CCW when viewed from desired_out, then rotate to UpperLeft."""
    pts = remove_closing_vertex(list(pts))
    if len(pts) < 3:
        return pts

    n, _ = plane_from_pts(pts)
    # If normal points opposite of desired_out, reverse
    if dot(n, desired_out) < 0:
        pts = list(reversed(pts))

    # Rotate to upper-left
    idx = upper_left_index(pts, desired_out)
    pts = rotate_to_index(pts, idx)
    return pts


def wall_base_segment_xy(verts: List[Pt]) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Pick two lowest-Z points that form the widest base segment in XY."""
    zs = [p[2] for p in verts]
    zmin = min(zs)
    low = [p for p in verts if abs(p[2] - zmin) <= 1e-6]
    if len(low) < 2:
        low = sorted(verts, key=lambda p: p[2])[:2]
    # choose pair with max XY distance
    best = (low[0], low[1])
    bestd = -1.0
    for i in range(len(low)):
        for j in range(i + 1, len(low)):
            dx = low[j][0] - low[i][0]
            dy = low[j][1] - low[i][1]
            d = dx * dx + dy * dy
            if d > bestd:
                bestd = d
                best = (low[i], low[j])
    return (best[0][0], best[0][1]), (best[1][0], best[1][1])


# -------------------------
# Point in polygon (XY)
# -------------------------

def _pt_on_seg_xy(px, py, ax, ay, bx, by, tol=1e-9):
    if px < min(ax, bx) - tol or px > max(ax, bx) + tol or py < min(ay, by) - tol or py > max(ay, by) + tol:
        return False
    crossv = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(crossv) > tol * (abs(bx - ax) + abs(by - ay) + 1.0):
        return False
    return True


def point_in_poly_xy(px: float, py: float, poly: List[Tuple[float, float]], tol: float = 1e-9) -> bool:
    """Ray casting (boundary treated as inside)."""
    if not poly or len(poly) < 3:
        return False
    inside = False
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        if _pt_on_seg_xy(px, py, ax, ay, bx, by, tol=tol):
            return True
        cond = (ay > py) != (by > py)
        if cond:
            xint = ax + (py - ay) * (bx - ax) / (by - ay)
            if xint > px:
                inside = not inside
    return inside


# -------------------------
# Wall outside direction (robust)
# -------------------------

def wall_out_dir_from_zone_polygon(verts: List[Pt], zone_poly: Optional[List[Tuple[float, float]]]) -> Optional[Tuple[float, float]]:
    """Determine outward XY direction for a wall using point-in-polygon test.

    Works on concave footprints because it uses the wall segment direction and checks
    which side is outside the zone polygon.
    """
    if not zone_poly or len(zone_poly) < 3:
        return None

    (a, b) = wall_base_segment_xy(verts)
    ex = b[0] - a[0]
    ey = b[1] - a[1]
    L = math.hypot(ex, ey)
    if L <= 1e-12:
        return None

    # candidate perp (left normal)
    nx, ny = (-ey / L, ex / L)
    mx, my = ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)

    eps = 0.05
    p1 = (mx + eps * nx, my + eps * ny)
    p2 = (mx - eps * nx, my - eps * ny)

    in1 = point_in_poly_xy(p1[0], p1[1], zone_poly)
    in2 = point_in_poly_xy(p2[0], p2[1], zone_poly)

    if in1 and not in2:
        return (-nx, -ny)
    if not in1 and in2:
        return (nx, ny)

    # ambiguous -> fallback: use zone center
    cx = sum(x for x, y in zone_poly) / len(zone_poly)
    cy = sum(y for x, y in zone_poly) / len(zone_poly)
    vx, vy = (mx - cx, my - cy)
    L2 = math.hypot(vx, vy)
    if L2 > 1e-12:
        return (vx / L2, vy / L2)
    return None


# -------------------------
# Snap points to plane (fenestration)
# -------------------------

def snap_to_plane(pts: List[Pt], n: Vec, d: float) -> List[Pt]:
    n = unit(n)
    out = []
    for p in pts:
        dist = dot(n, p) - d
        out.append((p[0] - dist * n[0], p[1] - dist * n[1], p[2] - dist * n[2]))
    return out


# -------------------------
# Main
# -------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("in_json")
    ap.add_argument("out_json")
    args = ap.parse_args()

    with open(args.in_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    zones = data.get("zones") or []

    # Build surface maps (by name) for pairing and fenestration
    surfaces_by_name: Dict[str, Dict[str, Any]] = {}
    wall_by_name: Dict[str, Dict[str, Any]] = {}

    for z in zones:
        for stype, lst in (z.get("surfaces") or {}).items():
            for s in (lst or []):
                nm = s.get("name")
                if nm:
                    surfaces_by_name[nm] = s
                    if stype == "wall":
                        wall_by_name[nm] = s

    # 1) Orient floors / ceilings / roofs
    for z in zones:
        surfs = z.get("surfaces", {}) or {}
        for fobj in (surfs.get("floor") or []):
            pts = [tuple(p) for p in fobj.get("vertices_3d", [])]
            pts = enforce_ccw_and_upperleft(pts, (0.0, 0.0, -1.0))
            fobj["vertices_3d"] = [list(p) for p in pts]
        for cobj in (surfs.get("ceiling") or []):
            pts = [tuple(p) for p in cobj.get("vertices_3d", [])]
            pts = enforce_ccw_and_upperleft(pts, (0.0, 0.0, 1.0))
            cobj["vertices_3d"] = [list(p) for p in pts]
        for robj in (surfs.get("roof") or []):
            pts = [tuple(p) for p in robj.get("vertices_3d", [])]
            pts = enforce_ccw_and_upperleft(pts, (0.0, 0.0, 1.0))
            robj["vertices_3d"] = [list(p) for p in pts]

    # 2) Walls: outward from zone footprint (robust)
    for z in zones:
        surfs = z.get("surfaces", {}) or {}

        zone_poly = None
        if isinstance(z.get("footprint_xy"), list) and len(z.get("footprint_xy")) >= 3:
            zone_poly = [(float(x), float(y)) for x, y in z.get("footprint_xy")]
        else:
            floors = surfs.get("floor") or []
            if floors:
                fp = floors[0].get("vertices_3d", [])
                if isinstance(fp, list) and len(fp) >= 3:
                    zone_poly = [(float(p[0]), float(p[1])) for p in fp]

        for w in (surfs.get("wall") or []):
            verts = [tuple(p) for p in w.get("vertices_3d", [])]
            if len(verts) < 3:
                continue

            out_xy = wall_out_dir_from_zone_polygon(verts, zone_poly)
            if out_xy is None:
                # fallback: current plane normal
                n, _ = plane_from_pts(verts)
                verts = enforce_ccw_and_upperleft(verts, n)
            else:
                desired_out = unit((out_xy[0], out_xy[1], 0.0))
                verts = enforce_ccw_and_upperleft(verts, desired_out)
            w["vertices_3d"] = [list(p) for p in verts]

    # 3) Surface<->Surface pairs: ensure opposite normals for ALL types
    surf_normal: Dict[str, Vec] = {}
    for z in zones:
        for stype, lst in (z.get("surfaces") or {}).items():
            for s in (lst or []):
                name = s.get("name")
                pts = [tuple(p) for p in s.get("vertices_3d", [])]
                n, _ = plane_from_pts(pts)
                if name:
                    surf_normal[name] = n

    visited = set()
    for z in zones:
        for stype, lst in (z.get("surfaces") or {}).items():
            for s in (lst or []):
                if (s.get("OutsideBoundaryCondition") or "") != "Surface":
                    continue
                a = s.get("name")
                b = s.get("OutsideBoundaryConditionObject")
                if not a or not b:
                    continue
                if (a, b) in visited or (b, a) in visited:
                    continue
                if b not in surfaces_by_name:
                    continue

                n1 = surf_normal.get(a)
                n2 = surf_normal.get(b)
                if n1 is None or n2 is None:
                    continue
                if dot(n1, n2) > 0:
                    mate = surfaces_by_name[b]
                    pts = [tuple(p) for p in mate.get("vertices_3d", [])]
                    pts = list(reversed(pts))
                    pts = enforce_ccw_and_upperleft(pts, mul(n1, -1.0))
                    mate["vertices_3d"] = [list(p) for p in pts]
                    n2, _ = plane_from_pts([tuple(p) for p in mate["vertices_3d"]])
                    surf_normal[b] = n2

                visited.add((a, b))

    # 4) Fenestration: normalize keys + orient to host wall
    def iter_fen_lists(zobj: Dict[str, Any]) -> Dict[str, Any]:
        fen = zobj.get("fenestration", {}) or {}
        # normalize variant keys
        if "doors" not in fen and "door" in fen:
            fen["doors"] = fen.get("door") or []
        if "windows" not in fen and "window" in fen:
            fen["windows"] = fen.get("window") or []
        zobj["fenestration"] = fen
        return fen

    for z in zones:
        fen = iter_fen_lists(z)
        for kind in ("doors", "windows"):
            for fobj in (fen.get(kind) or []):
                host = fobj.get("BuildingSurfaceName")
                if not host or host not in wall_by_name:
                    continue
                wall = wall_by_name[host]
                wpts = [tuple(p) for p in wall.get("vertices_3d", [])]
                wn, wd = plane_from_pts(wpts)

                raw = fobj.get("opening_rect_world_m")
                if not raw:
                    raw = fobj.get("vertices_3d")
                pts = [tuple(p) for p in (raw or [])]
                pts = remove_closing_vertex(pts)
                if len(pts) < 3:
                    continue

                pts = snap_to_plane(pts, wn, wd)
                fn, _ = plane_from_pts(pts)
                if dot(fn, wn) < 0:
                    pts = list(reversed(pts))
                pts = enforce_ccw_and_upperleft(pts, wn)

                # write back to both keys for compatibility
                fobj["vertices_3d"] = [list(p) for p in pts]
                fobj["opening_rect_world_m"] = [list(p) for p in pts]

    out = round_json(data)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())