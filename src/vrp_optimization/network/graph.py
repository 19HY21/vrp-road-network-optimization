"""
【目的】
    神奈川県の OSM 道路グラフを取得・保存・読み込みする。
    キャッシュが存在する場合はネットワークアクセスを行わず再利用する。

【処理の流れ】
    1. data/processed/osm_network/kanagawa_drive_latest.graphml が存在すれば読み込んで返す
    2. 存在しない場合は Overpass API（osmnx 経由）で神奈川県の drive ネットワークを取得する
    3. 版付きファイル名（kanagawa_drive_YYYYMMDD.graphml）で保存し、
       latest.graphml にもコピーする

【出力先】
    data/processed/osm_network/kanagawa_drive_YYYYMMDD.graphml
    data/processed/osm_network/kanagawa_drive_latest.graphml

【注意事項】
    - 初回取得時は Overpass API へのネットワークアクセスが発生し数分かかる
    - グラフは GraphML 形式で保存する（再現性確保のため）
    - 月次など OSM 更新時は latest.graphml を削除して再実行することで再取得できる

【実行方法】
    python -m vrp_optimization.network.graph
"""
import shutil
from datetime import datetime
from pathlib import Path

import networkx as nx
import osmnx as ox

_ROOT = Path(__file__).parents[3]
NETWORK_DIR = _ROOT / "data" / "processed" / "osm_network"
LATEST_PATH = NETWORK_DIR / "kanagawa_drive_latest.graphml"

PLACE = "Kanagawa, Japan"
NETWORK_TYPE = "drive"


def load_graph() -> nx.MultiDiGraph:
    """OSM 道路グラフを返す。キャッシュがあれば読み込み、なければ取得して保存する。"""
    if LATEST_PATH.exists():
        print(f"キャッシュから読み込み: {LATEST_PATH}")
        return ox.load_graphml(LATEST_PATH)

    print(f"OSM からグラフを取得中: {PLACE} / network_type={NETWORK_TYPE}")
    G = ox.graph_from_place(PLACE, network_type=NETWORK_TYPE)

    NETWORK_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.today().strftime("%Y%m%d")
    versioned_path = NETWORK_DIR / f"kanagawa_drive_{date_str}.graphml"

    ox.save_graphml(G, versioned_path)
    shutil.copy2(versioned_path, LATEST_PATH)

    nodes, edges = len(G.nodes), len(G.edges)
    print(f"保存完了: {versioned_path} (nodes={nodes:,}, edges={edges:,})")
    return G


def main() -> None:
    G = load_graph()
    print(f"グラフ読み込み完了: nodes={len(G.nodes):,}, edges={len(G.edges):,}")


if __name__ == "__main__":
    main()
