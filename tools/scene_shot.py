"""広島シーンの目視確認: 9タイルのUSDを読み込み、指定視点でスクリーンショットを保存。

座標系: X=東, Y=上, Z=南（原爆ドーム前が原点）。Isaac SimのステージはZ-upが既定なので、
都市タイルは Xform でY-up→Z-up（X軸+90°回転）に載せ替える。

使い方:
    python tools/scene_shot.py --out shot.png [--cam 100 -150 80] [--target 0 0 0]
"""

import argparse
from pathlib import Path

from isaacsim import SimulationApp

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="shot.png")
ap.add_argument("--cam", nargs=3, type=float, default=[250.0, -350.0, 180.0])  # Z-up world
ap.add_argument("--target", nargs=3, type=float, default=[0.0, 0.0, 20.0])
ap.add_argument("--usd_dir", default="data/usd")
args = ap.parse_args()

app = SimulationApp({"headless": True, "width": 1920, "height": 1080})

import omni.usd  # noqa: E402
from omni.kit.viewport.utility import get_active_viewport, capture_viewport_to_file  # noqa: E402
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux  # noqa: E402
import omni.kit.app  # noqa: E402

ctx = omni.usd.get_context()
ctx.new_stage()
stage = ctx.get_stage()
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
UsdGeom.SetStageMetersPerUnit(stage, 1.0)

# 都市タイル（OBJ由来はY-up想定 → X+90°でZ-upへ。Y-up時の -Z(北) が +Y(北) になる）
city = UsdGeom.Xform.Define(stage, "/World/City")
city.AddRotateXOp().Set(90.0)
usd_dir = Path(args.usd_dir)
n = 0
for usd in sorted(usd_dir.glob("*.usd")):
    ref = stage.DefinePrim(f"/World/City/tile_{usd.stem}", "Xform")
    ref.GetReferences().AddReference(str(usd.resolve()))
    n += 1
print(f"loaded {n} tiles")

# ライトと空
light = UsdLux.DistantLight.Define(stage, "/World/Sun")
light.CreateIntensityAttr(3000.0)
UsdGeom.Xform(light.GetPrim()).AddRotateXYZOp().Set(Gf.Vec3f(-50.0, 30.0, 0.0))
dome = UsdLux.DomeLight.Define(stage, "/World/Dome")
dome.CreateIntensityAttr(400.0)

# カメラ
cam = UsdGeom.Camera.Define(stage, "/World/Cam")
cam.CreateFocalLengthAttr(24.0)
cam.CreateClippingRangeAttr(Gf.Vec2f(0.5, 20000.0))
eye = Gf.Vec3d(*args.cam)
tgt = Gf.Vec3d(*args.target)
m = Gf.Matrix4d()
m.SetLookAt(eye, tgt, Gf.Vec3d(0, 0, 1))
xf = UsdGeom.Xformable(cam.GetPrim())
xf.AddTransformOp().Set(m.GetInverse())

vp = get_active_viewport()
vp.set_active_camera("/World/Cam")

# 描画を数十フレーム回してテクスチャ読込を待つ
for _ in range(120):
    app.update()

capture_viewport_to_file(vp, str(Path(args.out).resolve()))
for _ in range(30):
    app.update()
print("saved:", args.out)
app.close()
