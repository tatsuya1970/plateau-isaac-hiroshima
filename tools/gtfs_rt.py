"""広島の路線バス GTFSリアルタイム車両位置（CC0）の取得モジュール。

web-metaverse server/server.mjs と同じフィード・同じ方針:
- 3事業者（広電バス・広島バス・広交通）のvehicle_position.binを取得しprotobufデコード
- 広島中心部bboxでフィルタ、更新が止まった車両（>120s）は除外
- 15秒キャッシュ（配信元の更新周期に合わせ、高頻度アクセスを避ける）
- 座標は原爆ドーム基準ENU（X=東, Y=上, Z=南）に変換して返す

単体テスト: python tools/gtfs_rt.py
"""

import math
import time
import urllib.request

from google.transit import gtfs_realtime_pb2

FEEDS = [
    ("hiroden", "https://ajt-mobusta-gtfs.mcapps.jp/realtime/8/vehicle_position.bin"),
    ("hirobus", "https://ajt-mobusta-gtfs.mcapps.jp/realtime/9/vehicle_position.bin"),
    ("hirokotsu", "https://ajt-mobusta-gtfs.mcapps.jp/realtime/10/vehicle_position.bin"),
]
BBOX = (34.365, 132.425, 34.425, 132.495)  # S, W, N, E
STALE_SEC = 120
CACHE_SEC = 15

ORIGIN_LAT = 34.39561
ORIGIN_LON = 132.45347
A = 6378137.0
F = 1 / 298.257223563
E2 = F * (2 - F)
_lat0 = math.radians(ORIGIN_LAT)
_sin2 = math.sin(_lat0) ** 2
MERIDIONAL = A * (1 - E2) / (1 - E2 * _sin2) ** 1.5
PRIME_VERT = A / math.sqrt(1 - E2 * _sin2)

_cache = {"t": 0.0, "data": []}


def latlon_to_local(lat, lon):
    x = math.radians(lon - ORIGIN_LON) * PRIME_VERT * math.cos(_lat0)
    z = -math.radians(lat - ORIGIN_LAT) * MERIDIONAL
    return x, z


def fetch_buses():
    """[{id, op, lat, lon, x, z, bearing, route_id}] を返す（15秒キャッシュ）。"""
    now = time.time()
    if now - _cache["t"] < CACHE_SEC:
        return _cache["data"]
    out = []
    s, w, n, e = BBOX
    for op, url in FEEDS:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                buf = r.read()
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(buf)
            for ent in feed.entity:
                v = ent.vehicle
                if not v.HasField("position"):
                    continue
                lat, lon = v.position.latitude, v.position.longitude
                if lat < s or lat > n or lon < w or lon > e:
                    continue
                ts = v.timestamp if v.HasField("timestamp") else 0
                if ts and now - ts > STALE_SEC:
                    continue
                x, z = latlon_to_local(lat, lon)
                out.append({
                    "id": f"{op}:{v.vehicle.id or ent.id}",
                    "op": op,
                    "lat": lat,
                    "lon": lon,
                    "x": x,
                    "z": z,
                    "bearing": v.position.bearing if v.position.HasField("bearing") else None,
                    "route_id": v.trip.route_id or None,
                })
        except Exception as ex:
            print(f"[gtfs_rt] {op} fetch error: {ex}")
    _cache["t"] = now
    _cache["data"] = out
    return out


if __name__ == "__main__":
    buses = fetch_buses()
    print(f"buses in central Hiroshima: {len(buses)}")
    for b in buses[:10]:
        print(f"  {b['id']:24s} route={b['route_id']} x={b['x']:8.1f} z={b['z']:8.1f} bearing={b['bearing']}")
