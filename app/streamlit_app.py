"""
VRP 配送最適化 Streamlit アプリ。

起動方法:
    streamlit run app/streamlit_app.py

事前に FastAPI サーバーを起動しておくこと:
    uvicorn api.main:app --port 8000
"""
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

API_URL = "http://localhost:8000"
st.set_page_config(page_title="VRP 配送最適化", layout="wide")


# ── ユーティリティ ──────────────────────────────────────────

_DEFAULT_OUTPUT_DIR = str(Path(__file__).parents[1] / "outputs")


def _pick_folder() -> str:
    """別プロセスで tkinter ダイアログを開き、選択パスを返す。"""
    import subprocess
    script = (
        "import tkinter as tk;"
        "from tkinter import filedialog;"
        "root = tk.Tk();"
        "root.withdraw();"
        "root.wm_attributes('-topmost', 1);"
        "folder = filedialog.askdirectory(title='出力先フォルダを選択');"
        "root.destroy();"
        "print(folder, end='')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def _api_available() -> bool:
    try:
        r = requests.get(f"{API_URL}/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _submit_job(uploaded_file, v_min: int, v_max: int, output_dir: str) -> str | None:
    try:
        r = requests.post(
            f"{API_URL}/jobs",
            files={"file": (uploaded_file.name, uploaded_file.getvalue(), "text/csv")},
            data={"v_min": v_min, "v_max": v_max, "output_dir": output_dir},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()["job_id"]
        st.error(f"ジョブ送信エラー: {r.json().get('error', r.text)}")
        return None
    except Exception as e:
        st.error(f"API 接続エラー: {e}")
        return None


def _poll_job(job_id: str) -> dict:
    try:
        r = requests.get(f"{API_URL}/jobs/{job_id}", timeout=5)
        return r.json()
    except Exception:
        return {"status": "running", "step": "サーバーと通信中...", "progress": 0.0}


# ── ページ: 入力 ────────────────────────────────────────────

def page_input() -> None:
    st.title("VRP 配送最適化")
    st.caption("配送データをアップロードして最適ルートを生成します")

    if not _api_available():
        st.error(
            "FastAPI サーバーに接続できません。  \n"
            "`uvicorn api.main:app --port 8000` を別ターミナルで起動してください。"
        )

    st.divider()

    # ① 配送データ
    st.subheader("① 配送データ")
    uploaded_file = st.file_uploader(
        "delivery_transaction.csv をアップロード",
        type="csv",
        help="配送先ID・荷物個数・時間帯コードを含む CSV ファイル",
    )
    if uploaded_file:
        preview = pd.read_csv(uploaded_file)
        uploaded_file.seek(0)
        st.dataframe(preview.head(5), width="stretch")

    st.divider()

    # ② 車両台数レンジ
    st.subheader("② 車両台数レンジ")
    col1, col2 = st.columns(2)
    with col1:
        v_min = st.number_input("最小台数", min_value=1, max_value=50, value=2, step=1)
    with col2:
        v_max = st.number_input("最大台数", min_value=1, max_value=50, value=5, step=1)
    if v_min > v_max:
        st.warning("最小台数は最大台数以下にしてください")

    st.divider()

    # ③ 出力先フォルダ
    st.subheader("③ 出力先フォルダ")
    if st.button("フォルダを選択", icon="📁"):
        folder = _pick_folder()
        if folder:
            st.session_state.output_dir = folder

    output_dir = st.session_state.get("output_dir", "")
    if output_dir:
        st.info(f"選択済み: `{output_dir}`")
    else:
        st.warning("フォルダを選択してください")

    st.divider()

    # 実行ボタン
    can_run = (
        uploaded_file is not None
        and output_dir != ""
        and v_min <= v_max
        and _api_available()
        and st.session_state.get("job_id") is None
    )
    if st.button("最適化を実行", type="primary", disabled=not can_run, width="stretch"):
        job_id = _submit_job(uploaded_file, int(v_min), int(v_max), output_dir)
        if job_id:
            st.session_state.job_id = job_id
            st.rerun()

    # ── 実行中プログレス（ボタン直下）
    job_id = st.session_state.get("job_id")
    if job_id:
        job = _poll_job(job_id)
        status = job.get("status", "running")

        st.divider()
        st.progress(float(job.get("progress", 0.0)))
        st.write(f"**{job.get('step', '処理中...')}**")

        if status == "done":
            st.session_state.plan_id = job.get("plan_id")
            st.session_state.output_path = job.get("output_path")
            st.session_state.job_id = None
            st.session_state.page = "done"
            st.rerun()
        elif status == "error":
            st.session_state.error = job.get("error", "不明なエラー")
            st.session_state.traceback = job.get("traceback", "")
            st.session_state.job_id = None
            st.session_state.page = "error"
            st.rerun()
        else:
            time.sleep(2)
            st.rerun()


# ── ページ: 結果 ────────────────────────────────────────────

def page_done() -> None:
    output_path = Path(st.session_state.output_path)
    plan_id = st.session_state.plan_id

    st.title("最適化完了")
    st.caption(f"plan_id: `{plan_id}`  |  出力先: `{output_path}`")

    if st.button("新しい最適化を実行", icon="🔄"):
        st.session_state.page = "input"
        st.rerun()

    st.divider()

    # サマリメトリクス
    summary_df = pd.read_csv(output_path / "output" / "table" / "route_summary.csv")
    solved = summary_df[summary_df["solve_status"].isin(["OPTIMAL", "FEASIBLE"])]
    best = solved.sort_values(["vehicles_used", "total_cost_yen", "num_vehicles_tried"]).iloc[0]

    col1, col2, col3 = st.columns(3)
    col1.metric("推奨使用台数", f"{int(best['vehicles_used'])} 台")
    col2.metric("総走行距離", f"{best['total_dist_km']:.2f} km")
    col3.metric("総コスト", f"¥{int(float(best['total_cost_yen'])):,}")

    st.divider()

    # 候補プランサマリ
    st.subheader("候補プランサマリ")
    st.dataframe(summary_df, width="stretch")

    # ルート詳細
    with st.expander("ルート詳細（全停留所）"):
        detail_df = pd.read_csv(output_path / "output" / "table" / "route_detail.csv")
        best_k = int(best["num_vehicles_tried"])
        st.dataframe(
            detail_df[detail_df["num_vehicles"] == best_k],
            width="stretch",
        )

    # 評価レポート
    eval_path = output_path / "output" / "table" / "evaluation_report.csv"
    if eval_path.exists():
        with st.expander("制約充足・評価レポート"):
            st.dataframe(pd.read_csv(eval_path), width="stretch")

    st.divider()

    # ルートマップ
    st.subheader("配送ルートマップ")
    image_dir = output_path / "output" / "image"
    overview_file = image_dir / "route_map.html"
    vehicle_files = sorted(image_dir.glob("route_map_vehicle_*.html"))

    tab_labels = ["全体俯瞰"] + [f"車両 {f.stem.split('_')[-1]}" for f in vehicle_files]
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        if overview_file.exists():
            components.html(overview_file.read_text(encoding="utf-8"), height=520)

    for tab, vfile in zip(tabs[1:], vehicle_files):
        with tab:
            components.html(vfile.read_text(encoding="utf-8"), height=620)


# ── ページ: エラー ──────────────────────────────────────────

def page_error() -> None:
    st.title("エラーが発生しました")
    st.error(st.session_state.get("error", "不明なエラー"))
    tb = st.session_state.get("traceback", "")
    if tb:
        with st.expander("詳細（traceback）"):
            st.code(tb)
    if st.button("最初に戻る"):
        st.session_state.page = "input"
        st.rerun()


# ── ルーティング ────────────────────────────────────────────

def main() -> None:
    if "page" not in st.session_state:
        st.session_state.page = "input"

    page = st.session_state.page
    if page == "input":
        page_input()
    elif page == "done":
        page_done()
    elif page == "error":
        page_error()


main()
