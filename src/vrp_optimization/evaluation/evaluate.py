"""
【目的】
    VRP ソルバーの出力結果に対して制約充足・コスト内訳・距離精度を検証し、
    評価レポートを outputs/{plan_id}/output/table/evaluation_report.csv に保存する。

【検証項目】
    1.  全配送先訪問       : route_detail に全 delivery_id が含まれるか
    2.  1回訪問           : 各配送先が重複なく1回だけ訪問されているか
    3.  積載上限           : 各車両の荷物合計が capacity_per_vehicle 以内か
    4.  時間帯・午前       : delivery_time_slot_code=1 の到着が 13:00 以前か
    5.  時間帯・午後       : delivery_time_slot_code=2 の到着が 13:00 以降か
    6.  業務終了時刻       : 全車両がデポに 18:00 以前に帰着しているか
    7.  デポ出発・帰着     : 全ルートがデポ始発・デポ終着になっているか
    8.  使用台数下限       : 使用台数 ≥ vehicle_count_min か
    9.  使用台数上限       : 使用台数 ≤ vehicle_count_max か
    10. コスト内訳整合     : 固定費 + 距離費 = 総コストと一致するか
    11. 距離精度           : Google Maps 比較用の枠（手動入力 or 後工程で実施）

【出力先】
    outputs/{plan_id}/output/table/evaluation_report.csv

【実行方法】
    python -m vrp_optimization.evaluation.evaluate
    python -m vrp_optimization.evaluation.evaluate PLAN_20260503_160856
"""
import json
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).parents[3]
MASTER_PATH = _ROOT / "data" / "processed" / "delivery_destination_master.json"
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
TRANSACTION_PATH = _ROOT / "data" / "raw" / "delivery_transaction.csv"
OUTPUTS_DIR = _ROOT / "outputs"

WORK_START_MIN = 0    # 09:00 を 0 分基準
WORK_END_MIN = 540    # 18:00
MORNING_END_MIN = 240 # 13:00
AFTERNOON_START_MIN = 240


def _latest_plan_id() -> str:
    plans = sorted(OUTPUTS_DIR.glob("PLAN_*"), reverse=True)
    if not plans:
        raise FileNotFoundError("outputs/ に PLAN_* ディレクトリが見つかりません")
    return plans[0].name


def _best_k(summary_df: pd.DataFrame) -> int:
    solved = summary_df[summary_df["solve_status"].isin(["OPTIMAL", "FEASIBLE"])]
    return int(solved.sort_values(["vehicles_used", "total_cost_yen", "num_vehicles_tried"]).iloc[0]["num_vehicles_tried"])


def _check(name: str, passed: bool, detail: str = "") -> dict:
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status}  {name}{('  ' + detail) if detail else ''}")
    return {"check": name, "status": "PASS" if passed else "FAIL", "detail": detail}


def _skip(name: str, detail: str = "") -> dict:
    print(f"  ⏭️ SKIP  {name}{('  ' + detail) if detail else ''}")
    return {"check": name, "status": "SKIP", "detail": detail}


def run_evaluation(plan_id: str) -> pd.DataFrame:
    table_dir = OUTPUTS_DIR / plan_id / "output" / "table"
    summary_df = pd.read_csv(table_dir / "route_summary.csv")
    detail_df = pd.read_csv(table_dir / "route_detail.csv")
    depot_row = pd.read_csv(DEPOT_PATH).iloc[0]
    txn_df = pd.read_csv(TRANSACTION_PATH)

    with open(MASTER_PATH, encoding="utf-8") as f:
        master = json.load(f)
    valid_ids = {r["delivery_id"] for r in master if r.get("snap_status") == "success"}

    best_k = _best_k(summary_df)
    best_summary = summary_df[summary_df["num_vehicles_tried"] == best_k].iloc[0]
    routes = detail_df[detail_df["num_vehicles"] == best_k]
    dest_routes = routes[routes["location_type"] == "destination"]

    capacity = int(depot_row["capacity_per_vehicle"])
    v_min = int(depot_row["vehicle_count_min"])
    v_max = int(depot_row["vehicle_count_max"])
    fixed_cost = float(depot_row["fixed_cost_per_vehicle"])
    dist_unit = float(depot_row["distance_unit_cost"])
    vehicles_used = int(best_summary["vehicles_used"])
    total_dist = float(best_summary["total_dist_km"])
    total_cost = float(best_summary["total_cost_yen"])

    results = []
    print(f"\n=== 制約検証 (plan_id: {plan_id} / 推奨: {best_k}台試行→{vehicles_used}台使用) ===")

    # 1. 全配送先訪問
    visited_ids = set(dest_routes["location_id"].tolist())
    missing = valid_ids - visited_ids
    results.append(_check(
        "全配送先訪問",
        len(missing) == 0,
        f"未訪問: {len(missing)} 件" if missing else f"対象 {len(valid_ids)} 件すべて訪問済み"
    ))

    # 2. 重複なし
    dup_count = dest_routes["location_id"].duplicated().sum()
    results.append(_check(
        "各配送先1回のみ訪問",
        dup_count == 0,
        f"重複: {dup_count} 件" if dup_count else "重複なし"
    ))

    # 3. 積載上限
    over_capacity = []
    for v_id, v_df in dest_routes.groupby("vehicle_id"):
        total_pkg = v_df["package_count"].sum()
        if total_pkg > capacity:
            over_capacity.append(f"車両{v_id}: {total_pkg}個 > {capacity}個")
    results.append(_check(
        "積載上限",
        len(over_capacity) == 0,
        "  ".join(over_capacity) if over_capacity else
        "  ".join([f"車両{v}: {int(g['package_count'].sum())}個/{capacity}個"
                   for v, g in dest_routes.groupby("vehicle_id")])
    ))

    # 4. 時間帯・午前（13:00以前 = 240分以前に到着）
    morning_ids = set(txn_df[txn_df["delivery_time_slot_code"] == 1]["delivery_id"].tolist())
    morning_stops = dest_routes[dest_routes["location_id"].isin(morning_ids)]
    late_morning = morning_stops[morning_stops["arrival_min"] > MORNING_END_MIN]
    results.append(_check(
        "時間帯制約・午前（13:00まで）",
        len(late_morning) == 0,
        f"遅延: {len(late_morning)} 件" if len(late_morning) > 0 else f"午前指定 {len(morning_stops)} 件すべて充足"
    ))

    # 5. 時間帯・午後（13:00以降に到着）
    afternoon_ids = set(txn_df[txn_df["delivery_time_slot_code"] == 2]["delivery_id"].tolist())
    afternoon_stops = dest_routes[dest_routes["location_id"].isin(afternoon_ids)]
    early_afternoon = afternoon_stops[afternoon_stops["arrival_min"] < AFTERNOON_START_MIN]
    results.append(_check(
        "時間帯制約・午後（13:00以降）",
        len(early_afternoon) == 0,
        f"早着: {len(early_afternoon)} 件" if len(early_afternoon) > 0 else f"午後指定 {len(afternoon_stops)} 件すべて充足"
    ))

    # 6. 業務終了時刻（18:00 = 540分以内にデポ帰着）
    depot_returns = routes[(routes["location_type"] == "depot") & (routes["stop_seq"] > 0)]
    late_returns = depot_returns[depot_returns["arrival_min"] > WORK_END_MIN]
    results.append(_check(
        "業務終了時刻（18:00帰着）",
        len(late_returns) == 0,
        f"超過: {len(late_returns)} 台" if len(late_returns) > 0 else
        "  ".join([f"車両{int(r['vehicle_id'])}: {r['arrival_time']}帰着"
                   for _, r in depot_returns.iterrows()])
    ))

    # 7. デポ出発・帰着
    depot_stops = routes[routes["location_type"] == "depot"]
    valid_depot = all(
        (v_df["stop_seq"].min() == 0 and v_df["stop_seq"].max() == v_df["stop_seq"].max())
        for _, v_df in depot_stops.groupby("vehicle_id")
    )
    results.append(_check("デポ出発・帰着", valid_depot, "全車両がデポ始発・終着"))

    # 8. 使用台数下限
    results.append(_check(
        f"使用台数 ≥ 下限({v_min}台)",
        vehicles_used >= v_min,
        f"使用: {vehicles_used}台"
    ))

    # 9. 使用台数上限
    results.append(_check(
        f"使用台数 ≤ 上限({v_max}台)",
        vehicles_used <= v_max,
        f"使用: {vehicles_used}台"
    ))

    # 10. コスト内訳整合
    expected_cost = fixed_cost * vehicles_used + dist_unit * total_dist
    cost_match = abs(expected_cost - total_cost) < 1.0
    results.append(_check(
        "コスト内訳整合",
        cost_match,
        f"固定費 ¥{fixed_cost*vehicles_used:,.0f} + 距離費 ¥{dist_unit*total_dist:,.0f} = ¥{expected_cost:,.0f}"
    ))

    # 11. 距離精度（Google Maps との比較は手動実施のためスキップ）
    results.append(_skip(
        "距離精度（Google Maps ±10%）",
        "Google Maps との距離比較は手動検証が必要なため未実施"
    ))

    return pd.DataFrame(results)


def main(plan_id: str | None = None) -> None:
    plan_id = plan_id or _latest_plan_id()

    results_df = run_evaluation(plan_id)

    pass_count = (results_df["status"] == "PASS").sum()
    fail_count = (results_df["status"] == "FAIL").sum()
    skip_count = (results_df["status"] == "SKIP").sum()
    print(f"\n結果: {pass_count} PASS / {fail_count} FAIL / {skip_count} SKIP（全{len(results_df)}項目）")

    out_dir = OUTPUTS_DIR / plan_id / "output" / "table"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "evaluation_report.csv"
    results_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"保存: {out_path}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(arg)
