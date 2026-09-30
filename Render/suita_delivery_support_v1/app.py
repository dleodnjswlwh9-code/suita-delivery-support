from flask import Flask, render_template
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

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
    return render_template("plan.html", active_page="plan")

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
