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


@app.post("/jobs")
async def create_job(
    file: UploadFile = File(..., description="delivery_transaction.csv"),
    v_min: int = Form(..., description="最小車両台数"),
    v_max: int = Form(..., description="最大車両台数"),
    output_dir: str = Form(..., description="出力先フォルダの絶対パス"),
) -> dict:
    if v_min > v_max:
        return JSONResponse(
            status_code=422,
            content={"error": f"v_min ({v_min}) は v_max ({v_max}) 以下にしてください"},
        )

    job_id = str(uuid.uuid4())
    csv_bytes = await file.read()

    # CSV を一時ファイルに保存（サブプロセスに渡すため）
    tmp_csv = Path(tempfile.mktemp(suffix=".csv"))
    tmp_csv.write_bytes(csv_bytes)

    init_job(job_id)

    # OR-Tools CP-SAT はスレッドから呼ぶと macOS でデッドロックするため
    # 別プロセスとして起動する
    subprocess.Popen(
        [
            sys.executable, "-m", "api.pipeline",
            job_id, str(tmp_csv), output_dir, str(v_min), str(v_max),
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
