"""
【目的】
    デポ・配送先の緯度経度を OSM 道路ネットワーク上の最近傍ノードに割り当てる。
    スナップ結果はトレーサビリティのため geocode 結果（delivery_destination_master.json）と
    分離し、snap_destination_master.json に保存する。

【処理の流れ】
    1. ノードスナップ開始をログ出力する（スナップ距離閾値の定義も明示）
    2. graph.py から OSM 道路グラフを取得し、地図ファイル名をログ出力する
    3. depot_master.csv / delivery_transaction_1000.csv /
       data/processed/geocode/{input_stem}/delivery_destination_master.json /
       data/processed/snap/{input_stem}/snap_destination_master.json を読み込む
    4. デポ名称をログ出力する
    5. デポをスナップする（最近傍ノード・距離・品質をログ出力）
    6. 配送先の総件数・ユニーク件数・ジオコーディング済み件数をログ出力する
       graph_metadata.csv でグラフ変更を検知し、スナップ対象の内訳を出力する
       内訳: 新規 / 地図更新 / 再スナップ（以前 failed） / スキップ（geocode 失敗）
    7. 配送先をスナップする（新規 → 地図更新 → 再スナップ の順）
       各件に対して区分・品質・距離をログ出力する
    8. スナップ距離の最小値・最大値・平均値をログ出力する
    9. 保存先ファイルパスをログ出力する（depot_master.csv → snap_destination_master.json）

【snap_status の値】
    success : スナップ成功
    failed  : スナップ処理が技術的に失敗（例外発生等）
    skipped : geocode_status != "success" のためスナップ対象外

【snap_quality の値（snap_status == "success" のみ）】
    ok      : SNAP_WARN_M 以内
    caution : SNAP_WARN_M 超〜SNAP_ALERT_M 以内
    warning : SNAP_ALERT_M 超

【出力先】
    data/raw/depot_master.csv                                              （スナップ結果を上書き）
    data/processed/snap/{input_stem}/snap_destination_master.json         （スナップ結果を上書き）

【注意事項】
    - data/processed/geocode/{input_stem}/delivery_destination_master.json は読み取り専用（geocode.py の管轄）
    - snap_destination_master.json には VRP ソルバーに必要な delivery_id /
      destination_address を geocode master からコピーして保持する
    - graph_metadata.csv（graph.py が生成）でノード数・エッジ数を比較し、
      実質変更がない場合は既存スナップを再利用する

【実行方法】
    python -m vrp_optimization.network.snap
    python -m vrp_optimization.network.snap delivery_transaction_1000
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
import osmnx as ox
import pandas as pd

from vrp_optimization.network.graph import (
    GRAPH_METADATA_PATH,
    NETWORK_TYPE,
    load_graph,
    prefecture_name,
)

_ROOT = Path(__file__).parents[3]
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
TRANSACTION_PATH = _ROOT / "data" / "raw" / "delivery_transaction_1000.csv"
_GEOCODE_DIR = _ROOT / "data" / "processed" / "geocode"
_SNAP_DIR = _ROOT / "data" / "processed" / "snap"

SNAP_WARN_M = 100   # 100m 超: 注意
SNAP_ALERT_M = 200  # 200m 超: 警告

_QUALITY_LABELS: dict[str, str] = {
    "ok": "問題なし",
    "caution": f"注意({SNAP_WARN_M}m超)",
    "warning": f"警告({SNAP_ALERT_M}m超)",
}

logger = logging.getLogger(__name__)


def _normalize(address: str) -> str:
    # geocode.py と同様のロジックを使用している
    return str(address).strip()


def _snap_quality(dist: float) -> str:
    if dist > SNAP_ALERT_M:
        return "warning"
    if dist > SNAP_WARN_M:
        return "caution"
    return "ok"


def _quality_label(quality: str) -> str:
    return _QUALITY_LABELS[quality]


def _snap_node(G: nx.MultiDiGraph, lat: float, lon: float) -> tuple[int, float]:
    """最近傍ノード ID とスナップ距離（m）を返す。"""
    node_id = ox.distance.nearest_nodes(G, X=lon, Y=lat)
    node_data = G.nodes[node_id]
    dist = ox.distance.great_circle(lat, lon, node_data["y"], node_data["x"])
    return node_id, round(dist, 1)


def _detect_graph_change(G: nx.MultiDiGraph, current_graph_name: str) -> bool:
    """graph_metadata.csv の直前エントリとノード数・エッジ数を比較してグラフ変更を検知する。"""
    if not GRAPH_METADATA_PATH.exists():
        return False

    metadata_df = pd.read_csv(GRAPH_METADATA_PATH, encoding="utf-8-sig")
    prev = metadata_df[metadata_df["graph_name"] != current_graph_name]
    if prev.empty:
        return False

    prev_row = prev.iloc[-1]
    return int(prev_row["nodes"]) != len(G.nodes) or int(prev_row["edges"]) != len(G.edges)


def _load_snap_master(path: Path) -> dict[str, dict]:
    """snap_destination_master.json をロードし normalized_destination_address をキーとする辞書を返す。"""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    return {r["normalized_destination_address"]: r for r in records}


def _save_snap_master(path: Path, snap_master: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(snap_master.values()), f, ensure_ascii=False, indent=2)


def snap_depot(G: nx.MultiDiGraph, depot_df: pd.DataFrame, graph_name: str) -> pd.DataFrame:
    """depot_master のデポをスナップし結果列を更新して返す。"""
    depot_df = depot_df.copy()
    now = datetime.now(timezone.utc).isoformat()

    required_cols = [
        "depot_network_node_id", "depot_snap_status", "depot_snap_quality",
        "depot_snap_distance", "depot_snap_latitude", "depot_snap_longitude",
        "depot_snap_graph_name", "depot_snap_at", "depot_snap_updated_at",
    ]
    for col in required_cols:
        if col not in depot_df.columns:
            depot_df[col] = None

    for idx, row in depot_df.iterrows():
        lat, lon = row.get("depot_latitude"), row.get("depot_longitude")

        if row.get("depot_snap_status") == "success" and row.get("depot_snap_graph_name") == graph_name:
            logger.info("  [スキップ] デポは現在の地図でスナップ済み: %s", row["depot_id"])
            continue

        if pd.isna(lat) or pd.isna(lon):
            depot_df.at[idx, "depot_snap_status"] = "failed"
            depot_df.at[idx, "depot_snap_graph_name"] = graph_name
            depot_df.at[idx, "depot_snap_updated_at"] = now
            logger.warning("  [失敗] デポ緯度経度未設定: %s", row["depot_id"])
            continue

        try:
            node_id, dist = _snap_node(G, float(lat), float(lon))
        except Exception as e:
            depot_df.at[idx, "depot_snap_status"] = "failed"
            depot_df.at[idx, "depot_snap_graph_name"] = graph_name
            depot_df.at[idx, "depot_snap_updated_at"] = now
            logger.error("  [失敗] デポスナップエラー: %s (%s)", row["depot_id"], e)
            continue

        quality = _snap_quality(dist)
        is_first = pd.isna(row.get("depot_snap_at"))

        depot_df.at[idx, "depot_network_node_id"] = str(node_id)
        depot_df.at[idx, "depot_snap_status"] = "success"
        depot_df.at[idx, "depot_snap_quality"] = quality
        depot_df.at[idx, "depot_snap_distance"] = dist
        depot_df.at[idx, "depot_snap_latitude"] = float(lat)
        depot_df.at[idx, "depot_snap_longitude"] = float(lon)
        depot_df.at[idx, "depot_snap_graph_name"] = graph_name
        if is_first:
            depot_df.at[idx, "depot_snap_at"] = now
        depot_df.at[idx, "depot_snap_updated_at"] = now

        logger.info(
            "  デポスナップ完了: %s → node=%s dist=%.2fm [%s]",
            row["depot_id"], node_id, dist, _quality_label(quality),
        )

    return depot_df


def _base_snap_record(
    norm: str, geocode_rec: dict, existing: dict, graph_name: str, now: str
) -> dict:
    """skipped/failed/success の共通フィールドを返す。snap_status は呼び出し元が上書きする。"""
    return {
        "normalized_destination_address": norm,
        "delivery_id": geocode_rec.get("delivery_id"),
        "destination_address": geocode_rec.get("destination_address", norm),
        "destination_name": geocode_rec.get("destination_name", ""),
        "snap_quality": None,
        "snap_distance": None,
        "network_node_id": None,
        "snap_latitude": None,
        "snap_longitude": None,
        "snap_graph_name": graph_name,
        "snap_at": existing.get("snap_at"),
        "snap_updated_at": now,
    }


def snap_destinations(
    G: nx.MultiDiGraph,
    unique_norms: set[str],
    geocode_master: dict[str, dict],
    snap_master: dict[str, dict],
    graph_name: str,
    graph_changed: bool,
) -> tuple[dict[str, dict], list[float]]:
    """配送先をスナップし snap_master を更新して返す。完了したスナップの距離リストも返す。"""
    now = datetime.now(timezone.utc).isoformat()

    new_targets: list[str] = []
    map_update_targets: list[str] = []
    retry_targets: list[str] = []
    skipped_norms: list[str] = []
    already_current = 0

    for norm in unique_norms:
        if geocode_master.get(norm, {}).get("geocode_status") != "success":
            skipped_norms.append(norm)
            continue

        snap_rec = snap_master.get(norm)
        if snap_rec is None or snap_rec.get("snap_status") not in ("success", "failed", "skipped"):
            new_targets.append(norm)
        elif snap_rec.get("snap_status") == "failed":
            retry_targets.append(norm)
        elif snap_rec.get("snap_graph_name") == graph_name:
            already_current += 1
        elif graph_changed:
            map_update_targets.append(norm)
        else:
            already_current += 1  # グラフ変更なし → ノード数・エッジ数が同一のため既存を再利用

    logger.info(
        "スナップ対象: 新規 %d 件 / 地図更新 %d 件 / 再スナップ %d 件 / "
        "スキップ(geocode失敗) %d 件 / 処理済 %d 件",
        len(new_targets), len(map_update_targets), len(retry_targets),
        len(skipped_norms), already_current,
    )

    for norm in skipped_norms:
        geocode_rec = geocode_master.get(norm, {})
        existing = snap_master.get(norm, {})
        snap_master[norm] = {
            **_base_snap_record(norm, geocode_rec, existing, graph_name, now),
            "snap_status": "skipped",
        }

    completed_dists: list[float] = []

    def _do_snap(norm: str, label: str) -> None:
        geocode_rec = geocode_master[norm]
        lat = geocode_rec.get("destination_latitude")
        lon = geocode_rec.get("destination_longitude")
        existing = snap_master.get(norm, {})

        try:
            node_id, dist = _snap_node(G, float(lat), float(lon))
        except Exception as e:
            snap_master[norm] = {
                **_base_snap_record(norm, geocode_rec, existing, graph_name, now),
                "snap_status": "failed",
            }
            logger.error("  [失敗][%s] %s (%s)", label, norm[:40], e)
            return

        quality = _snap_quality(dist)
        snap_master[norm] = {
            **_base_snap_record(norm, geocode_rec, existing, graph_name, now),
            "snap_status": "success",
            "snap_quality": quality,
            "snap_distance": dist,
            "network_node_id": str(node_id),
            "snap_latitude": float(lat),
            "snap_longitude": float(lon),
            "snap_at": existing.get("snap_at") or now,  # 初回スナップ時は now を設定
        }
        completed_dists.append(dist)
        logger.info(
            "  [%s] %s → node=%s dist=%.2fm [%s]",
            label, norm[:40], node_id, dist, _quality_label(quality),
        )

    for norm in new_targets:
        _do_snap(norm, "新規")
    for norm in map_update_targets:
        _do_snap(norm, "地図更新")
    for norm in retry_targets:
        _do_snap(norm, "再スナップ")

    return snap_master, completed_dists


def main(input_stem: str | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    input_stem = input_stem or TRANSACTION_PATH.stem
    geocode_master_path = _GEOCODE_DIR / input_stem / "delivery_destination_master.json"
    snap_master_path = _SNAP_DIR / input_stem / "snap_destination_master.json"

    logger.info("=== ノードスナップ開始 ===")
    logger.info("[設定] スナップ距離閾値 — 注意: %dm超 / 警告: %dm超", SNAP_WARN_M, SNAP_ALERT_M)

    G, graph_version = load_graph()
    current_graph_name = f"{prefecture_name}_{NETWORK_TYPE}_{graph_version}.graphml"

    logger.info("--- データ読み込み ---")
    depot_dtypes = {"depot_network_node_id": str, "depot_snap_graph_name": str}
    depot_df = pd.read_csv(DEPOT_PATH, dtype=depot_dtypes)
    df = pd.read_csv(TRANSACTION_PATH)
    with open(geocode_master_path, encoding="utf-8") as f:
        geocode_master = {r["normalized_destination_address"]: r for r in json.load(f)}
    snap_master = _load_snap_master(snap_master_path)

    logger.info("読み込みファイル:")
    logger.info("  デポマスタ     : %s", DEPOT_PATH)
    logger.info("  配送データ     : %s", TRANSACTION_PATH)
    logger.info("  ジオコードJSON : %s", geocode_master_path)

    logger.info("--- デポ情報 ---")
    for _, row in depot_df.iterrows():
        logger.info("デポ: %s (%s)", row["depot_name"], row["depot_id"])

    logger.info("--- デポスナップ ---")
    depot_df = snap_depot(G, depot_df, current_graph_name)

    logger.info("--- 配送先スナップ対象の確認 ---")
    unique_norms = {_normalize(addr) for addr in df["destination_address"]}
    geocode_success_count = sum(
        1 for norm in unique_norms
        if geocode_master.get(norm, {}).get("geocode_status") == "success"
    )
    logger.info(
        "配送先: 総件数 %d 件 / ユニーク %d 件 / うちジオコーディング済み %d 件",
        len(df), len(unique_norms), geocode_success_count,
    )

    graph_changed = _detect_graph_change(G, current_graph_name)
    if graph_changed:
        logger.info("[地図変更あり] ノード数またはエッジ数が変化 — スナップ済み住所を再スナップします")
    else:
        logger.info("[地図変更なし] ノード数・エッジ数が同一 — スナップ済み住所はスキップします")

    logger.info("--- 配送先スナップ ---")
    snap_master, completed_dists = snap_destinations(
        G, unique_norms, geocode_master, snap_master, current_graph_name, graph_changed,
    )

    processed = [snap_master[n] for n in unique_norms if n in snap_master]
    success_recs = [r for r in processed if r.get("snap_status") == "success"]
    skipped_count = sum(1 for r in processed if r.get("snap_status") == "skipped")
    failed_count = sum(1 for r in processed if r.get("snap_status") == "failed")
    logger.info(
        "スナップ結果: 成功 %d 件 / スキップ %d 件 / 失敗 %d 件",
        len(success_recs), skipped_count, failed_count,
    )
    if success_recs:
        ok_count = sum(1 for r in success_recs if r.get("snap_quality") == "ok")
        caution_count = sum(1 for r in success_recs if r.get("snap_quality") == "caution")
        warning_count = sum(1 for r in success_recs if r.get("snap_quality") == "warning")
        logger.info(
            "品質内訳(成功分): 問題なし %d 件 / 注意(%dm超) %d 件 / 警告(%dm超) %d 件",
            ok_count, SNAP_WARN_M, caution_count, SNAP_ALERT_M, warning_count,
        )
    if completed_dists:
        logger.info(
            "スナップ距離統計(今回実行分): 最小 %.2fm / 最大 %.2fm / 平均 %.2fm",
            min(completed_dists), max(completed_dists),
            sum(completed_dists) / len(completed_dists),
        )

    depot_df.to_csv(DEPOT_PATH, index=False, encoding="utf-8-sig")
    _save_snap_master(snap_master_path, snap_master)

    logger.info("保存先:")
    logger.info("  デポマスタ     : %s", DEPOT_PATH)
    logger.info("  スナップJSON   : %s", snap_master_path)


if __name__ == "__main__":
    _input_stem = sys.argv[1] if len(sys.argv) > 1 else None
    main(input_stem=_input_stem)
