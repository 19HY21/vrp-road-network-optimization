# Google Maps Comparison Scripts

`calc_google_maps_from_lat_lon.gs` は、Google Apps Script でスプレッドシート上の緯度経度から Google Maps の距離と所要時間を取得する補助スクリプトです。

想定列:

- E列: `from_latitude`
- F列: `from_longitude`
- J列: `to_latitude`
- K列: `to_longitude`
- N列: `google_maps_distance_km`
- O列: `google_maps_time_min`
- P列: `google_maps_checked_at`
- Q列: `google_maps_status`

主用途:

- `data/raw/route_validation/` にある比較テンプレート CSV をスプレッドシートへ取り込み
- Google Maps の距離・時間を埋める
- CSV としてエクスポートして VS Code 側へ戻す
