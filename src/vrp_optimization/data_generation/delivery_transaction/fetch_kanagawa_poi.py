import random
import uuid
from pathlib import Path

import osmnx as ox
import pandas as pd

# --- 設定 ---
PLACE = "Kanagawa, Japan"
TAGS = {
    "amenity": ["post_office", "pharmacy", "bank"],
    "shop": ["convenience", "electronics"],
}
TARGET_COUNT = 1_000
DELIVERY_DATE = "2026-05-25"
RANDOM_SEED = 42

# --- 出力ファイルパス --- 
_ROOT = Path('./')
OUTPUT_PATH = _ROOT / "data" / "raw" / "delivery_transaction_1000.csv"


def _build_address(row: pd.Series) -> str:
    """OSM タグから日本語住所文字列を組み立てる。addr:full を優先し、なければ各コンポーネントを結合する。"""
    full = row.get("addr:full") #addr:full を優先取得する→住所全体が1フィールドに格納されており、コンポーネント結合より精度が高い
    #NaN・空文字を除外する→欠損値が混入すると住所文字列が崩れジオコーディングが失敗する
    if pd.notna(full) and str(full).strip(): 
        return str(full).strip()

    parts = []
    #住所を上位（都道府県）から下位（番地）の順に定義する→順序通りに結合することで日本語住所として自然な形式を再現する
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
        #欠損タグをスキップする→NaNをそのまま結合すると不正な住所文字列が生成される
        if pd.notna(val) and str(val).strip():
            parts.append(str(val).strip())
    return "".join(parts) #区切り文字なしで結合する→日本語住所はスペース不要な形式のため


def _get_poi_category_for_gdf(row: pd.Series, tags: dict):
    """GeoDataFrameの行からPOIカテゴリを判断するためのヘルパー関数。"""
    #定義済みタグを順に走査する→複数カテゴリを漏れなく検索するため
    for tag_key, tag_values in tags.items(): 
        val = row.get(tag_key)
        #NaNを除外しTAGSの候補値に含まれるか確認する→OSMのタグ値は定義外の文字列も含む可能性があるため
        if pd.notna(val) and str(val).strip() in tag_values: 
            return tag_key, str(val).strip()
    return None, None #該当カテゴリなしの場合はNoneタプルを返す→呼び出し元でNoneチェックにより未分類POIを識別できる


def fetch_poi(place: str, tags: dict) -> pd.DataFrame:
    """Overpass API から POI を取得する。Way/Relation はセントロイドに変換して返す。"""
    gdf = ox.features_from_place(place, tags=tags) #Overpass APIからPOIを一括取得する→osmnxが複数タグのクエリを抽象化するため1回の呼び出しで効率的に収集できる
    gdf = gdf.copy() #GeoDataFrameのコピーを作成する→元オブジェクトを直接変更するとSettingWithCopyWarningが発生しデバッグが困難になるため
    gdf["geometry"] = gdf["geometry"].to_crs("EPSG:6677").centroid.to_crs("EPSG:4326") #平面直角座標系でセントロイドを計算する→緯度経度のまま計算すると歪みが生じ距離精度が低下するため
    return gdf


def generate_transactions(gdf: pd.DataFrame, count: int) -> pd.DataFrame:
    """POI GeoDataFrame から delivery_transaction レコードを生成する。住所なしの行はスキップする。"""
    rng = random.Random(RANDOM_SEED) #固定シードで乱数生成器を初期化する→同一データから常に同じテストデータが生成され実験の再現性を確保できる
    records = []
    # NOTE: 現在のデータ規模 (TARGET_COUNT=100) ではiterrows()で十分なパフォーマンスが得られるため、可読性を優先しこの実装を選択。
    #       データ規模が数十万件以上になる場合は、apply()やベクトル化された処理への移行を検討する。その際はRANDOM_SEEDの扱いを考慮。
    for _, row in gdf.iterrows():
        address = _build_address(row)
        #住所が取得できないPOIをスキップする→住所なしのデータはジオコーディングで処理できないため
        if not address: 
            continue

        #タグリストを走査してカテゴリを特定する→各レコードにカテゴリ情報を付与することでログでの分布確認を可能にする
        poi_category_key = ""
        poi_category_value = ""
        for tag_key, tag_values in TAGS.items():
            val = row.get(tag_key)
            if pd.notna(val) and str(val).strip() in tag_values:
                poi_category_key = tag_key
                poi_category_value = str(val).strip()
                break

        records.append(
            {
                "transaction_id": f"TXN_{str(uuid.UUID(int=rng.getrandbits(128)))[:8].upper()}", #UUIDベースで識別子を生成する→重複のない一意なIDを簡潔に生成できる
                "delivery_date": DELIVERY_DATE,
                "destination_name": row.get("name", ""),
                "destination_address": address,
                # NOTE: package_countとdelivery_time_slot_codeは、VRPの機能検証を主眼に置くため、現在は一様分布でランダム値を生成している。
                #       より現実に即したテストデータが必要な場合は、過去データに基づいたポアソン分布や重み付けされた選択（例: 午前指定の割合が高い）などを検討し、分布を変更する可能性がある。
                "package_count": rng.randint(1, 5),
                "delivery_time_slot_code": rng.choice([1, 2, 3]),
                "poi_category_key": poi_category_key,
                "poi_category_value": poi_category_value,
            }
        )
        #件数上限に達した時点で処理を打ち切る→全POIを処理する必要がなく必要数だけ生成すれば十分なため
        if len(records) >= count:
            break
    return pd.DataFrame(records)


def main() -> tuple[pd.DataFrame, pd.DataFrame]:
    # POI取得からCSV生成までを一括実行し、VRPパイプラインへの入力ファイルを作成する
    print(f"POI 取得中: {PLACE} / tags={list(TAGS.keys())}")
    gdf = fetch_poi(PLACE, TAGS)
    print(f"  取得件数（住所フィルタ前）: {len(gdf)}")

    df = generate_transactions(gdf, TARGET_COUNT)
    print(f"  生成件数（住所あり）: {len(df)}")

    if df.empty:
        print("住所付き POI が見つかりませんでした。TAGS を見直してください。")
        return pd.DataFrame(), pd.DataFrame()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(
        df[["destination_name", "destination_address", "package_count", "delivery_time_slot_code"]]
        .to_string(index=False)
    )
    return gdf, df


if __name__ == "__main__":
    gdf_main, df_main = main()

    # --- タグ別ロギング ---
    # gdf_main に一時的なカテゴリ列を追加し、カウントに利用します
    gdf_with_categories = gdf_main.copy()
    gdf_with_categories[['temp_poi_category_key', 'temp_poi_category_value']] = gdf_with_categories.apply(
        lambda row: pd.Series(_get_poi_category_for_gdf(row, TAGS)), axis=1
    )

    # generate_transactions と同様に、有効な住所とカテゴリを持つgdfをフィルタリングします
    gdf_with_categories = gdf_with_categories[
        gdf_with_categories['temp_poi_category_key'].notna() &
        gdf_with_categories.apply(lambda row: bool(_build_address(row)), axis=1)
    ]

    # gdf_main のタグ別件数を計算します (有効な住所とカテゴリを持つ初期POI)
    gdf_tag_counts = gdf_with_categories.groupby(['temp_poi_category_key', 'temp_poi_category_value']).size().to_dict()
    gdf_tag_counts_formatted = {f"{k[0]}:{k[1]}": v for k, v in gdf_tag_counts.items()}

    print("\n--- POI (gdf) タグ別件数 (住所とカテゴリでフィルタリング後) ---")
    for tag, count in gdf_tag_counts_formatted.items():
        print(f"  {tag}: {count}件")

    # df_main のタグ別件数を計算します (生成されたトランザクション)
    df_tag_counts = df_main.groupby(['poi_category_key', 'poi_category_value']).size().to_dict()
    df_tag_counts_formatted = {f"{k[0]}:{k[1]}": v for k, v in df_tag_counts.items()}

    print("\n--- トランザクション (df) タグ別件数 ---")
    for tag, count in df_tag_counts_formatted.items():
        print(f"  {tag}: {count}件")

    print("\n--- タグ別差異 (gdf - df) ---")
    all_tags = set(gdf_tag_counts_formatted.keys()).union(set(df_tag_counts_formatted.keys()))
    for tag in sorted(list(all_tags)):
        gdf_count = gdf_tag_counts_formatted.get(tag, 0)
        df_count = df_tag_counts_formatted.get(tag, 0)
        diff = gdf_count - df_count
        print(f"  {tag}: {gdf_count} (POI) - {df_count} (Txn) = {diff}件")
    # --- タグ別ロギング終了 ---