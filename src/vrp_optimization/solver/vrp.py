"""
【目的】
    OD 行列・荷物個数・時間帯制約を OR-Tools に渡し、配送ルートを最適化する。
    車両台数レンジ（min〜max）の各台数で候補プランを生成し結果を保存する。

【処理の流れ】
    1. outputs/{plan_id}/distance/od_matrix.csv を読み込む
    2. delivery_transaction.csv と delivery_destination_master.json から需要・時間帯を収集する
    3. 車両台数ごとに OR-Tools VRP ソルバーを実行する
    4. 解が得られた台数の中で最小コストプランを推奨とし結果を保存する

【出力先】
    outputs/{plan_id}/output/table/route_summary.csv  （台数別サマリ）
    outputs/{plan_id}/output/table/route_detail.csv   （停留所別詳細）

【最適化モデル】
    目的関数: 固定コスト × 使用台数 + 距離比例コスト × 総走行距離(km)
    制約    : 積載上限 / 時間帯制約 / 業務時間（09:00〜18:00）

【注意事項】
    - 1 台あたり解探索時間は 30 秒（定数 SOLVE_TIME_LIMIT_SEC で変更可能）
    - geocode_status / snap_status が success の配送先のみを対象とする
    - 同一 delivery_id に複数トランザクションがある場合は荷物個数を合算する

【実行方法】
    python -m vrp_optimization.solver.vrp                         # 最新プランを使用
    python -m vrp_optimization.solver.vrp PLAN_20260503_160856    # プランを指定
"""
import json
import sys
from pathlib import Path

import pandas as pd
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

_ROOT = Path(__file__).parents[3]
TRANSACTION_PATH = _ROOT / "data" / "raw" / "delivery_transaction.csv"
MASTER_PATH = _ROOT / "data" / "processed" / "delivery_destination_master.json"
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
OUTPUTS_DIR = _ROOT / "outputs"

SOLVE_TIME_LIMIT_SEC = 30
WORK_START_HOUR = 9   # 09:00 を 0 分の基準とする
WORK_MINUTES = 540    # 09:00〜18:00 = 540 分

# 時間帯コードごとの時間窓（分）: work_start からのオフセット
TIME_WINDOWS = {
    1: (0, 240),    # 午前: 09:00〜13:00
    2: (240, 540),  # 午後: 13:00〜18:00
    3: (0, 540),    # 時間指定なし
}


def _latest_plan_id() -> str:
    plans = sorted(OUTPUTS_DIR.glob("PLAN_*"), reverse=True)
    if not plans:
        raise FileNotFoundError("outputs/ に PLAN_* ディレクトリが見つかりません")
    return plans[0].name


def _load_data(plan_id: str) -> dict:
    """VRP に必要なデータを収集して辞書で返す。"""
    od_path = OUTPUTS_DIR / plan_id / "distance" / "od_matrix.csv"
    od_df = pd.read_csv(od_path)

    depot_df = pd.read_csv(DEPOT_PATH)
    depot_row = depot_df.iloc[0]

    with open(MASTER_PATH, encoding="utf-8") as f:
        master_records = json.load(f)

    txn_df = pd.read_csv(TRANSACTION_PATH)

    # 有効配送先（スナップ済み）を順序付きリストとして構築
    valid_dests = [r for r in master_records if r.get("snap_status") == "success"]

    # delivery_id ごとに荷物個数合算・時間帯幅広取り
    demands_by_id: dict[str, int] = {}
    windows_by_id: dict[str, tuple[int, int]] = {}
    for did in [r["delivery_id"] for r in valid_dests]:
        rows = txn_df[txn_df["delivery_id"] == did]
        demands_by_id[did] = int(rows["package_count"].sum())
        codes = rows["delivery_time_slot_code"].unique().tolist()
        starts = [TIME_WINDOWS[c][0] for c in codes]
        ends = [TIME_WINDOWS[c][1] for c in codes]
        windows_by_id[did] = (min(starts), max(ends))

    # ロケーション順: [depot, dest1, dest2, ...]
    depot_id = depot_row["depot_id"]
    locations = [(depot_id, "depot")] + [(r["delivery_id"], r["destination_address"]) for r in valid_dests]
    loc_ids = [loc_id for loc_id, _ in locations]
    n = len(locations)

    # OD 行列をインデックス行列（メートル整数）に変換
    dist_lookup = {(row["origin_id"], row["destination_id"]): int(row["path_distance_km"] * 1000)
                   for _, row in od_df.iterrows()}
    time_lookup = {(row["origin_id"], row["destination_id"]): int(row["estimated_travel_time_min"])
                   for _, row in od_df.iterrows()}

    dist_matrix = [[dist_lookup.get((loc_ids[i], loc_ids[j]), 0) for j in range(n)] for i in range(n)]
    time_matrix = [[time_lookup.get((loc_ids[i], loc_ids[j]), 0) for j in range(n)] for i in range(n)]

    demands = [0] + [demands_by_id.get(did, 0) for did, _ in locations[1:]]
    time_windows = [(0, WORK_MINUTES)] + [windows_by_id.get(did, (0, WORK_MINUTES)) for did, _ in locations[1:]]

    return {
        "locations": locations,
        "dist_matrix": dist_matrix,
        "time_matrix": time_matrix,
        "demands": demands,
        "time_windows": time_windows,
        "capacity": int(depot_row["capacity_per_vehicle"]),
        "fixed_cost_yen": float(depot_row["fixed_cost_per_vehicle"]),
        "dist_unit_cost_yen_per_km": float(depot_row["distance_unit_cost"]),
        "vehicle_count_min": int(depot_row["vehicle_count_min"]),
        "vehicle_count_max": int(depot_row["vehicle_count_max"]),
    }


def _solve_for_k(data: dict, k: int) -> dict:
    """k 台で VRP を解いて結果辞書を返す。解なし時は status='no_solution'。"""
    n = len(data["locations"])
    manager = pywrapcp.RoutingIndexManager(n, k, 0)
    routing = pywrapcp.RoutingModel(manager)

    dist_matrix = data["dist_matrix"]

    def dist_cb(fi, ti):
        return dist_matrix[manager.IndexToNode(fi)][manager.IndexToNode(ti)]

    transit_idx = routing.RegisterTransitCallback(dist_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    # 固定コストを距離換算で設定
    fixed_cost_m = int(data["fixed_cost_yen"] / data["dist_unit_cost_yen_per_km"] * 1000)
    for v in range(k):
        routing.SetFixedCostOfVehicle(fixed_cost_m, v)

    # 積載制約
    demands = data["demands"]

    def demand_cb(fi):
        return demands[manager.IndexToNode(fi)]

    demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
    routing.AddDimensionWithVehicleCapacity(demand_idx, 0, [data["capacity"]] * k, True, "Capacity")

    # 時間窓制約
    time_matrix = data["time_matrix"]

    def time_cb(fi, ti):
        return time_matrix[manager.IndexToNode(fi)][manager.IndexToNode(ti)]

    time_idx = routing.RegisterTransitCallback(time_cb)
    routing.AddDimension(time_idx, 60, WORK_MINUTES, False, "Time")
    time_dim = routing.GetDimensionOrDie("Time")
    for i, (start, end) in enumerate(data["time_windows"]):
        time_dim.CumulVar(manager.NodeToIndex(i)).SetRange(start, end)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = SOLVE_TIME_LIMIT_SEC

    solution = routing.SolveWithParameters(params)
    if not solution:
        return {"status": "no_solution", "num_vehicles": k}

    # ルート抽出
    routes = []
    total_dist_m = 0
    vehicles_used = 0
    for v in range(k):
        index = routing.Start(v)
        stops = []
        route_dist = 0
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            arrival = solution.Value(time_dim.CumulVar(index))
            stops.append({"node": node, "arrival_min": arrival})
            next_index = solution.Value(routing.NextVar(index))
            route_dist += dist_matrix[node][manager.IndexToNode(next_index)]
            index = next_index
        stops.append({"node": manager.IndexToNode(index), "arrival_min": solution.Value(time_dim.CumulVar(index))})
        if len(stops) > 2:  # depot → depot のみは空ルート
            vehicles_used += 1
            total_dist_m += route_dist
        routes.append(stops)

    total_dist_km = round(total_dist_m / 1000, 2)
    total_cost = data["fixed_cost_yen"] * vehicles_used + data["dist_unit_cost_yen_per_km"] * total_dist_km

    return {
        "status": "success",
        "num_vehicles": k,
        "vehicles_used": vehicles_used,
        "total_dist_km": total_dist_km,
        "total_cost_yen": round(total_cost, 0),
        "routes": routes,
    }


def _build_output(data: dict, results: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """サマリ・詳細 DataFrame を構築する。"""
    locations = data["locations"]
    summary_rows = []
    detail_rows = []

    for res in results:
        summary_rows.append({
            "num_vehicles_tried": res["num_vehicles"],
            "vehicles_used": res.get("vehicles_used", "-"),
            "solve_status": res["status"],
            "total_dist_km": res.get("total_dist_km", "-"),
            "total_cost_yen": res.get("total_cost_yen", "-"),
        })
        if res["status"] != "success":
            continue
        k = res["num_vehicles"]
        for v_idx, stops in enumerate(res["routes"]):
            if len(stops) <= 2:
                continue
            for seq, stop in enumerate(stops):
                node = stop["node"]
                loc_id, label = locations[node]
                detail_rows.append({
                    "num_vehicles": k,
                    "vehicle_id": v_idx + 1,
                    "stop_seq": seq,
                    "location_type": "depot" if node == 0 else "destination",
                    "location_id": loc_id,
                    "address": label,
                    "arrival_min": stop["arrival_min"],
                    "arrival_time": f"{WORK_START_HOUR + stop['arrival_min'] // 60:02d}:{stop['arrival_min'] % 60:02d}",
                    "package_count": data["demands"][node],
                })

    return pd.DataFrame(summary_rows), pd.DataFrame(detail_rows)


def main(plan_id: str | None = None) -> None:
    plan_id = plan_id or _latest_plan_id()
    print(f"=== VRP ソルバー実行 ===")
    print(f"plan_id: {plan_id}")

    data = _load_data(plan_id)
    n_dest = len(data["locations"]) - 1
    total_demand = sum(data["demands"])
    print(f"配送先: {n_dest} 件 / 総荷物: {total_demand} 個")
    print(f"車両台数レンジ: {data['vehicle_count_min']}〜{data['vehicle_count_max']} 台")

    results = []
    for k in range(data["vehicle_count_min"], data["vehicle_count_max"] + 1):
        print(f"\n  [{k} 台] 最適化中...")
        res = _solve_for_k(data, k)
        results.append(res)
        if res["status"] == "success":
            print(f"  [{k} 台] 完了: 走行距離={res['total_dist_km']}km / コスト={res['total_cost_yen']:,.0f}円")
        else:
            print(f"  [{k} 台] 解なし")

    summary_df, detail_df = _build_output(data, results)

    out_dir = OUTPUTS_DIR / plan_id / "output" / "table"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(out_dir / "route_summary.csv", index=False, encoding="utf-8-sig")
    detail_df.to_csv(out_dir / "route_detail.csv", index=False, encoding="utf-8-sig")

    solved = [r for r in results if r["status"] == "success"]
    if solved:
        best = min(solved, key=lambda r: r["total_cost_yen"])
        print(f"\n推奨プラン: {best['vehicles_used']} 台 / "
              f"走行距離 {best['total_dist_km']} km / コスト {best['total_cost_yen']:,.0f} 円")
    print(f"保存: {out_dir}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(arg)
