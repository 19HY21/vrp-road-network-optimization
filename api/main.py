"""
VRP 最適化 FastAPI サーバー。

エンドポイント:
    POST /jobs           ジョブを作成してサブプロセスで pipeline を実行する
    GET  /jobs/{job_id}  ジョブの状態・進捗・結果を返す
    GET  /jobs           全ジョブ一覧
    GET  /health         ヘルスチェック

起動方法:
    uvicorn api.main:app --port 8000
"""
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from api.pipeline import get_job, init_job, list_jobs

_ROOT = Path(__file__).parents[1]
app = FastAPI(title="VRP Optimization API", version="0.1.0")

# StreamlitとFastAPIが異なるポートで動作するため、開発環境ではオリジン制限を緩和する（本番では限定すること）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/jobs")
def get_jobs() -> list:
    return list_jobs()


@app.get("/depots")
def get_depots() -> list:
    import pandas as pd
    depot_path = _ROOT / "data" / "raw" / "depot_master.csv"
    df = pd.read_csv(depot_path)
    return df[["depot_id", "depot_name"]].to_dict(orient="records")


@app.post("/jobs")
async def create_job(
    file: UploadFile = File(..., description="delivery_transaction.csv"),
    depot_id: str = Form(..., description="使用するデポID"),
    output_dir: str = Form(..., description="出力先フォルダの絶対パス"),
    vehicle_count: int = Form(..., description="最大稼働台数（UI 入力値）"),
    solve_time_limit: int = Form(120, description="1戦略あたりのソルバー制限時間（秒）"),
) -> dict:
    job_id = str(uuid.uuid4())
    csv_bytes = await file.read()

    # アップロードCSVを一時ファイルに保存することで、別プロセスのパイプラインへファイルパスとして渡せるようにする
    tmp_csv = Path(tempfile.mktemp(suffix=".csv"))
    tmp_csv.write_bytes(csv_bytes)

    init_job(job_id)

    subprocess.Popen(
        [
            sys.executable, "-m", "api.pipeline",
            job_id, str(tmp_csv), output_dir, depot_id,
            str(vehicle_count), str(solve_time_limit),
        ],
        cwd=str(_ROOT),
    )

    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def get_job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    return job
