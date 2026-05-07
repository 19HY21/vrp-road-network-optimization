"""
【目的】
    Google Maps 距離検証用の OD ペア CSV を生成する。
    OSMnx がルート計算に使用したネットワークノードの実座標（スナップ後）を使用する。

【出力先】
    outputs/{plan_id}/validation/gas_input.csv

【GAS スクリプトの列マッピング】
    E列 (col 5) : from_lat  → origin_snap_lat
    F列 (col 6) : from_lon  → origin_snap_lon
    J列 (col 10): to_lat    → dest_snap_lat
    K列 (col 11): to_lon    → dest_snap_lon
    N列 (col 14): distance_km  ← GAS が書き込む
    O列 (col 15): time_min     ← GAS が書き込む
    Q列 (col 17): status       ← GAS が書き込む

【実行方法】
    python scripts/generate_gas_input.py
    python scripts/generate_gas_input.py PLAN_20260503_160856
"""
import json
import sys
from itertools import permutations
from pathlib import Path

import osmnx as ox
import pandas as pd

_ROOT = Path(__file__).parents[1]
MASTER_PATH = _ROOT / "data" / "processed" / "delivery_destination_master.json"
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
GRAPH_PATH = _ROOT / "data" / "processed" / "osm_network" / "kanagawa_drive_latest.graphml"
OUTPUTS_DIR = _ROOT / "outputs"


def _latest_plan_id() -> str:
    plans = sorted(OUTPUTS_DIR.glob("PLAN_*"), reverse=True)
    if not plans:
        raise FileNotFoundError("outputs/ に PLAN_* ディレクトリが見つかりません")
    return plans[0].name


def main(plan_id: str | None = None) -> None:
    plan_id = plan_id or _latest_plan_id()
    print(f"plan_id: {plan_id}")

    # グラフ読み込み（ノード座標取得のため）
    print("OSMnx グラフ読み込み中...")
    G = ox.load_graphml(GRAPH_PATH)

    # デポ情報
    depot_row = pd.read_csv(DEPOT_PATH).iloc[0]
    depot_node_id = int(depot_row["depot_network_node_id"])
    depot_node = G.nodes[depot_node_id]
    depot = {
        "id": depot_row["depot_id"],
        "name": depot_row["depot_name"],
        "address": depot_row["depot_address"],
        "snap_lat": depot_node["y"],
        "snap_lon": depot_node["x"],
    }

    # 配送先情報（スナップ成功のみ）
    with open(MASTER_PATH, encoding="utf-8") as f:
        master = json.load(f)
    valid_dests = [r for r in master if r.get("snap_status") == "success"]

    destinations = []
    for r in valid_dests:
        node_id = int(r["network_node_id"])
        node = G.nodes[node_id]
        destinations.append({
            "id": r["delivery_id"],
            "name": r["destination_name"],
            "address": r["destination_address"],
            "snap_lat": node["y"],
            "snap_lon": node["x"],
        })

    locations = [depot] + destinations
    print(f"ロケーション数: {len(locations)} 件（デポ 1 + 配送先 {len(destinations)}）")

    # 全 OD ペア生成（自己ループ除く）
    rows = []
    for origin, dest in permutations(locations, 2):
        rows.append({
            "origin_id":       origin["id"],
            "origin_name":     origin["name"],
            "origin_address":  origin["address"],
            "origin_snap_lat": origin["snap_lat"],   # GAS: E列
            "origin_snap_lon": origin["snap_lon"],   # GAS: F列
            "dest_id":         dest["id"],
            "dest_name":       dest["name"],
            "dest_address":    dest["address"],
            "dest_snap_lat":   dest["snap_lat"],     # GAS: J列
            "dest_snap_lon":   dest["snap_lon"],     # GAS: K列
            "google_distance_km": "",                # GAS: N列（書き込み先）
            "google_time_min":    "",                # GAS: O列（書き込み先）
            "retrieved_at":       "",                # GAS: P列（書き込み先）
            "status":             "",                # GAS: Q列（書き込み先）
        })

    df = pd.DataFrame(rows)
    print(f"OD ペア数: {len(df)} 件（{len(locations)} × {len(locations) - 1}）")

    out_dir = OUTPUTS_DIR / plan_id / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "gas_input.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"保存: {out_path}")
    print()
    print("【次のステップ】")
    print("1. gas_input.csv を Google スプレッドシートにインポート")
    print("2. GAS スクリプトの列番号を以下に合わせて実行:")
    print("   from_lat → E列(5)  from_lon → F列(6)")
    print("   to_lat   → J列(10) to_lon   → K列(11)")
    print("3. 結果を CSV でダウンロードして outputs/{plan_id}/validation/gas_output.csv に配置")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(arg)
