"""
【目的】
    VRP パイプラインの開発・実験用サンプルデータとして、
    data/raw/delivery_transaction.csv を生成するスクリプト。

【処理の流れ】
    1. Overpass API（OSMnx 経由）で神奈川県内の POI（郵便局・薬局・コンビニ等）を取得する
    2. OSM アドレスタグ（addr:full または各コンポーネント）から日本語住所を組み立てる
    3. 住所が取得できた POI を対象に delivery_transaction レコードを生成する
       - transaction_id : UUID ベースのランダム ID
       - package_count  : 1〜5 個（乱数、再現性のため固定シード使用）
       - delivery_time_slot_code : 1=午前 / 2=午後 / 3=時間指定なし（乱数）
    4. data/raw/delivery_transaction.csv に上書き保存する

【出力先】
    data/raw/delivery_transaction.csv

【注意事項】
    - 実行時に Overpass API へのネットワークアクセスが発生する
    - OSM の住所データが不完全な POI（丁目・番地なし等）は自動スキップされる
    - 実クライアントデータではなく PoC 用疑似データとして使用する想定

【実行方法】
    python -m vrp_optimization.data_generation.delivery_transaction.fetch_kanagawa_poi
"""
import random
import uuid
from pathlib import Path

import osmnx as ox
import pandas as pd

# --- 設定 ---
PLACE = "Kanagawa, Japan"
TAGS = {
    "amenity": ["post_office", "pharmacy"],
    "shop": ["convenience"],
}
TARGET_COUNT = 20
DEPOT_ID = "DEPOT_001"
DELIVERY_DATE = "2026-05-20"
RANDOM_SEED = 42

_ROOT = Path(__file__).parents[4]
OUTPUT_PATH = _ROOT / "data" / "raw" / "delivery_transaction.csv"


def _build_address(row: pd.Series) -> str:
    """OSM タグから日本語住所文字列を組み立てる。addr:full を優先し、なければ各コンポーネントを結合する。"""
    full = row.get("addr:full")
    if pd.notna(full) and str(full).strip():
        return str(full).strip()

    parts = []
    for key in (
        "addr:province",
        "addr:city",
        "addr:suburb",
        "addr:quarter",
        "addr:neighbourhood",
        "addr:street",
        "addr:housenumber",
    ):
        val = row.get(key)
        if pd.notna(val) and str(val).strip():
            parts.append(str(val).strip())
    return "".join(parts)


def fetch_poi(place: str, tags: dict) -> pd.DataFrame:
    """Overpass API から POI を取得する。Way/Relation はセントロイドに変換して返す。"""
    gdf = ox.features_from_place(place, tags=tags)
    gdf = gdf.copy()
    # セントロイド計算は投影座標系で行い、結果を WGS84 に戻す
    gdf["geometry"] = gdf["geometry"].to_crs("EPSG:6677").centroid.to_crs("EPSG:4326")
    return gdf


def generate_transactions(gdf: pd.DataFrame, count: int) -> pd.DataFrame:
    """POI GeoDataFrame から delivery_transaction レコードを生成する。住所なしの行はスキップする。"""
    rng = random.Random(RANDOM_SEED)
    records = []
    for _, row in gdf.iterrows():
        address = _build_address(row)
        if not address:
            continue
        records.append(
            {
                "transaction_id": f"TXN_{str(uuid.UUID(int=rng.getrandbits(128)))[:8].upper()}",
                "delivery_id": "",
                "delivery_date": DELIVERY_DATE,
                "destination_name": row.get("name", ""),
                "destination_address": address,
                "depot_id": DEPOT_ID,
                "package_count": rng.randint(1, 5),
                "delivery_time_slot_code": rng.choice([1, 2, 3]),
            }
        )
        if len(records) >= count:
            break
    return pd.DataFrame(records)


def main() -> None:
    print(f"POI 取得中: {PLACE} / tags={list(TAGS.keys())}")
    gdf = fetch_poi(PLACE, TAGS)
    print(f"  取得件数（住所フィルタ前）: {len(gdf)}")

    df = generate_transactions(gdf, TARGET_COUNT)
    print(f"  生成件数（住所あり）: {len(df)}")

    if df.empty:
        print("住所付き POI が見つかりませんでした。TAGS を見直してください。")
        return

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n保存完了: {OUTPUT_PATH}")
    print(
        df[["destination_name", "destination_address", "package_count", "delivery_time_slot_code"]]
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
