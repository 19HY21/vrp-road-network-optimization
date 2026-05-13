"""
【目的】
    delivery_transaction_1000.csv の配送先住所を緯度経度に変換し、
    processed/delivery_destination_master.json にキャッシュする前処理スクリプト。
    depot_master.csv のデポ住所も未設定の場合にジオコーディングする。

【処理の流れ】
    1. delivery_transaction_1000.csv / depot_master.csv / delivery_destination_master.json を読み込む
    2. depot_master.csv の全デポ住所から都道府県をユニーク抽出し、配送先フィルタの基準とする
    3. デポ住所をジオコーディングする（緯度経度未設定のデポのみ）
       - API 結果が市区レベルまたは対象都道府県外の場合は失敗として記録し処理を停止する
    4. キャッシュ済みエントリを再検証し、都道府県フィルタを満たさないものを無効化する
    5. 配送先を事前フィルタリングし API 処理対象を抽出する
       - ① 都道府県フィルタ: 対象外都道府県の住所は API を呼ばず失敗として記録する
       - ② JSON 上に success で存在: スキップ
       - ③ JSON 上に failed で存在: 再試行
       - ④ JSON 上にない: 新規取得
    6. 国土地理院（GSI）API でジオコーディングする
       - API 結果が市区レベルまたは対象都道府県外の場合は失敗として記録する
       - API 呼び出し 100 件ごとに JSON へ中間保存する（障害時のデータ消失を防ぐため）
    7. 失敗住所を CSV に上書き保存する
    8. 保存先ファイルパスをすべて logging で明示する

【出力先】
    data/processed/delivery_destination_master.json
    data/raw/delivery_transaction_1000.csv        （delivery_id 列を更新）
    data/raw/depot_master.csv                      （depot_latitude / depot_longitude を更新）
    data/processed/geocode_failures_delivery.csv  （失敗した配送先住所）
    data/processed/geocode_failures_depot.csv     （失敗したデポ住所）

【注意事項】
    - 国土地理院 API は無料・API キー不要だが、過負荷を避けるため 0.2s 間隔を確保する
    - ジオコーディング失敗行は緯度経度が null のまま残る（後続ステップで除外）
    - 都道府県フィルタは depot_master.csv の全デポ住所から自動抽出する（マルチデポ対応）
    - 都道府県事前フィルタは日本語住所（都道府県名が漢字で始まる形式）のみ対応する
    - 途中でクラッシュした場合は再実行することでキャッシュ済みエントリをスキップして再開できる
    - 実行時にネットワークアクセスが発生する

【実行方法】
    python -m vrp_optimization.preprocessing.geocode
"""
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

_ROOT = Path(__file__).parents[3]
TRANSACTION_PATH = _ROOT / "data" / "raw" / "delivery_transaction_1000.csv"
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
MASTER_PATH = _ROOT / "data" / "processed" / "delivery_destination_master.json"
GEOCODE_FAILURES_DELIVERY_PATH = _ROOT / "data" / "processed" / "geocode_failures_delivery.csv"
GEOCODE_FAILURES_DEPOT_PATH = _ROOT / "data" / "processed" / "geocode_failures_depot.csv"

GSI_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch"
GSI_PAUSE = 0.2  # seconds between requests

CHECKPOINT_INTERVAL = 100  # API呼び出しがこの件数に達するたびにJSONへ中間保存する

logger = logging.getLogger(__name__)


def _extract_prefecture(address: str) -> str | None:
    """
        住所文字列の先頭から都道府県名を抽出する。
        NOTE:
            現在は日本語住所（都道府県名が漢字で始まる形式）のみ対応。英語表記（"Kanagawa-ken" 等）への対応は将来拡張とする。
    """
    m = re.match(r"^(東京都|大阪府|京都府|北海道|.{2,4}県)", str(address))
    return m.group(1) if m else None


def _extract_prefectures(depot_df: pd.DataFrame) -> set[str]:
    """
        depot_master の全デポ住所から都道府県名をユニーク抽出する。
        NOTE:
            異なる都道府県のデポが混在する場合もすべてのデポ都道府県を有効として扱う仕様としている。
            デポが追加されるたびに有効都道府県セットが自動拡張されるため、個別の設定変更は不要。
    """
    return {pref for addr in depot_df["depot_address"] if (pref := _extract_prefecture(addr))}


def _is_geocode_valid(title: str, target_prefectures: set[str] | None) -> bool:
    """
        ジオコーディング結果（API レスポンスのタイトル）が有効かチェックする。
            - 市・区レベルで終わっている（丁目・町名がない）場合は粒度不足として無効
            - target_prefectures が指定されており対象都道府県外の場合は無効
    """
    if re.search(r"[市区]$", title):
        return False
    if target_prefectures and not any(title.startswith(p) for p in target_prefectures):
        return False
    return True


def geocode_address(
    address: str, target_prefectures: set[str] | None = None
) -> tuple[tuple[float, float, str] | None, str | None]:
    """
        国土地理院 API で住所をジオコーディングする。
        Returns:
            (result, failure_reason)
            - 成功時: ((lat, lon, title), None)
            - 失敗時: (None, "api_no_result" | "api_invalid_result")
    """
    try:
        resp = requests.get(GSI_URL, params={"q": address}, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        if not results:
            return None, "api_no_result"
        lon, lat = results[0]["geometry"]["coordinates"]
        title = results[0]["properties"]["title"]
        if not _is_geocode_valid(title, target_prefectures):
            return None, "api_invalid_result"
        return (lat, lon, title), None
    except Exception:
        return None, "api_no_result"
    finally:
        time.sleep(GSI_PAUSE)


def _load_master(path: Path) -> dict[str, dict]:
    """delivery_destination_master.json をロードし normalized_address をキーとする辞書を返す。"""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    return {r["normalized_destination_address"]: r for r in records}


def _save_master(path: Path, master: dict[str, dict]) -> None:
    """delivery_destination_master.json を保存する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(master.values()), f, ensure_ascii=False, indent=2)


def _normalize(address: str) -> str:
    """
        住所文字列を正規化する。
    NOTE:
        全角半角変換やスペースの統一などもここで行う想定。
    """
    return str(address).strip()


def _revalidate_cached_entries(master: dict, target_prefectures: set[str] | None) -> int:
    """
        キャッシュ済みエントリのうち現在のバリデーションに通らないものを無効化する。
        geocode / snap 両方のフィールドをリセットして再スナップを強制する。
    """
    count = 0
    now = datetime.now(timezone.utc).isoformat()
    for r in master.values():
        if r.get("geocode_status") != "success":
            continue
        title = r.get("geocode_resolved_title") or ""
        if not _is_geocode_valid(title, target_prefectures):
            logger.warning("[再検証] 無効エントリを除外: %s → %s", r["destination_address"], title)
            r["geocode_status"] = "failed"
            r["geocode_failure_reason"] = "revalidation"
            r["destination_latitude"] = None
            r["destination_longitude"] = None
            r["network_node_id"] = None
            r["snap_status"] = "invalid"
            r["snap_distance"] = None
            r["updated_at"] = now
            count += 1
    return count


def _save_failures_delivery(
    path: Path, master: dict, source_filename: str, unique_norms: set[str]
) -> int:
    """
        今回処理した住所（unique_norms）のうちジオコーディング失敗した配送先を CSV に上書き保存する。
        失敗がなければファイルを削除する。
    """
    failed = [
        {
            "delivery_id": r["delivery_id"],
            "destination_name": r.get("destination_name", ""),
            "destination_address": r["destination_address"],
            "file_name": source_filename,
            "failed_reason": r.get("geocode_failure_reason", "unknown"),
            "failed_at": r.get("updated_at", ""),
        }
        for norm, r in master.items()
        if norm in unique_norms and r.get("geocode_status") == "failed"
    ]
    if failed: # 失敗がある場合は CSV に保存する
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(failed).to_csv(path, index=False, encoding="utf-8-sig")
    elif path.exists():# 失敗がない場合は既存のファイルを削除する
        path.unlink()
    return len(failed)


def _save_failures_depot(failures: list[dict]) -> None:
    """ジオコーディング失敗デポを CSV に上書き保存する。"""
    GEOCODE_FAILURES_DEPOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(failures).to_csv(GEOCODE_FAILURES_DEPOT_PATH, index=False, encoding="utf-8-sig")


def geocode_depot(
    depot_df: pd.DataFrame, target_prefectures: set[str] | None = None
) -> pd.DataFrame:
    """
        depot_master の緯度経度が未設定の行をジオコーディングする。
        失敗したデポがあれば failures CSV を保存したうえで RuntimeError を送出する。
    """
    depot_df = depot_df.copy()
    failures = []
    now = datetime.now(timezone.utc).isoformat()

    for idx, row in depot_df.iterrows():
        # すでに緯度経度が設定されている場合はスキップする（API 呼び出しを避けるため）
        if pd.notna(row.get("depot_latitude")) and pd.notna(row.get("depot_longitude")):
            logger.info("デポスキップ: %s (緯度経度設定済み)", row["depot_id"])
            continue
        address = _normalize(row["depot_address"])
        logger.info("デポジオコーディング: %s", address)
        result, reason = geocode_address(address, target_prefectures)
        if result:
            depot_df.at[idx, "depot_latitude"] = result[0]
            depot_df.at[idx, "depot_longitude"] = result[1]
            logger.info("デポジオコーディング成功: %s", address)
        else:
            failures.append({
                "depot_id": row["depot_id"],
                "depot_name": row.get("depot_name", ""),
                "depot_address": row["depot_address"],
                "file_name": DEPOT_PATH.name,
                "failed_reason": reason,
                "failed_at": now,
            })
            logger.error("[エラー] デポ住所のジオコーディング失敗: %s (理由: %s)", address, reason)

    if failures:
        _save_failures_depot(failures)
        raise RuntimeError(
            f"デポのジオコーディングに失敗しました（{len(failures)} 件）。"
            f"詳細は {GEOCODE_FAILURES_DEPOT_PATH} を確認してください。"
        )

    return depot_df


def geocode_transactions(
    df: pd.DataFrame,
    master: dict,
    master_path: Path,
    target_prefectures: set[str] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """delivery_transaction の各行をジオコーディングし master を更新する。"""

    # ── 事前フィルタリング: API 処理対象の抽出 ─────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    skip_count = 0
    filtered_count = 0
    retry_targets: list[tuple[str, pd.Series]] = []
    new_targets: list[tuple[str, pd.Series]] = []
    seen_norms: set[str] = set()  # CSV 内の重複住所を除外し、同一住所を1回だけ API 対象に追加するため

    for _, row in df.iterrows():
        norm = _normalize(row["destination_address"])

        # 同一住所の2件目以降はスキップ（全カウントをユニーク住所ベースに統一するため先頭で判定）
        if norm in seen_norms:
            continue
        seen_norms.add(norm)

        # ② キャッシュヒット（success）→ スキップ
        if norm in master and master[norm].get("geocode_status") == "success":
            skip_count += 1
            continue

        # ① 都道府県フィルタ（入力住所で判定、API を呼ばない）
        pref = _extract_prefecture(norm)
        if target_prefectures and pref and pref not in target_prefectures:
            filtered_count += 1
            if norm not in master:
                master[norm] = {
                    "delivery_id": str(uuid.uuid4()),
                    "destination_name": _normalize(row.get("destination_name", "")),
                    "destination_address": str(row["destination_address"]),
                    "normalized_destination_address": norm,
                    "geocode_status": "failed",
                    "geocode_failure_reason": "prefecture_filter",
                    "geocode_resolved_title": None,
                    "destination_latitude": None,
                    "destination_longitude": None,
                    "created_at": now,
                    "updated_at": now,
                }
            continue

        # ③ 失敗済み → 再試行
        if norm in master and master[norm].get("geocode_status") == "failed":
            retry_targets.append((norm, row))
        else:
            # ④ 新規
            new_targets.append((norm, row))

    logger.info(
        "事前フィルタリング結果: スキップ %d 件 / 都道府県除外 %d 件 / API 対象 %d 件"
        "（新規 %d 件 + 再試行 %d 件）",
        skip_count, filtered_count, len(retry_targets) + len(new_targets), len(new_targets), len(retry_targets),
    )

    # ── API 処理 ──────────────────────────────────────────────────────
    api_call_count = 0

    for norm, row in retry_targets + new_targets:
        now = datetime.now(timezone.utc).isoformat()
        is_retry = norm in master

        logger.info("%s: %s", "再ジオコーディング" if is_retry else "ジオコーディング", norm)
        result, reason = geocode_address(norm, target_prefectures)
        api_call_count += 1

        if is_retry:
            if result: # 再試行成功 → 成功情報で上書き
                master[norm].update({
                    "geocode_status": "success",
                    "geocode_failure_reason": None,
                    "geocode_resolved_title": result[2],
                    "destination_latitude": result[0],
                    "destination_longitude": result[1],
                    "network_node_id": None,
                    "snap_status": "invalid",
                    "snap_distance": None,
                    "updated_at": now,
                })
                logger.info("再ジオコーディング成功: %s", norm)
            else: # 再試行失敗 → 失敗理由と更新日時を更新
                master[norm]["geocode_failure_reason"] = reason
                master[norm]["updated_at"] = now
        else: # 新規エントリは初回登録（失敗も含む）
            master[norm] = {
                "delivery_id": str(uuid.uuid4()),
                "destination_name": _normalize(row.get("destination_name", "")),
                "destination_address": str(row["destination_address"]),
                "normalized_destination_address": norm,
                "geocode_status": "success" if result else "failed",
                "geocode_failure_reason": None if result else reason,
                "geocode_resolved_title": result[2] if result else None,
                "destination_latitude": result[0] if result else None,
                "destination_longitude": result[1] if result else None,
                "created_at": now,
                "updated_at": now,
            }

        # API 呼び出し 100 件ごとに JSON へ中間保存する（障害時のデータ消失を防ぐため）
        if api_call_count % CHECKPOINT_INTERVAL == 0:
            _save_master(master_path, master)
            logger.info("チェックポイント保存: API %d 件完了", api_call_count)

    # ── delivery_id を DataFrame に付与 ──────────────────────────────
    df = df.copy()
    df["delivery_id"] = [
        master[_normalize(row["destination_address"])]["delivery_id"]
        for _, row in df.iterrows()
    ]
    return df, master


def main(source_filename: str | None = None) -> None:
    """ジオコーディング処理のメイン関数。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    source_filename = source_filename or TRANSACTION_PATH.name

    logger.info("=== ジオコーディング開始 (国土地理院 API) ===")

    df = pd.read_csv(TRANSACTION_PATH)
    depot_df = pd.read_csv(DEPOT_PATH)
    master = _load_master(MASTER_PATH)

    target_prefectures = _extract_prefectures(depot_df)

    # Step 1: デポを先にジオコーディング（失敗時は RuntimeError で停止）
    logger.info("--- デポのジオコーディング ---")
    if target_prefectures:
        logger.info("対象都道府県: %s（デポ住所より自動抽出）", "、".join(sorted(target_prefectures)))
    else:
        logger.warning("デポ住所から都道府県を抽出できません。都道府県フィルタを無効化します。")
    depot_df = geocode_depot(depot_df, target_prefectures)
    depot_df.to_csv(DEPOT_PATH, index=False, encoding="utf-8-sig")

    # Step 2: 配送先のキャッシュ状況を把握（配送件数 >= ユニーク件数 >= キャッシュ済み件数）
    unique_norms = {_normalize(addr) for addr in df["destination_address"]}
    unique_count = len(unique_norms)
    # ユニーク住所ベースでキャッシュヒット率を把握するため master に成功エントリがある件数を数える
    cached_count = sum(
        1 for norm in unique_norms
        if norm in master and master[norm].get("geocode_status") == "success"
    )
    logger.info(
        "配送先: %d 件 / ユニーク住所: %d 件 / うちキャッシュ済み: %d 件",
        len(df), unique_count, cached_count,
    )

    # Step 3: キャッシュ済みエントリの再検証と無効化
    invalidated = _revalidate_cached_entries(master, target_prefectures)
    if invalidated:
        logger.info("[再検証] %d 件のキャッシュエントリを無効化しました", invalidated)

    # Step 4: 配送先のジオコーディング
    logger.info("--- 配送先のジオコーディング ---")
    df, master = geocode_transactions(df, master, MASTER_PATH, target_prefectures)
    df.to_csv(TRANSACTION_PATH, index=False, encoding="utf-8-sig")
    _save_master(MASTER_PATH, master)

    # Step 5: 失敗レポートの保存（ユニーク住所ベースで Step 2 と軸を揃える）
    success = sum(
        1 for norm in unique_norms
        if master.get(norm, {}).get("geocode_status") == "success"
    )
    fail_count = _save_failures_delivery(
        GEOCODE_FAILURES_DELIVERY_PATH, master, source_filename, unique_norms
    )
    logger.info(
        "ジオコーディング完了: ユニーク住所 %d 件 / 成功 %d 件 / 失敗 %d 件",
        unique_count, success, fail_count,
    )

    # Step 6: 保存先ファイルパスの明示
    logger.info("保存先:")
    logger.info("  デポマスタ     : %s", DEPOT_PATH)
    logger.info("  配送データ     : %s", TRANSACTION_PATH)
    logger.info("  JSON キャッシュ: %s", MASTER_PATH)
    if fail_count:
        logger.info("  失敗レポート   : %s", GEOCODE_FAILURES_DELIVERY_PATH)


if __name__ == "__main__":
    main()
