Suita Delivery Support v53.3 変更点 (2026-10-27)

1. ホームの画像バナー上の白い重複タイトル・日付を削除。既存の画像をそのまま表示し、システム名・日本の日付は上部ヘッダーに表示。
2. 左側メニューは「ホーム → データ → 配分計画 → 配送計画 → 物資輸送経路 → 結果の表示」。
3. データ画面からExcel3ファイルのプレビューとログイン不要のダウンロードを提供。
   - 避難所データ.xlsx
   - 緊急交通路データ.xlsx
   - 吹田市救援物資配分用基礎データ.xlsx
4. 「操作の流れ」を削除。
5. 配分結果「1日分セット供給可能率」を「総合充足率」に修正。
   計算式は食料・飲料水の充足率の最小値のまま変更していません。
6. データ画面の灰色の説明文を全削除し、ファイル名と操作ボタンを大きくしました。その他の注釈は必要な箇所に改行を加えました。
7. P0/P1/P2の計算ロジックと既存データ形式は変更していません。

GitHub: リポジトリ直下に README_UPLOAD.txt / requirements.txt / suita_delivery_support フォルダが来るようにアップロードしてください。
Render (Root Directoryが未設定の場合):
 Build Command: pip install -r requirements.txt
 Start Command: gunicorn --chdir suita_delivery_support app:app --bind 0.0.0.0:$PORT

注意: 公開データはインターネット上の誰でも取得できます。公開前に資料の再配布権限を確認してください。

8. データの表示名と実際のダウンロード名から (10)、(2)、(1) の番号を削除。Excelの内容は変更していません。
9. Googleマップの「正しく読み込まれませんでした」は外部Google Maps JavaScript APIの認証・課金・リファラー・API有効化などの問題です。
   Google Cloud ConsoleでMaps JavaScript APIと課金、ブラウザー用キーのHTTPリファラー https://suita-delivery-support.onrender.com/* を確認してください。
   ブラウザーConsoleに出る「Google Maps JavaScript API error: ...」が原因特定の手がかりです。
   このZIPにはAPIキーを含めていません。APIキーそのものをGitHubへアップロードしないでください。
