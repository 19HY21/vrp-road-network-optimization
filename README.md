# 概要
本プロジェクトは OpenStreetMap の実道路ネットワークを利用した **Vehicle Routing Problem（VRP）配送ルート最適化システム** を構築するプロジェクトです。

物流配送では以下の要素を考慮した配送計画が必要になります。
- 配送先
- 車両数
- 車両容量
- 道路ネットワーク
- 配送距離
- 配送時間

これらの制約条件のもとで、配送コストを最小化するルートを求める問題は **Vehicle Routing Problem（VRP）** と呼ばれます。

本プロジェクトでは
- 実道路ネットワーク
- 最短経路
- 距離行列
- VRP最適化
- 可視化
- シナリオ分析
を統合した **実務PoCレベルの最適化パイプライン** を構築します。

# 背景
物流業界では配送効率の向上が重要な課題となっています。

例えば以下の問題があります。
- 配送ルートが経験則に依存している
- 配送距離・配送時間の最適化が難しい
- 複数車両のルート設計が複雑

これらの問題に対し、数理最適化を利用することで配送ルートの効率化が可能になります。
本プロジェクトでは**実道路ネットワークを利用したVRP最適化**を実装し、配送計画最適化のPoCを構築します。

# システムアーキテクチャ
※後で図を追加予定
本システムは以下の処理パイプラインで構成されます。
```
OpenStreetMap
      ↓
Road Network Extraction
      ↓
Shortest Path Computation
      ↓
Distance Matrix Generation
      ↓
VRP Solver
      ↓
Evaluation
      ↓
Visualization
```
将来的には以下のようなアーキテクチャ図を追加予定です。
（ここに図を追加予定）

# プロジェクト構成
```
vrp-road-network-optimization/

README.md
LICENSE
CONTRIBUTING.md

docs/
    00_problem_definition.md
    01_business_requirements.md
    02_data_definition.md
    03_network_design.md
    04_math_model.md
    05_algorithm_design.md
    06_experiment_design.md
    07_results.md
    architecture.md

src/
    vrp_optimization/
        __init__.py
        cli.py
        config/
        data_generation/
        network/
        distance_matrix/
        solver/
        simulation/
        evaluation/
        visualization/
        app/

config/
    default.yaml
    logging.yaml

notebooks/

data/
    README.md
    raw/
    processed/

experiments/

outputs/
    routes/
    metrics/
    figures/

logs/

tests/

scripts/

.github/workflows/

requirements.txt
pyproject.toml
.env.example
.gitignore
Makefile
```

# 各ディレクトリの役割
このセクションでは 生成AIおよび開発者がプロジェクト構造を理解できるようにすべてのディレクトリの役割を説明します。

## docs
プロジェクトの設計ドキュメントを格納します。
このディレクトリは プロジェクト設計フェーズの成果物です。
### 00_problem_definition.md
解決する業務課題を定義します。
内容例
- 問題の背景
- 対象業務
- 解決する課題
- 成功指標

### 01_business_requirements.md
業務要件を定義します。
内容例
- 配送車両数
- 配送時間制約
- 車両容量
- 配送先数
- 配送拠点

### 02_data_definition.md
データ構造を定義します。
内容例
- 配送地点データ
- 車両データ
- 道路ネットワーク
- 距離行列

### 03_network_design.md
道路ネットワーク取得方法を設計します。
内容例
- OpenStreetMapデータ取得
- OSMnx利用方法
- グラフ構造
- 道路ネットワーク前処理

### 04_math_model.md
VRPの数理モデルを記述します。
内容例
- 目的関数
- 制約条件
- 数理式
- 変数定義

### 05_algorithm_design.md
最適化アルゴリズム設計を記述します。
内容例
- OR-Tools設定
- Solver構成
- 初期解生成
- ヒューリスティック

### 06_experiment_design.md
実験設計を記述します。
内容例
- シナリオ設定
- 評価指標
- 比較方法

### 07_results.md

実験結果をまとめます。
内容例
- 配送距離
- 計算時間
- シナリオ比較

### architecture.md
システムアーキテクチャ図を格納します。

## src
最適化システムの実装コードを格納します。
このディレクトリは プロジェクトのコア実装です。

### vrp_optimization
Pythonパッケージとして実装します。

#### cli.py
コマンドラインインターフェース。
例
python -m vrp_optimization.cli

#### network
道路ネットワーク取得処理。
内容
- OSMnxによる地図取得
- NetworkXグラフ生成

#### distance_matrix
距離行列生成。
内容
- 最短経路計算
- travel time計算

#### solver
VRP最適化ソルバー。
内容
- OR-Tools
- RoutingModel
- 制約設定

#### data_generation
配送地点データ生成。
内容
- ランダム配送地点
- サンプル配送データ

#### simulation
シナリオシミュレーション。
内容
- 配送件数変化
- 車両数変化

#### evaluation
最適化結果の評価。
内容
- 総距離
- 計算時間
- 車両使用数

#### visualization
地図可視化。
内容
- Folium
- ルート描画

#### app
Streamlitアプリ。

## config
設定ファイルを格納します。

### default.yaml
実験設定
例
- 車両数
- 容量
- Solver時間

### logging.yaml
ログ設定。

## data

プロジェクトで使用するデータ。
- raw
- processed

### raw
外部データ

### processed
前処理済みデータ

## notebooks
探索的分析。
例
- ネットワーク確認
- 距離行列テスト

## experiments
実験設定と結果。
例
- experiment_01
- experiment_02

## outputs
最適化結果。
- routes
- metrics
- figures

## logs
ログファイル。

## tests
ユニットテスト。

## scripts
パイプライン実行。
例
run_pipeline.py


# 技術スタック
Python
主要ライブラリ
- OSMnx
- NetworkX
- OR-Tools
- Pandas
- NumPy
- GeoPandas
- Folium
- Streamlit


# 数理モデル概要
※後で追記予定

詳細はdocs/04_math_model.md参照。


# 実験設計
※後で追記予定

docs/06_experiment_design.md参照。

# 実行方法
※実装後に追記
- make network
- make distance
- make solve
- make simulation

または
- python scripts/run_pipeline.py

# 実験結果
※実装後に追記予定

# 可視化結果
※実装後に追記予定

# パフォーマンス評価
※実装後に追記予定

# 再現方法
※後で追記予定

# 想定ユースケース
- 配送ルート最適化
- 物流ネットワーク分析
- 配送計画シミュレーション

# ライセンス
MIT License
