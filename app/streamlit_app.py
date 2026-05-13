"""
VRP 配送最適化 Streamlit アプリ。

起動方法:
    streamlit run app/streamlit_app.py

事前に FastAPI サーバーを起動しておくこと:
    uvicorn api.main:app --port 8000
"""
import math
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

API_URL = "http://localhost:8000"
_DEPOT_PATH = Path(__file__).parents[1] / "data" / "raw" / "depot_master.csv"
st.set_page_config(page_title="VRP 配送最適化", layout="wide")


# ── ユーティリティ ──────────────────────────────────────────

_DEFAULT_OUTPUT_DIR = str(Path(__file__).parents[1] / "outputs")


def _pick_folder() -> str:
    """別プロセスで tkinter ダイアログを開き、選択パスを返す。"""
    # StreamlitはブラウザベースでありtkinterのGUIをメインスレッドで直接起動できないため、サブプロセス経由で開く
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


def _fetch_depots() -> list[dict]:
    try:
        r = requests.get(f"{API_URL}/depots", timeout=5)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def _submit_job(
    uploaded_file,
    depot_id: str,
    output_dir: str,
    solve_time_limit: int,
    vehicle_count: int,
) -> str | None:
    try:
        r = requests.post(
            f"{API_URL}/jobs",
            files={"file": (uploaded_file.name, uploaded_file.getvalue(), "text/csv")},
            data={
                "depot_id": depot_id,
                "output_dir": output_dir,
                "solve_time_limit": solve_time_limit,
                "vehicle_count": vehicle_count,
            },
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


_STRATEGY_LABELS = {
    "A": "最近傍法",
    "B": "節約法",
    "C": "クリストフィデス法",
}


def _extract_vehicle_id(stem: str) -> str:
    """route_map_vehicle_{id}_strategy_{s} からビークル ID を抽出する。"""
    m = re.search(r"route_map_vehicle_(\w+)_strategy_", stem)
    return m.group(1) if m else stem


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
        uploaded_file.seek(0)  # プレビューで消費したカーソルを先頭に戻し、後続のAPI送信でファイルを再読み込みできるようにする
        st.dataframe(preview.head(5), width="stretch")

    st.divider()

    # ② デポ選択
    st.subheader("② デポ選択")
    depots = _fetch_depots()
    depot_row = None
    depot_id = ""
    vehicle_count_master = 1

    if depots:
        depot_options = {f"{d['depot_name']} ({d['depot_id']})": d["depot_id"] for d in depots}
        selected_label = st.selectbox("使用するデポ", options=list(depot_options.keys()))
        depot_id = depot_options[selected_label]

        try:
            depot_df = pd.read_csv(_DEPOT_PATH)
            depot_row = depot_df[depot_df["depot_id"] == depot_id].iloc[0]
            capacity = int(depot_row["capacity_per_vehicle"])
            vehicle_count_master = int(depot_row["vehicle_count"])
            st.caption(
                f"最大稼働台数: {vehicle_count_master} 台　|　"
                f"積載上限: {capacity} 個/台　|　"
                f"勤務時間: {depot_row['work_start_time']}〜{depot_row['work_end_time']}"
            )
        except Exception:
            depot_row = None
    else:
        st.error("デポ情報を取得できませんでした")

    # アップロード済み CSV から最低台数を簡易計算
    if uploaded_file is not None and depot_row is not None:
        try:
            _df = pd.read_csv(uploaded_file)
            uploaded_file.seek(0)
            _capacity = int(depot_row["capacity_per_vehicle"])
            _total_packages = int(_df["package_count"].sum())
            _min_vehicles = math.ceil(_total_packages / _capacity)
            st.info(
                f"総荷物数 **{_total_packages} 個** ÷ 1台あたり最大 **{_capacity} 個** "
                f"= 最低 **{_min_vehicles} 台** 必要（積載制約のみの概算）"
            )
        except Exception:
            pass

    st.divider()

    # ③ 車両台数
    st.subheader("③ 車両台数")
    vehicle_count_input = st.number_input(
        "最大稼働台数",
        min_value=1,
        max_value=99,
        value=vehicle_count_master,
        step=1,
        key=f"vehicle_count_{depot_id}",
        help="デポマスタの登録値を初期値とします。変更可能ですがマスタ値を超えると実行できません。",
    )
    if vehicle_count_input > vehicle_count_master:
        st.warning(
            f"マスタ登録値（{vehicle_count_master} 台）を超えています。"
            "実行ボタンを押した時点でエラーとなります。"
        )

    st.divider()

    # ④ ソルバー設定
    st.subheader("④ ソルバー設定")
    solve_time_limit = st.number_input(
        "1戦略あたりの探索時間（秒）",
        min_value=10, max_value=600, value=120, step=10,
    )
    st.caption(
        "**目安（1戦略あたり）**　"
        "🟢 〜20件: 30秒　"
        "🟡 〜50件: 60秒　"
        "🔴 〜100件: 120秒以上　　"
        "※3戦略（A/B/C）分の合計時間がかかります"
    )

    st.divider()

    # ⑤ 出力先フォルダ
    st.subheader("⑤ 出力先フォルダ")
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
        and depot_id != ""
        and _api_available()
        and st.session_state.get("job_id") is None
    )
    if st.button("最適化を実行", type="primary", disabled=not can_run, width="stretch"):
        if vehicle_count_input > vehicle_count_master:
            st.error(
                f"車両台数（{vehicle_count_input} 台）がマスタの上限（{vehicle_count_master} 台）を"
                "超えているため実行できません。台数を修正してください。"
            )
        else:
            job_id = _submit_job(
                uploaded_file, depot_id, output_dir,
                int(solve_time_limit), int(vehicle_count_input),
            )
            if job_id:
                st.session_state.job_id = job_id
                st.rerun()

    # ── 実行中プログレス
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

    # サマリ読み込み・推奨戦略の決定（最小コスト）
    summary_df = pd.read_csv(output_path / "output" / "table" / "route_summary.csv")
    solved = summary_df[summary_df["solve_status"].isin(["OPTIMAL", "FEASIBLE"])].copy()
    solved["total_dist_km"]  = pd.to_numeric(solved["total_dist_km"])
    solved["total_cost_yen"] = pd.to_numeric(solved["total_cost_yen"])
    solved["vehicles_used"]  = pd.to_numeric(solved["vehicles_used"])
    best = solved.sort_values("total_cost_yen").iloc[0]
    best_strategy = str(best["strategy"])

    # 推奨プランメトリクス
    eval_path = output_path / "output" / "table" / "evaluation_report.csv"
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("推奨戦略", f"戦略 {best_strategy}")
    st.caption(f"戦略 A: 最近傍法 　戦略 B: 節約法 　戦略 C: クリストフィデス法")
    col2.metric("推奨使用台数", f"{int(best['vehicles_used'])} 台")
    col3.metric("総走行距離", f"{best['total_dist_km']:.2f} km")
    col4.metric("総コスト", f"¥{int(best['total_cost_yen']):,}")
    if eval_path.exists():
        eval_df = pd.read_csv(eval_path)
        pass_count = (eval_df["status"] == "PASS").sum()
        total_count = len(eval_df)
        col5.metric("制約充足", f"{pass_count} / {total_count} PASS")

    st.divider()

    # 候補プランサマリ
    st.subheader("候補プランサマリ")
    st.dataframe(summary_df, width="stretch")

    # ルート詳細（推奨戦略）
    detail_df = pd.read_csv(output_path / "output" / "table" / "route_detail.csv")
    with st.expander(f"ルート詳細（推奨戦略: {best_strategy}（{_STRATEGY_LABELS.get(best_strategy, best_strategy)}））"):
        st.dataframe(
            detail_df[detail_df["strategy"] == best_strategy],
            width="stretch",
        )

    # 評価レポート（推奨戦略）
    if eval_path.exists():
        with st.expander("制約充足・評価レポート（推奨戦略）"):
            st.dataframe(pd.read_csv(eval_path), width="stretch")

    st.divider()

    # 配送ルートマップ（戦略タブ A / B / C）
    st.subheader("配送ルートマップ")
    image_dir = output_path / "output" / "image"

    available_strategies = [
        s for s in ["A", "B", "C"]
        if (image_dir / f"route_map_strategy_{s}.html").exists()
    ]

    if not available_strategies:
        st.warning("マップファイルが見つかりません。")
        return

    tabs = st.tabs([f"戦略 {s}: {_STRATEGY_LABELS.get(s, s)}" for s in available_strategies])

    for tab, strategy in zip(tabs, available_strategies):
        with tab:
            overview_file = image_dir / f"route_map_strategy_{strategy}.html"
            components.html(overview_file.read_text(encoding="utf-8"), height=520)

            vehicle_files = sorted(
                image_dir.glob(f"route_map_vehicle_*_strategy_{strategy}.html")
            )
            if vehicle_files:
                with st.expander(f"車両別マップ（戦略 {strategy}: {_STRATEGY_LABELS.get(strategy, strategy)}）"):
                    v_labels = [f"車両 {_extract_vehicle_id(f.stem)}" for f in vehicle_files]
                    v_tabs = st.tabs(v_labels)
                    for v_tab, vfile in zip(v_tabs, vehicle_files):
                        with v_tab:
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
