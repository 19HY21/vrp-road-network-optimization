# 001 OSM Network Feasibility Validation Plan

version: v1
status: brainstorming
author: Hayato Yamada

---

# 1. 目的

本ドキュメントは、実道路ネットワークを用いた VRP 配送最適化プロジェクトに着手してよいかを判断するための、
**OSM 道路ネットワーク取得・保存・結合・経路探索の事前検証計画** を整理することを目的とする。

本検証は VRP 本体の実装前に実施するゲートであり、以下を判定対象とする。

- 1 都道府県の道路ネットワークを現実的な時間で取得できるか
- 行政区単位で分割取得し、後から結合できるか
- 結合後も行政区を跨ぐ経路探索と道のり距離算出が成立するか
- GitHub 公開を前提に、保存・再利用・再現性のある構成を作れるか

---

# 2. 検証背景

本プロジェクトの最終目標は、OpenStreetMap の実道路ネットワークを利用し、
ラストマイル配送を想定した VRP 最適化システムを社内 PoC レベルまで構築することである。

ただし、VRP に進む前に次の制約が存在する。

- 実道路ネットワークを毎回 OSM から取得すると、処理時間と再現性の面で不利
- 本来は全国データを事前保存したいが、GitHub 公開時の容量制約がある
- 公開用ポートフォリオでは、1 都道府県にスコープを絞る必要がある
- 1 都道府県をそのまま取得するだけでは実装上の工夫として弱いため、行政区分割取得と結合まで示したい

そのため、本検証では以下の方針を採る。

- 公開用の対象範囲は 1 都道府県
- 取得単位は都道府県一括取得と行政区分割取得の両方を検証
- 行政区単位で取得したネットワークを結合し、疑似的な広域拡張性を示す

---

# 3. 本検証で答えるべき問い

1. OSM から 1 都道府県の道路ネットワークを安定取得できるか
2. 同じ都道府県を行政区単位で分割取得できるか
3. 分割取得したネットワークを結合し、1 つのグラフとして扱えるか
4. 行政区を跨ぐ OD でも経路探索と道のり距離算出が成立するか
5. 保存済みネットワークを再利用する運用が成立するか
6. 距離だけでなく、所要時間推定へ拡張できる余地があるか

---

# 4. 検証スコープ

## 4.1 対象

- 対象都道府県: 神奈川県
- 同都道府県内の複数行政区
- ラストマイル配送を想定した道路ネットワーク

## 4.1.1 神奈川県を選定する理由

- 自身に土地勘があり、取得結果や経路の妥当性を感覚的にも確認しやすい
- 東京都ほど道路密度と複雑性が極端ではなく、初期検証の難易度を過度に上げにくい
- 都市部、住宅地、湾岸部、郊外を含み、ラストマイル配送の検証対象として十分な多様性がある
- 行政区分割取得と結合の検証題材として扱いやすい
- ポートフォリオとしても、実務を想定した規模と複雑性を示しやすい

## 4.1.2 東京都を初期対象から外す理由

- 道路ネットワークが高密度で、初期の取得・結合・妥当性確認コストが高くなりやすい
- 行政区境界や都心部の道路構造が複雑で、基盤検証の難易度を不必要に押し上げる可能性がある
- 初期フェーズでは、難易度よりも VRP に進めるかどうかの判定速度を優先する

## 4.2 今回やること

- 都道府県一括取得
- 行政区分割取得
- 行政区分割データの保存
- 分割ネットワークの結合
- 結合後の最短経路探索
- 道のり距離の算出
- 所要時間推定の実現可能性確認
- 保存形式、容量、再現手順の確認

## 4.3 今回やらないこと

- 全国対応の本格実装
- 車種別制約の本格実装
- 高度な VRP 制約の実装
- 本番運用を想定した API 化や UI 作り込み

## 4.4 事前に固定しておく前提条件

- 対象エリアは神奈川県の 1 都道府県に限定する
- 業務想定はラストマイル配送とする
- ラストマイル配送を想定するため、基本の移動手段は車両とする
- 道路ネットワークは OSM 由来データを使用する
- 取得対象ネットワークは自動車走行可能道路を表す `drive` を基本とする
- 検証では都道府県一括取得版と行政区分割取得版の両方を扱う
- 検証の主目的は VRP 前段の技術成立性確認であり、最終最適化目的の確定は後続フェーズで行う
- 初期評価指標は道のり距離を主とし、所要時間は拡張項目として扱う
- 保存済みネットワークを再利用する前提で、毎回の再取得を避ける
- GitHub 公開を前提に、生データを含めた容量制約と再現手順を考慮する
- 行政区分割と結合は、県跨ぎ実装そのものではなく、広域拡張性の疑似検証として位置付ける
- 車種別条件は初期検証では必須とせず、属性確認と将来拡張の可能性確認に留める

---

# 5. 検証項目

## 5.1 必須項目

### A. 都道府県一括取得可否

- OSM から 1 都道府県の道路ネットワークを取得できるか
- 取得処理がタイムアウトやメモリエラーなく完了するか

### B. 行政区分割取得可否

- 同一都道府県を行政区単位で取得できるか
- 各行政区の取得結果を個別に保存できるか

### C. 分割ネットワーク結合可否

- 行政区ごとに取得したグラフを結合できるか
- 境界付近でノードやエッジの接続が破綻しないか

### D. 行政区跨ぎ経路探索可否

- 出発地と到着地が異なる行政区にあっても、最短経路を探索できるか
- ルートが不自然に途切れたり、到達不能にならないか

### E. 道のり距離算出可否

- 実道路ベースの道のり距離を安定算出できるか
- 少数サンプルで妥当な経路が得られるか

### F. 保存・再利用可否

- GraphML などで保存し、再読込できるか
- 再取得せずに同一ネットワークで検証を再現できるか

## 5.2 できれば確認したい項目

### G. 所要時間推定可否

- エッジ長と速度仮定から所要時間を計算できるか
- 将来的に所要時間最小化へ移行できる見込みがあるか

### H. 一括取得版と分割結合版の差分確認

- 同じ OD に対し、都道府県一括取得版と行政区分割結合版で極端な差が出ないか

### I. 外部比較による妥当性確認

- Google Maps 等と比較して、道のり距離や所要時間が極端に乖離していないか

### J. 計算性能確認

- 取得時間
- 保存時間
- 読込時間
- 最短経路計算時間

---

# 6. 不足しやすい追加確認項目

本検証では、単に「取得できたか」だけでなく、後続の VRP 実装に影響する基盤品質も確認する。

## 6.1 データ品質

- 孤立ノードが過剰にないか
- 行政区ごとに道路データの欠損がないか
- 一方通行や道路種別が明らかに欠落していないか

## 6.2 座標スナップの成立性

- 配送先座標を道路ネットワーク上のノードへ安定的に割り当てられるか
- 行政区境界付近でも異常なスナップが起きないか

## 6.3 GitHub 公開前提の運用性

- 保存ファイルサイズが公開運用上許容範囲か
- 生データをコミットしない場合でも再現手順を文書化できるか

---

# 7. 検証手順

## Step 1. 対象都道府県の決定

- 検証対象を神奈川県として確定する
- 神奈川県を選定した理由を記録する
- 行政区一覧を整理する
- 取得対象道路種別の方針を決める
- 事前前提条件を明文化する

成果物

- 対象都道府県名
- 対象都道府県の選定理由
- 行政区一覧
- 前提条件メモ

## Step 1 補足. 取得対象道路種別の方針

- 本プロジェクトはラストマイル配送を想定する
- そのため、初期検証では基本の移動手段を車両とみなす
- OSM 取得時のネットワーク種別は `drive` を採用する
- 歩行者専用、自転車専用、階段など配送車両で通行しない経路は初期検証の対象外とする
- 将来的に車種別制約を検討する場合も、まずは `drive` ネットワーク上で基盤検証を完了させる

## Step 2. 都道府県一括取得

- OSMnx 等で都道府県全体の道路ネットワークを取得する
- ノード数、エッジ数、保存ファイルサイズを記録する
- 保存と再読込を確認する

成果物

- 都道府県一括取得グラフ: `data/raw/road_network/kanagawa_drive.graphml`
- 基本メトリクス: `outputs/metrics/kanagawa_drive_network_metrics.csv`

検証結果

- OSMnx を用いて神奈川県全体の `drive` ネットワークを一括取得できた
- ノード数は `223,850`、エッジ数は `608,205`、ファイルサイズは `259.52 MB`、取得時間は `296.38` 秒だった
- 保存後の再読込でもノード数、エッジ数は一致し、一括取得と保存再利用が成立することを確認した

## Step 2.5 一括取得版の後処理検証

- 一括取得した都道府県全体グラフを、後続の経路探索や VRP 前処理に使いやすい形へ整える
- 最大弱連結成分の確認、属性削減、`travel_time` 付与を行う
- 後処理後の保存、再読込、差分確認を行う

実施理由

- 一括取得できることと、後続の routing や VRP 前処理に耐えることは別論点であるため
- 属性整理や `travel_time` 付与が、後続ステップの前処理として成立するかを先に確認するため
- 保存と再読込を経ても差分が出ないことを確認し、再利用可能な中間成果物にできるかを見るため

成果物

- 後処理ロジック: `notebooks/001_osm_network_feasibility_validation_plan.ipynb` の `step3-network-postprocess` セル
- 後処理済みメトリクス: `data/processed/kanagawa_drive_step3/kanagawa_drive_processed_metrics.csv`
- 実行ログ: `logs/001_osm_network_feasibility_validation_plan_step3_<timestamp>.log`

検証結果

- 一括取得版に対して最大弱連結成分の確認、属性削減、`travel_time` 付与、保存、再読込差分確認を実施した
- 今回の神奈川県 `drive` ネットワークでは、弱連結成分数は処理前後とも `1` であり、削除対象となる小成分はなかった
- 再読込差分は `0` 件であり、後処理済みネットワークを再利用可能な形で保存できることを確認した
- GraphML サイズは属性削減後でも `travel_time` 追加の影響により増加し、軽量化そのものの効果は限定的だった
- この結果から、一括取得版は後処理を加えても一貫して利用可能であり、以降の比較基準となる正本候補として扱えると判断した

## Step 3. 行政区分割取得

- 同一都道府県を行政区単位で順次取得する
- 各行政区ごとに保存する
- 行政区ごとの取得成否、サイズ、取得時間を記録する

成果物

- 行政区一覧: `data/raw/admin_units/kanagawa_municipalities.csv`
- 行政区単位グラフ群: `data/raw/road_network/kanagawa_municipalities/`
- 取得結果メトリクス: `outputs/metrics/kanagawa_municipalities/kanagawa_municipality_fetch_metrics_latest.csv`
- 失敗行政区一覧: `outputs/metrics/kanagawa_municipalities/kanagawa_municipality_failures_latest.csv`
- 取得ログ: `logs/001_osm_network_feasibility_validation_plan_step3_fetch_20260318_111723.log`

検証結果

- 神奈川県の市区町村 33 件を対象に `drive` ネットワークの分割取得を実施した
- 33 件中 33 件が成功し、エラーは 0 件だった
- 失敗行政区一覧は空だった
- 最大ファイルは横浜市の `90.96 MB` で、分割取得データ全体の合計サイズは約 `257.44 MB` だった
- 行政区単位での安定取得と、失敗分のみ再実行できる運用方針を確認できた

## Step 4. 分割データ結合

- 行政区単位グラフを結合する
- 境界付近の接続状況を確認する
- 結合グラフを保存する

成果物

- 結合グラフ: `data/processed/kanagawa_municipality_merged.graphml`
- 結合ロジック: `notebooks/001_osm_network_feasibility_validation_plan.ipynb` の `step4-merge-municipality-graphs` セル
- 結合結果メトリクス: `outputs/metrics/kanagawa_municipality_merged_metrics.csv`
- 経路疎通確認結果: `outputs/metrics/kanagawa_municipality_merged_route_checks.csv`
- 成分分析結果: `outputs/metrics/kanagawa_municipality_merged_component_analysis.csv`
- 成分別ルート地点分析: `outputs/metrics/kanagawa_municipality_merged_component_route_points.csv`
- 境界補完候補: `outputs/metrics/kanagawa_municipality_boundary_bridge_candidates.csv`
- 境界補完試行結果: `outputs/metrics/kanagawa_municipality_boundary_bridge_results.csv`
- 補完候補診断: `outputs/metrics/kanagawa_municipality_boundary_bridge_diagnosis.csv`
- 補完候補診断サンプル: `outputs/metrics/kanagawa_municipality_boundary_bridge_diagnosis_samples.csv`
- 一括取得版比較: `outputs/metrics/kanagawa_batch_vs_split_route_checks.csv`

検証結果

- 市区町村単位で個別取得した 33 件の GraphML を単純結合した
- 結合後グラフのノード数は `223,152`、エッジ数は `604,442` で、一括取得版に対してノード `-698`、エッジ `-3,763` の差分があった
- 結合後グラフの弱連結成分数は `21` であり、県全体の道路ネットワークとして一続きにはなっていなかった
- 有名地点を用いた経路疎通確認では、`Kawasaki Station -> Great Buddha of Kamakura` は取得できた一方、`Yokohama Station -> Odawara Station` と `Fujisawa Station -> Hakone-Yumoto Station` は `No path` となった
- 一括取得版では同一の 3 経路すべてで経路取得できたため、問題は分割取得後の単純結合方式に起因すると判断した
- 原因分析の結果、`Yokohama Station` は `component 1`、`Odawara Station` は `component 6`、`Hakone-Yumoto Station` は `component 14` に属しており、異なる component 間で経路が分断されていた
- 境界補完接続も試行したが、`component 1-6` および `component 1-14` の候補ノード対は `10m, 20m, 30m, 50m` のいずれの閾値でも近接候補が 0 件であり、後付けの近接接続では解消できなかった
- 以上より、「自治体ごとに独立取得したグラフを後から単純結合する方式」は、県全体 routing を前提とする基盤としては不適と判断した

PoC レベルの判断基準

- `graph_from_place` による自治体別個別取得は、各自治体を独立した place polygon として別々に取得するため、県全体で共通の node / edge 集合を前提としていない
- そのため、後から単純結合しても一括取得版と同じ node 一致が起きず、県全体 routing に必要な道路接続が欠落しうる
- 実際に今回の検証では、ノード差分 `-698`、エッジ差分 `-3,763`、`weak component = 21`、`No path` 発生を確認しており、PoC 基盤としては不採用とする
- 分割運用のメリットは、1 ファイルあたりのサイズ低減、地域単位の再取得、失敗時の再実行、限定エリアの更新がしやすい点にある
- 一方で、最初から自治体単位で独立取得する方式は、境界整合性が崩れると県全体 routing の成立性を失うため、PoC ではデメリットがメリットを上回る
- このため、社内 PoC の標準仕様としては「自治体単位で初回取得して後から結合する方式」は採用しない

## Step 4.5 親グラフ分割方式の追加検証

- 都道府県一括取得版を親グラフとして用意する
- 自治体ポリゴンを用いて、親グラフから自治体単位に切り出す
- 切り出した自治体グラフを保存する
- 必要に応じて再結合し、一括取得版との整合性を確認する
- 分割後も行政区跨ぎの経路探索が成立するかを確認する

成果物

- 親グラフ基準の自治体切り出しグラフ群: `data/processed/kanagawa_municipalities_from_master/`
- 切り出しロジック: `notebooks/001_osm_network_feasibility_validation_plan.ipynb` の `step45-master-split-and-merge` セル
- 再結合グラフ: `data/processed/kanagawa_municipality_merged_from_master.graphml`
- 切り出し結果メトリクス: `outputs/metrics/kanagawa_municipalities_from_master_metrics.csv`
- 一括取得版との比較結果: `outputs/metrics/kanagawa_municipalities_from_master_compare_metrics.csv`
- 経路疎通確認結果: `outputs/metrics/kanagawa_municipalities_from_master_route_checks.csv`
- 実行ログ: `logs/001_osm_network_feasibility_validation_plan_step45_20260319_143215.log`

検証結果

- 神奈川県一括取得版を親グラフとして用い、自治体ポリゴンごとに切り出す方式を実施した
- 33 件中 33 件の自治体切り出しが成功し、エラーは 0 件だった
- 再結合後グラフは、一括取得版に対してノード差分 `0`、エッジ差分 `0`、欠損ノード `0`、欠損エッジ `0` だった
- 再結合後グラフの弱連結成分数は `1` であり、県全体の道路ネットワークとして一続きの状態を保てた
- 有名地点を用いた経路疎通確認では、`Kawasaki Station -> Great Buddha of Kamakura`、`Yokohama Station -> Odawara Station`、`Fujisawa Station -> Hakone-Yumoto Station` の 3 経路すべてで道のり距離を取得できた
- 以上より、「一括取得した親グラフを正本として自治体単位に切り出し、必要に応じて再結合する方式」は、県全体 routing を維持したまま分割運用する方式として成立すると判断した

PoC レベルの判断基準

- 一括取得版を正本として分割する方式は、そもそも 1 枚の県全体道路ネットワークを分割しているため、再結合時に元の node / edge 接続を保ちやすい
- 実際に今回の検証では、再結合後にノード差分 `0`、エッジ差分 `0`、`weak component = 1`、代表 3 経路すべて成功を確認できた
- 分割運用のメリットは、必要な自治体だけを利用用キャッシュとして保持できること、再取得ではなく再切り出しで済むこと、限定エリアの検証や更新がしやすいことにある
- 一方で、神奈川県内だけを対象とする社内 PoC では、一括取得版だけでも技術成立性は十分確認できるため、分割は必須ではない
- したがって PoC では、まず「一括取得版を正本として利用する」ことを基本方針とし、運用上の都合で分割が必要な場合のみ「親グラフからの切り出し方式」を採用する
- 採用条件は、一括取得版に対してノード差分 `0`、エッジ差分 `0`、`weak component = 1`、代表的な行政区跨ぎ経路で `No path` が発生しないこととする

## Step 5. 経路探索検証

- 同一行政区内の OD を数件用意する
- 行政区跨ぎの OD を数件用意する
- 最短経路が取得できるか確認する
- 道のり距離を記録する

成果物

- OD 候補一覧: `data/raw/route_validation/kanagawa_od_point_candidates.csv`
- `001` 地点 OD 一覧: `outputs/metrics/kanagawa_step5_od_pairs.csv`
- `001` 地点経路探索結果: `outputs/metrics/kanagawa_step5_route_results.csv`
- `001` 地点差分結果: `outputs/metrics/kanagawa_step5_route_differences.csv`
- 全地点 OD 一覧: `outputs/metrics/kanagawa_step5_all_od_pairs.csv`
- 全地点経路探索結果: `outputs/metrics/kanagawa_step5_all_route_results.csv`
- 全地点差分結果: `outputs/metrics/kanagawa_step5_all_route_differences.csv`
- `001` 地点経路探索ロジック: `notebooks/001_osm_network_feasibility_validation_plan.ipynb` の `step5-route-validation` セル
- 全地点経路探索ロジック: `notebooks/001_osm_network_feasibility_validation_plan.ipynb` の `step5-all-route-validation` セル
- `001` 地点実行ログ: `logs/001_osm_network_feasibility_validation_plan_step5_<timestamp>.log`
- 全地点実行ログ: `logs/001_osm_network_feasibility_validation_plan_step5_all_<timestamp>.log`

検証結果

- `point_id` の末尾が `001` の 6 地点を対象に、同一点を除く総当たり `30 OD` を作成して検証した
- `30 OD` では、一括取得版と親グラフ分割版の双方で `30/30` 件の経路探索に成功した
- `30 OD` では、距離差 `0`、所要時間差 `0`、ノード数差 `0`、`status_match = True` を全件で確認した
- 地点候補 CSV に登録した全 12 地点を対象に、同一点を除く総当たり `132 OD` を作成して追加検証した
- `132 OD` では、一括取得版と親グラフ分割版の双方で `132/132` 件の経路探索に成功した
- `132 OD` でも、距離差 `0`、所要時間差 `0`、ノード数差 `0`、`status_match = True` を全件で確認した
- 以上より、今回検証した地点候補集合では、一括取得版と親グラフ分割版の道のり距離・所要時間・経路ノード数の整合性は `100%` 一致した
- この結果から、親グラフ分割版は一括取得版と同等の経路探索結果を返せると判断した

PoC レベルの判断基準

- 社内 PoC で採用する分割運用方式は、一括取得版に対して距離、所要時間、経路ノード数の差分が実務上許容可能であることを条件とする
- 今回の検証範囲では `30 OD` と `132 OD` の両方で差分 `0` を確認したため、神奈川県内 PoC においては親グラフ分割版を一括取得版と同等の経路基盤として扱ってよい
- 今後、地点候補や対象範囲を広げる場合も、同様に総当たりまたは代表 OD 群で差分確認を行うことを継続条件とする

## Step 6. 妥当性確認

- 一括取得版と分割結合版で同一 OD の距離差を確認する
- 少数ケースを Google Maps 等と比較する
- 極端な乖離がないかを確認する

成果物

- Google Maps 比較元データ `30 OD`: `data/raw/route_validation/kanagawa_step6_google_maps_30od.csv`
- Google Maps 比較元データ `全地点`: `data/raw/route_validation/kanagawa_step6_google_maps_all.csv`
- 比較準備テンプレート `30 OD`: `data/raw/route_validation/kanagawa_step6_google_maps_30od_template.csv`
- 比較準備テンプレート `全地点`: `data/raw/route_validation/kanagawa_step6_google_maps_all_template.csv`
- 緯度経度付き比較ファイル `30 OD`: `outputs/metrics/kanagawa_step5_route_results_with_coords.csv`
- 緯度経度付き比較ファイル `全地点`: `outputs/metrics/kanagawa_step5_all_route_results_with_coords.csv`
- Step 6 セットアップ: `notebooks/001_osm_network_feasibility_validation_plan.ipynb` の `step6-setup` セル
- 記述統計: `notebooks/001_osm_network_feasibility_validation_plan.ipynb` の `step6-descriptive-stats` セル
- Wilcoxon 検定: `notebooks/001_osm_network_feasibility_validation_plan.ipynb` の `step6-wilcoxon` セル
- 効果量: `notebooks/001_osm_network_feasibility_validation_plan.ipynb` の `step6-effect-size` セル
- 実務閾値判定: `notebooks/001_osm_network_feasibility_validation_plan.ipynb` の `step6-threshold-judgement` セル
- 順位一致率: `notebooks/001_osm_network_feasibility_validation_plan.ipynb` の `step6-ranking-agreement` セル
- Step 6 比較基礎データ: `outputs/validation/step6/kanagawa_step6_30od_base_comparison.csv`
- Step 6 記述統計: `outputs/validation/step6/kanagawa_step6_30od_descriptive_stats.csv`
- Step 6 Wilcoxon 結果: `outputs/validation/step6/kanagawa_step6_30od_wilcoxon.csv`
- Step 6 効果量: `outputs/validation/step6/kanagawa_step6_30od_effect_size.csv`
- Step 6 実務閾値判定: `outputs/validation/step6/kanagawa_step6_30od_threshold_judgement.csv`
- Step 6 順位一致詳細: `outputs/validation/step6/kanagawa_step6_30od_ranking_detail.csv`
- Step 6 順位一致要約: `outputs/validation/step6/kanagawa_step6_30od_ranking_summary.csv`

検証結果

- `30 OD` を対象に、OSMnx と Google Maps の距離・時間差分、誤差率、順位一致を比較した
- 距離差は平均 `-3.89 km`、平均誤差率 `10.01%`、`p95 = 22.35%`、最大誤差率 `23.74%` だった
- 時間差は平均 `-8.76 分`、平均誤差率 `22.57%`、`p95 = 51.02%`、最大誤差率 `55.58%` だった
- Wilcoxon 符号付順位検定では、距離 `p = 0.000006`、時間 `p = 0.000001` であり、いずれも統計的に一貫した差が確認された
- 効果量は距離 `d = -1.17`、時間 `d = -1.27` であり、いずれも大きい差と判定された
- 実務閾値判定では、距離は平均誤差率と `p95` が閾値をわずかに超過し、時間は平均、`p95`、最大のすべてで閾値を超過した
- 順位一致では、距離の Top1 一致率 `100%`、平均 Spearman 相関 `0.983`、時間の Top1 一致率 `100%`、平均 Spearman 相関 `0.933` を確認した
- この結果から、OSMnx は Google Maps に対して距離・時間を一貫して短めに見積もる傾向があるが、候補順位の整合性は高いと判断した
- 距離については完全一致ではないものの、VRP の経路候補順位を大きく崩すほどの差ではなかった
- 時間については Google Maps の実交通反映値と比べて差が大きく、補正なしにそのまま業務制約へ使うのは危険と判断した

PoC レベルの判断基準

- 距離は「OSM 実道路ネットワーク上の最短経路距離」として利用し、Google Maps と完全一致を求めるのではなく、候補順位を崩さない範囲で許容する
- 社内 PoC の目的関数は、現時点では距離最小を第一候補とし、時間は参考値または補正前提の制約値として扱う
- 時間を最適化対象や厳密な制約条件に使う場合は、地域別または時間帯別の補正係数を別途設計することを前提とする
- OSMnx と Google Maps の比較で、距離の Top1 一致率が高く、順位相関が高い場合は、距離ベースの VRP PoC には十分利用可能とみなす
- 一方で、時間の平均誤差率や `p95` が閾値を超過する場合は、補正なしの travel time をそのまま採用しない

## Step 7. 所要時間と拡張性確認

- 道路属性と速度仮定から所要時間を試算する
- 車種別制約に使えそうな属性の有無を棚卸しする
- 今後の VRP 目的関数候補を整理する

成果物

- 所要時間ロジック確認: `notebooks/001_osm_network_feasibility_validation_plan.ipynb` の `step7-travel-time-logic` セル
- 所要時間深掘り比較: `notebooks/001_osm_network_feasibility_validation_plan.ipynb` の `step7-travel-time-deep-dive` セル
- 属性棚卸し: `notebooks/001_osm_network_feasibility_validation_plan.ipynb` の `step7-attribute-inventory` セル
- エッジ属性要約: `outputs/validation/step7/kanagawa_travel_time_edge_attr_summary.csv`
- 道路種別別所要時間要約: `outputs/validation/step7/kanagawa_travel_time_highway_summary.csv`
- 代表エッジ確認: `outputs/validation/step7/kanagawa_travel_time_sample_edges.csv`
- 速度推定ソース要約: `outputs/validation/step7/kanagawa_travel_time_speed_source_summary.csv`
- 道路種別別速度ソース要約: `outputs/validation/step7/kanagawa_travel_time_highway_source_summary.csv`
- 距離最短 / 時間最短ルート比較: `outputs/validation/step7/kanagawa_travel_time_route_objective_comparison.csv`
- エッジ属性棚卸し: `outputs/validation/step7/kanagawa_attribute_inventory_edges.csv`
- ノード属性棚卸し: `outputs/validation/step7/kanagawa_attribute_inventory_nodes.csv`
- 属性利用性評価: `outputs/validation/step7/kanagawa_attribute_inventory_assessment.csv`

検証結果

- 生の `kanagawa_drive.graphml` には `speed_kph` と `travel_time` は含まれておらず、これらは `OSMnx` の `add_edge_speeds` と `add_edge_travel_times` により付与される派生属性であることを確認した
- `speed_kph` の付与元を確認した結果、`83.40%` が `inferred_or_default`、`16.56%` が `matches_maxspeed`、`0.04%` が `adjusted_from_maxspeed` だった。神奈川県全体の所要時間推定の大半は、明示的な速度制限値ではなく、道路種別ベースの補完速度に依存している
- 道路種別別の平均速度は、`residential` が約 `30 km/h`、`tertiary` が約 `35.7 km/h`、`secondary` が約 `38.9 km/h`、`primary` が約 `41.3 km/h`、`trunk` が約 `46.7 km/h`、`motorway` が約 `73-74 km/h` で、道路階層に応じた静的速度ロジックになっていた
- 距離最短ルートと時間最短ルートを `30 OD` で比較した結果、同一経路だったのは `2/30` 件のみで、`28/30` 件は異なる経路になった。時間最短ルートに切り替えると、平均で `5.93 分` 短縮する一方、平均 `2.88 km` の距離増加が発生した。最大では `15.33 分` の短縮と `12.36 km` の距離増加が確認された
- この結果から、`travel_time` は「距離最短ルートに付随する参考時間」ではなく、重みとして使うとルート構造そのものを大きく変える指標であることを確認した。ただし、その時間は実交通を反映した動的時間ではなく、静的な推定時間である
- 属性棚卸しでは、`highway`、`oneway`、`length` はほぼ全面的に利用可能で、`maxspeed` は一部利用可能、`access`、`lanes`、`width`、`est_width`、`bridge`、`tunnel` は補助的に利用可能だった。ノード側では `x`、`y`、`street_count` は十分に使え、`node.highway` や `junction` は信号機そのものではなく交差点複雑性の proxy として使うのが現実的だった
- 車種別制約や通行可否制約に関しては、`highway`、`access`、`oneway`、`lanes`、`width/est_width`、`bridge`、`tunnel` を組み合わせれば PoC レベルの粗い制約条件は設計可能だが、幅員や一部制限系の欠損が多いため、厳密な実務制約をそのまま再現できる水準ではない
- 以上より、`OSMnx` の `travel_time` は「実交通時間」ではなく「道路種別と速度仮定に基づく静的基準所要時間」として扱うのが適切であり、そのまま動的時間最適化の目的関数へ入れるのは不適切と判断した

PoC レベルの判断基準

- 神奈川県単一エリア、`人数 = 台数`、`1 人が 1 台を担当する配送` を前提とした VRP PoC では、目的関数を `総コスト = 車両固定費 × 台数 + 距離単価 × 総走行距離` として定義する
- 距離は `OSM` 実道路ネットワーク上の最短経路距離として採用し、PoC の主目的関数に使用する。これは `Step 6` で Google Maps と比較した際に、距離の順位一致率が高く、ルート選択の妥当性が相対的に高かったためである
- `travel_time` は補正なしのまま目的関数には採用せず、制約条件または参考値としてのみ扱う。勤務時間上限や配送時間帯制約に組み込む場合も、そのまま実時間と見なさず、補正前提の静的基準時間として扱う
- 時間補正の方法は将来課題として整理し、PoC 段階では `時間帯別係数` や `教師学習による補正` を候補とする。ただし本 Step では補正モデルの実装までは行わず、`OSM travel_time` をそのまま動的時間として採用しないことを判断基準とする
- 属性拡張性の観点では、`highway`、`oneway`、`access`、`lanes`、`maxspeed`、`width/est_width`、`bridge`、`tunnel`、`street_count` 等を用いれば、車種別制約、一方通行制約、速度制限制約、道路幅制約、交差点複雑性を考慮した拡張の余地がある。ただし欠損の多い属性は PoC では補助情報として扱い、厳密制約は今後のデータ補完または外部データ連携を前提とする
- 以上から、社内 PoC としては「距離中心の最適化モデルを先に成立させ、時間は補正付き制約として段階的に導入する」方針を採用する。これにより、最適化モデルの説明可能性と再現性を維持しつつ、後続で時間補正や教師学習へ発展可能な構成とする

## Step 8. Go / No-Go 判定

- 検証結果を合否基準に照らして判定する
- VRP 本体に進むか、テーマの縮小・再設計を行うか判断する

成果物

- Go / No-Go 判定メモ
- PoC 採用構成メモ
- 次フェーズ着手タスク一覧
- 将来課題一覧

検証結果

- 神奈川県全体の道路ネットワークは OSMnx で一括取得でき、保存・再読込も安定して実施できた
- 神奈川県全体の一括取得版を親グラフとして自治体単位に切り出し、再結合した場合は、一括取得版との差分が `0` であり、`weak component = 1` を維持できた
- 自治体ごとに独立取得したグラフを後から単純結合する方式では、ノード数・エッジ数の差分が発生し、`No path` が出る OD が確認されたため、県全体 routing 用の基盤としては不採用と判断した
- `Step 5` の OD 検証では、一括取得版と親グラフ切り出し版で `30 OD` および `132 OD` の全件一致を確認した
- `Step 6` の Google Maps 比較では、距離は相対的に近く順位一致率も高かった一方、所要時間は Google Maps より短く出る傾向が確認された
- `Step 7` の検証では、`travel_time` は道路種別ベースの静的推定値に大きく依存しており、そのまま動的時間最適化の目的関数に使うには不適切と判断した
- 以上より、神奈川県単一エリアを対象とした社内 PoC では、距離中心の最適化を採用する構成が最も妥当である

PoC レベルの判断基準

- 判定: `Go`
- 対象範囲は神奈川県単一エリアとする
- ネットワークの正本は神奈川県全体の一括取得版とする
- 分割運用が必要な場合は、親グラフから自治体単位に切り出す方式のみ採用する
- 自治体ごとの独立取得グラフを後から結合する方式は採用しない
- `人数 = 台数`、`1 人が 1 台を担当する配送` を前提とする
- 目的関数は `総コスト = 車両固定費 × 台数 + 距離単価 × 総走行距離` とする
- 距離は OSM 実道路ネットワーク上の最短経路距離を採用する
- 所要時間は補正前提の静的推定時間として扱い、目的関数には入れず、制約条件または参考値として利用する
- 車種別制約、一方通行、通行可否、速度制限、道路幅などは、OSM 属性を使って PoC レベルの粗い制約として拡張可能とする

次フェーズで行うこと

- `docs/design/` 配下の `.md` を順に埋め、PoC の設計を具体化する
- デポ、配送先、需要量、車両台数上限などの入力条件を整理する
- 距離中心の目的関数と制約条件を設計書に落とし込む
- OR-Tools 等で神奈川県単一エリアの VRP PoC を実装する
- 必要に応じて親グラフ切り出し方式を前提としたデータ更新運用を整理する

将来課題

- 所要時間の精度向上
- 時間帯別係数や教師学習による所要時間補正
- Google Maps など外部動的データを用いた時間モデル改善
- 複数都道府県や広域配送への拡張
- 都道府県間の大距離移送を含むネットワーク設計
- 車種別制約や業務ルールを含む高度制約の追加

---

# 8. 合否判定

## 8.1 Go 判定条件

以下をすべて満たした場合、VRP 本体実装へ進む。

1. 1 都道府県の道路ネットワークを安定取得できる
2. 行政区単位で分割取得できる
3. 分割取得データを結合できる
4. 行政区跨ぎの経路探索が成立する
5. 道のり距離を再現可能な形で算出できる
6. 保存・再利用の運用が成立する

## 8.2 条件付き Go

以下に該当する場合は、スコープを絞って継続する。

- 行政区結合は不安定だが、都道府県一括取得であれば問題なく動く
- 所要時間推定は未完成だが、距離ベース最適化は可能
- GitHub 容量制約はあるが、再生成手順の整備で回避可能

この場合は、初期 PoC を以下のいずれかに縮小する。

- 都道府県一括取得版 VRP
- 距離最小化のみの VRP
- 行政区跨ぎ比較を分析資料として残し、実装は単一グラフで進める

## 8.3 No-Go 判定条件

以下のいずれかに該当する場合は、実道路 VRP を主テーマとする計画を再検討する。

- 都道府県取得自体が安定しない
- 行政区分割取得または結合が継続的に破綻する
- 行政区跨ぎ経路探索が成立しない
- 距離算出結果が実務利用に耐えないほど不自然
- 保存・再利用ができず、再現性を確保できない

---

# 9. 想定スケジュール

本検証に使える期間は、全体 6 か月のうち 1 〜 2 か月を想定する。

## 9.1 4 週間で終える最短計画

### Week 1

- 神奈川県を対象都道府県として確定
- 選定理由の記録
- 前提条件の明文化
- 行政区一覧整理
- 都道府県一括取得
- 保存と再読込確認

### Week 2

- 行政区分割取得
- 保存形式確認
- ノード数、エッジ数、ファイルサイズ記録

### Week 3

- 分割データ結合
- 行政区跨ぎ経路探索
- OD サンプル作成

### Week 4

- 一括取得版との比較
- Google Maps との少数比較
- 所要時間試算
- Go / No-Go 判定

## 9.2 8 週間で進める現実的計画

### Weeks 1-2

- 神奈川県を対象都道府県として確定
- 選定理由と前提条件の整理
- 取得方針決定
- 都道府県一括取得
- 保存、再読込、基本メトリクス確認

### Weeks 3-4

- 行政区分割取得
- 分割データ保存
- 取得ログ整備

### Weeks 5-6

- 分割データ結合
- 境界部確認
- 同一区内、行政区跨ぎの経路探索検証

### Weeks 7-8

- 距離妥当性確認
- 所要時間試算
- 処理性能整理
- Go / No-Go 判定

---

# 10. 想定成果物

- 検証メモ
- 都道府県一括取得スクリプト
- 行政区分割取得スクリプト
- グラフ結合スクリプト
- 経路探索サンプル
- 距離比較表
- Go / No-Go 判定結果

---

# 11. 次アクション

1. 神奈川県を対象都道府県として確定する
2. 神奈川県の選定理由と前提条件を確定する
3. 取得ライブラリと保存形式を確定する
4. 都道府県一括取得の最初の技術検証を実施する
5. 結果をもとに行政区分割取得と結合の検証へ進む
