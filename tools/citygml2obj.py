"""PLATEAU CityGML (bldg) → OBJ+MTL+テクスチャ 変換。

広島市2024 CityGML（EPSG:6697 = JGD2011 緯度経度+標高、posListは「緯度 経度 高さ」順）の
建物LOD2（無ければLOD1）を、原爆ドーム基準のローカルENU座標系
（X=東, Y=上, Z=南。web-metaverseの src/geo.ts と同一）のOBJに変換する。

- テクスチャ: app:ParameterizedTexture の imageURI を out/textures/ へコピー
  （長辺2048px超はVRAM対策で2048に縮小 — web-metaverse実測の知見）
- UV: app:textureCoordinates の ring 参照（#ringId）で LinearRing に対応付け
- 三角形分割: 面の法線（Newell法）平面へ投影して mapbox_earcut
- 出力: メッシュコード毎に <mesh>.obj / <mesh>.mtl

使い方:
    python tools/citygml2obj.py <gmlファイル...> --out data/obj
"""

import argparse
import math
import shutil
import sys
from pathlib import Path

import mapbox_earcut
import numpy as np
from lxml import etree
from PIL import Image

# ワールド原点 = 原爆ドーム前（web-metaverse src/tilesets.ts ORIGIN と同一）
ORIGIN_LAT = 34.39561
ORIGIN_LON = 132.45347

# WGS84/GRS80 楕円体（JGD2011はGRS80だが、この用途では差は無視できる）
A = 6378137.0
F = 1 / 298.257223563
E2 = F * (2 - F)

_lat0 = math.radians(ORIGIN_LAT)
_sin2 = math.sin(_lat0) ** 2
MERIDIONAL = A * (1 - E2) / (1 - E2 * _sin2) ** 1.5
PRIME_VERT = A / math.sqrt(1 - E2 * _sin2)

NS = {
    "core": "http://www.opengis.net/citygml/2.0",
    "bldg": "http://www.opengis.net/citygml/building/2.0",
    "gml": "http://www.opengis.net/gml",
    "app": "http://www.opengis.net/citygml/appearance/2.0",
}
GML_ID = "{http://www.opengis.net/gml}id"

MAX_TEX = 2048  # テクスチャ長辺の上限[px]


def latlon_to_local(lat: float, lon: float, h: float):
    """緯度経度→ローカルENU（X=東, Y=上, Z=南）。geo.ts localToLatLon の逆変換。"""
    x = math.radians(lon - ORIGIN_LON) * PRIME_VERT * math.cos(_lat0)
    z = -math.radians(lat - ORIGIN_LAT) * MERIDIONAL
    return x, h, z


def parse_poslist(text: str):
    v = text.split()
    pts = []
    for i in range(0, len(v) - 2, 3):
        lat, lon, h = float(v[i]), float(v[i + 1]), float(v[i + 2])
        pts.append(latlon_to_local(lat, lon, h))
    return pts


def ring_points(ring_el):
    pl = ring_el.find("gml:posList", NS)
    if pl is None or not pl.text:
        return []
    pts = parse_poslist(pl.text)
    # 閉環（先頭=末尾）は末尾を落とす
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def triangulate(exterior, holes):
    """3D多角形（外環+穴）を法線平面投影+earcutで三角形化。頂点indexのタプル列を返す。"""
    all_pts = exterior + [p for h in holes for p in h]
    if len(exterior) < 3:
        return []
    pts = np.array(all_pts, dtype=np.float64)
    # Newell法で法線
    n = np.zeros(3)
    e = np.array(exterior)
    for i in range(len(e)):
        j = (i + 1) % len(e)
        n[0] += (e[i][1] - e[j][1]) * (e[i][2] + e[j][2])
        n[1] += (e[i][2] - e[j][2]) * (e[i][0] + e[j][0])
        n[2] += (e[i][0] - e[j][0]) * (e[i][1] + e[j][1])
    ln = np.linalg.norm(n)
    if ln < 1e-12:
        return []
    n /= ln
    # 平面基底
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(n, a)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    pts2 = np.stack([pts @ u, pts @ v], axis=1)
    rings = []
    end = len(exterior)
    rings.append(end)
    for h in holes:
        end += len(h)
        rings.append(end)
    try:
        idx = mapbox_earcut.triangulate_float64(pts2, np.array(rings, dtype=np.uint32))
    except Exception:
        return []
    tris = [(int(idx[i]), int(idx[i + 1]), int(idx[i + 2])) for i in range(0, len(idx), 3)]
    # earcutの向きが実法線と逆なら反転（投影基底の掌性に依存するため実測で合わせる）
    if tris:
        i0, i1, i2 = tris[0]
        tn = np.cross(pts[i1] - pts[i0], pts[i2] - pts[i0])
        if np.dot(tn, n) < 0:
            tris = [(c, b, a2) for a2, b, c in tris]
    return tris


def load_appearance(root):
    """polyId→imageURI と ringId→UV列 の対応表を作る。"""
    tex_by_poly = {}
    uv_by_ring = {}
    for pt in root.iterfind(".//app:ParameterizedTexture", NS):
        uri_el = pt.find("app:imageURI", NS)
        if uri_el is None or not uri_el.text:
            continue
        uri = uri_el.text.strip()
        for tgt in pt.iterfind("app:target", NS):
            poly_ref = (tgt.get("uri") or "").lstrip("#")
            if poly_ref:
                tex_by_poly[poly_ref] = uri
            for tc in tgt.iterfind(".//app:textureCoordinates", NS):
                ring_ref = (tc.get("ring") or "").lstrip("#")
                if not ring_ref or not tc.text:
                    continue
                vals = tc.text.split()
                uv_by_ring[ring_ref] = [
                    (float(vals[i]), float(vals[i + 1])) for i in range(0, len(vals) - 1, 2)
                ]
    return tex_by_poly, uv_by_ring


def building_polygons(b):
    """Building（Part含む）のLOD2面（無ければLOD1）のgml:Polygon列。"""
    polys = []
    for ms in b.iterfind(".//bldg:lod2MultiSurface", NS):
        polys.extend(ms.iter("{http://www.opengis.net/gml}Polygon"))
    if not polys:
        for s in b.iterfind(".//bldg:lod1Solid", NS):
            polys.extend(s.iter("{http://www.opengis.net/gml}Polygon"))
    return polys


def convert(gml_path: Path, out_dir: Path):
    mesh = gml_path.stem.split("_")[0]
    tree = etree.parse(str(gml_path))
    root = tree.getroot()
    tex_by_poly, uv_by_ring = load_appearance(root)

    tex_dir = out_dir / "textures" / mesh
    tex_dir.mkdir(parents=True, exist_ok=True)

    # マテリアル（=テクスチャ画像）毎に面を貯める
    verts = []          # (x,y,z)
    uvs = []            # (u,v)
    faces_by_mat = {}   # mat名 → [(vi,vti|None)×3, ...]
    copied = {}         # imageURI → mat名

    n_bldg = 0
    for b in root.iterfind(".//bldg:Building", NS):
        polys = building_polygons(b)
        if not polys:
            continue
        n_bldg += 1
        for poly in polys:
            pid = poly.get(GML_ID) or ""
            ext_el = poly.find("gml:exterior/gml:LinearRing", NS)
            if ext_el is None:
                continue
            exterior = ring_points(ext_el)
            if len(exterior) < 3:
                continue
            holes = []
            hole_els = []
            for hel in poly.iterfind("gml:interior/gml:LinearRing", NS):
                hp = ring_points(hel)
                if len(hp) >= 3:
                    holes.append(hp)
                    hole_els.append(hel)
            tris = triangulate(exterior, holes)
            if not tris:
                continue

            # UV: 外環+穴の順で頂点に対応させる（閉環の重複分は ring_points と同じく末尾破棄）
            uri = tex_by_poly.get(pid)
            ring_els = [ext_el] + hole_els
            ring_pts = [exterior] + holes
            poly_uvs = None
            if uri:
                poly_uvs = []
                ok = True
                for rel, rp in zip(ring_els, ring_pts):
                    rid = rel.get(GML_ID) or ""
                    ruv = uv_by_ring.get(rid)
                    if ruv is None:
                        ok = False
                        break
                    if len(ruv) == len(rp) + 1:
                        ruv = ruv[:-1]
                    if len(ruv) != len(rp):
                        ok = False
                        break
                    poly_uvs.extend(ruv)
                if not ok:
                    poly_uvs = None

            if uri and poly_uvs is not None:
                if uri not in copied:
                    src = gml_path.parent / uri
                    mat = f"m{len(copied):04d}"
                    dst = tex_dir / (mat + src.suffix.lower())
                    if src.exists():
                        _copy_downscaled(src, dst)
                        copied[uri] = mat
                    else:
                        copied[uri] = None
                mat = copied[uri] or "untextured"
            else:
                mat = "untextured"

            base_v = len(verts)
            base_vt = len(uvs)
            pts_all = exterior + [p for h in holes for p in h]
            verts.extend(pts_all)
            if mat != "untextured" and poly_uvs is not None:
                uvs.extend(poly_uvs)
                fl = faces_by_mat.setdefault(mat, [])
                for t in tris:
                    fl.append(tuple((base_v + i, base_vt + i) for i in t))
            else:
                fl = faces_by_mat.setdefault("untextured", [])
                for t in tris:
                    fl.append(tuple((base_v + i, None) for i in t))

    # 書き出し
    out_dir.mkdir(parents=True, exist_ok=True)
    obj_path = out_dir / f"{mesh}.obj"
    mtl_path = out_dir / f"{mesh}.mtl"
    with open(mtl_path, "w", encoding="ascii") as m:
        m.write("newmtl untextured\nKd 0.82 0.80 0.78\n")
        for uri, mat in copied.items():
            if mat is None:
                continue
            suffix = Path(uri).suffix.lower()
            m.write(f"\nnewmtl {mat}\nKd 1 1 1\nmap_Kd textures/{mesh}/{mat}{suffix}\n")
    with open(obj_path, "w", encoding="ascii") as o:
        o.write(f"mtllib {mesh}.mtl\n")
        for x, y, z in verts:
            o.write(f"v {x:.3f} {y:.3f} {z:.3f}\n")
        for u, v in uvs:
            o.write(f"vt {u:.6f} {v:.6f}\n")
        for mat, faces in faces_by_mat.items():
            o.write(f"usemtl {mat}\n")
            for f in faces:
                parts = []
                for vi, vti in f:
                    parts.append(f"{vi+1}/{vti+1}" if vti is not None else f"{vi+1}")
                o.write("f " + " ".join(parts) + "\n")
    print(f"{mesh}: buildings={n_bldg} verts={len(verts)} mats={len(faces_by_mat)} -> {obj_path.name}")


def _copy_downscaled(src: Path, dst: Path):
    try:
        img = Image.open(src)
        if max(img.size) > MAX_TEX:
            s = MAX_TEX / max(img.size)
            img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
            img.save(dst, quality=88)
        else:
            shutil.copyfile(src, dst)
    except Exception as e:
        print(f"  texture error {src.name}: {e}", file=sys.stderr)
        shutil.copyfile(src, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gml", nargs="+")
    ap.add_argument("--out", default="data/obj")
    args = ap.parse_args()
    out = Path(args.out)
    for g in args.gml:
        convert(Path(g), out)


if __name__ == "__main__":
    main()
