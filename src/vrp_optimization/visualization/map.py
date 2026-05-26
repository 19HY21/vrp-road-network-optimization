"""
【目的】
    VRP ソルバーの結果（ルート詳細）を Folium で地図上に描画し HTML として保存する。
    ・全体俯瞰マップ（直線）              : route_map.html
    ・車両別詳細マップ（道路沿い + 矢印）  : route_map_vehicle_{id}.html

【出力先】
    outputs/{plan_id}/output/image/route_map.html
    outputs/{plan_id}/output/image/route_map_vehicle_{id}.html

【実行方法】
    python -m vrp_optimization.visualization.map
    python -m vrp_optimization.visualization.map PLAN_20260503_160856
"""
import json
import sys
from pathlib import Path

import folium
from folium.plugins import AntPath
import matplotlib
import matplotlib.colors as mcolors
import osmnx as ox
import pandas as pd

from vrp_optimization.network.graph import OLD_NETWORK_DIR

_ROOT = Path(__file__).parents[3]
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
OUTPUTS_DIR = _ROOT / "outputs"
_SNAP_DIR = _ROOT / "data" / "processed" / "snap"

_FALLBACK_CENTER = [35.45, 139.55]


def _vehicle_colors(n: int) -> list[str]:
    """n 台分の識別色リストを生成する。20台以下は qualitative、21台以上は turbo グラデーション。"""
    n = max(n, 1)
    if n <= 20:
        cmap = matplotlib.colormaps.get_cmap("tab20" if n > 10 else "tab10")
        return [mcolors.to_hex(cmap.colors[i]) for i in range(n)]
    cmap = matplotlib.colormaps.get_cmap("turbo")
    return [mcolors.to_hex(cmap(i / (n - 1))) for i in range(n)]


def _load_snap_graph(snap_master_path: Path):
    with open(snap_master_path, encoding="utf-8") as f:
        records = json.load(f)
    if not records:
        raise ValueError(f"スナップマスタが空です: {snap_master_path}")
    snap_graph_name = records[0]["snap_graph_name"]
    graph_path = OLD_NETWORK_DIR / snap_graph_name
    if not graph_path.exists():
        raise FileNotFoundError(f"スナップ時のグラフが見つかりません: {graph_path}")
    print(f"スナップ時グラフ読み込み: {graph_path}")
    return ox.load_graphml(graph_path)


def _latest_plan_id() -> str:
    plans = sorted(OUTPUTS_DIR.glob("PLAN_*"), reverse=True)
    if not plans:
        raise FileNotFoundError("outputs/ に PLAN_* ディレクトリが見つかりません")
    return plans[0].name


def _build_location_lookup(snap_master_path: Path) -> dict[str, dict]:
    """location_id → {lat, lon, address, node_id} の辞書を返す。"""
    lookup = {}

    depot_df = pd.read_csv(DEPOT_PATH)
    for _, row in depot_df.iterrows():
        lookup[row["depot_id"]] = {
            "lat": float(row["depot_latitude"]),
            "lon": float(row["depot_longitude"]),
            "address": row["depot_name"],
            "type": "depot",
            "node_id": int(row["depot_network_node_id"]),
        }

    with open(snap_master_path, encoding="utf-8") as f:
        master = json.load(f)
    for r in master:
        if r.get("snap_latitude") is None or r.get("snap_longitude") is None:
            continue
        lookup[r["delivery_id"]] = {
            "lat": float(r["snap_latitude"]),
            "lon": float(r["snap_longitude"]),
            "address": r["destination_address"],
            "type": "destination",
            "node_id": int(r["network_node_id"]) if r.get("network_node_id") else None,
        }

    return lookup


def _solved_strategies(summary_df: pd.DataFrame) -> list[str]:
    """解が得られた戦略キーのリストを返す（コスト昇順）。"""
    solved = summary_df[summary_df["solve_status"].isin(["OPTIMAL", "FEASIBLE"])]
    return solved.sort_values(["vehicles_used", "total_cost_yen"])["strategy"].tolist()


def _road_coords(G, from_node: int, to_node: int) -> list[list[float]]:
    """OSMnx 最短経路ノード列から [lat, lon] リストを返す。経路が見つからない場合は空リスト。"""
    try:
        nodes = ox.shortest_path(G, from_node, to_node, weight="length")
        if nodes is None:
            return []
        return [[G.nodes[n]["y"], G.nodes[n]["x"]] for n in nodes]
    except Exception:
        return []


def _add_stop_markers(m: folium.Map, v_df: pd.DataFrame, vehicle_id, color: str, location_lookup: dict) -> None:
    """停留所マーカーとデポマーカーを地図に追加する。"""
    for _, row in v_df.iterrows():
        loc = location_lookup.get(row["location_id"])
        if not loc:
            continue

        if row["location_type"] == "depot":
            if row["stop_seq"] == 0:
                folium.Marker(
                    location=[loc["lat"], loc["lon"]],
                    tooltip="デポ（出発・帰着拠点）",
                    popup=folium.Popup(f"<b>{loc['address']}</b>", max_width=200),
                    icon=folium.Icon(color="black", icon="home", prefix="fa"),
                ).add_to(m)
        else:
            popup_html = (
                f"<b>車両 {vehicle_id} / 停留所 {int(row['stop_seq'])}</b><br>"
                f"{row['address']}<br>"
                f"到着: {row['arrival_time']}<br>"
                f"荷物: {int(row['package_count'])} 個"
            )
            folium.CircleMarker(
                location=[loc["lat"], loc["lon"]],
                radius=8,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.8,
                tooltip=f"車両{vehicle_id} | {row['arrival_time']} | {row['address'][:20]}",
                popup=folium.Popup(popup_html, max_width=250),
            ).add_to(m)
            folium.Marker(
                location=[loc["lat"], loc["lon"]],
                icon=folium.DivIcon(
                    html=f'<div style="font-size:10px; font-weight:bold; color:white;">{int(row["stop_seq"])}</div>',
                    icon_size=(16, 16),
                    icon_anchor=(8, 8),
                ),
            ).add_to(m)


def _add_legend(m: folium.Map, vehicle_ids: list, palette: list[str]) -> None:
    legend_items = ""
    for i, vehicle_id in enumerate(vehicle_ids):
        c = palette[i]
        legend_items += f'<span style="color:{c};">■</span> 車両 {vehicle_id}&nbsp;&nbsp;'
    legend_html = f"""
    <div style="position:fixed; bottom:30px; left:60px; z-index:1000;
                background:white; padding:8px; border-radius:6px;
                border:1px solid #aaa; font-size:13px; font-family:sans-serif;">
        {legend_items}
        <span style="color:black;">⌂ デポ</span>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))


def build_overview_map(plan_id: str, best_summary: pd.Series, routes_df: pd.DataFrame, location_lookup: dict) -> folium.Map:
    """全車両を直線で俯瞰するマップ。"""
    depot_rows = routes_df[routes_df["location_type"] == "depot"]
    if not depot_rows.empty:
        depot_loc = location_lookup.get(depot_rows.iloc[0]["location_id"])
        center = [depot_loc["lat"], depot_loc["lon"]] if depot_loc else _FALLBACK_CENTER
    else:
        center = _FALLBACK_CENTER
    m = folium.Map(location=center, zoom_start=11, tiles="OpenStreetMap")

    title_html = f"""
    <div style="position:fixed; top:10px; left:60px; z-index:1000;
                background:white; padding:10px; border-radius:6px;
                border:2px solid #333; font-size:13px; font-family:sans-serif;">
        <b>VRP 配送ルート（全体俯瞰）</b><br>
        plan_id: {plan_id}<br>
        使用台数: {int(best_summary['vehicles_used'])} 台 &nbsp;|&nbsp;
        総距離: {best_summary['total_dist_km']} km &nbsp;|&nbsp;
        総コスト: ¥{int(float(best_summary['total_cost_yen'])):,}
    </div>
    """
    m.get_root().html.add_child(folium.Element(title_html))

    vehicle_ids = list(routes_df["vehicle_id"].unique())
    palette = _vehicle_colors(len(vehicle_ids))
    v_idx_map = {vid: i for i, vid in enumerate(vehicle_ids)}

    for vehicle_id, v_df in routes_df.groupby("vehicle_id"):
        color = palette[v_idx_map[vehicle_id]]
        v_df = v_df.sort_values("stop_seq")

        _add_stop_markers(m, v_df, vehicle_id, color, location_lookup)

        coords = [
            [location_lookup[sid]["lat"], location_lookup[sid]["lon"]]
            for sid in v_df["location_id"]
            if sid in location_lookup
        ]
        if len(coords) >= 2:
            folium.PolyLine(
                locations=coords,
                color=color,
                weight=3,
                opacity=0.8,
                tooltip=f"車両 {vehicle_id}",
            ).add_to(m)

    _add_legend(m, vehicle_ids, palette)
    return m


def build_vehicle_map(
    plan_id: str, G, vehicle_id, v_df: pd.DataFrame, color: str,
    location_lookup: dict, dist_km: float, cost_yen: float,
) -> folium.Map:
    """車両1台分の道路沿いルート + AntPath 矢印マップ。"""
    v_df = v_df.sort_values("stop_seq")
    stop_ids = v_df["location_id"].tolist()

    lats = [location_lookup[sid]["lat"] for sid in stop_ids if sid in location_lookup]
    lons = [location_lookup[sid]["lon"] for sid in stop_ids if sid in location_lookup]
    dest_count = len(v_df[v_df["location_type"] == "destination"])

    center = [sum(lats) / len(lats), sum(lons) / len(lons)]
    span = max(max(lats) - min(lats), max(lons) - min(lons))
    if span < 0.05:
        zoom = 14
    elif span < 0.15:
        zoom = 13
    elif span < 0.4:
        zoom = 12
    else:
        zoom = 11

    m = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")

    title_html = f"""
    <div style="position:fixed; top:10px; left:60px; z-index:1000;
                background:white; padding:10px; border-radius:6px;
                border:2px solid #333; font-size:13px; font-family:sans-serif;">
        <b>VRP 配送ルート - 車両 {vehicle_id}</b><br>
        plan_id: {plan_id}<br>
        配送先: {dest_count} 件 &nbsp;|&nbsp;
        走行距離: {dist_km:.2f} km &nbsp;|&nbsp;
        コスト: ¥{int(cost_yen):,}
    </div>
    """
    m.get_root().html.add_child(folium.Element(title_html))

    _add_stop_markers(m, v_df, vehicle_id, color, location_lookup)

    for i in range(len(stop_ids) - 1):
        from_loc = location_lookup.get(stop_ids[i])
        to_loc = location_lookup.get(stop_ids[i + 1])
        if not from_loc or not to_loc:
            continue
        from_node = from_loc.get("node_id")
        to_node = to_loc.get("node_id")
        if from_node is None or to_node is None:
            continue
        coords = _road_coords(G, from_node, to_node)
        if len(coords) >= 2:
            AntPath(
                locations=coords,
                color=color,
                weight=4,
                opacity=0.9,
                delay=600,
                tooltip=f"車両 {vehicle_id} | 停留所 {i} → {i + 1}",
            ).add_to(m)

    return m


def _vehicle_stats(routes_df: pd.DataFrame, od_matrix_df: pd.DataFrame, fixed_cost: float, dist_unit: float) -> dict:
    """vehicle_id → {dist_km, cost_yen} を返す。"""
    dist_lookup = {
        (r["origin_id"], r["destination_id"]): r["path_distance_km"]
        for _, r in od_matrix_df.iterrows()
    }
    stats = {}
    for vehicle_id, v_df in routes_df.groupby("vehicle_id"):
        v_df = v_df.sort_values("stop_seq")
        stop_ids = v_df["location_id"].tolist()
        dist_km = sum(
            dist_lookup.get((stop_ids[i], stop_ids[i + 1]), 0.0)
            for i in range(len(stop_ids) - 1)
        )
        stats[vehicle_id] = {
            "dist_km": dist_km,
            "cost_yen": fixed_cost + dist_unit * dist_km,
        }
    return stats


def main(plan_id: str | None = None, depot_id: str | None = None, input_stem: str | None = None) -> None:
    plan_id = plan_id or _latest_plan_id()
    print(f"=== ルートマップ生成 ===")
    print(f"plan_id: {plan_id}")

    snap_master_path = _SNAP_DIR / input_stem / "snap_destination_master.json" if input_stem else None
    if snap_master_path is None or not snap_master_path.exists():
        raise FileNotFoundError(f"スナップマスタが見つかりません: {snap_master_path}")

    table_dir = OUTPUTS_DIR / plan_id / "output" / "table"
    summary_df = pd.read_csv(table_dir / "route_summary.csv")
    detail_df = pd.read_csv(table_dir / "route_detail.csv")
    od_matrix_df = pd.read_csv(_ROOT / "data" / "processed" / "compute" / input_stem / depot_id / "od_matrix.csv")
    location_lookup = _build_location_lookup(snap_master_path)

    depot_df = pd.read_csv(DEPOT_PATH)
    depot_row = depot_df[depot_df["depot_id"] == depot_id].iloc[0] if depot_id else depot_df.iloc[0]

    strategies = _solved_strategies(summary_df)
    if not strategies:
        print("解が得られた戦略がありません。マップ生成をスキップします。")
        return

    out_dir = OUTPUTS_DIR / plan_id / "output" / "image"
    out_dir.mkdir(parents=True, exist_ok=True)

    G = _load_snap_graph(snap_master_path)

    for strategy in strategies:
        strategy_summary = summary_df[summary_df["strategy"] == strategy].iloc[0]
        routes_df = detail_df[detail_df["strategy"] == strategy]

        v_stats = _vehicle_stats(
            routes_df, od_matrix_df,
            float(depot_row["fixed_cost_per_vehicle"]),
            float(depot_row["distance_unit_cost"]),
        )

        # 全体俯瞰マップ（直線・軽量）
        overview = build_overview_map(plan_id, strategy_summary, routes_df, location_lookup)
        overview_path = out_dir / f"route_map_strategy_{strategy}.html"
        overview.save(str(overview_path))
        print(f"保存: {overview_path}")

        # 車両別詳細マップ（道路沿い + AntPath）
        vehicle_ids = list(routes_df["vehicle_id"].unique())
        palette = _vehicle_colors(len(vehicle_ids))
        v_idx_map = {vid: i for i, vid in enumerate(vehicle_ids)}

        for vehicle_id, v_df in routes_df.groupby("vehicle_id"):
            color = palette[v_idx_map[vehicle_id]]
            stats = v_stats[vehicle_id]
            vm = build_vehicle_map(
                plan_id, G, vehicle_id, v_df, color, location_lookup,
                stats["dist_km"], stats["cost_yen"],
            )
            vm_path = out_dir / f"route_map_vehicle_{vehicle_id}_strategy_{strategy}.html"
            vm.save(str(vm_path))
            print(f"保存: {vm_path}")


if __name__ == "__main__":
    _plan_id    = sys.argv[1] if len(sys.argv) > 1 else None
    _depot_id   = sys.argv[2] if len(sys.argv) > 2 else None
    _input_stem = sys.argv[3] if len(sys.argv) > 3 else None
    main(_plan_id, depot_id=_depot_id, input_stem=_input_stem)
