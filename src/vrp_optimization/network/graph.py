"""
【目的】
    神奈川県の OSM 道路グラフを取得・保存・読み込みする。
    `old`ディレクトリで過去バージョンを管理しつつ、`latest`ディレクトリで最新版のキャッシュを再利用する。

【処理の流れ】
    1. `data/processed/osm_network/latest/kanagawa_drive_latest.graphml` が存在し、かつ日付が今日と一致すれば読み込んで返す。
    2. `data/processed/osm_network/latest/kanagawa_drive_latest.graphml` の日付が古い場合、または存在しない場合は Overpass API（osmnx 経由）で神奈川県の drive ネットワークを取得する。
    3. 取得したグラフは、日付付きファイル名（`kanagawa_drive_YYYYMMDD.graphml`）で `old` ディレクトリに保存し、
       そのファイルを `latest` ディレクトリ内の `kanagawa_drive_latest.graphml` にもコピーする。

【出力先】
    - 過去バージョン: `data/processed/osm_network/old/kanagawa_drive_YYYYMMDD.graphml`
    - 最新バージョン: `data/processed/osm_network/latest/kanagawa_drive_latest.graphml`

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

import shutil
from datetime import datetime
from pathlib import Path

import networkx as nx
import osmnx as ox

PLACE = "Kanagawa, Japan"
NETWORK_TYPE = "drive"

_ROOT = Path(__file__).parents[3]
NETWORK_DIR = _ROOT / "data" / "processed" / "osm_network"


OLD_NETWORK_DIR = NETWORK_DIR / "old"
LATEST_NETWORK_DIR = NETWORK_DIR / "latest"


prefecture_name = PLACE.split(',')[0].strip()

LATEST_PATH = LATEST_NETWORK_DIR / f"{prefecture_name}_{NETWORK_TYPE}_latest.graphml"


def load_graph() -> tuple[nx.MultiDiGraph, str]:
    """OSM 道路グラフを返す。キャッシュがあれば読み込み、なければ取得して保存する。"""
    today_str = datetime.today().strftime("%Y%m%d") #本日の日付文字列を生成する→キャッシュの鮮度判定とバージョン管理ファイル名に使用するため

    #以前のノード数を初期化する→グラフ更新後に差分を出力しOSMデータの変化量を監視するため
    old_nodes_count = None
    old_edges_count = None

    #保存先ディレクトリを事前作成する→ファイル保存時のFileNotFoundErrorを防ぐため
    OLD_NETWORK_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_NETWORK_DIR.mkdir(parents=True, exist_ok=True)

    #キャッシュファイルの存在を確認する→当日取得済みであれば再利用しAPIへの不要なアクセスを防ぐため
    if LATEST_PATH.exists():
        try:
            #既存キャッシュを読み込む→更新後にノード・エッジ数の差分を計算するため
            old_G = ox.load_graphml(LATEST_PATH)
            old_nodes_count = len(old_G.nodes)
            old_edges_count = len(old_G.edges)
        except Exception as e:
            print(f"既存のキャッシュファイル {LATEST_PATH} の読み込み中にエラーが発生しました: {e}")
            # エラーが発生しても処理を続行するために old_nodes_count, old_edges_count は None のまま

        mod_timestamp = LATEST_PATH.stat().st_mtime
        mod_date_str = datetime.fromtimestamp(mod_timestamp).strftime("%Y%m%d") #ファイルの最終更新日を取得する→当日と比較してキャッシュの鮮度を判定するため

        if mod_date_str != today_str:
            print(f"キャッシュファイル {LATEST_PATH} の日付が古いため削除します (最終更新日: {mod_date_str}, 本日: {today_str})")
            LATEST_PATH.unlink() #古いキャッシュを削除する→次の処理でAPIから最新データを再取得させるため
        else:
            print(f"キャッシュから読み込み: {LATEST_PATH}")
            G = old_G #当日キャッシュをそのまま使用する→APIを呼ばずにグラフを返すことで処理コストを削減するため
            nodes, edges = len(G.nodes), len(G.edges)
            print(f"グラフ読み込み完了: nodes={nodes:,}, edges={edges:,} (キャッシュ)")
            return G, mod_date_str


    print(f"OSM からグラフを取得中: {PLACE} / network_type={NETWORK_TYPE}")
    G = ox.graph_from_place(PLACE, network_type=NETWORK_TYPE) #drive networkのみ取得する→歩道・自転車道を除外し配送車両の走行可能経路のみに絞り込むため

    versioned_path = OLD_NETWORK_DIR / f"{prefecture_name}_{NETWORK_TYPE}_{today_str}.graphml" #日付付きファイル名で保存する→oldディレクトリで過去バージョンを管理し変化量を追跡できる

    ox.save_graphml(G, versioned_path) #GraphML形式で保存する→再取得なしでネットワーク構造を完全に再現でき実験の再現性を確保できる
    shutil.copy2(versioned_path, LATEST_PATH) #versioned_pathをlatestにコピーする→呼び出し元が常に同一パスを参照できシンプルな実装を維持するため

    nodes, edges = len(G.nodes), len(G.edges)
    print(f"保存完了: {versioned_path} (nodes={nodes:,}, edges={edges:,})")
    print(f"最新版としてコピー: {LATEST_PATH}")

    #前回取得値がある場合のみ差分を計算する→OSMデータの変化量を可視化しグラフ品質の監視に役立てる
    if old_nodes_count is not None and old_edges_count is not None:
        node_diff = nodes - old_nodes_count
        edge_diff = edges - old_edges_count
        print(f"ノード数の差分: {node_diff:,} (以前: {old_nodes_count:,}, 現在: {nodes:,})")
        print(f"エッジ数の差分: {edge_diff:,} (以前: {old_edges_count:,}, 現在: {edges:,})")

    return G, today_str


def main() -> None:
    #グラフを取得または読み込む→戻り値の日付文字列でキャッシュ利用か新規取得かを判別できる
    G, graph_date_str = load_graph()


if __name__ == "__main__":
    main()