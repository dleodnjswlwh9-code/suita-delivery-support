救援物資配送支援システム v24（統合P1配分モデル）

起動方法
  pip install -r requirements.txt
  python app.py
  ブラウザー: http://localhost:5000/allocation

Render 設定（ZIPを展開したフォルダーをGitHubに配置）
  Root Directory: suita_delivery_support_v24
  Build Command: pip install -r requirements.txt
  Start Command: gunicorn app:app
  地図を表示する場合は GOOGLE_MAPS_API_KEY を環境変数に登録する。

画面の操作
  1. 配分計画を開く。避難所データは123か所を自動読込。
     現在の台帳では、備蓄データ未整備として23か所を対象外にし、100か所を計算する。
  2. 食料・飲料水の輸送拠点物資量（kg）を入力する。
  3. 2tトラック台数を入力する（初期値1台）。
  4. 必要なら「詳細設定」で ρ、最小配送量δ、配送回数上限を設定する。
  5. 「配分計画を実行する」を押す。
  6. 食料・飲料水の配分を同時に表示し、総合充足率は両方のうち低い値を使う。

固定条件
  希求水準 80%（全避難所共通）／重み w=1/(1-0.8)=5.00
  2tトラックのみ／食料と飲料水は別々の在庫として管理
  食料必要量1.5kg/人・日、飲料水必要量3.0kg/人・日

研究モデル上の注意
  教授論文 4.2節の上位問題（P1）の「希求水準法」を2物資へ拡張したもの。
  1つの避難所について g_k=max(g_{k,食料},g_{k,飲料水}) とし、
  F1=θ+ρΣ_k g_k を最小化する。θ≧g_k は改善可能な避難所に適用。
  各 g_{k,c}=(0.8-(備蓄量+配分量)/必要量)/0.2。
  希求水準80%は配分上限ではなく、100%まで配分できる。
  同一F1の複数最適解がある場合は、無駄な配分を避けるため配分合計が小さい解を選ぶ。
  P1の車両積載量・訪問下限は必要条件の近似。P0（実装可能性ギャップ）・
  P2（車両別配送経路の最適化）は未実装なので、P1の配分予定量は実配送を保証しない。
  既存の「備蓄量」を初期確保量に利用するため、論文の既配送累積 S^b と意味が異なる。

データ
  data/allocation_shelters.json：ZIPに付属のsample_data/shelters.xlsxから作成。
  data/road_names.json：付属のsample_data/emergency_roads.xlsxから作成。
  data/hubs.json、data/emergency_roads.geojson、data/regional_population.json：付属データ。
  原本を変更するときは同梱JSONファイルを更新する。

計算の検証
  python -m unittest discover -s tests -v
