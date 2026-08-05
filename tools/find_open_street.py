"""建物OBJの頂点分布から「開けた道路上の点」を探す（スポーン・カメラ位置決め用）。

2mグリッドで建物頂点の占有マップを作り、半径10mに建物が無い点を「開空間」、
そのうち30m以内に建物がある点を「道路（建物に囲まれた開空間）」として列挙する。
座標はZ-upワールド（X=東, Y=北）で出力。

使い方:
    python tools/find_open_street.py data/obj/51324376.obj --bbox 400 900 50 350
    python tools/find_open_street.py data/obj/51324376.obj --check 700 -128 --heading -17
"""

import argparse
import math

import numpy as np
from scipy import ndimage

RES = 2.0
CLEAR_R = 5   # 開空間の判定半径[セル]（=10m）
NEAR_R = 15   # 「建物が近い」判定半径[セル]（=30m）


def load_occupancy(obj_path, x0, x1, z0, z1):
    xs, zs = [], []
    with open(obj_path) as f:
        for ln in f:
            if ln.startswith("v "):
                p = ln.split()
                xs.append(float(p[1]))
                zs.append(float(p[3]))
    xs, zs = np.array(xs), np.array(zs)
    occ = np.zeros((int((x1 - x0) / RES), int((z1 - z0) / RES)), bool)
    m = (xs >= x0) & (xs < x1) & (zs >= z0) & (zs < z1)
    occ[((xs[m] - x0) / RES).astype(int), ((zs[m] - z0) / RES).astype(int)] = True
    return occ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("obj")
    ap.add_argument("--bbox", nargs=4, type=float, default=[400, 900, 50, 350],
                    help="ENU x0 x1 z0 z1（z=南が正）")
    ap.add_argument("--check", nargs=2, type=float, default=None,
                    help="world X Y の1点を判定（--heading とセットで経路50mも判定）")
    ap.add_argument("--heading", type=float, default=0.0)
    args = ap.parse_args()

    x0, x1, z0, z1 = args.bbox
    occ = load_occupancy(args.obj, x0, x1, z0, z1)
    free = ~ndimage.binary_dilation(occ, iterations=CLEAR_R)
    street = free & ndimage.binary_dilation(occ, iterations=NEAR_R)

    def is_free(wx, wy):
        i, j = int((wx - x0) / RES), int((-wy - z0) / RES)
        if not (0 <= i < free.shape[0] and 0 <= j < free.shape[1]):
            return None
        return bool(free[i, j])

    if args.check:
        sx, sy = args.check
        hd = math.radians(args.heading)
        print("spawn", (sx, sy), is_free(sx, sy))
        cx, cy = sx - 9 * math.cos(hd), sy - 9 * math.sin(hd)
        print("cam(behind 9m)", (round(cx, 1), round(cy, 1)), is_free(cx, cy))
        for d in (10, 20, 30, 40, 50):
            px, py = sx + d * math.cos(hd), sy + d * math.sin(hd)
            print(f"path+{d}m", (round(px), round(py)), is_free(px, py))
    else:
        pts = np.argwhere(street)
        print(f"street points: {len(pts)}")
        for i, j in pts[:: max(1, len(pts) // 20)]:
            ex, ez = x0 + i * RES, z0 + j * RES
            print(f"  world ({ex:.0f}, {-ez:.0f})")


if __name__ == "__main__":
    main()
