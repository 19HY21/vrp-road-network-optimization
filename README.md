# VRP Road Network Optimization

OpenStreetMap の実道路ネットワークを用いて、配送計画における使用台数と総走行コストを最適化する VRP システムです。  
直線距離や経験則ではなく、実道路距離・時間帯制約・積載制約を前提に、現場担当者が判断根拠として使えるルート案とコスト参考値を提示します。

## 目的

配送計画における使用台数と総走行コストを、実道路ネットワーク上で最小化するシステムです。

直線距離や経験則ではなく、OSM の実道路・時間帯制約・積載制約を前提に計画を立案し、現場担当者が「なぜこのルートか」を説明・判断できる形でルート案とコスト内訳を提示します。

- **コスト最小化** — `使用台数 × 固定費 + 総走行距離 × 距離単価` を数理最適化で解く
- **実道路ベース** — 一方通行・道路接続を踏まえた距離と推定所要時間を使用
- **説明可能な出力** — 台数・ルート順・区間距離・コスト内訳・制約充足状況を一覧で提示
- **現場での意思決定支援** — 自動化ではなく、担当者・管理者が判断材料として使う位置づけ

## 課題

配送計画の現場では、次の3つの課題が根本にあります。

**属人化** — ルート組みがベテラン担当者の経験と勘に依存しているため、担当者が変わると同じ条件でも異なる計画になり、品質の再現性がありません。判断根拠が言語化されていないため引き継ぎも困難で、育成に時間がかかります。

**コスト根拠の不在** — 配送コストは使用台数・走行距離・燃料費などに左右されるため都度算出が必要ですが、現場ではそれらを加味しながらルートを組むことが難しく、「だいたいこのくらい」という感覚値にとどまりがちです。計画の妥当性を管理者や顧客に数字で示せません。

**使用台数の決定根拠がない** — 「いつも4台だから4台」という慣習や経験則で台数を決めているケースが多く、当日の配送件数・時間帯制約・積載量を踏まえて何台が適切かを数字で判断する手段がありません。台数が多すぎると固定費が増え、少なすぎると制約を満たせません。

本システムは、`使用台数 × 固定費 + 総走行距離 × 距離単価` を実道路距離で最小化し、制約を満たす最小台数とコスト参考値を算出することで、これら3つの課題に対して計算根拠のある判断材料を提供します。

## スコープ

- 対象エリア：神奈川県
- 配送形態：単一デポ、デポ出発・デポ帰着
- 配送体制：`人数 = 台数`、1 人 1 台
- 需要量単位：荷物個数
- 使用台数：固定値ではなく、当日の稼働可能台数レンジ内で決定
- 積載制約：depot_master に登録された1台あたり最大積載数（例：30 個）
- 主目的：`総コスト = 使用台数 × 固定コスト + 総走行距離 × 距離比例コスト`
- 時間帯区分：`午前 / 午後 / 時間指定なし` の3区分
- 勤務時間制約：depot_master に登録された勤務時間内に帰着（例：09:00〜18:00）
- 時間計算：OSM 道路属性に基づく静的推定時間を利用
- 出力：必要台数、ルート案、概算コスト、各区間距離、各ルート総距離、可視化、代替案
- 例外時：住所不備、ジオコーディング失敗、ネットワーク割当失敗がある場合は失敗地点を除いた暫定結果を返す

## 特徴

直線距離や概算距離ではなく、OSM の実道路ネットワークを前提にした配送計画システムです。

- **実道路ベースの距離・時間** — 一方通行や道路接続を踏まえた実道路距離と推定所要時間を使用
- **道路ネットワークの事前取得** — 県単位のネットワークを初回のみ取得・保存し、実行のたびに外部アクセスしない設計により、再現性の確保と実行時間の短縮を両立
- **説明可能な出力** — 配送ルート案・各拠点への帰着時刻・コスト内訳・制約充足状況（積載・時間帯・勤務時間）を一覧で提示し、現場担当者や管理者が判断根拠として使える形にしている
- **複数候補の一括提示** — 使用台数を v_min〜v_max の範囲で一括探索し、1回の実行で台数別の候補プランを比較できる
- **暫定結果の返却** — 住所不備・ジオコーディング失敗・ネットワーク割当失敗が一部あっても、失敗件数を除外した暫定結果を返し、完全停止しない設計

## スクリーンショット

### 入力画面（初期状態）

![入力画面](docs/images/screenshot_input.png)

### 入力画面（データ入力後）

![入力画面（入力後）](docs/images/screenshot_input2.png)

### 最適化結果

![最適化結果](docs/images/screenshot_result.png)

### 配送ルートマップ

![配送ルートマップ](docs/images/screenshot_map.png)

## 動かし方

### 前提

- Python 3.11 以上
- 本リポジトリをクローンして仮想環境を構築済みであること

```bash
git clone https://github.com/HAYATOYAMADA/vrp-road-network-optimization.git
cd vrp-road-network-optimization
python -m venv venv
source venv/bin/activate
pip install -e .
```

### 道路ネットワークの取得（初回のみ）

GraphML ファイルはサイズが大きいためリポジトリに含まれていません。初回起動前に以下のコマンドで取得してください。Overpass API へのアクセスが発生するため、完了まで数分かかります。

```bash
python -m vrp_optimization.network.graph
```

取得完了後は `data/processed/osm_network/kanagawa_drive_latest.graphml` が生成されます。以降の実行ではキャッシュが再利用されます。

#### 対象エリアを変更する場合

神奈川県以外を対象にする場合は以下の3箇所を変更してください。

| ファイル | 変数 | デフォルト値 | 変更例 |
|---|---|---|---|
| [src/vrp_optimization/network/graph.py](src/vrp_optimization/network/graph.py#L35) | `PLACE` | `"Kanagawa, Japan"` | `"Tokyo, Japan"` |
| [src/vrp_optimization/network/graph.py](src/vrp_optimization/network/graph.py#L33) | `LATEST_PATH` | `kanagawa_drive_latest.graphml` | `tokyo_drive_latest.graphml` |
| [src/vrp_optimization/visualization/map.py](src/vrp_optimization/visualization/map.py#L27) | `GRAPH_PATH` | `kanagawa_drive_latest.graphml` | `tokyo_drive_latest.graphml` |

変更後、再度 `python -m vrp_optimization.network.graph` を実行すると新しいエリアのネットワークが取得されます。

### 起動

```bash
bash start.sh
```

ブラウザで `http://localhost:8501` が自動的に開きます。

### 操作手順

1. **① 配送データ** — `delivery_transaction.csv` をアップロード
2. **② 車両台数レンジ** — 最小・最大台数を指定
3. **③ 出力先フォルダ** — 結果を保存するフォルダを選択
4. **「最適化を実行」** — ボタンをクリック
5. 完了後、候補プランサマリ・ルート詳細・配送ルートマップを確認

### 入力 CSV フォーマット

| 列名 | 内容 |
|---|---|
| `delivery_id` | 配送先 ID（UUID） |
| `destination_address` | 配送先住所 |
| `package_count` | 荷物個数 |
| `delivery_time_slot_code` | 時間帯コード（1: 午前 / 2: 午後 / 0: 指定なし） |

## パイプライン

```text
delivery_transaction.csv（アップロード）
    ↓
① 住所正規化 / ジオコーディング（Nominatim）
    ↓
② 道路ネットワークへのスナップ（OSMnx）
    ↓
③ 実道路 OD 行列計算（Dijkstra 最短経路）
    ↓
④ VRP 最適化（OR-Tools CP-SAT）
   台数 max → min の順に探索、INFEASIBLE で打ち切り
    ↓
⑤ 制約充足・コスト評価
    ↓
⑥ ルートマップ生成（Folium）
   ・全体俯瞰マップ（直線）
   ・車両別詳細マップ（道路沿い + AntPath 矢印）
    ↓
outputs/{plan_id}/ に保存
```

## 技術スタック・選定理由

| カテゴリ | 採用技術 | 選定理由 |
|---|---|---|
| 道路ネットワーク | OSMnx | OSM から有向グラフを直接取得・保存でき、再現性が高い |
| 最短経路 | NetworkX（Dijkstra） | OSMnx と統合されており、実道路距離を正確に算出できる |
| VRP ソルバー | OR-Tools CP-SAT | 制約プログラミングで時間帯・積載・業務時間を統一的に扱える。OPTIMAL ステータスによりこれ以上コストを下げられる組み合わせが存在しないことが保証される |
| 地図可視化 | Folium + AntPath | Python から HTML マップを生成でき、道路沿いルートと進行方向を表現できる |
| バックエンド | FastAPI | 長時間ジョブを別プロセスで実行し、フロントエンドからポーリングできる非同期構成を実現 |
| フロントエンド | Streamlit | データサイエンス向けの UI を少ないコード量で構築できる |
| ジオコーディング | Nominatim（OSM） | 無償で利用可能。住所の正規化と緯度経度変換を実施 |

### ソルバー選定の詳細

OR-Tools には Routing Library（ヒューリスティック探索）と CP-SAT（制約プログラミング）の 2 つがあります。本 PoC では以下の理由で CP-SAT を採用しました。

| | Routing Library | CP-SAT |
|---|---|---|
| 解法 | ヒューリスティック | 完全探索（分枝限定法） |
| 最適性保証 | なし | OPTIMAL で保証あり |
| 探索時間（19件） | 60 秒 | 2.25 秒 |
| 制約追加の柔軟性 | 限定的 | 高い |

19 件・2 台の構成で CP-SAT は **2.25 秒で OPTIMAL** を達成しており、これ以上コストを下げられる組み合わせが存在しないことが保証された上で、探索にかかる時間コストも低く抑えられています。

## 検証結果・知見

### PoC 実行例（配送先 19 件）

| 項目 | 値 |
|---|---|
| 推奨使用台数 | 2 台 |
| 総走行距離 | 218.83 km |
| 総コスト | ¥40,942 |
| ソルバーステータス | OPTIMAL |
| 制約充足 | 10 項目 PASS / 0 FAIL |

19 件・稼働可能台数 2〜5 台の条件で実行した結果、**2 台が最小コストの推奨プラン**として出力されました。ソルバーステータス OPTIMAL は、これ以上台数やルートを変えてもコストが下がらないことを意味します。制約充足 10 項目 PASS は、時間帯・積載・勤務時間のすべての条件をルートが満たしていることを示しており、計画をそのまま現場の判断材料として使用できる状態です。

### OSMnx vs Google Maps 距離検証

OSMnx で算出した距離と Google Maps の実測距離を全 OD ペアで比較した結果、乖離率の平均は **-16%（OSMnx が短い傾向）** でした。

| 指標 | 値 |
|---|---|
| 比較ペア数 | 380 ペア |
| 許容範囲内（±10%） | 22.9% |
| 許容範囲外 | 77.1% |
| 平均乖離率 | -16% |

主な原因は、OSMnx がスナップしたネットワークノードを起点とする一方、Google Maps は実際の建物・入口を起点とする差異と、高速道路の取り扱いの違いです。この乖離により、出力されるコストは実際より低めに見積もられる傾向があります。現時点では概算値として扱い、商用地図データへの切り替えにより精度向上が見込めます。

## 既知の制約・今後の課題

- 対象エリアが神奈川県に限定（道路グラフは事前取得済み）
- Nominatim のレート制限により、住所件数が多い場合はジオコーディングに時間を要する
- OSMnx 距離と実測距離に約 16% の乖離があり、商用地図データへの切り替えが望ましい
- 動的交通情報（渋滞等）は非対応
- 複数デポ・複数日配送は対象外

## 構成

```text
.
├── api/
│   ├── main.py              # FastAPI サーバー（ジョブ管理）
│   └── pipeline.py          # パイプライン実行オーケストレーター
│
├── app/
│   └── streamlit_app.py     # Streamlit Web アプリ
│
├── data/
│   ├── raw/                 # 入力 CSV（delivery_transaction, depot_master）
│   └── processed/           # ジオコーディング結果・OSM ネットワーク（GraphML）
│
├── docs/
│   └── design/              # 設計ドキュメント（00〜06）
│
├── notebooks/               # 実験・検証用 Notebook
│
├── outputs/
│   └── {plan_id}/
│       ├── distance/        # OD 距離行列 CSV
│       ├── output/
│       │   ├── table/       # ルートサマリ・詳細・評価レポート CSV
│       │   └── image/       # ルートマップ HTML
│       └── validation/      # 距離検証レポート
│
├── scripts/
│   └── generate_gas_input.py  # Google Maps 距離検証用 CSV 生成
│
├── src/vrp_optimization/
│   ├── preprocessing/       # ジオコーディング
│   ├── network/             # OSMnx グラフ取得・ノードスナップ
│   ├── distance_matrix/     # OD 距離行列計算・距離検証
│   ├── solver/              # VRP ソルバー（OR-Tools CP-SAT）
│   ├── evaluation/          # 制約充足・コスト評価
│   └── visualization/       # Folium ルートマップ生成
│
├── start.sh                 # 起動スクリプト（FastAPI + Streamlit）
└── pyproject.toml
```

## ドキュメント

- 問題定義：[docs/design/00_problem_definition.md](docs/design/00_problem_definition.md)
- 業務要件：[docs/design/01_business_requirements.md](docs/design/01_business_requirements.md)
- データ定義：[docs/design/02_data_definition.md](docs/design/02_data_definition.md)
- 道路ネットワーク設計：[docs/design/03_network_design.md](docs/design/03_network_design.md)
- 数理モデル設計：[docs/design/04_math_model.md](docs/design/04_math_model.md)
- アルゴリズム設計：[docs/design/05_algorithm_design.md](docs/design/05_algorithm_design.md)
- 実験設計：[docs/design/06_experiment_design.md](docs/design/06_experiment_design.md)

