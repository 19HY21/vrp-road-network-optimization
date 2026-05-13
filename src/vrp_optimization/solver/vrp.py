"""
【目的】
    OD 行列・荷物個数・時間帯制約を OR-Tools CP-SAT に渡し、配送ルートを最適化する。
    車両台数レンジ（max〜min）の各台数で候補プランを生成し結果を保存する。
    INFEASIBLE が確認された時点でそれ以下の台数のループを打ち切る。

【処理の流れ】
    1. outputs/{plan_id}/distance/od_matrix.csv を読み込む
    2. delivery_transaction.csv と delivery_destination_master.json から需要・時間帯を収集する
    3. 車両台数を max から min に向けて順次 CP-SAT で最適化する
    4. 解が得られた台数の中で最小コストプランを推奨とし結果を保存する

【出力先】
    outputs/{plan_id}/output/table/route_summary.csv  （台数別サマリ）
    outputs/{plan_id}/output/table/route_detail.csv   （停留所別詳細）

【最適化モデル】
    目的関数: 固定コスト × 使用台数 + 距離比例コスト × 総走行距離(km)
    制約    : 全件訪問 / 積載上限 / 時間帯 / 業務時間（09:00〜18:00）/ 部分巡回防止

【注意事項】
    - 1 台あたり解探索時間は 30 秒（SOLVE_TIME_LIMIT_SEC で変更可能）
    - snap_status が success の配送先のみを対象とする
    - 同一 delivery_id に複数トランザクションがある場合は荷物個数を合算する

【実行方法】
    python -m vrp_optimization.solver.vrp                         # 最新プランを使用
    python -m vrp_optimization.solver.vrp PLAN_20260503_160856    # プランを指定
"""
import json
import sys
from pathlib import Path

import pandas as pd
from ortools.sat.python import cp_model

_ROOT = Path(__file__).parents[3]
TRANSACTION_PATH = _ROOT / "data" / "raw" / "delivery_transaction.csv"
SNAP_MASTER_PATH = _ROOT / "data" / "processed" / "snap_destination_master.json"
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
OUTPUTS_DIR = _ROOT / "outputs"

SOLVE_TIME_LIMIT_SEC = 120

# 午前/午後の絶対時刻境界（分・勤務時間に依存しない固定値）
_NOON_MIN = 13 * 60  # 13:00 を午前/午後の境界とする


def _build_time_windows(work_start_hour: int, work_minutes: int) -> dict:
    """work_start からの相対オフセット（分）で時間帯窓を返す。
    午前: work_start〜13:00 / 午後: 13:00〜work_end / 指定なし: 全時間
    """
    ws = work_start_hour * 60
    return {
        1: (0, _NOON_MIN - ws),           # 午前: work_start〜13:00
        2: (_NOON_MIN - ws, work_minutes), # 午後: 13:00〜work_end
        3: (0, work_minutes),              # 指定なし
    }


def _latest_plan_id() -> str:
    plans = sorted(OUTPUTS_DIR.glob("PLAN_*"), reverse=True)
    if not plans:
        raise FileNotFoundError("outputs/ に PLAN_* ディレクトリが見つかりません")
    return plans[0].name


def _load_data(plan_id: str, depot_id: str | None = None) -> dict:
    """VRP に必要なデータを収集して辞書で返す。"""
    od_path = OUTPUTS_DIR / plan_id / "distance" / "od_matrix.csv"
    od_df = pd.read_csv(od_path)

    depot_df = pd.read_csv(DEPOT_PATH)
    if depot_id:
        depot_row = depot_df[depot_df["depot_id"] == depot_id].iloc[0]
    else:
        depot_row = depot_df.iloc[0]

    work_start_hour = int(str(depot_row["work_start_time"]).split(":")[0])
    work_end_hour   = int(str(depot_row["work_end_time"]).split(":")[0])
    work_minutes    = (work_end_hour - work_start_hour) * 60
    time_windows_map = _build_time_windows(work_start_hour, work_minutes)

    with open(SNAP_MASTER_PATH, encoding="utf-8") as f:
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
        starts = [time_windows_map[c][0] for c in codes]
        ends = [time_windows_map[c][1] for c in codes]
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
    time_windows = [(0, work_minutes)] + [windows_by_id.get(did, (0, work_minutes)) for did, _ in locations[1:]]

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
        "work_start_hour": work_start_hour,
        "work_minutes": work_minutes,
    }


def _solve_for_k(data: dict, k: int, solve_time_limit: int = SOLVE_TIME_LIMIT_SEC) -> dict:
    """k 台で VRP を OR-Tools CP-SAT で解いて結果辞書を返す。"""
    n = len(data["locations"])
    dist_matrix = data["dist_matrix"]
    time_matrix = data["time_matrix"]
    demands = data["demands"]
    time_windows = data["time_windows"]
    work_minutes = data["work_minutes"]

    model = cp_model.CpModel()

    # アーク変数: vehicle v が地点 i から j へ移動する (i != j)
    arc = {
        (v, i, j): model.new_bool_var(f"x_{v}_{i}_{j}")
        for v in range(k) for i in range(n) for j in range(n) if i != j
    }
    # 自己ループ変数: 未使用車両・未訪問ノードを表現するために全ノードに必要
    loop = {
        (v, i): model.new_bool_var(f"lp_{v}_{i}")
        for v in range(k) for i in range(n)
    }

    # 車両ごとの巡回路制約（自己ループにより未使用車両を許容）
    for v in range(k):
        literals = [(i, j, arc[v, i, j]) for i in range(n) for j in range(n) if i != j]
        literals += [(i, i, loop[v, i]) for i in range(n)]
        model.add_circuit(literals)

    # 各配送先をいずれか 1 台が訪問する（全件訪問制約）
    for i in range(1, n):
        model.add_exactly_one(arc[v, j, i] for v in range(k) for j in range(n) if j != i)

    # visit[v, i]: 車両 v が配送先 i を訪問するか
    visit = {
        (v, i): model.new_bool_var(f"vi_{v}_{i}")
        for v in range(k) for i in range(1, n)
    }
    for v in range(k):
        for i in range(1, n):
            model.add(sum(arc[v, j, i] for j in range(n) if j != i) == visit[v, i])

    # 積載制約
    for v in range(k):
        model.add(sum(demands[i] * visit[v, i] for i in range(1, n)) <= data["capacity"])

    # 到着時刻変数
    arrival = {
        (v, i): model.new_int_var(0, work_minutes, f"t_{v}_{i}")
        for v in range(k) for i in range(n)
    }
    for v in range(k):
        model.add(arrival[v, 0] == 0)

    # 時刻伝播制約
    for v in range(k):
        for i in range(n):
            for j in range(1, n):
                if i != j:
                    model.add(
                        arrival[v, j] >= arrival[v, i] + time_matrix[i][j]
                    ).only_enforce_if(arc[v, i, j])

    # 時間帯制約
    for i in range(1, n):
        tw_s, tw_e = time_windows[i]
        for v in range(k):
            model.add(arrival[v, i] >= tw_s).only_enforce_if(visit[v, i])
            model.add(arrival[v, i] <= tw_e).only_enforce_if(visit[v, i])

    # 業務時間内帰着制約
    for v in range(k):
        for i in range(1, n):
            model.add(
                arrival[v, i] + time_matrix[i][0] <= work_minutes
            ).only_enforce_if(arc[v, i, 0])

    # 使用台数を目的関数に含める: vehicle_active[v] = 1 iff v が 1 件以上訪問
    vehicle_active = {v: model.new_bool_var(f"active_{v}") for v in range(k)}
    for v in range(k):
        model.add_max_equality(vehicle_active[v], [visit[v, i] for i in range(1, n)])

    # 目的関数: fixed_cost * vehicles + dist_unit * dist_km
    # CP-SAT は整数のみのため 1000 倍（ミリ円単位）に変換:
    #   total_cost_milli_yen = fixed_cost * 1000 * active + dist_unit_per_km * dist_m
    fixed_cost_mc = round(data["fixed_cost_yen"] * 1000)
    dist_unit_mc = round(data["dist_unit_cost_yen_per_km"])
    model.minimize(
        sum(fixed_cost_mc * vehicle_active[v] for v in range(k))
        + sum(
            dist_unit_mc * dist_matrix[i][j] * arc[v, i, j]
            for v in range(k) for i in range(n) for j in range(n) if i != j
        )
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = solve_time_limit
    solver.parameters.log_search_progress = False
    solver.parameters.num_search_workers = 1  # macOS + Python 3.13 のスレッド問題を回避

    status_code = solver.solve(model)
    status_name = solver.status_name(status_code)

    if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": status_name, "num_vehicles": k}

    # ルート抽出: デポからアーク連鎖を追跡
    routes = []
    total_dist_m = 0
    vehicles_used = 0
    for v in range(k):
        current = 0
        stops = [{"node": 0, "arrival_min": solver.value(arrival[v, 0])}]
        for _ in range(n):
            moved = False
            for j in range(n):
                if j != current and solver.value(arc[v, current, j]):
                    stops.append({"node": j, "arrival_min": solver.value(arrival[v, j])})
                    current = j
                    moved = True
                    break
            if not moved or current == 0:
                break
        route_dist = sum(
            dist_matrix[stops[s]["node"]][stops[s + 1]["node"]]
            for s in range(len(stops) - 1)
        )
        if len(stops) > 2:
            vehicles_used += 1
            total_dist_m += route_dist
        routes.append(stops)

    total_dist_km = round(total_dist_m / 1000, 2)
    total_cost = data["fixed_cost_yen"] * vehicles_used + data["dist_unit_cost_yen_per_km"] * total_dist_km

    return {
        "status": status_name,
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
        if res["status"] not in ("OPTIMAL", "FEASIBLE"):
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
                    "arrival_time": f"{data['work_start_hour'] + stop['arrival_min'] // 60:02d}:{stop['arrival_min'] % 60:02d}",
                    "package_count": data["demands"][node],
                })

    return pd.DataFrame(summary_rows), pd.DataFrame(detail_rows)


def main(
    plan_id: str | None = None,
    v_min: int | None = None,
    v_max: int | None = None,
    depot_id: str | None = None,
    solve_time_limit: int = SOLVE_TIME_LIMIT_SEC,
    progress_callback=None,
) -> None:
    plan_id = plan_id or _latest_plan_id()
    print(f"=== VRP ソルバー実行 ===")
    print(f"plan_id: {plan_id}")

    data = _load_data(plan_id, depot_id=depot_id)
    if v_min is not None:
        data["vehicle_count_min"] = v_min
    if v_max is not None:
        data["vehicle_count_max"] = v_max

    n_dest = len(data["locations"]) - 1
    total_demand = sum(data["demands"])
    print(f"配送先: {n_dest} 件 / 総荷物: {total_demand} 個")
    print(f"車両台数レンジ: {data['vehicle_count_min']}〜{data['vehicle_count_max']} 台")

    k_min = data["vehicle_count_min"]
    k_max = data["vehicle_count_max"]
    k_total = k_max - k_min + 1

    results = []
    for k in range(k_max, k_min - 1, -1):
        k_done = k_max - k
        if progress_callback:
            progress_callback(k, k_done, k_total)
        print(f"\n  [{k} 台] 最適化中...")
        res = _solve_for_k(data, k, solve_time_limit=solve_time_limit)
        results.append(res)
        if res["status"] in ("OPTIMAL", "FEASIBLE"):
            print(f"  [{k} 台] 完了 ({res['status']}): 走行距離={res['total_dist_km']}km / コスト={res['total_cost_yen']:,.0f}円")
        else:
            print(f"  [{k} 台] 解なし ({res['status']})")
            if res["status"] == "INFEASIBLE":
                print(f"  → INFEASIBLE のためこれ以下の台数の探索を打ち切ります")
                break
            if k == k_max:
                print(f"  → 最大台数 {k_max} 台で解なし ({res['status']}) のため探索を打ち切ります")
                print(f"  → 解決策: ソルバー探索時間を延長するか、デポマスタの最大台数を増やしてください")
                break

    summary_df, detail_df = _build_output(data, results)

    out_dir = OUTPUTS_DIR / plan_id / "output" / "table"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(out_dir / "route_summary.csv", index=False, encoding="utf-8-sig")
    detail_df.to_csv(out_dir / "route_detail.csv", index=False, encoding="utf-8-sig")

    solved = [r for r in results if r["status"] in ("OPTIMAL", "FEASIBLE")]
    if solved:
        best = min(solved, key=lambda r: r["total_cost_yen"])
        print(f"\n推奨プラン: {best['vehicles_used']} 台 / "
              f"走行距離 {best['total_dist_km']} km / コスト {best['total_cost_yen']:,.0f} 円")
    print(f"保存: {out_dir}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(arg)
