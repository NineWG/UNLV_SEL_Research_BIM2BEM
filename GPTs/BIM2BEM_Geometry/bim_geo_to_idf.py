#!/usr/bin/env python3
"""
Step 7 — Generate IDF from EP-ready geometry (template injection) - V3 (Step6 schema)

Usage:
  python /mnt/data/bim_geo_to_idf_updated_v3.py /mnt/data/basic_setup.txt /mnt/data/step6_ep_ready.json --out /mnt/data/step7_output.idf

Guarantees:
- Python stdlib only
- No unit conversion (Step 6 is already meters)
- Uses Step 6 EP-ready vertices as-is (no reordering here)
- Vertex numeric formatting: 4 decimals
- Removes/replaces template objects case-insensitively:
    * Zone
    * BuildingSurface:Detailed
    * FenestrationSurface:Detailed
    * HVACTemplate:Zone:IdealLoadsAirSystem
- Supports Step6 JSON structure:
    { "zones":[ { "ZoneName":..., "surfaces":{floor/ceiling/roof/wall:[...]}, "fenestration":{doors/windows:[...]} }, ... ] }
"""

from __future__ import annotations
import argparse, json, re
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

# -------------------------
# Template parsing (verbatim-preserving)
# -------------------------
_OBJTYPE_RE = re.compile(r'^\s*([A-Za-z0-9_:]+)\s*,\s*(?:!.*)?$')

def split_idf_objects_verbatim(idf_text: str):
    """
    Split an IDF into object blocks, each including its terminating ';' line.
    Preserves formatting/comments exactly.
    Returns list of (objtype_or_None, block_text).
    """
    blocks=[]
    cur=[]
    objtype=None
    for ln in idf_text.splitlines():
        cur.append(ln)
        if objtype is None:
            if ln.strip().startswith('!'):
                pass
            else:
                m=_OBJTYPE_RE.match(ln)
                if m:
                    objtype=m.group(1)

        raw = ln
        if '!' in raw:
            raw = raw.split('!')[0]
        if ';' in raw:
            blocks.append((objtype, "\n".join(cur).rstrip() + "\n"))
            cur=[]
            objtype=None
    if cur:
        blocks.append((objtype, "\n".join(cur).rstrip() + "\n"))
    return blocks

def extract_fields_keep_empty(obj_block: str):
    """
    Extract (objtype, fields) from a block. Keeps empty fields. Strips inline comments.
    Fields returned exclude trailing ';'.
    """
    cleaned=[]
    for ln in obj_block.splitlines():
        if '!' in ln:
            ln = ln.split('!')[0]
        cleaned.append(ln)
    txt="\n".join(cleaned)

    m=re.search(r'^\s*([A-Za-z0-9_:]+)\s*,', txt, flags=re.MULTILINE)
    if not m:
        return None, []

    objtype=m.group(1)
    after=txt[m.end():]
    semi = after.find(';')
    if semi != -1:
        after = after[:semi]
    parts = [p.strip() for p in after.split(',')]
    return objtype, parts

def format_idf_object(objtype: str, fields: List[str]):
    lines=[f"{objtype},"]
    for i, val in enumerate(fields):
        end="," if i < len(fields)-1 else ";"
        lines.append(f"    {val}{end}")
    return "\n".join(lines) + "\n"

# -------------------------
# Mappings
# -------------------------
def ep_obc(obc: str) -> str:
    """Map pipeline OBC to EnergyPlus tokens."""
    o=(obc or "").strip().lower()
    if o in ("outdoor","outdoors"):
        return "Outdoors"
    if o=="surface":
        return "Surface"
    if o=="ground":
        return "Ground"
    if o=="adiabatic":
        return "Adiabatic"
    # fallback
    return "Outdoors"

def sun_wind_for_obc(ep_obc_token: str):
    if ep_obc_token.lower()=="outdoors":
        return "SunExposed","WindExposed"
    return "NoSun","NoWind"

def ep_surface_type(surface_type: str) -> str:
    st=(surface_type or "").strip().lower()
    if st=="floor":
        return "Floor"
    if st=="roof":
        return "Roof"
    if st=="ceiling":
        return "Ceiling"
    if st=="wall":
        return "Wall"
    # fallback
    return "Wall"

def construction_for_surface(ep_stype: str, ep_obc_token: str) -> str:
    st=ep_stype.lower()
    o=ep_obc_token.lower()
    if st=="wall":
        return "Interior Wall" if o in ("surface","adiabatic") else "Exterior Wall"
    if st=="floor":
        return "Interior Floor" if o in ("surface","adiabatic") else "Exterior Floor"
    if st in ("roof","ceiling"):
        # Ceiling between zones uses "Interior Ceiling", roof/exterior uses "Exterior Roof"
        return "Interior Ceiling" if o in ("surface","adiabatic") else "Exterior Roof"
    return "Exterior Wall"

# -------------------------
# Builders
# -------------------------
def fmt4(x: float) -> str:
    return f"{float(x):.4f}"

def build_zone_obj(zone_name: str, template_fields: List[str]):
    f=list(template_fields)
    if not f:
        f=[""]
    f[0]=zone_name
    return format_idf_object("Zone", f)

def build_ideal_obj(zone_name: str, template_fields: List[str]):
    f=list(template_fields)
    if not f:
        f=[""]
    f[0]=zone_name
    return format_idf_object("HVACTemplate:Zone:IdealLoadsAirSystem", f)

def build_buildingsurface(surface: Dict[str, Any], zone_name: str, surface_type_hint: Optional[str]=None):
    name = surface.get("name") or surface.get("surface_id") or "Surface"
    stype = ep_surface_type(surface_type_hint or surface.get("SurfaceType") or surface.get("surface_type") or "Wall")
    epobc = ep_obc(surface.get("OutsideBoundaryCondition") or "Outdoors")
    obco  = surface.get("OutsideBoundaryConditionObject") or ""
    sun, wind = sun_wind_for_obc(epobc)
    constr = construction_for_surface(stype, epobc)

    verts = surface.get("vertices_3d") or []
    fields = [
        str(name),
        stype,
        constr,
        zone_name,
        "",                 # Space Name (blank)
        epobc,
        str(obco),
        sun,
        wind,
        "",                 # View Factor to Ground (blank)
        str(len(verts))
    ]
    for v in verts:
        fields += [fmt4(v[0]), fmt4(v[1]), fmt4(v[2])]
    return format_idf_object("BuildingSurface:Detailed", fields)

def build_fenestration(fobj: Dict[str, Any], host_obc: Optional[str]):
    name = fobj.get("name") or fobj.get("surface_id") or fobj.get("StepId") or "Fenestration"
    ent = (fobj.get("SurfaceType") or fobj.get("Entity") or fobj.get("fenestration_type") or "").strip().lower()
    if ent in ("ifcdoor","door"):
        ftype="Door"
        constr = "Interior Door" if (host_obc or "").lower() in ("surface","adiabatic") else "Exterior Door"
    else:
        ftype="Window"
        constr = "Interior Window" if (host_obc or "").lower() in ("surface","adiabatic") else "Exterior Window"

    host = fobj.get("BuildingSurfaceName") or ""
    verts = fobj.get("opening_rect_world_m") or fobj.get("vertices_3d") or []
    # Keep optional fields blank to match template
    fields = [
        str(name),
        ftype,
        constr,
        str(host),
        "",   # Outside Boundary Condition Object
        "",   # View Factor to Ground
        "",   # Frame and Divider Name
        "",   # Multiplier
        str(len(verts)),
    ]
    for v in verts:
        fields += [fmt4(v[0]), fmt4(v[1]), fmt4(v[2])]
    return format_idf_object("FenestrationSurface:Detailed", fields)

# -------------------------
# Injection
# -------------------------
def inject(template_path: Path, ep_geo: Dict[str, Any], out_path: Path):
    tpl_text = template_path.read_text(encoding="utf-8", errors="ignore")
    blocks = split_idf_objects_verbatim(tpl_text)

    remove_types = {
        "zone",
        "buildingsurface:detailed",
        "fenestrationsurface:detailed",
        "hvactemplate:zone:idealloadsairsystem",
    }

    kept=[]
    template_zone_fields=None
    template_ideal_fields=None

    for t, blk in blocks:
        tl = (t or "").lower()
        if tl in remove_types:
            if tl=="zone" and template_zone_fields is None:
                _, template_zone_fields = extract_fields_keep_empty(blk)
            if tl=="hvactemplate:zone:idealloadsairsystem" and template_ideal_fields is None:
                _, template_ideal_fields = extract_fields_keep_empty(blk)
            continue
        kept.append(blk)

    if template_zone_fields is None:
        template_zone_fields=["", "0.0", "0.0", "0.0", "0.0", "", "1"]
    if template_ideal_fields is None:
        template_ideal_fields=["", "Constant Setpoint Thermostat", "", "50", "13"]

    zones = ep_geo.get("zones") or []
    # stable order
    zone_names=[z.get("ZoneName") for z in zones if z.get("ZoneName")]

    # host wall OBC lookup (for fenestration construction selection)
    host_obc={}
    for z in zones:
        for w in (z.get("surfaces", {}).get("wall") or []):
            host_obc[w.get("name")] = ep_obc(w.get("OutsideBoundaryCondition") or "Outdoors")

    zone_objs=[build_zone_obj(zn, template_zone_fields) for zn in zone_names]
    ideal_objs=[build_ideal_obj(zn, template_ideal_fields) for zn in zone_names]

    bs_objs=[]
    fen_objs=[]
    for z in zones:
        zn = z.get("ZoneName") or ""
        surfs = z.get("surfaces", {}) or {}
        for stype in ("floor","ceiling","roof","wall"):
            for s in (surfs.get(stype) or []):
                bs_objs.append(build_buildingsurface(s, zn, surface_type_hint=stype))
        fen = z.get("fenestration", {}) or {}
        for f in (fen.get("doors") or fen.get("door") or []):
            fen_objs.append(build_fenestration(f, host_obc.get(f.get("BuildingSurfaceName"))))
        for f in (fen.get("windows") or fen.get("window") or []):
            fen_objs.append(build_fenestration(f, host_obc.get(f.get("BuildingSurfaceName"))))

    out_parts=[]
    out_parts.extend(kept)
    out_parts.append("!- ======= AUTO-GENERATED ZONES =======\n")
    out_parts.extend(zone_objs)
    out_parts.append("!- ======= AUTO-GENERATED BUILDINGSURFACE:DETAILED =======\n")
    out_parts.extend(bs_objs)
    out_parts.append("!- ======= AUTO-GENERATED FENESTRATION =======\n")
    out_parts.extend(fen_objs)
    out_parts.append("!- ======= AUTO-GENERATED HVAC IDEAL LOADS (ONE PER ZONE) =======\n")
    out_parts.extend(ideal_objs)

    out_path.write_text("\n".join(p.rstrip("\n") for p in out_parts).rstrip()+"\n", encoding="utf-8")

# -------------------------
# Main
# -------------------------
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("template_idf")
    ap.add_argument("step6_json")
    ap.add_argument("--out", required=True)
    args=ap.parse_args()

    tpl=Path(args.template_idf)
    js=Path(args.step6_json)
    out=Path(args.out)

    ep_geo=json.loads(js.read_text(encoding="utf-8"))
    inject(tpl, ep_geo, out)
    print(f"Wrote IDF: {out}")

if __name__=="__main__":
    main()
