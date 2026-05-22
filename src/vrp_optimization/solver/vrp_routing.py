"""
OR-Tools Routing Library を使用した VRP ソルバー。

3 戦略（A: PATH_CHEAPEST_ARC / B: SAVINGS / C: CHRISTOFIDES）で
それぞれ 1 回ずつ解を探索し、候補プランを比較する。
ソルバーが時間内に最小台数を自動算出する。

出力先:
    outputs/{plan_id}/output/table/route_summary.csv
    outputs/{plan_id}/output/table/route_detail.csv
"""
import json
import sys
from pathlib import Path

import pandas as pd
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

_ROOT = Path(__file__).parents[3]
TRANSACTION_PATH = _ROOT / "data" / "raw" / "delivery_transaction.csv"
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
OUTPUTS_DIR = _ROOT / "outputs"
_SNAP_DIR = _ROOT / "data" / "processed" / "snap"
_COMPUTE_DIR = _ROOT / "data" / "processed" / "compute"
SOLVE_TIME_LIMIT_SEC = 120

_NOON_MIN = 13 * 60

# ヒューリスティックごとに解品質が異なるため3戦略を探索し、最小コストを推奨プランとして採用する
_STRATEGIES = [
    ("A", "PATH_CHEAPEST_ARC", routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC),
    ("B", "SAVINGS",           routing_enums_pb2.FirstSolutionStrategy.SAVINGS),
    ("C", "CHRISTOFIDES",      routing_enums_pb2.FirstSolutionStrategy.CHRISTOFIDES),
]


def _latest_plan_id() -> str:
    plans = sorted(OUTPUTS_DIR.glob("PLAN_*"), reverse=True)
    if not plans:
        raise FileNotFoundError("outputs/ に PLAN_* ディレクトリが見つかりません")
    return plans[0].name


def _build_time_windows(work_start_hour: int, work_minutes: int) -> dict:
    # ソルバーは業務開始からの相対分で制約を扱うため、時間帯コードを経過分の範囲に変換する
    ws = work_start_hour * 60
    return {
        1: (0, _NOON_MIN - ws),
        2: (_NOON_MIN - ws, work_minutes),
        3: (0, work_minutes),
    }


def _load_data(plan_id: str, depot_id: str | None = None, input_stem: str | None = None) -> dict:
    snap_master_path = _SNAP_DIR / input_stem / "snap_destination_master.json"
    od_path = _COMPUTE_DIR / input_stem / depot_id / "od_matrix.csv"
    od_df = pd.read_csv(od_path)

    depot_df = pd.read_csv(DEPOT_PATH)
    depot_row = depot_df[depot_df["depot_id"] == depot_id].iloc[0] if depot_id else depot_df.iloc[0]

    work_start_hour = int(str(depot_row["work_start_time"]).split(":")[0])
    work_end_hour   = int(str(depot_row["work_end_time"]).split(":")[0])
    work_minutes    = (work_end_hour - work_start_hour) * 60
    time_windows_map = _build_time_windows(work_start_hour, work_minutes)

    with open(snap_master_path, encoding="utf-8") as f:
        master_records = json.load(f)
    txn_df = pd.read_csv(TRANSACTION_PATH)

    valid_dests = [r for r in master_records if r.get("snap_status") == "success"]

    demands_by_id: dict[str, int] = {}
    windows_by_id: dict[str, tuple[int, int]] = {}
    slot_code_by_id: dict[str, int] = {}
    for did in [r["delivery_id"] for r in valid_dests]:
        rows = txn_df[txn_df["delivery_id"] == did]
        demands_by_id[did] = int(rows["package_count"].sum())
        codes = rows["delivery_time_slot_code"].dropna().unique().tolist()
        starts = [time_windows_map[c][0] for c in codes]
        ends   = [time_windows_map[c][1] for c in codes]
        windows_by_id[did] = (min(starts), max(ends))
        slot_code_by_id[did] = int(codes[0]) if len(codes) == 1 else 3

    dep_id = depot_row["depot_id"]
    locations = [(dep_id, "depot")] + [(r["delivery_id"], r["destination_address"]) for r in valid_dests]
    loc_ids = [loc_id for loc_id, _ in locations]
    n = len(locations)

    dist_lookup = {
        (row["origin_id"], row["destination_id"]): int(row["path_distance_km"] * 1000)
        for _, row in od_df.iterrows()
    }
    time_lookup = {
        (row["origin_id"], row["destination_id"]): int(row["estimated_travel_time_min"])
        for _, row in od_df.iterrows()
    }

    dist_matrix = [[dist_lookup.get((loc_ids[i], loc_ids[j]), 0) for j in range(n)] for i in range(n)]
    time_matrix = [[time_lookup.get((loc_ids[i], loc_ids[j]), 0) for j in range(n)] for i in range(n)]

    demands      = [0] + [demands_by_id.get(did, 0) for did, _ in locations[1:]]
    time_windows = [(0, work_minutes)] + [windows_by_id.get(did, (0, work_minutes)) for did, _ in locations[1:]]
    slot_codes   = [0] + [slot_code_by_id.get(did, 3) for did, _ in locations[1:]]
    morning_end_min = _NOON_MIN - work_start_hour * 60

    return {
        "locations": locations,
        "dist_matrix": dist_matrix,
        "time_matrix": time_matrix,
        "demands": demands,
        "time_windows": time_windows,
        "slot_codes": slot_codes,
        "morning_end_min": morning_end_min,
        "capacity": int(depot_row["capacity_per_vehicle"]),
        "fixed_cost_yen": float(depot_row["fixed_cost_per_vehicle"]),
        "dist_unit_cost_yen_per_km": float(depot_row["distance_unit_cost"]),
        "vehicle_count": int(depot_row["vehicle_count"]),
        "work_start_hour": work_start_hour,
        "work_minutes": work_minutes,
    }


def _solve_for_strategy(
    data: dict,
    k: int,
    strategy_key: str,
    strategy_name: str,
    first_solution_strategy,
    solve_time_limit: int = SOLVE_TIME_LIMIT_SEC,
) -> dict:
    n = len(data["locations"])
    work_minutes = data["work_minutes"]

    manager = pywrapcp.RoutingIndexManager(n, k, 0)
    routing = pywrapcp.RoutingModel(manager)

    dist_unit_mc = round(data["dist_unit_cost_yen_per_km"])

    def distance_callback(from_index, to_index):
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        return data["dist_matrix"][i][j] * dist_unit_mc

    transit_idx = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)
    routing.SetFixedCostOfAllVehicles(round(data["fixed_cost_yen"] * 1000))

    def demand_callback(from_index):
        return data["demands"][manager.IndexToNode(from_index)]

    demand_idx = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_idx, 0, [data["capacity"]] * k, True, "Capacity"
    )

    def time_callback(from_index, to_index):
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        return data["time_matrix"][i][j]

    time_idx = routing.RegisterTransitCallback(time_callback)
    routing.AddDimension(time_idx, work_minutes, work_minutes, True, "Time")
    time_dim = routing.GetDimensionOrDie("Time")

    for i in range(1, n):
        tw_s, tw_e = data["time_windows"][i]
        time_dim.CumulVar(manager.NodeToIndex(i)).SetRange(tw_s, tw_e)

    for v in range(k):
        time_dim.CumulVar(routing.End(v)).SetRange(0, work_minutes)
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.End(v)))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = first_solution_strategy
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = solve_time_limit

    solution = routing.SolveWithParameters(params)

    if solution is None:
        s = routing.status()
        status = "INFEASIBLE" if s == 6 else "FAIL"
        return {"strategy": strategy_key, "strategy_name": strategy_name, "status": status, "num_vehicles": k}

    routes = []
    total_dist_m = 0
    vehicles_used = 0
    for v in range(k):
        index = routing.Start(v)
        stops = []
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            stops.append({"node": node, "arrival_min": solution.Min(time_dim.CumulVar(index))})
            index = solution.Value(routing.NextVar(index))
        node = manager.IndexToNode(index)
        stops.append({"node": node, "arrival_min": solution.Min(time_dim.CumulVar(index))})

        if len(stops) > 2:
            vehicles_used += 1
            total_dist_m += sum(
                data["dist_matrix"][stops[s]["node"]][stops[s + 1]["node"]]
                for s in range(len(stops) - 1)
            )
        routes.append(stops)

    total_dist_km = round(total_dist_m / 1000, 2)
    total_cost = (
        data["fixed_cost_yen"] * vehicles_used
        + data["dist_unit_cost_yen_per_km"] * total_dist_km
    )
    return {
        "strategy": strategy_key,
        "strategy_name": strategy_name,
        "status": "FEASIBLE",
        "num_vehicles": k,
        "vehicles_used": vehicles_used,
        "total_dist_km": total_dist_km,
        "total_cost_yen": round(total_cost, 0),
        "routes": routes,
    }


def _build_output(data: dict, results: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    locations = data["locations"]
    summary_rows = []
    detail_rows = []

    for res in results:
        summary_rows.append({
            "strategy":       res["strategy"],
            "strategy_name":  res["strategy_name"],
            "solve_status":   res["status"],
            "vehicles_used":  res.get("vehicles_used", "-"),
            "total_dist_km":  res.get("total_dist_km", "-"),
            "total_cost_yen": res.get("total_cost_yen", "-"),
        })
        if res["status"] not in ("OPTIMAL", "FEASIBLE"):
            continue
        for v_idx, stops in enumerate(res["routes"]):
            if len(stops) <= 2:
                continue
            for seq, stop in enumerate(stops):
                node = stop["node"]
                loc_id, label = locations[node]
                is_depot = (node == 0)
                arrival = stop["arrival_min"]
                slot = data["slot_codes"][node]
                noon = data["morning_end_min"]
                if is_depot:
                    time_slot_ok = None
                elif slot == 1:
                    time_slot_ok = arrival <= noon
                elif slot == 2:
                    time_slot_ok = arrival >= noon
                else:
                    time_slot_ok = True
                detail_rows.append({
                    "strategy":      res["strategy"],
                    "vehicle_id":    v_idx + 1,
                    "stop_seq":      seq,
                    "location_type": "depot" if is_depot else "destination",
                    "location_id":   loc_id,
                    "address":       label,
                    "arrival_min":   arrival,
                    "arrival_time":  (
                        f"{data['work_start_hour'] + arrival // 60:02d}"
                        f":{arrival % 60:02d}"
                    ),
                    "package_count":  data["demands"][node],
                    "time_slot_code": None if is_depot else slot,
                    "time_slot_ok":   time_slot_ok,
                })

    return pd.DataFrame(summary_rows), pd.DataFrame(detail_rows)


def main(
    plan_id: str | None = None,
    k: int | None = None,
    depot_id: str | None = None,
    solve_time_limit: int = SOLVE_TIME_LIMIT_SEC,
    progress_callback=None,
    input_stem: str | None = None,
) -> None:
    plan_id = plan_id or _latest_plan_id()
    print("=== VRP ソルバー実行 (Routing Library) ===")
    print(f"plan_id: {plan_id}")

    data = _load_data(plan_id, depot_id=depot_id, input_stem=input_stem)
    if k is None:
        k = data["vehicle_count"]

    n_dest = len(data["locations"]) - 1
    total_demand = sum(data["demands"])
    print(f"配送先: {n_dest} 件 / 総荷物: {total_demand} 個")
    print(f"最大車両台数: {k} 台 / 探索時間: {solve_time_limit} 秒/戦略")

    results = []
    for i, (strategy_key, strategy_name, first_solution) in enumerate(_STRATEGIES):
        if progress_callback:
            progress_callback(strategy_key, i, len(_STRATEGIES))
        print(f"\n  [戦略 {strategy_key}: {strategy_name}] 最適化中...")
        res = _solve_for_strategy(data, k, strategy_key, strategy_name, first_solution, solve_time_limit)
        results.append(res)
        if res["status"] in ("OPTIMAL", "FEASIBLE"):
            print(
                f"  [戦略 {strategy_key}] 完了 ({res['status']}): "
                f"実使用={res['vehicles_used']} 台 / "
                f"走行距離={res['total_dist_km']} km / "
                f"コスト={res['total_cost_yen']:,.0f} 円"
            )
        else:
            print(f"  [戦略 {strategy_key}] 解なし ({res['status']})")

    summary_df, detail_df = _build_output(data, results)

    out_dir = OUTPUTS_DIR / plan_id / "output" / "table"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(out_dir / "route_summary.csv", index=False, encoding="utf-8-sig")
    detail_df.to_csv(out_dir / "route_detail.csv", index=False, encoding="utf-8-sig")

    solved = [r for r in results if r["status"] in ("OPTIMAL", "FEASIBLE")]
    if solved:
        best = min(solved, key=lambda r: r["total_cost_yen"])
        print(
            f"\n最良戦略: {best['strategy']} ({best['strategy_name']}) / "
            f"実使用台数 {best['vehicles_used']} 台 / "
            f"走行距離 {best['total_dist_km']} km / "
            f"コスト {best['total_cost_yen']:,.0f} 円"
        )
    print(f"保存: {out_dir}")


if __name__ == "__main__":
    _plan_id   = sys.argv[1] if len(sys.argv) > 1 else None
    _depot_id  = sys.argv[2] if len(sys.argv) > 2 else None
    main(_plan_id, depot_id=_depot_id)
