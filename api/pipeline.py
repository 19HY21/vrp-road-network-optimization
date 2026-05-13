"""
VRP パイプライン実行モジュール。
別プロセス（subprocess）として起動され、ジョブ状態を一時ファイルで管理する。

ステップ:
    1. ジオコーディング
    2. 道路ネットワークへのスナップ
    3. OD 行列計算
    4. VRP ソルバー実行
    5. 評価
    6. 可視化
    7. 出力先への保存
"""
import json
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir

_ROOT = Path(__file__).parents[1]
TRANSACTION_PATH = _ROOT / "data" / "raw" / "delivery_transaction.csv"
OUTPUTS_DIR = _ROOT / "outputs"
# DBを使わずTMP領域のJSONファイルでジョブ状態を管理し、PoC規模での外部依存を最小化する
_JOBS_DIR = Path(gettempdir()) / "vrp_jobs"
_JOBS_DIR.mkdir(exist_ok=True)


# ── ジョブ状態（ファイルベース） ────────────────────────────

def _job_path(job_id: str) -> Path:
    return _JOBS_DIR / f"{job_id}.json"


def init_job(job_id: str) -> None:
    _job_path(job_id).write_text(json.dumps({
        "status": "pending",
        "step": "待機中",
        "progress": 0.0,
        "plan_id": None,
        "output_path": None,
        "error": None,
    }), encoding="utf-8")


def get_job(job_id: str) -> dict | None:
    p = _job_path(job_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def list_jobs() -> list[dict]:
    result = []
    for p in _JOBS_DIR.glob("*.json"):
        job = json.loads(p.read_text(encoding="utf-8"))
        result.append({"job_id": p.stem, **job})
    return result


def _update(job_id: str, **kwargs) -> None:
    p = _job_path(job_id)
    job = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    job.update(kwargs)
    p.write_text(json.dumps(job), encoding="utf-8")


# ── パイプライン実行 ────────────────────────────────────────

def run_pipeline(
    job_id: str,
    transaction_csv_path: Path,
    output_dir: Path,
    depot_id: str,
    solve_time_limit: int = 120,
    vehicle_count: int | None = None,
) -> None:
    sys.path.insert(0, str(_ROOT / "src"))
    try:
        import pandas as pd
        depot_row = pd.read_csv(_ROOT / "data" / "raw" / "depot_master.csv")
        depot_row = depot_row[depot_row["depot_id"] == depot_id].iloc[0]
        k = vehicle_count if vehicle_count is not None else int(depot_row["vehicle_count"])

        _update(job_id, status="running", step="初期化中", progress=0.0)

        # 下流スクリプトが固定パスを参照するため、アップロードCSVで既存ファイルを上書きして互換性を維持する
        TRANSACTION_PATH.write_bytes(transaction_csv_path.read_bytes())

        # Step 1: ジオコーディング
        _update(job_id, step="住所のジオコーディング中", progress=0.05)
        from vrp_optimization.preprocessing.geocode import main as geocode_main
        geocode_main()

        # Step 2: 道路ネットワークへのスナップ
        _update(job_id, step="道路ネットワークへのスナップ中", progress=0.20)
        from vrp_optimization.network.snap import main as snap_main
        snap_main()

        # Step 3: OD 行列計算
        _update(job_id, step="OD 行列計算中（数分かかります）", progress=0.35)
        plan_id = f"PLAN_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        _update(job_id, plan_id=plan_id)
        from vrp_optimization.distance_matrix.compute import main as compute_main
        compute_main(plan_id=plan_id)

        # Step 4: VRP ソルバー実行
        _update(job_id, step="ルート最適化中...", progress=0.55)
        from vrp_optimization.solver.vrp_routing import main as vrp_main

        _STRATEGY_LABELS = {"A": "最近傍法", "B": "節約法", "C": "クリストフィデス法"}

        def solver_progress(strategy_key: str, i: int, total: int) -> None:
            pct = 0.55 + 0.25 * (i / total)
            label = _STRATEGY_LABELS.get(strategy_key, strategy_key)
            _update(
                job_id,
                step=f"ルート最適化中 — 戦略 {strategy_key}（{label}）（{i + 1} / {total}）",
                progress=round(pct, 3),
            )

        vrp_main(plan_id=plan_id, k=k, depot_id=depot_id,
                 solve_time_limit=solve_time_limit, progress_callback=solver_progress)

        # Step 5: 評価
        _update(job_id, step="制約・コスト評価中", progress=0.80)
        from vrp_optimization.evaluation.evaluate import main as eval_main
        eval_main(plan_id=plan_id, depot_id=depot_id)

        # Step 6: 可視化
        _update(job_id, step="ルートマップ生成中", progress=0.88)
        from vrp_optimization.visualization.map import main as map_main
        map_main(plan_id=plan_id)

        # Step 7: 出力先フォルダへコピー
        _update(job_id, step="出力先フォルダへ保存中", progress=0.97)
        src = OUTPUTS_DIR / plan_id
        dst = Path(output_dir) / plan_id
        if src.resolve() == dst.resolve():
            # 出力先がプロジェクト内 outputs/ と同じ場合はコピー不要
            _update(job_id, status="done", step="完了", progress=1.0, output_path=str(src))
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

        _update(job_id, status="done", step="完了", progress=1.0, output_path=str(dst))

    except Exception as e:
        _update(
            job_id,
            status="error",
            step="エラー発生",
            error=str(e),
            traceback=traceback.format_exc(),
        )


# ── サブプロセスとして直接実行 ──────────────────────────────

if __name__ == "__main__":
    # 引数: job_id csv_path output_dir depot_id [vehicle_count] [solve_time_limit]
    args = sys.argv[1:]
    job_id, csv_path, output_dir, depot_id = args[:4]
    vehicle_count = int(args[4]) if len(args) > 4 else None
    solve_time_limit = int(args[5]) if len(args) > 5 else 120
    run_pipeline(job_id, Path(csv_path), Path(output_dir), depot_id, solve_time_limit, vehicle_count)
