from flask import request
from kit_planning import clean_input, solve_p1, KitInputError
from p2_kit_optimizer import optimize_p2_kit, HUBS
from google_road_matrix import road_time_matrix, matrix_configuration
from nearby_shelters import NearbyError
from nearby_straight import straight_pairs, road_representative, centroid_representative
from p1_optimizer import P1InputError
from p1_full_constraints import optimize_joint_p1
from p0_kit_optimizer import optimize_p0_kits, p0_problem_signature
from rolling_actual import confirm_round, ActualDeliveryError
from excel_reader import read_xlsx_sheets, ExcelReadError, MAX_UPLOAD_BYTES
from flask import Flask, render_template, jsonify, send_file, abort
from datetime import datetime, timezone, timedelta
from pathlib import Path
from functools import lru_cache
import json
import os
import threading
import time
import uuid

app = Flask(__name__)
# 100施設のP0は計算負荷が高い。計算終了まで送信要求を待たせず、通信の時間切れを防ぐ。
P0_JOBS = {}
P0_JOB_LOCK = threading.RLock()
# P2では事前に検証済みの同一P0結果だけを再利用する。単一のGunicornプロセス内の保存情報は再起動時に消える。
P0_RESULT_CACHE = {}

def _remember_p0_result(answer):
    if not isinstance(answer,dict) or not answer.get('feasible') or not answer.get('p0InputSignature'):
        return
    with P0_JOB_LOCK:
        now=time.monotonic()
        for key,(created,_) in list(P0_RESULT_CACHE.items()):
            if now-created>1800:P0_RESULT_CACHE.pop(key,None)
        P0_RESULT_CACHE[answer['p0InputSignature']]=(now,answer)
        while len(P0_RESULT_CACHE)>6:
            oldest=min(P0_RESULT_CACHE,key=lambda k:P0_RESULT_CACHE[k][0])
            P0_RESULT_CACHE.pop(oldest,None)

def _cached_p0_for(payload):
    signature=p0_problem_signature(payload)
    with P0_JOB_LOCK:
        entry=P0_RESULT_CACHE.get(signature)
        if entry and time.monotonic()-entry[0]<=1800:return entry[1]
    return None


def _p0_worker(job_id, payload):
    try:
        answer = optimize_p0_kits(payload)
        _remember_p0_result(answer)
        with P0_JOB_LOCK:
            if job_id in P0_JOBS:
                P0_JOBS[job_id].update(status='done', result=answer)
    except Exception as exc:
        app.logger.exception('P0の計算処理に失敗しました')
        with P0_JOB_LOCK:
            if job_id in P0_JOBS:
                P0_JOBS[job_id].update(status='error', error=('P0計算中にサーバーエラーが発生しました。Renderログを確認してください。'))

@app.route('/api/p0-job', methods=['POST'])
def p0_job_start():
    if request.content_length and request.content_length > 250_000:
        return jsonify({'error':'P0の入力データが大きすぎます。'}), 413
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify({'error':'P0の入力データを確認してください。'}),400
    try:
        clean_input(payload)  # 処理を開始する前に入力値を検証し、不正な場合は直ちに終了する。
    except KitInputError as exc:
        return jsonify({'error':str(exc)}),422
    now=time.monotonic()
    with P0_JOB_LOCK:
        for jid in list(P0_JOBS):
            if now-P0_JOBS[jid]['created_at']>1800:P0_JOBS.pop(jid,None)
        if sum(j['status']=='working' for j in P0_JOBS.values())>=1:
            return jsonify({'error':'別のP0計算を実行中です。完了後に再計算してください。'}),429
        job_id=uuid.uuid4().hex
        P0_JOBS[job_id]={'status':'working','created_at':now}
    threading.Thread(target=_p0_worker,args=(job_id,payload),daemon=True).start()
    return jsonify({'status':'working','jobId':job_id}),202

@app.route('/api/p0-job/<job_id>', methods=['GET'])
def p0_job_status(job_id):
    with P0_JOB_LOCK:
        job=P0_JOBS.get(job_id)
        if not job:return jsonify({'error':'計算結果を取得できません。サーバーの再起動を確認してください。'}),404
        return jsonify({k:v for k,v in job.items() if k!='created_at'})

P2_JOBS = {}
P2_JOB_LOCK = threading.RLock()

def _p2_worker(job_id, payload):
    """P2内部のP0計算は長時間かかるため、通常の送信要求を待機させない。
    
    固定速度とGoogle交通情報の両方をバックグラウンド処理とする。
    処理状態は単一のGunicornプロセス内に保持する。"""
    def progress(percent):
        with P2_JOB_LOCK:
            if job_id in P2_JOBS:
                P2_JOBS[job_id]['progress'] = int(percent)
    try:
        clean = clean_input(payload)
        cached_p0=_cached_p0_for(payload)
        if payload.get('travelTimeMode', 'fixed') == 'google':
            progress(5)
            def matrix_progress(done, total):
                progress(5 + round(50 * done / max(1, total)))
            # 交通時間行列はP2の代表点座標から作成する。P0の公平性評価には元の避難所座標を保持する。
            point_rows=[dict(row) for row in clean['rows']]
            points=payload.get('deliveryPoints')
            if points is not None:
                if not isinstance(points,list) or len(points)!=len(point_rows):
                    raise KitInputError('施設別の配送代表点データが不正です。')
                for row,dp in zip(point_rows,points):
                    if not isinstance(dp,dict):raise KitInputError('配送代表点データが不正です。')
                    try:latitude=float(dp['lat']);longitude=float(dp['lng'])
                    except (TypeError,ValueError,KeyError):raise KitInputError('配送代表点の座標が不正です。')
                    if not (33<latitude<36 and 134<longitude<138):raise KitInputError('配送代表点は有効な緯度経度で設定してください。')
                    row.update(lat=latitude,lng=longitude)
            nodes=HUBS + point_rows
            unique=[];lookup=[];known={}
            for node in nodes:
                key=(round(float(node['lat']),7),round(float(node['lng']),7))
                if key not in known:
                    known[key]=len(unique);unique.append(node)
                lookup.append(known[key])
            small_mat, note = road_time_matrix(unique, progress_callback=matrix_progress)
            road_mat=[[small_mat[lookup[i]][lookup[j]] for j in range(len(nodes))]
                      for i in range(len(nodes))] if small_mat is not None else None
            if road_mat is None:
                raise KitInputError('Google道路時間を取得できません：' + note)
            progress(60)
            result = optimize_p2_kit(payload, driving_matrix=road_mat,
                         matrix_source='google-routes-traffic-aware', matrix_note=note,
                         p0_result=cached_p0)
        else:
            progress(10)
            result = optimize_p2_kit(payload, driving_matrix=None,
                        matrix_source='manhattan-20kmh',
                        matrix_note='設定速度20 km/h（マンハッタン距離）',
                        p0_result=cached_p0)
        _remember_p0_result(result.get('p0'))
        with P2_JOB_LOCK:
            if job_id in P2_JOBS:
                P2_JOBS[job_id].update(status='done', result=result, progress=100)
    except KitInputError as error:
        with P2_JOB_LOCK:
            if job_id in P2_JOBS:
                P2_JOBS[job_id].update(status='error', error=str(error)[:500])
    except Exception:
        app.logger.exception('P2の計算処理に失敗しました（処理番号：%s）', job_id)
        with P2_JOB_LOCK:
            if job_id in P2_JOBS:
                P2_JOBS[job_id].update(status='error',
                      error='P2の計算中に内部エラーが発生しました。Renderログの traceback を確認してください。')

@app.route('/api/p2-job/<job_id>')
def p2_job_status(job_id):
    with P2_JOB_LOCK:
        job=P2_JOBS.get(job_id)
        if not job:return jsonify({'error':'計算状態を取得できません。'}),404
        return jsonify({k:v for k,v in job.items() if k!='created_at'})


GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
BASE_DIR = Path(__file__).resolve().parent
# 単一の配分データ形式識別子。配分・配送の各画面で共通利用する。
ALLOCATION_SCHEMA_VERSION = "v68-fleet-2t4t-shelters-20261105"


def load_emergency_roads_geojson():
    path = BASE_DIR / "data" / "emergency_roads.geojson"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"type": "FeatureCollection", "features": []}


EMERGENCY_ROADS_GEOJSON = load_emergency_roads_geojson()


def japan_date():
    now = datetime.now(timezone(timedelta(hours=9)))
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    return f"{now.year}年{now.month}月{now.day}日（{weekdays[now.weekday()]}）"


@app.context_processor
def inject_common():
    return {"today": japan_date(), "allocation_schema_version": ALLOCATION_SCHEMA_VERSION}


@app.route("/")
def home():
    return render_template("home.html", active_page="home")


# 公開用の2ファイルは計算用データから独立して管理する。
# URLのファイル名はホワイトリストで制限し、任意のパスを参照させない。
PUBLIC_DATA_FILES = {
    'shelters': {
        'filename': '避難所データ.xlsx',
        'title': '避難所データ',
        'description': '避難所の名称・位置・収容人数・備蓄量をまとめたデータです。',
    },
    'roads': {
        'filename': '緊急交通路データ.xlsx',
        'title': '緊急交通路データ',
        'description': '災害時の物資輸送に関係する緊急交通路の区分・路線名です。',
    },
}


def public_file_path(key):
    item = PUBLIC_DATA_FILES.get(key)
    if item is None:
        abort(404)
    path = BASE_DIR / 'public_data' / item['filename']
    if not path.is_file():
        abort(404)
    return path


@app.route('/data')
def public_data_page():
    return render_template('data.html', active_page='data', datasets=PUBLIC_DATA_FILES)


@app.route('/data/<key>/download')
def public_data_download(key):
    path = public_file_path(key)
    return send_file(path, as_attachment=True, download_name=path.name,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@lru_cache(maxsize=2)
def cached_public_sheets(key):
    return read_xlsx_sheets(public_file_path(key).read_bytes())


@app.route('/api/public-data/<key>')
def public_data_preview(key):
    public_file_path(key)
    try:
        sheets = cached_public_sheets(key)
    except ExcelReadError:
        app.logger.exception('公開データのプレビューに失敗しました')
        return jsonify({'error': 'データを表示できません。Excelファイルをダウンロードしてご確認ください。'}), 500
    return jsonify({'sheets': sheets})


@app.route("/routes")
def routes_page():
    return render_template("routes.html", active_page="routes", api_key=GOOGLE_MAPS_API_KEY)


@app.route("/results")
def results_page():
    return render_template("results.html", active_page="results")


@app.route("/allocation")
def allocation():
    # 地域別想定人数・避難所台帳はプログラム内蔵の固定データ（利用者による変更なし）。
    regional = json.loads((BASE_DIR / "data" / "regional_population.json").read_text(encoding="utf-8"))
    # 画面表示時には同梱の正式な123施設データを読み込む。ブラウザからの差し替えは禁止し、配送実績による備蓄更新だけを引き継ぐ。
    default_roster = json.loads((BASE_DIR / "data" / "allocation_shelters.json").read_text(encoding="utf-8"))
    return render_template("allocation.html", active_page="allocation", api_key=GOOGLE_MAPS_API_KEY,
                           embedded_regions=regional["regions"], embedded_default_shelters=default_roster)


@app.route("/p0")
def p0_page():
    return render_template("p0.html", active_page="p0")

@app.route("/plan")
def plan():
    return render_template("plan.html", active_page="plan", api_key=GOOGLE_MAPS_API_KEY)


@app.route('/api/nearby-straight-pairs',methods=['POST'])
def nearby_straight_pairs():
    if request.content_length and request.content_length>120_000:return jsonify({'error':'送信データが大きすぎます。'}),413
    payload=request.get_json(silent=True) or {}
    try:return jsonify(straight_pairs(payload.get('shelters'),payload.get('maxDistanceMeters',300)))
    except NearbyError as e:return jsonify({'error':str(e)}),422

@app.route('/api/map-diagnostics', methods=['GET'])
def map_diagnostics():
    # APIキーの全部または一部を応答に含めない。
    return jsonify({
      'appVersion':'v73-p2-async-units',
      'googleMapsJavaScriptKeyConfigured':bool(GOOGLE_MAPS_API_KEY.strip()),
      'mapsJavaScriptEnvironmentVariable':'GOOGLE_MAPS_API_KEY',
      'googleRoadsServerKeyConfigured':bool((os.environ.get('GOOGLE_ROADS_SERVER_API_KEY') or '').strip()),
      'mapsAuthenticationValidated':False,
      'requiredBrowserApi':'Maps JavaScript API',
      'expectedWebsiteOrigin':request.host_url.rstrip('/'),
      'configurationChecklist':['Google Cloudの同じプロジェクトで請求先を有効化','Maps JavaScript APIを有効化','GOOGLE_MAPS_API_KEYがHTTPリファラー制限のブラウザ用キーであることを確認','現在のRenderサイトを許可リファラーに登録'],
      'note':'Googleマップの認証・課金・URL制限は、ブラウザの開発者コンソールとGoogle Cloudで確認してください。'
    })

@app.route('/api/roads-diagnostics',methods=['GET'])
def roads_diagnostics():
    # 診断結果にはAPIキーを表示しない。Google Cloudのプロジェクトは要求時の応答からのみ確認できる。
    roads=bool(str(os.environ.get('GOOGLE_ROADS_SERVER_API_KEY') or '').strip())
    return jsonify({
        'appVersion':'v73-p2-async-units',
        'roadsKeyConfigured':roads,
        'keySource':'GOOGLE_ROADS_SERVER_API_KEY' if roads else 'NONE',
        'automaticRoutesKeyFallback':False,
        'renderCommit':str(os.environ.get('RENDER_GIT_COMMIT',''))[:8] or None,
        'message':('Roads API 呼び出しは GOOGLE_ROADS_SERVER_API_KEY のみを使用します。'
                   if roads else 'Renderの環境変数に GOOGLE_ROADS_SERVER_API_KEY を設定してください。'),
    })

@app.route('/api/nearby-representative',methods=['POST'])
def nearby_representative():
    if request.content_length and request.content_length>150_000:return jsonify({'error':'送信データが大きすぎます。'}),413
    payload=request.get_json(silent=True) or {}
    try:return jsonify(centroid_representative(payload.get('members',[]),payload.get('shelters'),payload.get('pairs',[])))
    except NearbyError as e:return jsonify({'error':str(e)}),422
    except Exception:
        app.logger.exception('重心代表点の計算に失敗しました')
        return jsonify({'error':'代表点を計算できませんでした。'}),500

@app.route("/api/default-shelters")
def default_shelters():
    path=BASE_DIR / "data" / "allocation_shelters.json"
    return jsonify({"version":"suita-shelters-20261105-v68","shelters":json.loads(path.read_text(encoding="utf-8"))})

@app.route("/api/default-hubs")
def default_hubs():
    hubs=json.loads((BASE_DIR / "data" / "hubs.json").read_text(encoding="utf-8"))
    for hub in hubs:
        if hub.get('lat') is None or hub.get('lng') is None:
            hub['lat']=34.7702
            hub['lng']=135.5361
    return jsonify({"hubs":hubs})

@app.route("/api/default-roads")
def default_roads():
    path=BASE_DIR / "data" / "road_names.json"
    return jsonify({"roads":json.loads(path.read_text(encoding="utf-8"))})

@app.route("/api/emergency-roads")
def emergency_roads():
    return jsonify(EMERGENCY_ROADS_GEOJSON)


@app.route("/api/parse-excel", methods=["POST"])
def parse_excel():
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"error": "Excelファイルを選択してください。"}), 400
    if not file.filename.lower().endswith(".xlsx"):
        return jsonify({"error": ".xlsx形式を選択してください。"}), 400
    try:
        sheets = read_xlsx_sheets(file.read(MAX_UPLOAD_BYTES + 1))
    except ExcelReadError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"sheets": sheets})


@app.route("/api/p1-optimize-joint", methods=["POST"])
def p1_optimize_joint():
    if request.content_length and request.content_length > 1_000_000:
        return jsonify({"error":"P1の入力データが大きすぎます。"}), 413
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify({"error":"P1の入力形式が不正です。"}),400
    try:
        result=optimize_joint_p1(
            payload.get("foodRows"),payload.get("waterRows"),
            payload.get("totalAvailableKg"),
            payload.get("rho"),payload.get("minDeliveryKg"),
            payload.get("remainingTrips"),payload.get("vehicles"),payload.get("targetRate"))
    except P1InputError as error:
        return jsonify({"error":str(error)}),400
    return jsonify(result)


@app.errorhandler(500)
def handle_internal_error(exc):
    if request.path.startswith('/api/'):
        app.logger.exception('APIの内部処理でエラーが発生しました：%s',request.path)
        return jsonify({'error':'サーバー内部エラー。Renderログを確認してください。'}),500
    return exc

@app.route("/api/p0-kits", methods=["POST"])
@app.route("/api/p0-optimize", methods=["POST"])
def p0_optimize():
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify({'error':'P0の入力形式が不正です。'}),400
    try:
        return jsonify(optimize_p0_kits(payload))
    except KitInputError as error:
        return jsonify({'error':str(error)}),422


@app.route('/api/rolling-confirm', methods=['POST'])
def rolling_confirm():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify({'error':'実績データを確認してください。'}),400
    try:
        return jsonify(confirm_round(data.get('plan'),data.get('round'),data.get('actualKits'),data.get('actualMinutes')))
    except (ActualDeliveryError,TypeError,ValueError) as exc:
        return jsonify({'error':str(exc)}),422


@app.route("/api/p1-kits", methods=["POST"])
def p1_kits():
    payload = request.get_json(silent=True)
    try:
        c = clean_input(payload)
        p1 = solve_p1(c)
    except KitInputError as e:
        return jsonify({"error": str(e)}), 422
    return jsonify({"allocations": p1['allocations'], "objectiveF1":p1['f1'],
                    "theta":p1['theta'],"activeCount":p1['active'],
                    "mandatoryCount":p1['mandatory'],"model":"single_complete_kit_p1"})


@app.route("/api/p2-kits", methods=["POST"])
def p2_kits():
    """計算開始を素早く受け付け、通信中の502エラーを避ける。
    
    固定速度とGoogle交通情報のいずれも受付後に結果を照会する。
    Renderのメモリ枯渇を避けるため、同時実行を1件に制限する。"""
    if request.content_length and request.content_length > 500_000:
        return jsonify({'error':'入力データが大きすぎます。'}),413
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify({'error':'配送入力データを確認してください。'}),400
    try:
        clean=clean_input(payload)
        if payload.get('roadMode','all')!='all':
            raise KitInputError('緊急交通路優先は現在未実装です。')
        mode=payload.get('travelTimeMode','fixed')
        if mode not in ('fixed','google'):
            raise KitInputError('走行時間の計算方式が不正です。')
        if mode=='google':
            config=matrix_configuration(len(clean['rows']))
            if not config['ready']:
                raise KitInputError('Google交通情報モードは利用できません：'+config['reason'])
    except KitInputError as e:
        return jsonify({'error':str(e),'status':'input_or_feasibility_error'}),422
    with P0_JOB_LOCK:
        if any(j['status']=='working' for j in P0_JOBS.values()):
            return jsonify({'error':'P0計算中です。P0の完了後に配送経路を計算してください。'}),429
    now=time.monotonic()
    with P2_JOB_LOCK:
        for jid in list(P2_JOBS):
            if now-P2_JOBS[jid]['created_at']>3600:
                P2_JOBS.pop(jid,None)
        if any(j['status']=='working' for j in P2_JOBS.values()):
            return jsonify({'error':'別のP2計算が進行中です。完了後に再計算してください。'}),429
        job_id=uuid.uuid4().hex
        P2_JOBS[job_id]={'status':'working','progress':0,'created_at':now}
    threading.Thread(target=_p2_worker,args=(job_id,payload),daemon=True).start()
    return jsonify({'status':'working','jobId':job_id,'progress':0}),202

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
