# 001 OSM Prefecture Preload Architecture
version: v1  
status: brainstorming  
author: Hayato Yamada  

---

# 1. 目的

本ドキュメントは、VRP（Vehicle Routing Problem）配送ルート最適化システムにおいて  
**実道路ネットワークを効率的に利用するためのOSMデータ取得アーキテクチャ案**を整理することを目的とする。

特に以下の課題を解決することを目標とする。

- VRP計算時のAPI遅延
- 道路ネットワーク取得の再現性
- 大規模エリアへの対応
- 距離計算処理の高速化

本ドキュメントは **設計検討（Brainstorming）段階の資料**であり、  
最終仕様は今後の検証結果に基づいて決定する。

---

# 2. 背景

本プロジェクトでは以下の最適化パイプラインを構築する。

```
  
OpenStreetMap  
↓  
Road Network  
↓  
Shortest Path  
↓  
Distance Matrix  
↓  
VRP Solver  
↓  
Visualization  
  
```
VRPでは配送地点間の距離計算が大量に発生するため、  
道路ネットワーク取得方法がシステム全体の性能に大きく影響する。

主な課題は次の通り。

- OSM APIの取得時間
- 同一ネットワークの重複取得
- 実験再現性の確保

---

# 3. 検討の経緯

VRP最適化では配送地点間の距離計算が大量に発生する。

距離計算の精度を確保するためには  
**実道路ネットワークに基づく距離計算**が必要となる。

本プロジェクトでは以下のアプローチを検討した。

1. 直線距離（Haversine距離）
2. APIによるリアルタイム経路取得
3. 道路ネットワーク事前取得

---

# 4. アプローチ比較

| 方法 | 精度 | 計算速度 | 再現性 |
|-----|------|------|------|
| 直線距離 | 低 | 高 | 高 |
| API経路取得 | 高 | 低 | 低 |
| 事前取得ネットワーク | 高 | 高 | 高 |

直線距離は高速であるが実道路距離と乖離がある。

API経路取得は精度が高いが  
大量の経路計算を行うVRPでは計算時間が増大する。

そのため本プロジェクトでは  
**道路ネットワーク事前取得方式を有力候補とする。**

---

# 5. 検討したアーキテクチャ

## 5.1 リアルタイム取得方式

VRP実行時に必要な範囲の道路ネットワークを取得する。

```
  
配送地点  
↓  
Bounding Box計算  
↓  
OSM API取得  
↓  
Graph生成  
↓  
Shortest Path  
↓  
VRP  
  
```
### メリット

- 必要な範囲のみ取得
- データサイズが小さい

### デメリット

- API遅延
- 同一データの再取得
- 実験再現性が低い

---

## 5.2 事前取得方式（本検討）

日本の道路ネットワークを **事前取得して保存する方式**

```
  
OSM  
↓  
Prefecture Network Extraction  
↓  
GraphML保存  
↓  
VRP実行時にロード  
↓  
サブグラフ抽出  
↓  
Distance Matrix  
↓  
VRP  
  
```
---


```
# 6. 想定システム構成  
  
OpenStreetMap  
↓  
Prefecture Road Network Extraction  
↓  
GraphML保存  
↓  
Road Network Repository  
↓  
配送地点入力  
↓  
Network Selection  
↓  
Shortest Path  
↓  
Distance Matrix  
↓  
VRP Solver  
  
```
---

# 7. ネットワーク取得単位

候補

## 都道府県単位

```
  
47 Prefecture Graph  
  
```
例

```
  
tokyo.graphml  
kanagawa.graphml  
saitama.graphml  
chiba.graphml  
  
```
理由

- API負荷削減
- 管理しやすいサイズ
- 地域単位で再利用可能

---


```
# 8. VRP実行時の処理フロー  
  
配送地点入力  
↓  
Bounding Box算出  
↓  
対象Prefecture Networkロード  
↓  
Subgraph抽出  
↓  
Nearest Node Mapping  
↓  
Shortest Path  
↓  
Distance Matrix生成  
↓  
VRP Solver  
  
```
---


```
# 9. 想定ディレクトリ構成  
  
data/road_network/  
  
```
tokyo.graphml
kanagawa.graphml
saitama.graphml
chiba.graphml

```
  
```
保存形式

```
  
GraphML  
  
```
---

# 10. 期待されるメリット

## 再現性

道路ネットワークを保存することで

- 実験再現
- 結果比較
- デバッグ

が可能になる。

---

## API負荷削減

VRP実行時にOSM APIを呼び出す必要がなくなる。

---

## 計算高速化

VRP実行時

```
  
API取得  
↓  
Network構築  
  
```
の処理を省略できる。

---

# 11. 想定課題

## メモリ使用量

都道府県ネットワークは

- 数十MB
- 数十万ノード

になる可能性がある。

---

## 県跨ぎ配送

複数県のネットワーク結合が必要。

例

```
  
東京 → 神奈川  
  
```
---

# 12. 検証項目

以下の技術検証を実施する。

- 都道府県ネットワーク取得可能か
- ノード数
- エッジ数
- shortest path計算時間
- distance matrix生成時間

検証結果は以下に保存する。

```
  
docs/validation/  
  
```
---

# 13. 暫定結論

現時点では

**Prefecture Network Preload方式**

が有力候補である。

ただし以下の検証結果を踏まえて  
最終アーキテクチャを決定する。

- ネットワークサイズ
- shortest path計算時間
- VRP計算時間

---

# 14. 次のアクション

以下の技術検証を実施する。

1. OSMnxで都道府県ネットワーク取得
2. ノード数・エッジ数の確認
3. shortest path計算時間測定
4. distance matrix生成時間測定

検証結果は

```
  
docs/validation/  
  
```
に保存する。

```
