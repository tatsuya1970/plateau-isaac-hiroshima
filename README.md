# plateau-issac — PLATEAU広島 × Isaac Sim ロボットデモ

国土交通省PLATEAUの広島市3D都市モデル（2024年度・CC BY 4.0）をNVIDIA Isaac Simに取り込み、
実在の広島の街で Unitree G1（ヒューマノイド）/ Go2（四足）が歩き、
**実バスがGTFSリアルタイム位置（CC0）で動く**デジタルツインデモ。

関連プロジェクト:
- `C:\projects\web-metaverse` — 同じデータ源のWebメタバース（座標系・GTFS-RTフィードを共有）
- `C:\projects\humanoid-sim` — Isaac Sim 5.1 の venv（`.venv-isaac`）を本プロジェクトでも使用

## 環境

- Python venv: `C:\projects\humanoid-sim\.venv-isaac`（Isaac Sim 5.1 pip版 + Isaac Lab 2.3.2 + rsl-rl）
- Isaac Lab: `./IsaacLab`（v2.3.2 checkout、`pip install -e` 済み）
- GPU: RTX 5070 12GB（Blackwell、Isaac Sim 5.1対応済み）
- 実行時は `OMNI_KIT_ACCEPT_EULA=yes`、Git Bashでは `MSYS_NO_PATHCONV=1`、`python -X utf8 -u` を付ける

### 依存関係の注意（ハマったポイント）

- `tensordict` は **0.8.3 に固定**（0.13はtorch 2.7とABI不一致でSegfault）
- torch は **cu128ビルド**（`--index-url https://download.pytorch.org/whl/cu128`。
  pipが依存解決でCPU版に置き換えたら `--force-reinstall --no-deps` で戻す）
- `h5py` は **3.15.1 に固定**（`pip install --no-deps "h5py==3.15.1"`）。
  h5py 3.16はHDF5 2.0.0同梱で、Isaac Simが積む `hdf5.dll`（1.14.6）とプロセス内で衝突する。
  GUIモードのみ `omni.sensors.nv.*` が先に1.14.6を掴むため、後から読まれる h5py が
  `ImportError: DLL load failed while importing _errors` で落ち、`isaaclab_tasks` 拡張ごと死ぬ
  （headlessでは同拡張が読まれないので発症しない）。3.15.1はHDF5 1.14.6同梱で完全一致
- `flatdict` は `--no-build-isolation` でインストール（setuptools 81+のpkg_resources削除問題）
- `starlette<0.46` / `typing_extensions==4.12.2` は isaacsim-kernel 側の制約が優先

## 座標系（web-metaverseと同一）

- 原点 = 原爆ドーム前 `(34.39561, 132.45347)`
- ENU: X=東, Y=上, Z=南（OBJ、Y-up） → Isaac Sim ステージでは X+90°回転で Z-up（X=東, Y=北, Z=上）
- CityGMLのposListは「緯度 経度 高さ」順、EPSG:6697
- 地面標高: **2.35m**（建物基部の5パーセンタイル実測。tools/build_city_stage.py の GROUND_Z）

## パイプライン

```
G空間情報センター CityGML zip（data/に取得済み）
  → tools/citygml2obj.py   9メッシュ(51324365..87)のLOD2建物+テクスチャ(2048縮小) → data/obj/
  → tools/obj2usd.py       Isaac Sim asset converterでUSD化（メッシュ結合） → data/usd/
  → tools/build_city_stage.py  9タイル参照+地面平面+静的コライダー → data/usd/hiroshima_city.usd
```

確認用: `tools/scene_shot.py --out shot.png --cam X Y Z --target X Y Z`（Z-upワールド座標）

## デモ実行

### かんたん起動（Windows）

`run-demo.bat` をダブルクリック → Isaac SimのGUIが開き、G1が紙屋町から相生通りを歩く。
ビューポートは右ドラッグで視点回転、WASDで飛行、ホイールで前後。停止はターミナルで `Ctrl+C`。

引数を渡せばそのままデモスクリプトに素通しされる（`--headless` を付ければ従来の動画録画になる）。

```
run-demo.bat --spawn -60 -260 --heading 90        # 平和記念公園から北へ
run-demo.bat --headless --video --video_length 450 # 動画録画
```

### 直接実行

```
# G1が紙屋町の相生通りを歩く＋実バス表示（動画は videos/ に出力）
.venv-isaacのpython -X utf8 -u tools/g1_hiroshima_demo.py --headless --video --video_length 450 \
    --spawn 700 -150 --heading 0 --cam_offset -7 -8 3
```

- `--spawn` はZ-upワールドXY（X=東, Y=北）。スポーン地点は建物の無い道路上を選ぶこと
  （俯瞰ショットで確認: `scene_shot.py --cam 700 -250 500 --target 700 -249 0`）
- 学習済みポリシーは初回に自動DL（`.pretrained_checkpoints/`）
- バスは3事業者（広電・広島バス・広交通）のGTFS-RTを15秒ポーリング、
  中心部bboxの実車両を色分きボックスで表示（tools/gtfs_rt.py、単体テスト可）

## Isaac Lab 単体の動作確認

```
cd IsaacLab
python -u scripts/reinforcement_learning/rsl_rl/play.py --task Isaac-Velocity-Flat-Unitree-Go2-v0 \
    --num_envs 1 --headless --use_pretrained_checkpoint --video --video_length 300
# G1: --task Isaac-Velocity-Flat-G1-v0
```

- **G1/Go2ともIsaac Lab同梱アセットを使うこと**（Unitree公式USDは関節構成が違い学習が収束しない）

## リポジトリに含まれないもの（各自で用意）

サイズと上流リポジトリの都合で以下は `.gitignore` 済み。

| パス | 入手方法 |
| --- | --- |
| `data/` | PLATEAU広島市2024 CityGML を[G空間情報センター](https://www.geospatial.jp/)から取得し、上記パイプラインを実行（約1.9GB） |
| `IsaacLab/` | `git clone -b v2.3.2 https://github.com/isaac-sim/IsaacLab.git` して `pip install -e` |
| `.pretrained_checkpoints/` | デモ初回実行時に自動ダウンロード |

## デモ動画

`videos/g1-aioi-dori-demo.mp4` — G1が紙屋町・相生通りを歩行、緑のボックスがGTFS-RTの実バス位置。

## データ出典

- 3D都市モデル: 国土交通省 Project PLATEAU（広島市 2024年度）/ CC BY 4.0
- バス位置: 広島県バス協会 GTFSリアルタイムデータ / CC0
- ロボット: Unitree G1/Go2（Isaac Lab同梱アセット + 公式学習済みポリシー）

## ライセンス

本リポジトリのコードは MIT License（[LICENSE](LICENSE)）。
ただし上記データ出典それぞれのライセンス（PLATEAU: CC BY 4.0 / バス位置: CC0 / Isaac Lab: BSD-3-Clause）は各提供元に従うこと。

## 次の一手（未着手）

- Go2の統合（河岸段丘・階段はRoughポリシー）と配送ロボット（Nova Carter）追加
- バスをボックスから車両モデルへ、路線形状（web-metaverseのbus-gtfs.json）への吸着
- 洪水シミュレーション（web-metaverse flood.tsの水位ロジック移植）
- humanoid-simのモーキャプ→G1リアルタイムミミック演出の組み込み
