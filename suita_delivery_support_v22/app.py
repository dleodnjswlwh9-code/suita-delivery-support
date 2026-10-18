from flask import request
from p1_optimizer import P1InputError
from p1_full_constraints import optimize_joint_p1
from excel_reader import read_xlsx_sheets, ExcelReadError, MAX_UPLOAD_BYTES
from flask import Flask, render_template, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import json
import os

app = Flask(__name__)
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
BASE_DIR = Path(__file__).resolve().parent


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
    return {"today": japan_date()}


@app.route("/")
def home():
    return render_template("home.html", active_page="home")


@app.route("/routes")
def routes_page():
    return render_template("routes.html", active_page="routes")


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
            payload.get("foodAvailableKg"),payload.get("waterAvailableKg"),
            payload.get("rho"),payload.get("minDeliveryKg"),
            payload.get("remainingTrips"),payload.get("vehicles"))
    except P1InputError as error:
        return jsonify({"error":str(error)}),400
    if payload.get("compareRho") is True:
        summaries=[]
        for candidate in sorted({0.0001, 0.001, 0.01, float(payload["rho"])}):
            r=result if abs(float(payload["rho"])-candidate)<1e-15 else optimize_joint_p1(
                payload.get("foodRows"),payload.get("waterRows"),
                payload.get("foodAvailableKg"),payload.get("waterAvailableKg"),
                candidate,payload.get("minDeliveryKg"),
                payload.get("remainingTrips"),payload.get("vehicles"))
            record={"rho":candidate,"food":{},"water":{}}
            for label,rows,key in (("food",payload["foodRows"],"allocationsFoodKg"),
                                   ("water",payload["waterRows"],"allocationsWaterKg")):
                rates=[min(1.,(float(row["securedKg"])+float(add))/float(row["demandKg"]))
                       for row,add in zip(rows,r[key])]
                record[label]={"minimumRate":min(rates),
                               "targetMet":sum(rate+1e-8>=float(row["targetRate"])
                                   for rate,row in zip(rates,rows)),
                               "count":len(rates),"allocatedKg":sum(r[key])}
            summaries.append(record)
        result['sensitivity']=summaries
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
