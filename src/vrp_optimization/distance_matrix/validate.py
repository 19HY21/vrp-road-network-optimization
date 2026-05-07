"""
【目的】
    OSMnx で計算した OD 行列の距離精度を Google Maps 距離と比較して検証する。
    許容誤差 ±10% を基準に各 OD ペアの乖離率を評価する。

【入力】
    outputs/{plan_id}/distance/od_matrix.csv         （OSMnx 距離）
    outputs/{plan_id}/validation/gas_output.csv      （Google Maps 距離）

【出力】
    outputs/{plan_id}/validation/distance_validation_report.csv

【実行方法】
    python -m vrp_optimization.distance_matrix.validate
    python -m vrp_optimization.distance_matrix.validate PLAN_20260503_160856
"""
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).parents[3]
OUTPUTS_DIR = _ROOT / "outputs"
TOLERANCE_PCT = 10.0  # 許容誤差 ±10%


def _latest_plan_id() -> str:
    plans = sorted(OUTPUTS_DIR.glob("PLAN_*"), reverse=True)
    if not plans:
        raise FileNotFoundError("outputs/ に PLAN_* ディレクトリが見つかりません")
    return plans[0].name


def run_validation(plan_id: str) -> pd.DataFrame:
    dist_dir = OUTPUTS_DIR / plan_id / "distance"
    val_dir = OUTPUTS_DIR / plan_id / "validation"

    osmnx_df = pd.read_csv(dist_dir / "od_matrix.csv")
    gas_df = pd.read_csv(val_dir / "gas_output.csv")

    # GAS でエラーになったペアを除外
    error_rows = gas_df[gas_df["status"] != "OK"]
    if len(error_rows) > 0:
        print(f"  ⚠️  GAS エラー行をスキップ: {len(error_rows)} 件")
        for _, row in error_rows.iterrows():
            print(f"     {row['origin_id']} → {row['dest_id']}: {row['status']}")
    gas_ok = gas_df[gas_df["status"] == "OK"].copy()

    # origin_id + dest_id で突合（od_matrix は destination_id 列名）
    merged = pd.merge(
        osmnx_df,
        gas_ok[["origin_id", "dest_id", "google_distance_km"]],
        left_on=["origin_id", "destination_id"],
        right_on=["origin_id", "dest_id"],
        how="inner",
    )

    if len(merged) == 0:
        raise ValueError("OSMnx と GAS の突合結果が 0 件です。ID の一致を確認してください。")

    # 乖離率計算: (OSMnx - Google) / Google × 100
    merged["diff_km"] = merged["path_distance_km"] - merged["google_distance_km"]
    merged["diff_pct"] = (merged["diff_km"] / merged["google_distance_km"] * 100).round(2)
    merged["within_tolerance"] = merged["diff_pct"].abs() <= TOLERANCE_PCT
    merged["result"] = merged["within_tolerance"].map({True: "✅ PASS", False: "❌ FAIL"})

    return merged[[
        "origin_id", "destination_id",
        "path_distance_km", "google_distance_km",
        "diff_km", "diff_pct", "within_tolerance", "result",
    ]].rename(columns={
        "path_distance_km": "osmnx_distance_km",
    })


def main(plan_id: str | None = None) -> None:
    plan_id = plan_id or _latest_plan_id()
    print(f"=== 距離精度検証 (plan_id: {plan_id}) ===")
    print(f"許容誤差: ±{TOLERANCE_PCT}%\n")

    report_df = run_validation(plan_id)

    total = len(report_df)
    pass_count = report_df["within_tolerance"].sum()
    fail_count = total - pass_count

    # 統計サマリー
    print(f"突合件数   : {total} ペア")
    print(f"PASS       : {pass_count} 件 ({pass_count/total*100:.1f}%)")
    print(f"FAIL       : {fail_count} 件 ({fail_count/total*100:.1f}%)")
    print(f"\n乖離率統計（OSMnx vs Google Maps）:")
    print(f"  平均  : {report_df['diff_pct'].mean():+.2f}%")
    print(f"  中央値: {report_df['diff_pct'].median():+.2f}%")
    print(f"  最大  : {report_df['diff_pct'].max():+.2f}%")
    print(f"  最小  : {report_df['diff_pct'].min():+.2f}%")

    if fail_count > 0:
        print(f"\n❌ FAIL ペア（乖離率が ±{TOLERANCE_PCT}% 超）:")
        fails = report_df[~report_df["within_tolerance"]].sort_values("diff_pct", key=abs, ascending=False)
        for _, row in fails.head(10).iterrows():
            print(f"  {row['origin_id'][:8]}... → {row['destination_id'][:8]}...: "
                  f"OSMnx {row['osmnx_distance_km']:.2f}km / Google {row['google_distance_km']:.2f}km "
                  f"({row['diff_pct']:+.1f}%)")
    else:
        print(f"\n✅ 全ペアが ±{TOLERANCE_PCT}% 以内に収まっています")

    out_path = OUTPUTS_DIR / plan_id / "validation" / "distance_validation_report.csv"
    report_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n保存: {out_path}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(arg)
