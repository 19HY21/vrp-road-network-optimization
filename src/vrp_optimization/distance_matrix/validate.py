"""
【目的】
    OSMnx で計算した OD 行列の距離精度を Google Maps 距離と比較して検証する。
    許容誤差 ±10% を基準に各 OD ペアの乖離率を評価する。

【入力】
    data/processed/compute/{input_stem}/{depot_id}/od_matrix.csv    （OSMnx 距離）
    outputs/PLAN_{input_stem}_{depot_id}/validation/gas_output.csv  （Google Maps 距離）

【出力】
    outputs/PLAN_{input_stem}_{depot_id}/validation/distance_validation_report.csv

【実行方法】
    python -m vrp_optimization.distance_matrix.validate delivery_transaction_1000 DEPOT_001
"""
import logging
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).parents[3]
OUTPUTS_DIR = _ROOT / "outputs"
_COMPUTE_DIR = _ROOT / "data" / "processed" / "compute"
TOLERANCE_PCT = 10.0

logger = logging.getLogger(__name__)


def run_validation(input_stem: str, depot_id: str) -> pd.DataFrame:
    plan_id = f"PLAN_{input_stem}_{depot_id}"
    osmnx_path = _COMPUTE_DIR / input_stem / depot_id / "od_matrix.csv"
    gas_path = OUTPUTS_DIR / plan_id / "validation" / "gas_output.csv"

    # ── ファイル読み込み ──
    logger.info("OSMnx OD 行列: %s", osmnx_path)
    logger.info("GAS 出力     : %s", gas_path)
    osmnx_df = pd.read_csv(osmnx_path, encoding="utf-8-sig")
    gas_df = pd.read_csv(gas_path, encoding="utf-8-sig")

    # ── OSMnx 件数集計 ──
    osmnx_total_rows = len(osmnx_df)
    osmnx_unique = osmnx_df.drop_duplicates(subset=["origin_id", "destination_id"])
    osmnx_dup = osmnx_total_rows - len(osmnx_unique)
    logger.info("OSMnx: 総行数 %d / ユニーク OD ペア %d", osmnx_total_rows, len(osmnx_unique))
    if osmnx_dup > 0:
        logger.warning("OSMnx: 重複 OD ペア %d 件を検出（先頭行を使用）", osmnx_dup)
        osmnx_df = osmnx_unique

    # ── GAS 件数集計 ──
    gas_total_rows = len(gas_df)
    gas_ok = gas_df[gas_df["status"] == "OK"].drop_duplicates(subset=["origin_id", "dest_id"])
    gas_ng = gas_df[gas_df["status"] != "OK"].drop_duplicates(subset=["origin_id", "dest_id"])
    logger.info(
        "GAS  : 総行数 %d / ユニーク OK %d 件 / ユニーク NG %d 件",
        gas_total_rows, len(gas_ok), len(gas_ng),
    )

    # ── GAS NG 行を除外 ──
    if len(gas_ng) > 0:
        logger.warning("GAS NG ペアを除外: %d 件", len(gas_ng))
        for _, row in gas_ng.iterrows():
            logger.warning("  除外: %s → %s  status=%s", row["origin_id"], row["dest_id"], row["status"])

    # ── Outer join で突合 ──
    merged = pd.merge(
        osmnx_df[["origin_id", "destination_id", "path_distance_km"]].rename(
            columns={"path_distance_km": "osmnx_distance_km"}
        ),
        gas_ok[["origin_id", "dest_id", "google_distance_km"]].rename(
            columns={"dest_id": "destination_id"}
        ),
        on=["origin_id", "destination_id"],
        how="outer",
        indicator=True,
    )
    merged["in_osmnx"] = merged["_merge"].isin(["left_only", "both"])
    merged["in_gas"] = merged["_merge"].isin(["right_only", "both"])
    merged = merged.drop(columns=["_merge"])

    only_osmnx = int((merged["in_osmnx"] & ~merged["in_gas"]).sum())
    only_gas = int((~merged["in_osmnx"] & merged["in_gas"]).sum())
    both_count = int((merged["in_osmnx"] & merged["in_gas"]).sum())
    logger.info(
        "突合結果: 両方一致 %d ペア / OSMnx のみ %d ペア / GAS のみ %d ペア",
        both_count, only_osmnx, only_gas,
    )

    # ── 乖離率計算（突合済みペアのみ） ──
    logger.info("乖離率計算式: (OSMnx距離 - Google距離) / Google距離 × 100")
    logger.info("許容誤差    : ±%.1f%%", TOLERANCE_PCT)

    matched = merged["in_osmnx"] & merged["in_gas"]
    merged["diff_km"] = float("nan")
    merged["diff_pct"] = float("nan")
    merged["within_tolerance"] = pd.NA
    merged["result"] = "UNMATCH"

    if matched.any():
        merged.loc[matched, "diff_km"] = (
            merged.loc[matched, "osmnx_distance_km"] - merged.loc[matched, "google_distance_km"]
        ).round(3)
        merged.loc[matched, "diff_pct"] = (
            merged.loc[matched, "diff_km"] / merged.loc[matched, "google_distance_km"] * 100
        ).round(2)
        merged.loc[matched, "within_tolerance"] = (
            merged.loc[matched, "diff_pct"].abs() <= TOLERANCE_PCT
        )
        merged.loc[matched & merged["within_tolerance"].eq(True), "result"] = "PASS"
        merged.loc[matched & merged["within_tolerance"].eq(False), "result"] = "FAIL"

    return merged[[
        "origin_id", "destination_id",
        "osmnx_distance_km", "google_distance_km",
        "diff_km", "diff_pct",
        "in_osmnx", "in_gas", "within_tolerance", "result",
    ]]


def main(input_stem: str | None = None, depot_id: str | None = None) -> None:
    if input_stem is None or depot_id is None:
        raise ValueError("input_stem と depot_id の両方を指定してください")

    plan_id = f"PLAN_{input_stem}_{depot_id}"
    logger.info("=== 距離精度検証 (plan_id: %s) ===", plan_id)
    logger.info("許容誤差: ±%.1f%%", TOLERANCE_PCT)

    report_df = run_validation(input_stem, depot_id)

    matched_df = report_df[report_df["result"] != "UNMATCH"]
    total = len(matched_df)
    if total == 0:
        logger.warning("突合ペアが 0 件です。ID の一致を確認してください。")
        return

    pass_count = int((matched_df["result"] == "PASS").sum())
    fail_count = int((matched_df["result"] == "FAIL").sum())
    logger.info("突合件数: %d ペア", total)
    logger.info("PASS    : %d 件 (%.1f%%)", pass_count, pass_count / total * 100)
    logger.info("FAIL    : %d 件 (%.1f%%)", fail_count, fail_count / total * 100)

    logger.info("乖離率統計 (OSMnx vs Google Maps):")
    logger.info("  平均  : %+.2f%%", matched_df["diff_pct"].mean())
    logger.info("  中央値: %+.2f%%", matched_df["diff_pct"].median())
    logger.info("  最大  : %+.2f%%", matched_df["diff_pct"].max())
    logger.info("  最小  : %+.2f%%", matched_df["diff_pct"].min())

    if fail_count > 0:
        logger.warning("FAIL ペア (乖離率 ±%.1f%% 超):", TOLERANCE_PCT)
        fails = matched_df[matched_df["result"] == "FAIL"].sort_values(
            "diff_pct", key=abs, ascending=False
        )
        for _, row in fails.head(10).iterrows():
            logger.warning(
                "  %s → %s: OSMnx %.2fkm / Google %.2fkm (%+.1f%%)",
                str(row["origin_id"])[:12], str(row["destination_id"])[:12],
                row["osmnx_distance_km"], row["google_distance_km"], row["diff_pct"],
            )
    else:
        logger.info("全突合ペアが ±%.1f%% 以内に収まっています", TOLERANCE_PCT)

    out_dir = OUTPUTS_DIR / plan_id / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "distance_validation_report.csv"
    report_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    logger.info("保存: %s", out_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    _input_stem = sys.argv[1] if len(sys.argv) > 1 else None
    _depot_id   = sys.argv[2] if len(sys.argv) > 2 else None
    main(_input_stem, _depot_id)
