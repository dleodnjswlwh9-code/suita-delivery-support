from flask import request
from kit_planning import clean_input, solve_p1, KitInputError
from p2_kit_optimizer import optimize_p2_kit, HUBS
from google_road_matrix import road_time_matrix, matrix_configuration
from p1_optimizer import P1InputError
from p1_full_constraints import optimize_joint_p1
from p0_optimizer import optimize_p0
from excel_reader import read_xlsx_sheets, ExcelReadError, MAX_UPLOAD_BYTES
from flask import Flask, render_template, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import json
import os
import threading
import time
import uuid

app = Flask(__name__)
P2_JOBS = {}
P2_JOB_LOCK = threading.RLock()

def _google_p2_job(job_id, payload):
    def progress(done,total):
        with P2_JOB_LOCK:
            if job_id in P2_JOBS:
                P2_JOBS[job_id]['progress']=round(100*done/max(1,total))
    try:
        clean=clean_input(payload)
        road_mat,note=road_time_matrix(HUBS+clean['rows'],progress_callback=progress)
        if road_mat is None:
            raise KitInputError('Google道路時間を取得できません：'+note)
        result=optimize_p2_kit(payload,driving_matrix=road_mat,
              matrix_source='google-routes-traffic-aware',matrix_note=note)
        with P2_JOB_LOCK:
            P2_JOBS[job_id].update(status='done',result=result,progress=100)
    except Exception as error:
        app.logger.exception('Google P2 asynchronous computation failed')
        with P2_JOB_LOCK:
            if job_id in P2_JOBS:
                P2_JOBS[job_id].update(status='error',error=str(error)[:400])

@app.route('/api/p2-job/<job_id>')
def p2_job_status(job_id):
    with P2_JOB_LOCK:
        job=P2_JOBS.get(job_id)
        if not job:return jsonify({'error':'計算状態を取得できません。'}),404
        return jsonify({k:v for k,v in job.items() if k!='created_at'})


GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
BASE_DIR = Path(__file__).resolve().parent
# 単一の配分データ形式識別子。配分・配送の各画面で共通利用する。
ALLOCATION_SCHEMA_VERSION = "v45-complete-kit-p1"


def load_emergency_roads_geojson():
    path = BASE_DIR / "data" / "emergency_roads.geojson"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"type": "FeatureCollection", "features": []}


EMERGENCY_ROADS_GEOJSON = load_emergency_roads_geojson()


def japan_date():
    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    return f"{now.year}年{now.month}月{now.day}日（{weekdays[now.weekday()]}）"


@app.context_processor
def inject_common():
    return {"today": japan_date(), "allocation_schema_version": ALLOCATION_SCHEMA_VERSION}


@app.route("/")
def home():
    return render_template("home.html", active_page="home")


@app.route("/routes")
def routes_page():
    return render_template("routes.html", active_page="routes", api_key=GOOGLE_MAPS_API_KEY)


@app.route("/results")
def results_page():
    return render_template("results.html", active_page="results")


@app.route("/allocation")
def allocation():
    # 地域別の公式想定人数はプログラム内蔵。ユーザーのアップロードは避難所台帳だけ。
    regional = json.loads((BASE_DIR / "data" / "regional_population.json").read_text(encoding="utf-8"))
    return render_template("allocation.html", active_page="allocation", api_key=GOOGLE_MAPS_API_KEY,
                           embedded_regions=regional["regions"])


@app.route("/plan")
def plan():
    return render_template("plan.html", active_page="plan", api_key=GOOGLE_MAPS_API_KEY)


@app.route("/api/default-shelters")
def default_shelters():
    path=BASE_DIR / "data" / "allocation_shelters.json"
    return jsonify({"shelters":json.loads(path.read_text(encoding="utf-8"))})

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


@app.route("/api/p0-optimize", methods=["POST"])
def p0_optimize():
    # Previous kg/two-commodity P0 code remains in p0_optimizer.py for later
    # reference, but must not be used with the complete-kit P1/P2 model.
    return jsonify({"error":"P0は後続段階で実装します。現行の人日分方式には未接続です。"}), 501


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
    if request.content_length and request.content_length > 500_000:
        return jsonify({"error": "入力データが大きすぎます。"}), 413
    payload = request.get_json(silent=True)
    try:
        # The paid road matrix is explicitly opt-in, fully budgeted and
        # calculated from validated input, never from user-supplied matrices.
        clean = clean_input(payload)
        travel_mode=payload.get('travelTimeMode','fixed')
        if travel_mode not in ('fixed','google'):
            raise KitInputError('走行時間の計算方式が不正です。')
        if travel_mode=='google':
            config=matrix_configuration(len(clean['rows']))
            if not config['ready']:
                raise KitInputError('Google交通情報モードは利用できません：'+config['reason']+
                                    ' Renderのサーバー用APIキーと有料APIの許可・予算上限を設定してください。')
            coords = HUBS + clean['rows']
            if len(clean['rows'])>40:
                job_id=uuid.uuid4().hex
                with P2_JOB_LOCK:
                    now=time.monotonic()
                    for old in list(P2_JOBS):
                        if now-P2_JOBS[old]['created_at']>3600:P2_JOBS.pop(old,None)
                    P2_JOBS[job_id]={'status':'working','progress':0,'created_at':now}
                threading.Thread(target=_google_p2_job,args=(job_id,payload),daemon=True).start()
                return jsonify({'status':'working','jobId':job_id,'progress':0}),202
            road_mat,road_note=road_time_matrix(coords)
            if road_mat is None:
                raise KitInputError('Google道路時間を取得できません：'+road_note+
                                    ' 設定速度モードへの自動切替は行いません。')
            matrix_source='google-routes-traffic-aware'
        else:
            road_mat=None
            road_note='設定速度20 km/h（マンハッタン距離）'
            matrix_source='manhattan-20kmh'
        result = optimize_p2_kit(payload, driving_matrix=road_mat,
                                 matrix_source=matrix_source,matrix_note=road_note)
    except KitInputError as e:
        return jsonify({"error": str(e),"status":"input_or_feasibility_error"}), 422
    except Exception:
        app.logger.exception('P2 computation failed')
        return jsonify({"error": "P2の計算に失敗しました。"}), 500
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
