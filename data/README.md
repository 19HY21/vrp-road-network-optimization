# data/

VRP パイプラインで使用するデータを格納するディレクトリ。

- `raw/` : 業務入力データ（人手で用意する CSV）
- `processed/` : パイプラインが生成・再利用する中間データ

実行単位の出力（ジオコーディング結果・OD 行列・候補案等）は `outputs/{plan_id}/` に保存する。  
→ 詳細は [README.md §構成](../README.md) を参照。

---

## raw/

### depot_master.csv

デポ情報・車両台数レンジ・コスト・業務時間を保持するマスタ。  
本 PoC は単一デポ前提のため 1 行固定。

| 物理名 | 論理名 | 型 | 必須 | 備考 |
|---|---|---|---|---|
| `depot_id` | デポ ID | string | ○ | PK。例: `DEPOT_001` |
| `depot_name` | デポ名 | string | ○ | 表示用名称 |
| `depot_address` | デポ住所 | string | ○ | 緯度経度未設定時に前処理で付与する |
| `depot_latitude` | 緯度 | float | - | 初回前処理後に記入し以後再利用 |
| `depot_longitude` | 経度 | float | - | 初回前処理後に記入し以後再利用 |
| `depot_network_node_id` | ネットワークノード ID | string | - | OSM ノード ID。初回割当後に記入し以後再利用 |
| `depot_snap_status` | スナップ成否 | string | - | `success` / `failed` |
| `depot_snap_distance` | スナップ距離 (m) | float | - | 割当妥当性確認用 |
| `depot_osm_version` | 参照 OSM 版 | string | - | 再現性確認用。例: `20260401` |
| `vehicle_count_min` | 下限車両数 | integer | ○ | 当日の稼働可能台数レンジ下限 |
| `vehicle_count_max` | 上限車両数 | integer | ○ | 当日の稼働可能台数レンジ上限 |
| `fixed_cost_per_vehicle` | 1 台あたり固定コスト (円) | float | ○ | 人件費・車両固定費の簡略化パラメータ |
| `capacity_per_vehicle` | 1 台あたり積載上限 (個) | integer | ○ | 荷物個数ベース |
| `work_start_time` | 業務開始時刻 | time (HH:MM) | ○ | デポ出発基準時刻 |
| `work_end_time` | 業務終了時刻 | time (HH:MM) | ○ | デポ帰着期限 |
| `distance_unit_cost` | 距離比例コスト (円/km) | float | ○ | 距離コスト算出に使用 |

**サンプル行**

```csv
depot_id,depot_name,depot_address,depot_latitude,depot_longitude,depot_network_node_id,depot_snap_status,depot_snap_distance,depot_osm_version,vehicle_count_min,vehicle_count_max,fixed_cost_per_vehicle,capacity_per_vehicle,work_start_time,work_end_time,distance_unit_cost
DEPOT_001,横浜配送センター,神奈川県横浜市西区みなとみらい2-2-1,35.4578,139.6322,,,,, 2,5,15000,30,09:00,18:00,50.0
```

---

### time_slot_master.csv

時間帯区分コードと名称・時間範囲の対応表。  
`delivery_transaction.delivery_time_slot_code` の FK 参照元。

| 物理名 | 論理名 | 型 | 必須 | 備考 |
|---|---|---|---|---|
| `time_slot_code` | 時間帯区分コード | integer | ○ | PK |
| `time_slot_name` | 時間帯区分名 | string | ○ | `午前` / `午後` / `時間指定なし` |
| `slot_start_time` | 開始時刻 | time (HH:MM) | - | `時間指定なし` は空欄 |
| `slot_end_time` | 終了時刻 | time (HH:MM) | - | `時間指定なし` は空欄 |

**サンプル行**

```csv
time_slot_code,time_slot_name,slot_start_time,slot_end_time
1,午前,09:00,13:00
2,午後,13:00,18:00
3,時間指定なし,,
```

---

### delivery_transaction.csv

1 配送依頼 = 1 行。配送日・配送先住所・荷物個数・時間帯区分を保持する。

| 物理名 | 論理名 | 型 | 必須 | 備考 |
|---|---|---|---|---|
| `transaction_id` | トランザクション ID | string | ○ | PK。例: `TXN_001` |
| `delivery_id` | 配送先 ID | string | ○ | FK → `delivery_destination_master.delivery_id`。初回入力時は空欄可、前処理で付与 |
| `delivery_date` | 配送日 | date (YYYY-MM-DD) | ○ | 対象配送日 |
| `destination_name` | 配送先名 | string | - | 表示用。例: `株式会社〇〇` |
| `destination_address` | 配送先住所 | string | ○ | 元住所（正規化前）を保持 |
| `depot_id` | デポ ID | string | ○ | FK → `depot_master.depot_id` |
| `package_count` | 荷物個数 | integer | ○ | 需要量として使用。1 以上 |
| `delivery_time_slot_code` | 時間帯区分コード | integer | ○ | FK → `time_slot_master.time_slot_code` |

**サンプル行**

```csv
transaction_id,delivery_id,delivery_date,destination_name,destination_address,depot_id,package_count,delivery_time_slot_code
TXN_001,,2026-05-10,株式会社A,神奈川県横浜市中区山下町1-1,DEPOT_001,3,1
TXN_002,,2026-05-10,株式会社B,神奈川県川崎市幸区堀川町580,DEPOT_001,2,2
TXN_003,,2026-05-10,株式会社C,神奈川県相模原市中央区中央2-11-15,DEPOT_001,1,3
```

---

## processed/

パイプラインが生成し、複数回の実行にわたって再利用する中間データを格納する。  
実行単位ごとに変わる結果（ジオコーディング・OD 行列等）は `outputs/{plan_id}/` に保存する。

### delivery_destination_master.json

配送先の安定識別子と緯度経度を保持する内部生成型マスタ。  
前処理時に `delivery_transaction.destination_address` の正規化結果を照合し、新規配送先であれば UUID を付与して追記する。既存配送先は緯度経度を再利用する。

| 物理名 | 論理名 | 型 | 必須 | 備考 |
|---|---|---|---|---|
| `delivery_id` | 配送先 ID | string | ○ | PK。UUID で採番 |
| `destination_name` | 配送先名 | string | - | 表示用名称 |
| `destination_address` | 配送先住所 | string | ○ | 入力時点の元住所 |
| `normalized_destination_address` | 正規化後住所 | string | - | 同一配送先判定に使用 |
| `destination_latitude` | 緯度 | float | - | 新規登録時に付与し以後再利用 |
| `destination_longitude` | 経度 | float | - | 新規登録時に付与し以後再利用 |
| `created_at` | 登録日時 | datetime (ISO 8601) | ○ | 新規配送先登録時に記録 |
| `updated_at` | 更新日時 | datetime (ISO 8601) | - | 住所修正時などに更新 |

### osm_network/

OSM 道路ネットワークグラフのキャッシュファイルを格納する。  
再現性確保のため版を識別できるファイル名で保存し、旧版は `osm_network/old/` へ退避する。

```
processed/
  osm_network/
    kanagawa_drive_YYYYMMDD.graphml   # 版付きグラフ（GraphML 形式）
    kanagawa_drive_latest.graphml     # 最新版へのシンボリックまたはコピー
    old/
      kanagawa_drive_YYYYMMDD.graphml
```

グラフの取得条件・ノード数・エッジ数などのメタデータは `depot_master.depot_osm_version` および `execution_metadata.json` に記録する。
