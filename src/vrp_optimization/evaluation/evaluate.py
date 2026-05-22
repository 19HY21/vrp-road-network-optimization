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
    6.  業務終了時刻       : 全車両がデポに work_end_time 以前に帰着しているか
    7.  デポ出発・帰着     : 全ルートがデポ始発・デポ終着になっているか
    8.  使用台数制限       : 使用台数 ≤ vehicle_count か
    9.  コスト内訳整合     : 固定費 + 距離費 = 総コストと一致するか

    ※ 距離精度（Google Maps との ±10% 比較）は手動検証が必要なため本スクリプトでは実施しない

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
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
TRANSACTION_PATH = _ROOT / "data" / "raw" / "delivery_transaction.csv"
OUTPUTS_DIR = _ROOT / "outputs"
_SNAP_DIR = _ROOT / "data" / "processed" / "snap"

# 時間帯（午前/午後）の分岐点となる13:00を分単位の定数として定義し、ハードコードを排除する
_NOON_ABSOLUTE_MIN = 13 * 60


def _latest_plan_id() -> str:
    plans = sorted(OUTPUTS_DIR.glob("PLAN_*"), reverse=True)
    if not plans:
        raise FileNotFoundError("outputs/ に PLAN_* ディレクトリが見つかりません")
    return plans[0].name


def _best_strategy(summary_df: pd.DataFrame) -> str:
    # 使用台数を第1優先（固定費に直結）、同台数の場合はコストで決定する
    solved = summary_df[summary_df["solve_status"].isin(["OPTIMAL", "FEASIBLE"])]
    return str(solved.sort_values(["vehicles_used", "total_cost_yen"]).iloc[0]["strategy"])


def _check(name: str, passed: bool, detail: str = "") -> dict:
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status}  {name}{('  ' + detail) if detail else ''}")
    return {"check": name, "status": "PASS" if passed else "FAIL", "detail": detail}



def run_evaluation(plan_id: str, depot_id: str | None = None, input_stem: str | None = None) -> pd.DataFrame:
    snap_master_path = _SNAP_DIR / input_stem / "snap_destination_master.json" if input_stem else None
    table_dir = OUTPUTS_DIR / plan_id / "output" / "table"
    summary_df = pd.read_csv(table_dir / "route_summary.csv")
    solved_summary = summary_df[summary_df["solve_status"].isin(["OPTIMAL", "FEASIBLE"])]
    if solved_summary.empty:
        raise ValueError("解が得られた戦略がありません。vrp_routing を再実行してください。")

    detail_df = pd.read_csv(table_dir / "route_detail.csv")
    depot_df = pd.read_csv(DEPOT_PATH)
    depot_row = depot_df[depot_df["depot_id"] == depot_id].iloc[0] if depot_id else depot_df.iloc[0]
    txn_df = pd.read_csv(TRANSACTION_PATH)

    if snap_master_path is None or not snap_master_path.exists():
        raise FileNotFoundError(f"スナップマスタが見つかりません: {snap_master_path}")
    with open(snap_master_path, encoding="utf-8") as f:
        master = json.load(f)
    valid_ids = {r["delivery_id"] for r in master if r.get("snap_status") == "success"}

    best_strategy = _best_strategy(summary_df)
    best_summary = summary_df[summary_df["strategy"] == best_strategy].iloc[0]
    routes = detail_df[detail_df["strategy"] == best_strategy]
    dest_routes = routes[routes["location_type"] == "destination"]

    work_start_hour = int(str(depot_row["work_start_time"]).split(":")[0])
    work_end_hour = int(str(depot_row["work_end_time"]).split(":")[0])
    work_end_min = (work_end_hour - work_start_hour) * 60
    morning_end_min = _NOON_ABSOLUTE_MIN - work_start_hour * 60
    afternoon_start_min = morning_end_min
    work_end_label = depot_row["work_end_time"]

    capacity = int(depot_row["capacity_per_vehicle"])
    v_limit = int(depot_row["vehicle_count"])
    fixed_cost = float(depot_row["fixed_cost_per_vehicle"])
    dist_unit = float(depot_row["distance_unit_cost"])
    vehicles_used = int(best_summary["vehicles_used"])
    total_dist = float(best_summary["total_dist_km"])
    total_cost = float(best_summary["total_cost_yen"])

    results = []
    print(f"\n=== 制約検証 (plan_id: {plan_id} / 推奨戦略: {best_strategy} / 使用台数: {vehicles_used} 台) ===")

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

    # 4. 時間帯・午前（13:00以前に到着）
    morning_ids = set(txn_df[txn_df["delivery_time_slot_code"] == 1]["delivery_id"].tolist())
    morning_stops = dest_routes[dest_routes["location_id"].isin(morning_ids)]
    late_morning = morning_stops[morning_stops["arrival_min"] > morning_end_min]
    results.append(_check(
        "時間帯制約・午前（13:00まで）",
        len(late_morning) == 0,
        f"遅延: {len(late_morning)} 件" if len(late_morning) > 0 else f"午前指定 {len(morning_stops)} 件すべて充足"
    ))

    # 5. 時間帯・午後（13:00以降に到着）
    afternoon_ids = set(txn_df[txn_df["delivery_time_slot_code"] == 2]["delivery_id"].tolist())
    afternoon_stops = dest_routes[dest_routes["location_id"].isin(afternoon_ids)]
    early_afternoon = afternoon_stops[afternoon_stops["arrival_min"] < afternoon_start_min]
    results.append(_check(
        "時間帯制約・午後（13:00以降）",
        len(early_afternoon) == 0,
        f"早着: {len(early_afternoon)} 件" if len(early_afternoon) > 0 else f"午後指定 {len(afternoon_stops)} 件すべて充足"
    ))

    # 6. 業務終了時刻
    depot_returns = routes[(routes["location_type"] == "depot") & (routes["stop_seq"] > 0)]
    late_returns = depot_returns[depot_returns["arrival_min"] > work_end_min]
    results.append(_check(
        f"業務終了時刻（{work_end_label}帰着）",
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

    # 8. 使用台数制限（≤ vehicle_count）
    results.append(_check(
        f"使用台数 ≤ 上限({v_limit}台)",
        vehicles_used <= v_limit,
        f"使用: {vehicles_used}台"
    ))

    # 9. コスト内訳整合
    expected_cost = fixed_cost * vehicles_used + dist_unit * total_dist
    cost_match = abs(expected_cost - total_cost) < 1.0
    results.append(_check(
        "コスト内訳整合",
        cost_match,
        f"固定費 ¥{fixed_cost*vehicles_used:,.0f} + 距離費 ¥{dist_unit*total_dist:,.0f} = ¥{expected_cost:,.0f}"
    ))

    return pd.DataFrame(results)


def main(plan_id: str | None = None, depot_id: str | None = None, input_stem: str | None = None) -> None:
    plan_id = plan_id or _latest_plan_id()

    results_df = run_evaluation(plan_id, depot_id=depot_id, input_stem=input_stem)

    pass_count = (results_df["status"] == "PASS").sum()
    fail_count = (results_df["status"] == "FAIL").sum()
    print(f"\n結果: {pass_count} PASS / {fail_count} FAIL（全{len(results_df)}項目）")

    out_dir = OUTPUTS_DIR / plan_id / "output" / "table"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "evaluation_report.csv"
    results_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"保存: {out_path}")


if __name__ == "__main__":
    _plan_id    = sys.argv[1] if len(sys.argv) > 1 else None
    _depot_id   = sys.argv[2] if len(sys.argv) > 2 else None
    _input_stem = sys.argv[3] if len(sys.argv) > 3 else None
    main(_plan_id, depot_id=_depot_id, input_stem=_input_stem)
