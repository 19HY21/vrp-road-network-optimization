"""
【目的】
    delivery_transaction.csv の配送先住所を緯度経度に変換し、
    processed/delivery_destination_master.json にキャッシュする前処理スクリプト。
    depot_master.csv のデポ住所も未設定の場合にジオコーディングする。

【処理の流れ】
    1. delivery_transaction.csv / depot_master.csv を読み込む
    2. processed/delivery_destination_master.json をキャッシュとして読み込む（初回は空）
    3. キャッシュに未登録の住所を国土地理院（GSI）API でジオコーディング
       - 完全一致のみ（フォールバックなし）
       - 失敗した住所は geocode_status="failed" として記録し後続ステップで除外
       - API: https://msearch.gsi.go.jp/address-search/AddressSearch
    4. 新規配送先に UUID を付与し delivery_destination_master.json を更新
    5. delivery_transaction.csv の delivery_id 列を埋める
    6. depot_master.csv の緯度経度が空の行を更新

【出力先】
    data/processed/delivery_destination_master.json
    data/raw/delivery_transaction.csv  （delivery_id 列を更新）
    data/raw/depot_master.csv          （depot_latitude / depot_longitude を更新）

【注意事項】
    - 国土地理院 API は無料・API キー不要だが、過負荷を避けるため 0.2s 間隔を確保する
    - ジオコーディング失敗行は緯度経度が null のまま残る（後続ステップで除外）
    - 実行時にネットワークアクセスが発生する

【実行方法】
    python -m vrp_optimization.preprocessing.geocode
"""
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import re

import pandas as pd
import requests

_ROOT = Path(__file__).parents[3]
TRANSACTION_PATH = _ROOT / "data" / "raw" / "delivery_transaction.csv"
DEPOT_PATH = _ROOT / "data" / "raw" / "depot_master.csv"
MASTER_PATH = _ROOT / "data" / "processed" / "delivery_destination_master.json"

GSI_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch"
GSI_PAUSE = 0.2  # seconds between requests


def _extract_prefecture(address: str) -> str | None:
    """住所文字列の先頭から都道府県名を抽出する。"""
    m = re.match(r"^(東京都|大阪府|京都府|北海道|.{2,4}県)", str(address))
    return m.group(1) if m else None


def _is_geocode_valid(title: str, target_prefecture: str | None) -> bool:
    """ジオコーディング結果が有効かチェックする。
    - 市・区レベルで終わっている（丁目・町名がない）場合は粒度不足として無効
    - target_prefecture が指定されており対象都道府県外の場合は無効
    """
    if re.search(r"[市区]$", title):
        return False
    if target_prefecture and not title.startswith(target_prefecture):
        return False
    return True


def geocode_address(address: str, target_prefecture: str | None = None) -> tuple[float, float, str] | None:
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
            if not _is_geocode_valid(title, target_prefecture):
                return None
            return lat, lon, title
        return None
    except Exception:
        return None
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(master.values()), f, ensure_ascii=False, indent=2)


def _normalize(address: str) -> str:
    return str(address).strip()


def _revalidate_cached_entries(master: dict, target_prefecture: str | None) -> int:
    """キャッシュ済みエントリのうち現在のバリデーションに通らないものを無効化する。
    geocode / snap 両方のフィールドをリセットして再スナップを強制する。
    """
    count = 0
    now = datetime.now(timezone.utc).isoformat()
    for r in master.values():
        if r.get("geocode_status") != "success":
            continue
        title = r.get("geocode_resolved_title") or ""
        if not _is_geocode_valid(title, target_prefecture):
            print(f"  [再検証] 無効エントリを除外: {r['destination_address']} → {title}")
            r["geocode_status"] = "failed"
            r["destination_latitude"] = None
            r["destination_longitude"] = None
            r["network_node_id"] = None
            r["snap_status"] = "invalid"
            r["snap_distance"] = None
            r["updated_at"] = now
            count += 1
    return count


def geocode_transactions(df: pd.DataFrame, master: dict, target_prefecture: str | None = None) -> tuple[pd.DataFrame, dict]:
    """delivery_transaction の各行をジオコーディングし master を更新する。"""
    delivery_ids = []
    for _, row in df.iterrows():
        norm = _normalize(row["destination_address"])
        if norm in master:
            delivery_ids.append(master[norm]["delivery_id"])
            continue

        print(f"  ジオコーディング: {norm}")
        result = geocode_address(norm, target_prefecture)
        now = datetime.now(timezone.utc).isoformat()
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
            "updated_at": None,
        }
        delivery_ids.append(did)

    df = df.copy()
    df["delivery_id"] = delivery_ids
    return df, master


def geocode_depot(depot_df: pd.DataFrame) -> pd.DataFrame:
    """depot_master の緯度経度が未設定の行をジオコーディングする。"""
    depot_df = depot_df.copy()
    for idx, row in depot_df.iterrows():
        if pd.notna(row.get("depot_latitude")) and pd.notna(row.get("depot_longitude")):
            continue
        address = _normalize(row["depot_address"])
        print(f"  デポジオコーディング: {address}")
        result = geocode_address(address)
        if result:
            depot_df.at[idx, "depot_latitude"] = result[0]
            depot_df.at[idx, "depot_longitude"] = result[1]
        else:
            print(f"  [警告] デポ住所のジオコーディング失敗: {address}")
    return depot_df


def main() -> None:
    print("=== ジオコーディング開始 (国土地理院 API) ===")

    df = pd.read_csv(TRANSACTION_PATH)
    depot_df = pd.read_csv(DEPOT_PATH)
    master = _load_master(MASTER_PATH)

    print(f"配送先: {len(df)} 件 / キャッシュ済み: {len(master)} 件")

    # デポ住所から対象都道府県を自動抽出（全デポが同一都道府県を想定）
    target_prefecture = _extract_prefecture(depot_df["depot_address"].iloc[0])
    if target_prefecture:
        print(f"対象都道府県: {target_prefecture}（デポ住所より自動抽出）")
    else:
        print("[警告] デポ住所から都道府県を抽出できません。都道府県フィルタを無効化します。")

    invalidated = _revalidate_cached_entries(master, target_prefecture)
    if invalidated:
        print(f"[再検証] {invalidated} 件のキャッシュエントリを無効化しました")

    depot_df = geocode_depot(depot_df)
    depot_df.to_csv(DEPOT_PATH, index=False, encoding="utf-8-sig")

    df, master = geocode_transactions(df, master, target_prefecture)
    df.to_csv(TRANSACTION_PATH, index=False, encoding="utf-8-sig")
    _save_master(MASTER_PATH, master)

    success = sum(1 for r in master.values() if r["geocode_status"] == "success")
    failed = [r for r in master.values() if r["geocode_status"] == "failed"]
    print(f"\n完了: {success}/{len(master)} 件ジオコーディング成功")
    if failed:
        print(f"[警告] 以下 {len(failed)} 件は住所が解決できないため除外されます:")
        for r in failed:
            print(f"  - {r['destination_address']}")
    print(f"保存: {MASTER_PATH}")


if __name__ == "__main__":
    main()
