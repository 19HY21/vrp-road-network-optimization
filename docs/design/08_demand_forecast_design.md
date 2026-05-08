# 08 需要量予測・配送先按分 設計書

## 1. 目的・背景

現行の VRP システムは `delivery_transaction.csv` を手動でアップロードすることを前提としており、
「明日何件の配送が発生するか」を事前に把握する手段がない。

本設計では需要量予測モデルを追加し、予測件数を神奈川県の住所プールへ按分することで
`delivery_transaction.csv` を自動生成する仕組みを構築する。
これにより、VRP パイプラインへの入力生成を含めた**一気通貫の配送計画パイプライン**が完成する。

---

## 2. システム全体像

```text
【住所プール拡充】（初回のみ・モデル完成後に実施）
fetch_kanagawa_poi.py（TARGET_COUNT 拡大 + タグ追加）
    ↓
geocode.py
    ↓
delivery_destination_master.json（住所プール）

【本番フロー（日次）】

① 需要量予測
   Olist 時系列データで学習したモデル
       → 「明日の配送件数: N 件」を出力
           ↓
② 配送先按分
   住所プールから N 件をサンプリング
   package_count・delivery_time_slot_code を分布から付与
       → delivery_transaction.csv を自動生成
           ↓
③ VRP 最適化（既存パイプライン・無改修）
   geocode → snap → OD 行列 → ソルバー → 評価 → 可視化
```

---

## 3. ステップ①：需要量予測

### 3.1 予測対象

| 項目 | 内容 |
|---|---|
| 予測変数 | 翌日の配送件数（件/日） |
| 予測単位 | デポ単位（1 デポ = 1 モデル） |
| 予測タイミング | 前日に実行し、翌日の配車計画に使用 |

### 3.2 使用データ

**Kaggle: Brazilian E-Commerce Public Dataset by Olist**
（`https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce`）

| ファイル | 使用カラム | 用途 |
|---|---|---|
| `olist_orders_dataset.csv` | `order_purchase_timestamp`, `order_status` | 日次注文件数の集計 |
| `olist_order_items_dataset.csv` | `order_id`, `product_id` | 1注文あたりの商品数（package_count 分布の参考） |

**前処理方針**

1. `order_status == "delivered"` に絞り、`order_purchase_timestamp` を日付単位に集計
2. 日次件数の時系列データ（`date`, `order_count`）を生成
3. 欠損日（0件日）は 0 で補完
4. 学習期間：2016-09〜2018-08（約2年）、評価期間：直近3ヶ月

**前提と限界**

Olist はブラジルの EC データであり、日本の物流パターン（曜日傾向・繁忙期等）と完全には一致しない。
本 PoC では「時系列予測の実装・評価プロセスを示すこと」を主目的とし、
データの地域的差異は設計上の制約として明記する。

### 3.3 特徴量

| 特徴量 | 説明 |
|---|---|
| `day_of_week` | 曜日（0=月〜6=日） |
| `month` | 月（1〜12） |
| `week_of_year` | 週番号 |
| `is_weekend` | 土日フラグ |
| `is_month_start` / `is_month_end` | 月初・月末フラグ |
| `lag_7` | 7日前の件数 |
| `lag_14` | 14日前の件数 |
| `rolling_mean_7` | 過去7日移動平均 |
| `rolling_mean_28` | 過去28日移動平均 |

### 3.4 モデル選定

| モデル | 採用可否 | 理由 |
|---|---|---|
| **LightGBM**（主モデル） | ✅ 採用 | 表形式の特徴量に強く、特徴量重要度で解釈性を示せる |
| Prophet | 比較用 | 季節性・トレンド分解を自動化。LightGBM との精度比較に使用 |
| SARIMA | 参考 | 古典的手法として比較対象に含める |

### 3.5 評価指標

| 指標 | 説明 |
|---|---|
| MAE（平均絶対誤差） | 件数のズレを直感的に把握できる主指標 |
| RMSE（二乗平均平方根誤差） | 外れ値への感度を確認 |
| MAPE（平均絶対パーセント誤差） | スケール非依存での比較用 |

### 3.6 出力

```python
{
    "target_date": "2026-05-09",
    "predicted_count": 87,
    "model": "lightgbm",
    "predicted_at": "2026-05-08T23:00:00"
}
```

---

## 4. ステップ②：配送先按分

### 4.1 住所プールの拡充

現状の `delivery_destination_master.json` は約 100 件。
予測件数が上限を超えた際の重複サンプリングを避けるため、
モデル完成後に以下の手順でプールを拡充する。

**fetch_kanagawa_poi.py の変更点**

| パラメータ | 現行 | 拡充後（目安） |
|---|---|---|
| `TARGET_COUNT` | 100 | 500 |
| `TAGS` | 郵便局・薬局・銀行・コンビニ・電器店 | 上記 + スーパー・飲食店・病院等を追加 |

拡充後に `geocode.py` を実行し、`snap_status == "success"` の件数が
想定する最大予測件数（例: 300 件）を上回ることを確認する。

### 4.2 サンプリング方式

```text
住所プール（snap_status == "success" のエントリ）
    ↓ 重複なし無作為抽出（predicted_count 件）
サンプリング済みアドレス一覧
    ↓ package_count・delivery_time_slot_code を付与
delivery_transaction.csv
```

**package_count の付与**

既存データの分布（一様分布 1〜5 個）をそのまま踏襲する。
将来的にはエリア・品目カテゴリ別の分布に改善できる。

**delivery_time_slot_code の付与**

| コード | 意味 | 付与比率（初期値） |
|---|---|---|
| 1 | 午前 | 33% |
| 2 | 午後 | 33% |
| 3 | 時間指定なし | 34% |

既存の `delivery_transaction.csv` の実績比率を初期値とし、
将来的には予測モデルで時間帯分布も推定可能にする。

### 4.3 生成スクリプト

```text
src/vrp_optimization/demand_forecast/
├── train.py              # モデル学習・保存
├── predict.py            # 翌日需要量の予測
└── generate_transaction.py  # 按分・CSV 生成
```

`generate_transaction.py` の出力は既存の `delivery_transaction.csv` と**同一スキーマ**とし、
VRP パイプライン側の改修なしに接続する。

---

## 5. ステップ③：VRP との接続

按分で生成した `delivery_transaction.csv` を既存の Streamlit UI からアップロードするか、
将来的にはパイプライン起動時に自動で渡す構成に拡張する。

```text
【現状（手動）】
generate_transaction.py → delivery_transaction.csv → UI アップロード → VRP

【将来（自動化）】
predict.py → generate_transaction.py → pipeline.py → VRP（ノーオペレーション）
```

---

## 6. 制約・前提・今後の課題

| 項目 | 内容 |
|---|---|
| データの地域差 | Olist はブラジル EC データ。日本の物流季節性・曜日傾向と異なる可能性がある |
| 住所プール上限 | プール件数が予測件数を下回る場合は重複サンプリングが発生する。拡充で対応 |
| 時間帯分布の固定 | time_slot_code は固定比率で付与。エリア別・品目別の推定は将来課題 |
| デポ別モデル | 現行設計は単一デポ。複数デポへの対応は 09 番以降で検討 |
| 予測精度の商用利用 | PoC 目的のため概算精度で許容。実運用時は日本の実データへの置き換えが必要 |
