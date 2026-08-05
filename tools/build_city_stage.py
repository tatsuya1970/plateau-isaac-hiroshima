"""広島都市ステージ（hiroshima_city.usd）を構築する。

- Z-up・メートル単位。/Terrain 直下に:
  - City: 9タイルのUSD参照（OBJ由来Y-up → X+90°回転でZ-upへ）
  - Ground: 地面平面（標高2.35m = 建物基部の実測5パーセンタイル）
- 全メッシュに静的コライダー（UsdPhysics.CollisionAPI、三角形メッシュ近似）を付与
  → Isaac Lab の TerrainImporter(terrain_type="usd") がそのまま読める

使い方:
    python tools/build_city_stage.py [--out data/usd/hiroshima_city.usd]
"""

import argparse
from pathlib import Path

from isaacsim import SimulationApp

_app = SimulationApp({"headless": True})

from pxr import Usd, UsdGeom, UsdPhysics  # noqa: E402

GROUND_Z = 2.35
GROUND_HALF = 1600.0  # 地面平面の半径[m]（タイル9枚≈3km四方をカバー）


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/usd/hiroshima_city.usd")
    ap.add_argument("--usd_dir", default="data/usd")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    stage = Usd.Stage.CreateNew(str(out))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/Terrain")
    stage.SetDefaultPrim(root.GetPrim())

    # 都市タイル（Y-up→Z-up）
    city = UsdGeom.Xform.Define(stage, "/Terrain/City")
    city.AddRotateXOp().Set(90.0)
    usd_dir = Path(args.usd_dir).resolve()
    tiles = sorted(p for p in usd_dir.glob("513243*.usd"))
    for t in tiles:
        prim = stage.DefinePrim(f"/Terrain/City/tile_{t.stem}", "Xform")
        prim.GetReferences().AddReference(str(t))
    print(f"referenced {len(tiles)} tiles")

    # 地面平面（Z-up）
    ground = UsdGeom.Mesh.Define(stage, "/Terrain/Ground")
    h = GROUND_HALF
    ground.CreatePointsAttr([(-h, -h, GROUND_Z), (h, -h, GROUND_Z), (h, h, GROUND_Z), (-h, h, GROUND_Z)])
    ground.CreateFaceVertexCountsAttr([4])
    ground.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    ground.CreateDisplayColorAttr([(0.28, 0.28, 0.29)])  # アスファルト色

    # コライダー付与（全メッシュ＝静的三角形メッシュ）
    n_col = 0
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            UsdPhysics.CollisionAPI.Apply(prim)
            mesh_col = UsdPhysics.MeshCollisionAPI.Apply(prim)
            mesh_col.CreateApproximationAttr().Set(UsdPhysics.Tokens.none)
            n_col += 1
    print(f"colliders applied: {n_col} meshes")

    stage.GetRootLayer().Save()
    print("saved:", out)


if __name__ == "__main__":
    main()
    _app.close()
