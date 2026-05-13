"""
【目的】
    delivery_transaction.csv の配送先住所を緯度経度に変換し、
    processed/delivery_destination_master.json にキャッシュする前処理スクリプト。
    depot_master.csv のデポ住所も未設定の場合にジオコーディングする。

【処理の流れ】
    1. delivery_transaction.csv / depot_master.csv / delivery_destination_master.json を読み込む
    2. depot_master.csv の全デポ住所から都道府県をユニーク抽出し、配送先フィルタの基準とする
    3. キャッシュ済みエントリを再検証し、都道府県フィルタを満たさないものを無効化する
    4. depot_master.csv の緯度経度が未設定のデポをジオコーディングする
    5. delivery_transaction.csv の各配送先を国土地理院（GSI）API でジオコーディングする
       - キャッシュ済み（success）: API を呼ばず既存 delivery_id を再利用する
       - 都道府県事前フィルタ: 入力住所から都道府県を抽出しデポ都道府県と照合する。対象外の場合は API を呼ばず failed として記録する
       - 失敗済み（failed）: 再ジオコーディングを試み、成功した場合は座標・updated_at を更新する
       - 新規: UUID を付与しキャッシュに追加する。created_at / updated_at を同値で記録する
       - API: https://msearch.gsi.go.jp/address-search/AddressSearch
       - API 呼び出し 100 件ごとに JSON へ中間保存する（障害時のデータ消失を防ぐため）
    6. 全件処理完了後に delivery_transaction.csv / delivery_destination_master.json を保存する

【出力先】
    data/processed/delivery_destination_master.json
    data/raw/delivery_transaction.csv  （delivery_id 列を更新）
    data/raw/depot_master.csv          （depot_latitude / depot_longitude を更新）

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

GSI_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch"
GSI_PAUSE = 0.2  # seconds between requests

logger = logging.getLogger(__name__)


def _extract_prefecture(address: str) -> str | None:
    """住所文字列の先頭から都道府県名を抽出する。"""
    # NOTE: 現在は日本語住所（都道府県名が漢字で始まる形式）のみ対応。英語表記（"Kanagawa-ken" 等）への対応は将来拡張とする。
    m = re.match(r"^(東京都|大阪府|京都府|北海道|.{2,4}県)", str(address))
    return m.group(1) if m else None


def _extract_prefectures(depot_df: pd.DataFrame) -> set[str]:
    """depot_master の全デポ住所から都道府県名をユニーク抽出する。"""
    # NOTE: 現在は同一都道府県の複数デポを想定しているが、将来的に異なる都道府県のデポが
    #       混在するケースもすべてのデポ都道府県を有効として扱う仕様としている。
    #       デポが追加されるたびに有効都道府県セットが自動拡張されるため、個別の設定変更は不要。
    prefectures = set()
    for address in depot_df["depot_address"]:
        pref = _extract_prefecture(address)
        if pref:
            prefectures.add(pref)
    return prefectures


def _is_geocode_valid(title: str, target_prefectures: set[str] | None) -> bool:
    """ジオコーディング結果が有効かチェックする。
    - 市・区レベルで終わっている（丁目・町名がない）場合は粒度不足として無効
    - target_prefectures が指定されており対象都道府県外の場合は無効
    """
    if re.search(r"[市区]$", title): #市・区レベルで終わる結果を除外する→丁目・番地がなく精度不足のためスナップに失敗する可能性があるため
        return False
    if target_prefectures and not any(title.startswith(p) for p in target_prefectures): #対象都道府県外の結果を除外する→配送エリア外の住所に誤マッチしたジオコーディング結果を排除するため
        return False
    return True


def geocode_address(address: str, target_prefectures: set[str] | None = None) -> tuple[float, float, str] | None:
    """国土地理院 API で住所をジオコーディングする。
    成功時は (lat, lon, resolved_title) を返す。失敗または精度不足時は None を返す。
    """
    try:
        resp = requests.get(GSI_URL, params={"q": address}, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        if results:
            lon, lat = results[0]["geometry"]["coordinates"]
            title = results[0]["properties"]["title"]
            if not _is_geocode_valid(title, target_prefectures):
                return None
            return lat, lon, title
        return None
    except Exception:
        return None
    finally:
        time.sleep(GSI_PAUSE) #API呼び出しごとに待機する→過負荷によるレート制限やサービス障害を防ぐため


def _load_master(path: Path) -> dict[str, dict]:
    """delivery_destination_master.json をロードし normalized_address をキーとする辞書を返す。"""
    if not path.exists(): #ファイルが存在しない場合に空の辞書を返す→初回実行時のエラーを避け継続稼働を促すため
        return {}
    with open(path, encoding="utf-8") as f: #エンコーディングを明示する→日本語住所の文字化けを防ぐため
        records = json.load(f)
    return {r["normalized_destination_address"]: r for r in records} #正規化住所をキーとする辞書を返す→O(1)でのキャッシュ検索を可能にしジオコーディングの重複呼び出しを防ぐため


def _save_master(path: Path, master: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True) #保存先ディレクトリを事前作成する→初回実行時のFileNotFoundErrorを防ぐため
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(master.values()), f, ensure_ascii=False, indent=2) #ensure_ascii=Falseで日本語をそのまま出力する→エスケープされた文字列では人間が読めないため


def _normalize(address: str) -> str:
    return str(address).strip() #前後の空白を除去する→空白の有無でキャッシュキーが不一致になることを防ぐため


def _revalidate_cached_entries(master: dict, target_prefectures: set[str] | None) -> int:
    """キャッシュ済みエントリのうち現在のバリデーションに通らないものを無効化する。
    geocode / snap 両方のフィールドをリセットして再スナップを強制する。
    """
    count = 0
    now = datetime.now(timezone.utc).isoformat()
    for r in master.values():
        if r.get("geocode_status") != "success": #successのエントリのみ再検証する→失敗済みエントリは再検証不要なため
            continue
        title = r.get("geocode_resolved_title") or ""
        if not _is_geocode_valid(title, target_prefectures):
            logger.warning("[再検証] 無効エントリを除外: %s → %s", r["destination_address"], title)
            r["geocode_status"] = "failed"
            r["destination_latitude"] = None
            r["destination_longitude"] = None
            r["network_node_id"] = None
            r["snap_status"] = "invalid"
            r["snap_distance"] = None
            r["updated_at"] = now #無効化時刻を記録する→いつ都道府県フィルタによって除外されたかを追跡するため
            count += 1
    return count


CHECKPOINT_INTERVAL = 100  # API呼び出しがこの件数に達するたびにJSONへ中間保存する


def geocode_transactions(
    df: pd.DataFrame,
    master: dict,
    master_path: Path,
    target_prefectures: set[str] | None = None,
) -> tuple[pd.DataFrame, dict]:
    """delivery_transaction の各行をジオコーディングし master を更新する。"""
    delivery_ids = []
    api_call_count = 0  #実際にAPIを呼び出した回数をカウントする→キャッシュヒットを除いたチェックポイント判定に使用するため

    for _, row in df.iterrows():
        norm = _normalize(row["destination_address"])

        # キャッシュヒット（成功済み）→ API を呼ばずに既存 delivery_id を再利用する
        if norm in master and master[norm].get("geocode_status") == "success":
            delivery_ids.append(master[norm]["delivery_id"])
            continue

        now = datetime.now(timezone.utc).isoformat()

        # 都道府県事前フィルタ: APIを呼ぶ前に対象外都道府県の住所を除外する→処理時間削減とデータの再現性確保のため
        pref = _extract_prefecture(norm)
        if target_prefectures and pref and pref not in target_prefectures:
            logger.warning("[都道府県フィルタ] 対象外のため除外: %s (抽出都道府県: %s)", norm, pref)
            if norm not in master:
                did = str(uuid.uuid4())
                master[norm] = {
                    "delivery_id": did,
                    "destination_name": _normalize(row.get("destination_name", "")),
                    "destination_address": str(row["destination_address"]),
                    "normalized_destination_address": norm,
                    "geocode_status": "failed",
                    "geocode_resolved_title": None,
                    "destination_latitude": None,
                    "destination_longitude": None,
                    "created_at": now,
                    "updated_at": now,
                }
            delivery_ids.append(master[norm]["delivery_id"])
            continue

        # 失敗済みエントリの再ジオコーディング（無効化後の再試行）
        if norm in master and master[norm].get("geocode_status") == "failed":
            logger.info("再ジオコーディング: %s", norm)
            result = geocode_address(norm, target_prefectures)
            api_call_count += 1
            if result:
                master[norm]["geocode_status"] = "success"
                master[norm]["geocode_resolved_title"] = result[2]
                master[norm]["destination_latitude"] = result[0]
                master[norm]["destination_longitude"] = result[1]
                master[norm]["network_node_id"] = None #座標が変わったためスナップ結果をリセットする→古いノードIDが残ると距離計算が誤った経路を参照するため
                master[norm]["snap_status"] = "invalid"
                master[norm]["snap_distance"] = None
                master[norm]["updated_at"] = now #再ジオコーディング成功時刻を記録する→いつ座標が更新されたかを追跡するため
                logger.info("再ジオコーディング成功: %s", norm)
            delivery_ids.append(master[norm]["delivery_id"])

        else:
            # 新規エントリ
            logger.info("ジオコーディング: %s", norm)
            result = geocode_address(norm, target_prefectures)
            api_call_count += 1
            did = str(uuid.uuid4())
            master[norm] = {
                "delivery_id": did,
                "destination_name": _normalize(row.get("destination_name", "")),
                "destination_address": str(row["destination_address"]),
                "normalized_destination_address": norm,
                "geocode_status": "success" if result else "failed",
                "geocode_resolved_title": result[2] if result else None,
                "destination_latitude": result[0] if result else None,
                "destination_longitude": result[1] if result else None,
                "created_at": now,
                "updated_at": now, #新規作成時は created_at と同値にする→エントリの初期状態として作成時刻を統一管理するため
            }
            delivery_ids.append(did)

        # API呼び出しがCHECKPOINT_INTERVAL件に達したら中間保存する→クラッシュ時の処理済み結果の消失を防ぐため
        if api_call_count % CHECKPOINT_INTERVAL == 0:
            _save_master(master_path, master)
            logger.info("チェックポイント保存: API %d 件完了", api_call_count)

    df = df.copy()
    df["delivery_id"] = delivery_ids
    return df, master


def geocode_depot(depot_df: pd.DataFrame) -> pd.DataFrame:
    """depot_master の緯度経度が未設定の行をジオコーディングする。"""
    depot_df = depot_df.copy()
    for idx, row in depot_df.iterrows():
        if pd.notna(row.get("depot_latitude")) and pd.notna(row.get("depot_longitude")): #緯度経度が既に設定済みの場合はスキップする→不要なAPI呼び出しを防ぐため
            continue
        address = _normalize(row["depot_address"])
        logger.info("デポジオコーディング: %s", address)
        result = geocode_address(address)
        if result:
            depot_df.at[idx, "depot_latitude"] = result[0]
            depot_df.at[idx, "depot_longitude"] = result[1]
        else:
            logger.warning("[警告] デポ住所のジオコーディング失敗: %s", address)
    return depot_df


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("=== ジオコーディング開始 (国土地理院 API) ===")

    df = pd.read_csv(TRANSACTION_PATH)
    depot_df = pd.read_csv(DEPOT_PATH)
    master = _load_master(MASTER_PATH)

    logger.info("配送先: %d 件 / キャッシュ済み: %d 件", len(df), len(master))

    target_prefectures = _extract_prefectures(depot_df)
    if target_prefectures:
        logger.info("対象都道府県: %s（デポ住所より自動抽出）", "、".join(sorted(target_prefectures)))
    else:
        logger.warning("デポ住所から都道府県を抽出できません。都道府県フィルタを無効化します。")

    invalidated = _revalidate_cached_entries(master, target_prefectures)
    if invalidated:
        logger.info("[再検証] %d 件のキャッシュエントリを無効化しました", invalidated)

    depot_df = geocode_depot(depot_df)
    depot_df.to_csv(DEPOT_PATH, index=False, encoding="utf-8-sig")

    df, master = geocode_transactions(df, master, MASTER_PATH, target_prefectures)
    df.to_csv(TRANSACTION_PATH, index=False, encoding="utf-8-sig")
    _save_master(MASTER_PATH, master)

    success = sum(1 for r in master.values() if r["geocode_status"] == "success")
    failed = [r for r in master.values() if r["geocode_status"] == "failed"]
    logger.info("完了: %d/%d 件ジオコーディング成功", success, len(master))
    if failed:
        logger.warning("[警告] 以下 %d 件は住所が解決できないため除外されます:", len(failed))
        for r in failed:
            logger.warning("  - %s", r["destination_address"])

    logger.info("保存: %s", MASTER_PATH)
    logger.info("保存: %s", TRANSACTION_PATH)
    logger.info("保存: %s", DEPOT_PATH)


if __name__ == "__main__":
    main()
