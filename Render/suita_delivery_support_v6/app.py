from flask import Flask, render_template
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import json
import os

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

def load_json(name):
    path = BASE_DIR / "data" / name
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

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

@app.route("/plan")
def plan():
    return render_template(
        "plan.html",
        active_page="plan",
        api_key=GOOGLE_MAPS_API_KEY,
        shelters=load_json("shelters.json"),
        hubs=load_json("hubs.json"),
    )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
