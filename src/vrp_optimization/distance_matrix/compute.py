"""
【目的】
    デポ・配送先間の全地点間最短距離と推定所要時間を計算し、OD 行列として保存する。

【処理の流れ】
    1. depot_master.csv から指定デポのスナップ済みノード ID を取得する
    2. data/processed/snap/{input_stem}/snap_destination_master.json から
       snap_status=success の配送先ノード ID を収集する
    3. OSM グラフをキャッシュから読み込む
    4. 各地点を起点に Dijkstra 法で最短距離を計算する
    5. 距離(km) と推定所要時間(分) を OD 行列として
       data/processed/compute/{input_stem}/{depot_id}/od_matrix.csv に保存する

【出力先】
    data/processed/compute/{input_stem}/{depot_id}/od_matrix.csv

【前提条件】
    - depot_master.csv の depot_snap_status が "success" であること
    - snap_destination_master.json の snap_status が "success" の配送先のみを対象とする

【注意事項】
    - 平均走行速度 30km/h を前提とした静的推定時間を使用する（渋滞考慮なし）
    - 経路が存在しないペアはスキップしログに記録する
    - 神奈川県全域グラフでの計算のため数十秒かかる場合がある
    - 同一 input_stem × depot_id の組み合わせで再実行した場合は上書きされる

【実行方法】
    python -m vrp_optimization.distance_matrix.compute
    python -m vrp_optimization.distance_matrix.compute DEPOT_001
    python -m vrp_optimization.distance_matrix.compute DEPOT_001 delivery_transaction_1000
"""
import json
import logging
import math
import sys
from pathlib import Path

import networkx as nx
import pandas as pd

from vrp_optimization.network.graph import load_graph

_ROOT = Path(__file__).parents[3]
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
TRANSACTION_PATH = _ROOT / "data" / "raw" / "delivery_transaction_1000.csv"
_SNAP_DIR = _ROOT / "data" / "processed" / "snap"
_COMPUTE_DIR = _ROOT / "data" / "processed" / "compute"

AVG_SPEED_KPH = 30

logger = logging.getLogger(__name__)


def load_locations(depot_id: str, snap_master_path: Path) -> tuple[list[tuple[str, str, int]], list[dict]]:
    """指定デポと配送先のロケーション一覧を返す。

    Returns:
        locations: (location_id, label, node_id) のリスト（デポ先頭）
        excluded: snap_status != "success" の配送先レコードリスト
    """
    locations: list[tuple[str, str, int]] = []
    excluded: list[dict] = []

    depot_df = pd.read_csv(DEPOT_PATH)
    depot_row = depot_df[depot_df["depot_id"] == depot_id]
    if depot_row.empty:
        raise ValueError(f"デポが見つかりません: {depot_id}")
    row = depot_row.iloc[0]
    if str(row.get("depot_snap_status")) != "success":
        raise ValueError(f"デポのスナップが未完了です: {depot_id} (status={row.get('depot_snap_status')})")
    locations.append((row["depot_id"], row["depot_name"], int(row["depot_network_node_id"])))

    with open(snap_master_path, encoding="utf-8") as f:
        snap_records: list[dict] = json.load(f)

    for r in snap_records:
        if r.get("snap_status") == "success":
            locations.append((r["delivery_id"], r["destination_address"], int(r["network_node_id"])))
        else:
            excluded.append(r)

    return locations, excluded


def compute_od_matrix(G: nx.MultiDiGraph, locations: list[tuple[str, str, int]]) -> tuple[pd.DataFrame, int]:
    """全地点間の最短距離と推定所要時間を計算して DataFrame で返す。

    Returns:
        df: OD 行列 DataFrame
        no_path_count: 経路なしペア数
    """
    records = []
    no_path_count = 0

    for i, (origin_id, origin_label, origin_node) in enumerate(locations):
        logger.info("  計算中 (%d/%d): %s", i + 1, len(locations), origin_label[:25])
        lengths = dict(nx.single_source_dijkstra_path_length(G, origin_node, weight="length"))

        for dest_id, _, dest_node in locations:
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

    return pd.DataFrame(records), no_path_count


def main(plan_id: str | None = None, depot_id: str | None = None, input_stem: str | None = None) -> str:
    """OD 行列を計算して保存する。

    Args:
        plan_id: 指定があれば outputs/ のサブディレクトリ名として使用する（指定がなければ自動生成）
        depot_id: 指定がなければ depot_master.csv の先頭デポを使用する
        input_stem: 配送トランザクション CSV のステム名。指定がなければ TRANSACTION_PATH のステムを使用する

    Returns:
        使用した plan_id
    """
    logger.info("=== OD 行列計算開始 ===")

    input_stem = input_stem or TRANSACTION_PATH.stem
    snap_master_path = _SNAP_DIR / input_stem / "snap_destination_master.json"

    logger.info("使用ファイル:")
    logger.info("  デポ    : %s", DEPOT_PATH)
    logger.info("  配送先  : %s", snap_master_path)

    if depot_id is None:
        depot_df = pd.read_csv(DEPOT_PATH)
        depot_id = str(depot_df.iloc[0]["depot_id"])
        logger.info("デポ未指定のため先頭デポを使用: %s", depot_id)

    locations, excluded = load_locations(depot_id, snap_master_path)

    depot_loc = locations[0]
    dest_count = len(locations) - 1
    logger.info("デポ      : %s (%s)", depot_loc[0], depot_loc[1])
    logger.info(
        "配送先    : %d 件 (snap=success) / %d 件除外 (snap≠success)",
        dest_count, len(excluded),
    )

    if excluded:
        logger.warning("除外された配送先 (%d 件):", len(excluded))
        for r in excluded:
            logger.warning(
                "  [%s] %s — %s",
                r.get("snap_status"), r.get("delivery_id", ""), r.get("destination_address", ""),
            )

    if plan_id is None:
        plan_id = f"PLAN_{input_stem}_{depot_id}"
    logger.info("plan_id   : %s", plan_id)

    G, _ = load_graph()

    logger.info("OD 行列計算中...")
    df, no_path_count = compute_od_matrix(G, locations)

    if no_path_count:
        logger.warning("経路なし: %d ペア（孤立ノードの可能性）", no_path_count)

    logger.info("OD 行列計算完了: %d ペア / 経路なし %d ペア", len(df), no_path_count)
    if not df.empty:
        nonzero = df.loc[df["path_distance_km"] > 0, "path_distance_km"]
        logger.info(
            "  最短距離: %.2f km / 最長距離: %.2f km / 平均距離: %.2f km",
            nonzero.min() if not nonzero.empty else 0.0,
            df["path_distance_km"].max(),
            df["path_distance_km"].mean(),
        )

    out_dir = _COMPUTE_DIR / input_stem / depot_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "od_matrix.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    logger.info("保存: %s", out_path)

    return plan_id


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    _depot_id = sys.argv[1] if len(sys.argv) > 1 else None
    _input_stem = sys.argv[2] if len(sys.argv) > 2 else None
    main(depot_id=_depot_id, input_stem=_input_stem)
