"""
【目的】
    デポ・配送先の緯度経度を OSM 道路ネットワーク上の最近傍ノードに割り当てる。
    スナップ結果（ノード ID・距離・ステータス）を各マスタファイルに書き戻す。

【処理の流れ】
    1. OSM グラフを graph.load_graph() で取得する
    2. depot_master.csv のデポをスナップし、
       depot_network_node_id / depot_snap_status / depot_snap_distance を更新する
    3. delivery_destination_master.json の配送先（geocode_status=="success" のみ）をスナップし、
       network_node_id / snap_status / snap_distance を更新する

【出力先】
    data/raw/depot_master.csv                         （スナップ結果を上書き）
    data/processed/delivery_destination_master.json   （スナップ結果を上書き）

【注意事項】
    - スナップ距離が大きい地点は住所・ジオコーディング結果の確認を推奨する
    - geocode_status=="failed" の配送先はスナップをスキップし snap_status="skipped" とする

【実行方法】
    python -m vrp_optimization.network.snap
"""
import json
from pathlib import Path

import networkx as nx
import osmnx as ox
import pandas as pd

from vrp_optimization.network.graph import load_graph

_ROOT = Path(__file__).parents[3]
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
MASTER_PATH = _ROOT / "data" / "processed" / "delivery_destination_master.json"

SNAP_WARN_M = 100   # 100m 超: 注意（丁目レベルの住所精度）
SNAP_ALERT_M = 200  # 200m 超: 警告（番地未解決の可能性）


def _snap_label(dist: float) -> str:
    if dist > SNAP_ALERT_M:
        return f"[警告] スナップ距離 {dist}m — 住所が番地レベルで解決できていない可能性があります"
    if dist > SNAP_WARN_M:
        return f"[注意] スナップ距離 {dist}m — 丁目レベルの精度です。住所を確認してください"
    return ""


def _snap_node(G: nx.MultiDiGraph, lat: float, lon: float) -> tuple[int, float]:
    """最近傍ノード ID とスナップ距離（m）を返す。"""
    node_id = ox.distance.nearest_nodes(G, X=lon, Y=lat)
    node_data = G.nodes[node_id]
    dist = ox.distance.great_circle(lat, lon, node_data["y"], node_data["x"])
    return node_id, round(dist, 1)


def snap_depot(G: nx.MultiDiGraph, depot_df: pd.DataFrame) -> pd.DataFrame:
    """depot_master のデポをスナップし結果列を更新して返す。"""
    depot_df = depot_df.copy()
    for col in ("depot_network_node_id", "depot_snap_status", "depot_snap_distance"):
        depot_df[col] = depot_df[col].astype(object)
    for idx, row in depot_df.iterrows():
        lat, lon = row.get("depot_latitude"), row.get("depot_longitude")
        if pd.isna(lat) or pd.isna(lon):
            depot_df.at[idx, "depot_snap_status"] = "failed"
            print(f"  [スキップ] デポ緯度経度未設定: {row['depot_id']}")
            continue
        node_id, dist = _snap_node(G, float(lat), float(lon))
        depot_df.at[idx, "depot_network_node_id"] = str(node_id)
        depot_df.at[idx, "depot_snap_status"] = "success"
        depot_df.at[idx, "depot_snap_distance"] = dist
        label = _snap_label(dist)
        print(f"  デポスナップ: {row['depot_id']} → node={node_id} ({dist}m){('  ' + label) if label else ''}")
    return depot_df


def snap_destinations(G: nx.MultiDiGraph, master: list[dict]) -> list[dict]:
    """配送先マスタをスナップし結果フィールドを更新して返す。"""
    updated = []
    for record in master:
        if record.get("geocode_status") != "success":
            record["snap_status"] = "skipped"
            record["snap_distance"] = None
            record["network_node_id"] = None
            updated.append(record)
            continue

        lat = record.get("destination_latitude")
        lon = record.get("destination_longitude")
        node_id, dist = _snap_node(G, float(lat), float(lon))
        record["network_node_id"] = str(node_id)
        record["snap_status"] = "success"
        record["snap_distance"] = dist
        label = _snap_label(dist)
        print(f"  スナップ: {record['destination_address'][:30]} → node={node_id} ({dist}m)")
        if label:
            print(f"    {label}")
        updated.append(record)
    return updated


def main() -> None:
    print("=== ノードスナップ開始 ===")

    G = load_graph()

    depot_df = pd.read_csv(DEPOT_PATH)
    depot_df = snap_depot(G, depot_df)
    depot_df.to_csv(DEPOT_PATH, index=False, encoding="utf-8-sig")

    with open(MASTER_PATH, encoding="utf-8") as f:
        master = json.load(f)
    master = snap_destinations(G, master)
    with open(MASTER_PATH, "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False, indent=2)

    success = sum(1 for r in master if r.get("snap_status") == "success")
    skipped = sum(1 for r in master if r.get("snap_status") == "skipped")
    warn = sum(1 for r in master if r.get("snap_distance") and SNAP_WARN_M < r["snap_distance"] <= SNAP_ALERT_M)
    alert = sum(1 for r in master if r.get("snap_distance") and r["snap_distance"] > SNAP_ALERT_M)
    print(f"\n完了: {success} 件スナップ成功 / {skipped} 件スキップ")
    if warn:
        print(f"  [注意] {warn} 件が {SNAP_WARN_M}m〜{SNAP_ALERT_M}m（住所精度を確認してください）")
    if alert:
        print(f"  [警告] {alert} 件が {SNAP_ALERT_M}m 超（番地レベルで解決できていない可能性があります）")
    print(f"保存: {DEPOT_PATH.name}, {MASTER_PATH.name}")


if __name__ == "__main__":
    main()
