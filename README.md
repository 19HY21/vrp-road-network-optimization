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

---

# 背景
物流業界では配送効率の向上が重要な課題となっています。

例えば以下の問題があります。
- 配送ルートが経験則に依存している
- 配送距離・配送時間の最適化が難しい
- 複数車両のルート設計が複雑

これらの問題に対し、数理最適化を利用することで配送ルートの効率化が可能になります。
本プロジェクトでは**実道路ネットワークを利用したVRP最適化**を実装し、配送計画最適化のPoCを構築します。

---

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

---

# プロジェクト構成
```
vrp-road-network-optimization/

github/
      workflows/

.vscode/
      setting.json

archive/

config/
      default.yaml
      logging.yaml

data/
    raw/
    processed/
    README.md

docs/
      archives/
      assumptions/
            modeling_assumptions.md
      brainstrorming/
            001_001_osm_prefecture_preload_architecture_v1.md
      data_dictionary/
            customer_schema.md
            distance_matrix_schema.md
            network_schema.md
            vehicle_shcem.md
      decision_log
      design/
            00_problem_definition.md
            01_business_requirements.md
            02_data_definition.md
            03_network_design.md
            04_math_model.md
            05_algorithm_design.md
            06_experiment_design.md
      feasibility/
            01_osm_network_feasibility.md
      result/
            01_experiment_results.md
            02_performance_analysis.md
            03_scenario_analysis.md
      architecture.md

experiments/
      exp001_base_case

logs/

notebooks/
      archive/
      001_osm_perfecture_network_check.ipynb
      002_prefecture_batch_network_check.ipynb

outputs/
    figures/
    metrics/
    routes/

scripts/
      run_pipline.py


src/
      vrp_optimization/
            app/
            config/
            data_generation/
            distance_matrix/
            evaluation/
            network/
            simulation/
            solver/
            visualization/
            __init__.py
            cli.py

tests/

.env.example

.gitnore

LICENSE

Makefile

pyproject.toml

REAMDE.md

requirements.txt

```

---

# ディレクトリ構造と役割

## `.github/`

GitHub のリポジトリ運用に関する設定を管理するディレクトリです。
主に GitHub Actions などの CI/CD ワークフローを格納します。


## `.vscode/`

Visual Studio Code 用の開発環境設定を管理するディレクトリです。
エディタ設定、Python 実行環境、フォーマッタ設定などを保存します。


## `archive/`

過去の実験結果、旧バージョンのコード、廃止された設計資料などを保存するディレクトリです。
現在は使用しないが履歴として残しておく資料を保管します。


## `config/`

アプリケーションや実験設定を管理するディレクトリです。
モデル設定、実験パラメータ、ログ設定などの YAML ファイルを配置します。


## `data/`

プロジェクトで使用するデータを格納するディレクトリです。
主に以下の2種類のデータを管理します。

* **raw**：外部から取得した未加工データ
* **processed**：前処理済みデータ

データの取得方法や管理ルールは `data/README.md` に記載します。


## `docs/`

プロジェクト設計・検討・分析結果などのドキュメントを管理するディレクトリです。

主な内容

* 問題定義
* 数理モデル設計
* アルゴリズム設計
* 実験設計
* 技術検証
* 結果分析
* データ定義
* 設計判断ログ

最適化プロジェクトの設計・分析ドキュメントを体系的に整理するためのディレクトリです。


## `experiments/`

実験単位の設定や結果を管理するディレクトリです。
各実験ごとにサブフォルダを作成し、以下の情報を管理します。

* 実験設定
* 実験ログ
* 評価結果
* 実験用データ


## `logs/`

プログラム実行時に出力されるログファイルを保存するディレクトリです。
デバッグや実験の再現性確認に利用します。


## `notebooks/`

Jupyter Notebook を用いた分析や検証を行うディレクトリです。

主な用途

* データ探索（EDA）
* ネットワーク確認
* 距離計算検証
* モデル挙動確認


## `outputs/`

プログラム実行結果を保存するディレクトリです。

主な内容

* ルート結果
* 評価指標
* 可視化図


## `scripts/`

パイプライン実行やデータ処理を行うスクリプトを格納するディレクトリです。
主に CLI から実行するスクリプトを配置します。


## `src/`

アプリケーションのメイン実装コードを格納するディレクトリです。

主な内容

* 最適化ロジック
* ネットワーク処理
* 距離行列生成
* シミュレーション
* 可視化

プロジェクトのコアロジックを実装するディレクトリです。


## `tests/`

ユニットテストや統合テストを格納するディレクトリです。
各モジュールの動作確認と品質保証を目的として使用します。


## `.env.example`

環境変数設定のテンプレートファイルです。
実際の `.env` ファイル作成時のサンプルとして使用します。


## `.gitignore`

Git 管理対象外にするファイルやディレクトリを定義する設定ファイルです。


## `LICENSE`

プロジェクトのライセンスを定義するファイルです。


## `Makefile`

開発用コマンドをまとめたファイルです。
ビルド・テスト・実行などのコマンドを簡略化するために使用します。


## `pyproject.toml`

Python プロジェクトの設定ファイルです。
パッケージ管理やビルド設定を定義します。


## `README.md`

プロジェクトの概要、使い方、構成などを説明するドキュメントです。


## `requirements.txt`

プロジェクトで使用する Python ライブラリの依存関係を定義するファイルです。

---

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

---


# 数理モデル概要
※後で追記予定

詳細はdocs/04_math_model.md参照。

---

# 実験設計
※後で追記予定

docs/06_experiment_design.md参照。

---

# 実行方法
※実装後に追記
- make network
- make distance
- make solve
- make simulation

または
- python scripts/run_pipeline.py

---

# 実験結果
※実装後に追記予定

---

# 可視化結果
※実装後に追記予定

---

# パフォーマンス評価
※実装後に追記予定

---

# 再現方法
※後で追記予定

---

# 想定ユースケース
- 配送ルート最適化
- 物流ネットワーク分析
- 配送計画シミュレーション

---

# ライセンス
MIT License
