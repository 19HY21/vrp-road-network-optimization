"""
【目的】
    Google Maps 距離検証用の OD ペア CSV を生成する。
    OSMnx がルート計算に使用したネットワークノードの実座標（スナップ後）を使用する。

【入力】
    data/processed/snap/{input_stem}/snap_destination_master.json
    data/raw/depot_master.csv

【出力先】
    outputs/PLAN_{input_stem}_{depot_id}/validation/gas_input.csv

【GAS スクリプトの列マッピング】
    E列 (col 5) : from_lat  → origin_snap_lat
    F列 (col 6) : from_lon  → origin_snap_lon
    J列 (col 10): to_lat    → dest_snap_lat
    K列 (col 11): to_lon    → dest_snap_lon
    N列 (col 14): distance_km  ← GAS が書き込む
    O列 (col 15): time_min     ← GAS が書き込む
    Q列 (col 17): status       ← GAS が書き込む

【実行方法】
    python scripts/generate_gas_input.py delivery_transaction_1000 DEPOT_001
"""
import json
import sys
from itertools import permutations
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).parents[1]
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
OUTPUTS_DIR = _ROOT / "outputs"
_SNAP_DIR = _ROOT / "data" / "processed" / "snap"


def main(input_stem: str | None = None, depot_id: str | None = None) -> None:
    if input_stem is None or depot_id is None:
        raise ValueError("input_stem と depot_id の両方を指定してください")

    plan_id = f"PLAN_{input_stem}_{depot_id}"
    snap_master_path = _SNAP_DIR / input_stem / "snap_destination_master.json"
    print(f"plan_id         : {plan_id}")
    print(f"スナップマスタ  : {snap_master_path}")
    print(f"デポID      : {depot_id}")

    # デポ情報（depot_master.csv のスナップ済み座標を使用）
    depot_df = pd.read_csv(DEPOT_PATH)
    depot_row = depot_df[depot_df["depot_id"] == depot_id]
    if depot_row.empty:
        raise ValueError(f"デポが見つかりません: {depot_id}")
    depot_row = depot_row.iloc[0]
    depot = {
        "id": depot_row["depot_id"],
        "name": depot_row["depot_name"],
        "address": depot_row["depot_address"],
        "snap_lat": float(depot_row["depot_snap_latitude"]),
        "snap_lon": float(depot_row["depot_snap_longitude"]),
    }

    # 配送先情報（snap_destination_master.json のスナップ済み座標を使用）
    with open(snap_master_path, encoding="utf-8") as f:
        master = json.load(f)
    valid_dests = [r for r in master if r.get("snap_status") == "success"]
    print(f"配送先マスタ: {len(master)} 件（スナップ成功 {len(valid_dests)} 件 / スナップ失敗 {len(master) - len(valid_dests)} 件）")

    destinations = []
    for r in valid_dests:
        destinations.append({
            "id": r["delivery_id"],
            "name": r.get("destination_name", ""),
            "address": r["destination_address"],
            "snap_lat": float(r["snap_latitude"]),
            "snap_lon": float(r["snap_longitude"]),
        })

    locations = [depot] + destinations
    print(f"ロケーション数: {len(locations)} 件（デポ 1 + 配送先 {len(destinations)}）")

    # 全 OD ペア生成（自己ループ除く）
    rows = []
    for origin, dest in permutations(locations, 2):
        rows.append({
            "origin_id":          origin["id"],
            "origin_name":        origin["name"],
            "origin_address":     origin["address"],
            "origin_snap_lat":    origin["snap_lat"],   # GAS: E列
            "origin_snap_lon":    origin["snap_lon"],   # GAS: F列
            "dest_id":            dest["id"],
            "dest_name":          dest["name"],
            "dest_address":       dest["address"],
            "dest_snap_lat":      dest["snap_lat"],     # GAS: J列
            "dest_snap_lon":      dest["snap_lon"],     # GAS: K列
            "google_distance_km": "",                   # GAS: N列（書き込み先）
            "google_time_min":    "",                   # GAS: O列（書き込み先）
            "retrieved_at":       "",                   # GAS: P列（書き込み先）
            "status":             "",                   # GAS: Q列（書き込み先）
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
    print(f"3. 結果を CSV でダウンロードして outputs/{plan_id}/validation/gas_output.csv に配置")


if __name__ == "__main__":
    _input_stem = sys.argv[1] if len(sys.argv) > 1 else None
    _depot_id   = sys.argv[2] if len(sys.argv) > 2 else None
    main(_input_stem, _depot_id)
