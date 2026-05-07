"""
【目的】
    デポ・配送先間の全地点間最短距離と推定所要時間を計算し、OD 行列として保存する。

【処理の流れ】
    1. depot_master.csv と delivery_destination_master.json からスナップ済みノード ID を収集する
    2. OSM グラフをキャッシュから読み込む
    3. 各地点を起点に Dijkstra 法で最短距離を計算する
    4. 距離(km) と推定所要時間(分) を OD 行列として outputs/{plan_id}/distance/od_matrix.csv に保存する

【出力先】
    outputs/{plan_id}/distance/od_matrix.csv

【前提条件】
    - depot_master.csv の depot_snap_status が "success" であること
    - delivery_destination_master.json の snap_status が "success" の配送先のみを対象とする

【注意事項】
    - 平均走行速度 30km/h を前提とした静的推定時間を使用する（渋滞考慮なし）
    - 経路が存在しないペアはスキップしログに記録する
    - 神奈川県全域グラフでの計算のため数十秒かかる場合がある

【実行方法】
    python -m vrp_optimization.distance_matrix.compute
"""
import json
import math
from datetime import datetime
from pathlib import Path

import networkx as nx
import pandas as pd

from vrp_optimization.network.graph import load_graph

_ROOT = Path(__file__).parents[3]
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
MASTER_PATH = _ROOT / "data" / "processed" / "delivery_destination_master.json"
OUTPUTS_DIR = _ROOT / "outputs"

AVG_SPEED_KPH = 30  # 都市部配送の平均走行速度（km/h）


def _generate_plan_id() -> str:
    return f"PLAN_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def load_locations() -> list[tuple[str, str, int]]:
    """デポ・配送先のロケーション一覧を返す。(location_id, label, node_id) のリスト。"""
    locations = []

    depot_df = pd.read_csv(DEPOT_PATH)
    for _, row in depot_df.iterrows():
        if str(row.get("depot_snap_status")) != "success":
            print(f"  [スキップ] デポスナップ未完了: {row['depot_id']}")
            continue
        locations.append((row["depot_id"], row["depot_name"], int(row["depot_network_node_id"])))

    with open(MASTER_PATH, encoding="utf-8") as f:
        master = json.load(f)
    for r in master:
        if r.get("snap_status") != "success":
            continue
        locations.append((r["delivery_id"], r["destination_address"], int(r["network_node_id"])))

    return locations


def compute_od_matrix(G: nx.MultiDiGraph, locations: list[tuple[str, str, int]]) -> pd.DataFrame:
    """全地点間の最短距離と推定所要時間を計算して DataFrame で返す。"""
    records = []
    no_path_count = 0

    for i, (origin_id, origin_label, origin_node) in enumerate(locations):
        print(f"  計算中 ({i + 1}/{len(locations)}): {origin_label[:25]}")
        lengths = dict(nx.single_source_dijkstra_path_length(G, origin_node, weight="length"))

        for dest_id, dest_label, dest_node in locations:
            if origin_id == dest_id:
                continue
            dist_m = lengths.get(dest_node)
            if dist_m is None:
                no_path_count += 1
                continue
            dist_km = round(dist_m / 1000, 2)
            travel_min = math.ceil(dist_km / AVG_SPEED_KPH * 60)
            records.append(
                {
                    "origin_id": origin_id,
                    "destination_id": dest_id,
                    "origin_node_id": origin_node,
                    "destination_node_id": dest_node,
                    "path_distance_km": dist_km,
                    "estimated_travel_time_min": travel_min,
                }
            )

    if no_path_count:
        print(f"  [警告] 経路なし: {no_path_count} ペア（孤立ノードの可能性）")

    return pd.DataFrame(records)


def main(plan_id: str | None = None) -> None:
    print("=== OD 行列計算開始 ===")

    plan_id = plan_id or _generate_plan_id()
    print(f"plan_id: {plan_id}")

    locations = load_locations()
    print(f"対象地点: {len(locations)} 件（デポ含む）")

    G = load_graph()
    df = compute_od_matrix(G, locations)

    out_dir = OUTPUTS_DIR / plan_id / "distance"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "od_matrix.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"\n完了: {len(df)} ペア計算")
    print(f"  最短距離: {df['path_distance_km'].min()} km")
    print(f"  最長距離: {df['path_distance_km'].max()} km")
    print(f"  平均距離: {df['path_distance_km'].mean():.2f} km")
    print(f"保存: {out_path}")
    print(f"\n次ステップで使用する plan_id: {plan_id}")


if __name__ == "__main__":
    main()
