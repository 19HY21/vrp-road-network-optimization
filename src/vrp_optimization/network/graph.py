"""
【目的】
    神奈川県の OSM 道路グラフを取得・保存・読み込みする。
    `old`ディレクトリで過去バージョンを管理しつつ、`latest`ディレクトリで最新版のキャッシュを再利用する。

【処理の流れ】
    1. `data/processed/osm_network/latest/kanagawa_drive_YYYYMMDD_latest.graphml` が存在すれば読み込んで返す。
    2. 存在しない場合は前日以前の stale な latest ファイルを削除し、Overpass API（osmnx 経由）で取得する。
    3. 取得したグラフは、日付付きファイル名（`kanagawa_drive_YYYYMMDD.graphml`）で `old` ディレクトリに保存し、
       `kanagawa_drive_YYYYMMDD_latest.graphml` として `latest` ディレクトリにもコピーする。

【出力先】
    - 過去バージョン: `data/processed/osm_network/old/kanagawa_drive_YYYYMMDD.graphml`
    - 最新バージョン: `data/processed/osm_network/latest/kanagawa_drive_YYYYMMDD_latest.graphml`
    - グラフメタデータ: `data/processed/osm_network/graph_metadata.csv`

【注意事項】
    - 初回取得時は Overpass API へのネットワークアクセスが発生し数分かかる。
    - グラフは GraphML 形式で保存する（再現性確保のため）。
    - `latest`ディレクトリのファイルを削除して再実行することで、強制的に最新データを再取得できる。

【将来の拡張】
    - 複数都道府県対応:
        - フォルダ構成: `data/processed/osm_network/{都道府県名}/old` および `data/processed/osm_network/{都道府県名}/latest` のように、都道府県ごとにデータを分離する。
        - 実装要件: `mkdir` を用いて、指定された都道府県のディレクトリを動的に作成する。
        - 入力ソース: UIや設定ファイルなど、外部から取得対象の都道府県を指定できるようにする。
    - 定期的なデータ更新:
        - 月次更新: 月に一度など、定期的に`graphml`ファイルを自動で更新する仕組みを導入する。
          (例: cronジョブ、Cloud Schedulerなどの外部連携)

【実行方法】
    python -m vrp_optimization.network.graph
"""

import csv
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
import osmnx as ox

PLACE = "Kanagawa, Japan"
NETWORK_TYPE = "drive"

_ROOT = Path(__file__).parents[3]
NETWORK_DIR = _ROOT / "data" / "processed" / "osm_network"

OLD_NETWORK_DIR = NETWORK_DIR / "old"
LATEST_NETWORK_DIR = NETWORK_DIR / "latest"

GRAPH_METADATA_PATH = _ROOT / "data" / "processed" / "osm_network" / "graph_metadata.csv"
_METADATA_COLUMNS = ["graph_name", "prefecture", "nodes", "edges", "created_at"]

prefecture_name = PLACE.split(',')[0].strip()
logger = logging.getLogger(__name__)


def _get_old_counts_from_metadata(graph_name: str) -> tuple[int, int] | None:
    """
        graph_metadata.csv から指定 graph_name のノード数・エッジ数を返す。
        新しいエントリほど末尾にあるため末尾から検索する。見つからない場合は None を返す。
    """
    if not GRAPH_METADATA_PATH.exists():
        return None
    with open(GRAPH_METADATA_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for row in reversed(rows):
        if row["graph_name"] == graph_name:
            return int(row["nodes"]), int(row["edges"])
    return None


def _ensure_graph_metadata(graph_name: str, prefecture: str, nodes: int, edges: int) -> None:
    """graph_metadata.csv に指定 graph_name のエントリがなければ追記する。"""
    GRAPH_METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)

    file_exists = GRAPH_METADATA_PATH.exists()
    if file_exists:
        with open(GRAPH_METADATA_PATH, encoding="utf-8-sig") as f:
            if graph_name in {row["graph_name"] for row in csv.DictReader(f)}:
                return

    with open(GRAPH_METADATA_PATH, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_METADATA_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "graph_name": graph_name,
            "prefecture": prefecture,
            "nodes": nodes,
            "edges": edges,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    logger.info(f"グラフメタデータ保存: {GRAPH_METADATA_PATH}")


def load_graph() -> tuple[nx.MultiDiGraph, str]:
    """OSM 道路グラフを返す。キャッシュがあれば読み込み、なければ取得して保存する。"""
    today_str = datetime.today().strftime("%Y%m%d")
    versioned_name = f"{prefecture_name}_{NETWORK_TYPE}_{today_str}.graphml"
    latest_path = LATEST_NETWORK_DIR / f"{prefecture_name}_{NETWORK_TYPE}_{today_str}_latest.graphml"

    logger.info("--- 地図データ取得 ---")
    logger.info("対象: %s / network_type=%s", PLACE, NETWORK_TYPE)

    OLD_NETWORK_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_NETWORK_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("キャッシュを確認中...")
    if latest_path.exists():
        logger.info("  → キャッシュが存在します")
        try:
            G = ox.load_graphml(latest_path)
        except Exception as e:
            logger.error(f"既存のキャッシュファイル {latest_path} の読み込み中にエラーが発生しました: {e}")
            latest_path.unlink()
        else:
            nodes, edges = len(G.nodes), len(G.edges)
            logger.info(f"キャッシュから読み込み: {latest_path}")
            logger.info(f"グラフ読み込み完了: nodes={nodes:,}, edges={edges:,} (キャッシュ)")
            _ensure_graph_metadata(versioned_name, prefecture_name, nodes, edges)
            return G, today_str
    else:
        logger.info("  → キャッシュが存在しません")

    old_nodes_count = None
    old_edges_count = None
    for stale in LATEST_NETWORK_DIR.glob(f"{prefecture_name}_{NETWORK_TYPE}_*_latest.graphml"):
        old_name = stale.name.replace("_latest.graphml", ".graphml")
        counts = _get_old_counts_from_metadata(old_name)
        if counts:
            old_nodes_count, old_edges_count = counts
        logger.info(f"古いキャッシュを削除します: {stale.name}")
        stale.unlink()

    logger.info("OSM からグラフを取得中...")
    G = ox.graph_from_place(PLACE, network_type=NETWORK_TYPE)

    versioned_path = OLD_NETWORK_DIR / versioned_name
    ox.save_graphml(G, versioned_path)
    shutil.copy2(versioned_path, latest_path)

    nodes, edges = len(G.nodes), len(G.edges)
    logger.info(f"保存完了: {versioned_path} (nodes={nodes:,}, edges={edges:,})")
    logger.info(f"最新版としてコピー: {latest_path}")
    _ensure_graph_metadata(versioned_name, prefecture_name, nodes, edges)

    if old_nodes_count is not None and old_edges_count is not None:
        node_diff = nodes - old_nodes_count
        edge_diff = edges - old_edges_count
        logger.info(f"ノード数の差分: {node_diff:,} (以前: {old_nodes_count:,}, 現在: {nodes:,})")
        logger.info(f"エッジ数の差分: {edge_diff:,} (以前: {old_edges_count:,}, 現在: {edges:,})")

    return G, today_str


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    load_graph()


if __name__ == "__main__":
    main()
