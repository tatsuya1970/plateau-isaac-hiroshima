"""OBJ → USD 変換（Isaac Sim の asset converter をヘッドレスで使用）。

使い方:
    python tools/obj2usd.py data/obj/51324376.obj [more.obj ...] --out data/usd
"""

import argparse
import asyncio
import sys
from pathlib import Path

from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

import omni.kit.asset_converter as converter  # noqa: E402


async def convert_one(src: Path, dst: Path) -> bool:
    ctx = converter.AssetConverterContext()
    ctx.ignore_materials = False
    ctx.ignore_animations = True
    ctx.ignore_camera = True
    ctx.ignore_light = True
    ctx.merge_all_meshes = True  # タイル単位で1メッシュに（ドローコール削減）
    ctx.use_meter_as_world_unit = True
    task = converter.get_instance().create_converter_task(str(src), str(dst), None, ctx)
    ok = await task.wait_until_finished()
    if not ok:
        print(f"FAILED {src.name}: {task.get_status()} {task.get_error_message()}")
    return ok


async def main_async(files, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    for f in files:
        src = Path(f)
        dst = out_dir / (src.stem + ".usd")
        ok = await convert_one(src, dst)
        if ok:
            size = dst.stat().st_size if dst.exists() else 0
            print(f"OK {src.name} -> {dst.name} ({size/1e6:.1f} MB)")
            n_ok += 1
    print(f"done: {n_ok}/{len(files)}")
    return n_ok == len(files)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("obj", nargs="+")
    ap.add_argument("--out", default="data/usd")
    args = ap.parse_args()
    ok = asyncio.get_event_loop().run_until_complete(main_async(args.obj, Path(args.out)))
    app.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
