"""広島×Isaac Sim 統合デモ: PLATEAU広島の街でUnitree G1が歩き、実バスがリアルタイムに動く。

- 地形: data/usd/hiroshima_city.usd（PLATEAU 中区9タイル+地面、コライダー焼込み済み）
- G1: Isaac Lab学習済みポリシー（Isaac-Velocity-Flat-G1-v0）で指定方向へ歩行
- バス: 広島県バス協会 GTFSリアルタイム車両位置（CC0）を15秒ごとに取得し、
  色分きボックスとして実位置に表示（bearingで向きも反映）

使い方（動画録画・300ステップ≈6秒）:
    python tools/g1_hiroshima_demo.py --headless --video --video_length 300
"""

import argparse
import math
import sys
import threading
import time
from pathlib import Path

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser()
parser.add_argument("--video", action="store_true")
parser.add_argument("--video_length", type=int, default=300)
parser.add_argument("--steps", type=int, default=0, help="0=video_length+α で終了")
parser.add_argument("--spawn", nargs=2, type=float, default=[-60.0, -260.0],
                    help="G1のスポーン位置 world XY（X=東, Y=北）。既定は平和記念公園の広場")
parser.add_argument("--heading", type=float, default=90.0, help="歩行方位[deg]（0=東, 90=北）")
parser.add_argument("--speed", type=float, default=0.7, help="歩行速度[m/s]")
parser.add_argument("--cam_offset", nargs=3, type=float, default=[7.0, -9.0, 3.2])
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()
if args_cli.video:
    args_cli.enable_cameras = True

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import gymnasium as gym  # noqa: E402
import torch  # noqa: E402
from rsl_rl.runners import OnPolicyRunner  # noqa: E402

from isaaclab_rl.rsl_rl import RslRlVecEnvWrapper  # noqa: E402
from isaaclab_rl.utils.pretrained_checkpoint import get_published_pretrained_checkpoint  # noqa: E402

import isaaclab_tasks  # noqa: F401, E402
from isaaclab_tasks.utils import load_cfg_from_registry, parse_env_cfg  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from gtfs_rt import fetch_buses  # noqa: E402

TASK = "Isaac-Velocity-Flat-G1-v0"
CITY_USD = Path(__file__).parent.parent / "data" / "usd" / "hiroshima_city.usd"
GROUND_Z = 2.35
BUS_COLORS = {"hiroden": (0.13, 0.55, 0.13), "hirobus": (0.75, 0.12, 0.12), "hirokotsu": (0.9, 0.55, 0.1)}
BUS_RANGE = 1500.0  # タイル範囲内のバスだけ表示

# ---------------------------------------------------------------------------
# 環境設定
# ---------------------------------------------------------------------------
env_cfg = parse_env_cfg(TASK, device=args_cli.device, num_envs=1)
agent_cfg = load_cfg_from_registry(TASK, "rsl_rl_cfg_entry_point")

# 地形をPLATEAU広島に差し替え
env_cfg.scene.terrain.terrain_type = "usd"
env_cfg.scene.terrain.usd_path = str(CITY_USD.resolve())
env_cfg.scene.terrain.terrain_generator = None
env_cfg.scene.terrain.max_init_terrain_level = None

# スポーン位置（Z-up world。ヒップ高0.74+地面標高）
sx, sy = args_cli.spawn
env_cfg.scene.robot.init_state.pos = (sx, sy, GROUND_Z + 0.76)
yaw0 = math.radians(args_cli.heading)
env_cfg.scene.robot.init_state.rot = (math.cos(yaw0 / 2), 0.0, 0.0, math.sin(yaw0 / 2))

# 一定速度・一定方位で歩かせる（コマンド再サンプリング実質無効化）
cmd = env_cfg.commands.base_velocity
cmd.resampling_time_range = (1.0e6, 1.0e6)
cmd.ranges.lin_vel_x = (args_cli.speed, args_cli.speed)
cmd.ranges.lin_vel_y = (0.0, 0.0)
cmd.ranges.ang_vel_z = (0.0, 0.0)
if hasattr(cmd, "heading_command") and cmd.heading_command:
    cmd.ranges.heading = (yaw0, yaw0)

# デバッグ矢印（頭上の速度コマンド可視化）を消す
cmd.debug_vis = False

# 外乱イベント（押し）を無効化して観賞用に安定させる
if hasattr(env_cfg.events, "push_robot"):
    env_cfg.events.push_robot = None
if hasattr(env_cfg.events, "base_external_force_torque"):
    env_cfg.events.base_external_force_torque = None
env_cfg.episode_length_s = 3600.0

# カメラ（ロボット後方斜めから進行方向を望む）
ox, oy, oz = args_cli.cam_offset
hx, hy = math.cos(yaw0), math.sin(yaw0)
env_cfg.viewer.eye = (sx + ox, sy + oy, GROUND_Z + oz)
env_cfg.viewer.lookat = (sx + hx * 8.0, sy + hy * 8.0, GROUND_Z + 1.2)

# ---------------------------------------------------------------------------
# 環境生成・ポリシー読込
# ---------------------------------------------------------------------------
env = gym.make(TASK, cfg=env_cfg, render_mode="rgb_array" if args_cli.video else None)
if args_cli.video:
    video_kwargs = {
        "video_folder": "videos",
        "step_trigger": lambda step: step == 0,
        "video_length": args_cli.video_length,
        "disable_logger": True,
    }
    env = gym.wrappers.RecordVideo(env, **video_kwargs)
env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)

ckpt = get_published_pretrained_checkpoint("rsl_rl", TASK)
runner = OnPolicyRunner(env, agent_cfg.to_dict(), log_dir=None, device=agent_cfg.device)
runner.load(ckpt)
policy = runner.get_inference_policy(device=env.unwrapped.device)
print(f"[demo] policy loaded: {ckpt}")

# ---------------------------------------------------------------------------
# バス表示（ビジュアルのみ。GTFS-RTを別スレッドで15秒ポーリング）
# ---------------------------------------------------------------------------
import omni.usd  # noqa: E402
from pxr import Gf, UsdGeom  # noqa: E402

stage = omni.usd.get_context().get_stage()
_bus_lock = threading.Lock()
_bus_latest = {"data": []}


def _bus_poller():
    while simulation_app.is_running():
        try:
            data = [b for b in fetch_buses() if abs(b["x"]) < BUS_RANGE and abs(b["z"]) < BUS_RANGE]
            with _bus_lock:
                _bus_latest["data"] = data
        except Exception as ex:
            print("[demo] bus poll error:", ex)
        time.sleep(15)


_bus_prims = {}


def _update_buses():
    with _bus_lock:
        data = list(_bus_latest["data"])
    for b in data:
        key = b["id"].replace(":", "_").replace("-", "_")
        path = f"/World/Buses/{key}"
        if key not in _bus_prims:
            cube = UsdGeom.Cube.Define(stage, path)
            cube.CreateSizeAttr(1.0)
            color = BUS_COLORS.get(b["op"], (0.2, 0.2, 0.8))
            cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
            xf = UsdGeom.Xformable(cube.GetPrim())
            xf.AddTranslateOp()
            xf.AddRotateZOp()
            xf.AddScaleOp().Set(Gf.Vec3f(2.3, 10.5, 3.0))  # 幅・全長・高さ[m]
            _bus_prims[key] = cube.GetPrim()
        prim = _bus_prims[key]
        xf = UsdGeom.Xformable(prim)
        ops = xf.GetOrderedXformOps()
        # ENU: x=東, z=南 → world: x=東, y=北=-z
        ops[0].Set(Gf.Vec3d(b["x"], -b["z"], GROUND_Z + 1.5))
        yaw = 0.0 if b["bearing"] is None else -b["bearing"]  # bearing=北から時計回り → Z回転
        ops[1].Set(yaw)


threading.Thread(target=_bus_poller, daemon=True).start()

# ---------------------------------------------------------------------------
# メインループ
# ---------------------------------------------------------------------------
obs = env.get_observations()
total = args_cli.steps or (args_cli.video_length + 60)
t0 = time.time()
for step in range(total):
    _update_buses()
    with torch.inference_mode():
        actions = policy(obs)
        obs, _, _, _ = env.step(actions)
    if step % 100 == 0:
        with _bus_lock:
            nb = len(_bus_latest["data"])
        print(f"[demo] step {step}/{total} buses={nb} elapsed={time.time()-t0:.0f}s")

env.close()
simulation_app.close()
print("[demo] done")
