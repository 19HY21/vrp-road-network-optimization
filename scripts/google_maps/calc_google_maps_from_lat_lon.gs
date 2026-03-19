function calcGoogleMaps_FromLatLon() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const lastRow = sheet.getLastRow();

  Logger.log("処理開始");

  for (let i = 2; i <= lastRow; i++) {
    try {
      // ===== 入力 =====
      const from_lat = sheet.getRange(i, 5).getValue(); // E
      const from_lon = sheet.getRange(i, 6).getValue(); // F
      const to_lat = sheet.getRange(i, 10).getValue(); // J
      const to_lon = sheet.getRange(i, 11).getValue(); // K

      // 空チェック
      if (!from_lat || !from_lon || !to_lat || !to_lon) {
        sheet.getRange(i, 17).setValue("座標欠損"); // Q列
        continue;
      }

      // ===== 座標フォーマット =====
      const origin = `${from_lat},${from_lon}`;
      const destination = `${to_lat},${to_lon}`;

      // ===== Directions取得 =====
      const directions = Maps.newDirectionFinder()
        .setOrigin(origin)
        .setDestination(destination)
        .setMode(Maps.DirectionFinder.Mode.DRIVING)
        .getDirections();

      // ===== エラーハンドリング =====
      if (!directions.routes || directions.routes.length === 0) {
        sheet.getRange(i, 17).setValue("ルート取得失敗");
        continue;
      }

      const leg = directions.routes[0].legs[0];

      // ===== 距離・時間 =====
      const distance_km = leg.distance.value / 1000; // m -> km
      const time_min = leg.duration.value / 60; // sec -> min

      // ===== 書き込み =====
      sheet.getRange(i, 14).setValue(distance_km); // N列
      sheet.getRange(i, 15).setValue(time_min); // O列
      sheet.getRange(i, 16).setValue(new Date()); // P列
      sheet.getRange(i, 17).setValue("OK"); // Q列

      // ===== 進捗ログ =====
      if (i % 5 === 0) {
        Logger.log(`進捗: ${i}/${lastRow}`);
      }

      // ===== レート制御 =====
      Utilities.sleep(200);
    } catch (e) {
      sheet.getRange(i, 17).setValue("ERROR: " + e);
      Logger.log(`Row ${i} Error: ${e}`);
    }
  }

  Logger.log("処理終了");
}
