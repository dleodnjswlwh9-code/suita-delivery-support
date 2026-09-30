from flask import Flask, render_template
from datetime import datetime
from zoneinfo import ZoneInfo
import os

app = Flask(__name__)

# ここにGoogle Maps APIキーを直接書いてもよい
# 例: GOOGLE_MAPS_API_KEY = "AIza...."
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

# 仮の表示用データ
# 後でExcel読込に差し替え可能
LOCATIONS = [
    {"name": "北部輸送拠点", "type": "hub", "lat": 34.77013251, "lng": 135.5385663},
    {"name": "南部輸送拠点", "type": "hub", "lat": 34.7440, "lng": 135.5030},
    {"name": "避難所A", "type": "shelter", "lat": 34.7670, "lng": 135.5260},
    {"name": "避難所B", "type": "shelter", "lat": 34.7580, "lng": 135.5150},
    {"name": "避難所C", "type": "shelter", "lat": 34.7480, "lng": 135.5035},
    {"name": "避難所D", "type": "shelter", "lat": 34.7415, "lng": 135.4940},
]

def japan_date():
    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    return f"{now.year}年{now.month}月{now.day}日（{weekdays[now.weekday()]}）"

@app.context_processor
def inject_common():
    return {
        "today": japan_date(),
    }

@app.route("/")
def home():
    return render_template("home.html", active_page="home")

@app.route("/plan")
def plan():
    return render_template(
        "plan.html",
        active_page="plan",
        google_maps_api_key=GOOGLE_MAPS_API_KEY,
        locations=LOCATIONS,
    )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
