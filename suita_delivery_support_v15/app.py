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


@app.route("/allocation")
def allocation():
    return render_template("allocation.html", active_page="allocation")


@app.route("/plan")
def plan():
    return render_template("plan.html", active_page="plan", api_key=GOOGLE_MAPS_API_KEY)


@app.route("/api/emergency-roads")
def emergency_roads():
    return jsonify(EMERGENCY_ROADS_GEOJSON)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
