"""
【目的】
    VRP ソルバーの結果（ルート詳細）を Folium で地図上に描画し HTML として保存する。

【処理の流れ】
    1. route_summary.csv から推奨プラン（最小コスト・成功）を特定する
    2. route_detail.csv から対象プランの停留所データを読み込む
    3. delivery_destination_master.json / depot_master.csv から緯度経度を取得する
    4. 車両ごとに異なる色でルートと停留所マーカーを描画する
    5. outputs/{plan_id}/output/image/route_map.html に保存する

【出力先】
    outputs/{plan_id}/output/image/route_map.html

【実行方法】
    python -m vrp_optimization.visualization.map
    python -m vrp_optimization.visualization.map PLAN_20260503_160856
"""
import json
import sys
from pathlib import Path

import folium
import pandas as pd

_ROOT = Path(__file__).parents[3]
MASTER_PATH = _ROOT / "data" / "processed" / "delivery_destination_master.json"
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
OUTPUTS_DIR = _ROOT / "outputs"

VEHICLE_COLORS = ["blue", "red", "green", "purple", "orange"]
KANAGAWA_CENTER = [35.45, 139.55]


def _latest_plan_id() -> str:
    plans = sorted(OUTPUTS_DIR.glob("PLAN_*"), reverse=True)
    if not plans:
        raise FileNotFoundError("outputs/ に PLAN_* ディレクトリが見つかりません")
    return plans[0].name


def _build_location_lookup() -> dict[str, dict]:
    """location_id → {lat, lon, address} の辞書を返す。"""
    lookup = {}

    depot_df = pd.read_csv(DEPOT_PATH)
    for _, row in depot_df.iterrows():
        lookup[row["depot_id"]] = {
            "lat": float(row["depot_latitude"]),
            "lon": float(row["depot_longitude"]),
            "address": row["depot_name"],
            "type": "depot",
        }

    with open(MASTER_PATH, encoding="utf-8") as f:
        master = json.load(f)
    for r in master:
        if r.get("destination_latitude") is None or r.get("destination_longitude") is None:
            continue
        lookup[r["delivery_id"]] = {
            "lat": float(r["destination_latitude"]),
            "lon": float(r["destination_longitude"]),
            "address": r["destination_address"],
            "type": "destination",
        }

    return lookup


def _best_num_vehicles(summary_df: pd.DataFrame) -> int:
    """最小コストで成功したプランの num_vehicles_tried を返す。"""
    solved = summary_df[summary_df["solve_status"] == "success"]
    return int(solved.sort_values("total_cost_yen").iloc[0]["num_vehicles_tried"])


def build_map(plan_id: str) -> folium.Map:
    """ルートマップを構築して返す。"""
    table_dir = OUTPUTS_DIR / plan_id / "output" / "table"
    summary_df = pd.read_csv(table_dir / "route_summary.csv")
    detail_df = pd.read_csv(table_dir / "route_detail.csv")
    location_lookup = _build_location_lookup()

    best_k = _best_num_vehicles(summary_df)
    best_summary = summary_df[summary_df["num_vehicles_tried"] == best_k].iloc[0]
    routes_df = detail_df[detail_df["num_vehicles"] == best_k]

    m = folium.Map(location=KANAGAWA_CENTER, zoom_start=11, tiles="OpenStreetMap")

    # タイトル
    title_html = f"""
    <div style="position:fixed; top:10px; left:60px; z-index:1000;
                background:white; padding:10px; border-radius:6px;
                border:2px solid #333; font-size:13px; font-family:sans-serif;">
        <b>VRP 配送ルート</b><br>
        plan_id: {plan_id}<br>
        使用台数: {int(best_summary['vehicles_used'])} 台 &nbsp;|&nbsp;
        総距離: {best_summary['total_dist_km']} km &nbsp;|&nbsp;
        総コスト: ¥{int(float(best_summary['total_cost_yen'])):,}
    </div>
    """
    m.get_root().html.add_child(folium.Element(title_html))

    # 車両ごとにルートを描画
    for v_idx, (vehicle_id, v_df) in enumerate(routes_df.groupby("vehicle_id")):
        color = VEHICLE_COLORS[v_idx % len(VEHICLE_COLORS)]
        v_df = v_df.sort_values("stop_seq")

        coords = []
        for _, row in v_df.iterrows():
            loc = location_lookup.get(row["location_id"])
            if not loc:
                continue
            coords.append([loc["lat"], loc["lon"]])

            if row["location_type"] == "depot":
                # デポマーカー（最初の1回のみ）
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

                # 停留所番号ラベル
                folium.Marker(
                    location=[loc["lat"], loc["lon"]],
                    icon=folium.DivIcon(
                        html=f'<div style="font-size:10px; font-weight:bold; color:white;">{int(row["stop_seq"])}</div>',
                        icon_size=(16, 16),
                        icon_anchor=(8, 8),
                    ),
                ).add_to(m)

        # ルートの線
        if len(coords) >= 2:
            folium.PolyLine(
                locations=coords,
                color=color,
                weight=3,
                opacity=0.8,
                tooltip=f"車両 {vehicle_id}",
            ).add_to(m)

    # 凡例
    legend_items = ""
    for v_idx, vehicle_id in enumerate(routes_df["vehicle_id"].unique()):
        c = VEHICLE_COLORS[v_idx % len(VEHICLE_COLORS)]
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

    return m


def main(plan_id: str | None = None) -> None:
    plan_id = plan_id or _latest_plan_id()
    print(f"=== ルートマップ生成 ===")
    print(f"plan_id: {plan_id}")

    m = build_map(plan_id)

    out_dir = OUTPUTS_DIR / plan_id / "output" / "image"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "route_map.html"
    m.save(str(out_path))

    print(f"保存完了: {out_path}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(arg)
