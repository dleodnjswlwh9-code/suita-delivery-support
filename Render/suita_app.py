from flask import Flask, request, render_template_string
import folium
import json
import urllib.request
import urllib.error
import polyline
import os


# =========================================================
# Flask
# =========================================================

app = Flask(__name__)


# =========================================================
# Google Maps APIキー
# =========================================================

API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")


# =========================================================
# HTML
# =========================================================

HTML = """
<!DOCTYPE html>
<html lang="ja">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>吹田市 交通情報考慮経路検索</title>

<style>

body {
    font-family:
        "Yu Gothic",
        "Meiryo",
        sans-serif;

    margin: 0;
    background: #f5f5f5;
}

.container {
    width: 90%;
    max-width: 1100px;
    margin: 30px auto;
}

h1 {
    text-align: center;
}

.subtitle {
    text-align: center;
    color: #666666;
    margin-bottom: 25px;
}

.panel {
    background: white;
    padding: 25px;
    border-radius: 10px;
    margin-bottom: 20px;
}

.input-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
}

.point-box {
    border: 1px solid #cccccc;
    padding: 15px;
    border-radius: 8px;
}

label {
    display: block;
    margin-top: 10px;
}

input {
    width: 95%;
    padding: 9px;
    font-size: 16px;
}

button {
    display: block;
    margin: 25px auto 0;
    padding: 12px 35px;
    font-size: 17px;
    cursor: pointer;
}

.result {
    font-size: 22px;
    font-weight: bold;
    text-align: center;
    line-height: 1.8;
    margin-bottom: 20px;
}

.note {
    text-align: center;
    font-size: 14px;
    color: #666666;
    margin-top: 8px;
}

.map-container {
    width: 100%;
}

.error {
    color: #c00000;
    background: white;
    padding: 20px;
    text-align: center;
    border-radius: 10px;
}

@media (max-width: 700px) {

    .input-grid {
        grid-template-columns: 1fr;
    }

    .container {
        width: 95%;
    }
}

</style>

</head>


<body>

<div class="container">


<h1>
吹田市 交通情報考慮経路検索
</h1>


<div class="subtitle">
Google Routes APIを用いた現在の交通情報を考慮した経路検索
</div>


<div class="panel">

<form method="POST">


<div class="input-grid">


<div class="point-box">

<h3>出発地点</h3>

<label>緯度</label>

<input
    type="number"
    step="any"
    name="start_lat"
    required
    value="{{ start_lat }}"
>

<label>経度</label>

<input
    type="number"
    step="any"
    name="start_lon"
    required
    value="{{ start_lon }}"
>

</div>


<div class="point-box">

<h3>目的地点</h3>

<label>緯度</label>

<input
    type="number"
    step="any"
    name="end_lat"
    required
    value="{{ end_lat }}"
>

<label>経度</label>

<input
    type="number"
    step="any"
    name="end_lon"
    required
    value="{{ end_lon }}"
>

</div>


</div>


<button type="submit">
交通情報を考慮した経路を計算
</button>


</form>

</div>


{% if distance is not none %}

<div class="panel">

<div class="result">

最小移動時間：{{ travel_time_min }} 分<br>

経路距離：{{ distance }} km

</div>


<div class="note">

現在の交通情報を考慮した自動車経路

</div>


<div class="map-container">

{{ map_html | safe }}

</div>

</div>

{% endif %}


{% if error %}

<div class="error">

{{ error }}

</div>

{% endif %}


</div>

</body>

</html>
"""


# =========================================================
# メイン画面
# =========================================================

@app.route("/", methods=["GET", "POST"])
def index():

    distance = None
    travel_time_min = None
    error = None
    map_html = None

    start_lat = ""
    start_lon = ""
    end_lat = ""
    end_lon = ""


    if request.method == "POST":

        try:

            # =================================================
            # 入力値
            # =================================================

            start_lat = float(
                request.form["start_lat"]
            )

            start_lon = float(
                request.form["start_lon"]
            )

            end_lat = float(
                request.form["end_lat"]
            )

            end_lon = float(
                request.form["end_lon"]
            )


            # =================================================
            # APIキー確認
            # =================================================

            if not API_KEY:

                raise Exception(
                    "Google Maps APIキーが設定されていません。"
                )


            # =================================================
            # Google Routes API
            # =================================================

            url = (
                "https://routes.googleapis.com/"
                "directions/v2:computeRoutes"
            )


            data = {

                "origin": {

                    "location": {

                        "latLng": {

                            "latitude": start_lat,

                            "longitude": start_lon
                        }
                    }
                },


                "destination": {

                    "location": {

                        "latLng": {

                            "latitude": end_lat,

                            "longitude": end_lon
                        }
                    }
                },


                "travelMode": "DRIVE",


                "routingPreference":
                    "TRAFFIC_AWARE_OPTIMAL",


                "computeAlternativeRoutes": False,


                "languageCode": "ja",


                "units": "METRIC"
            }


            headers = {

                "Content-Type":
                    "application/json",


                "X-Goog-Api-Key":
                    API_KEY,


                "X-Goog-FieldMask":
                    "routes.duration,"
                    "routes.distanceMeters,"
                    "routes.polyline.encodedPolyline"
            }


            api_request = urllib.request.Request(

                url,

                data=json.dumps(
                    data
                ).encode("utf-8"),

                headers=headers,

                method="POST"
            )


            # =================================================
            # Googleから結果取得
            # =================================================

            try:

                with urllib.request.urlopen(
                    api_request
                ) as response:

                    result = json.loads(

                        response.read().decode(
                            "utf-8"
                        )
                    )


            except urllib.error.HTTPError as e:

                api_error = e.read().decode(
                    "utf-8"
                )

                raise Exception(
                    f"Google Routes APIエラー：{api_error}"
                )


            # =================================================
            # 経路確認
            # =================================================

            if (
                "routes" not in result
                or len(result["routes"]) == 0
            ):

                raise Exception(
                    "経路を見つけることができませんでした。"
                )


            route = result["routes"][0]


            # =================================================
            # 経路距離
            # =================================================

            distance = round(

                route["distanceMeters"] / 1000,

                1
            )


            # =================================================
            # 移動時間
            # =================================================

            duration_text = route["duration"]


            duration_seconds = float(

                duration_text.replace(
                    "s",
                    ""
                )
            )


            travel_time_min = round(

                duration_seconds / 60,

                1
            )


            # =================================================
            # Google経路線
            # =================================================

            encoded_polyline = (

                route[
                    "polyline"
                ][
                    "encodedPolyline"
                ]
            )


            route_points = polyline.decode(

                encoded_polyline
            )


            # =================================================
            # 地図中心
            # =================================================

            center_lat = (

                start_lat + end_lat

            ) / 2


            center_lon = (

                start_lon + end_lon

            ) / 2


            # =================================================
            # 地図作成
            # =================================================

            m = folium.Map(

                location=[

                    center_lat,

                    center_lon
                ],

                zoom_start=14,

                tiles="OpenStreetMap"
            )


            # =================================================
            # 出発地点
            # =================================================

            folium.Marker(

                [

                    start_lat,

                    start_lon
                ],

                popup="出発地点",

                tooltip="出発地点"

            ).add_to(m)


            # =================================================
            # 目的地点
            # =================================================

            folium.Marker(

                [

                    end_lat,

                    end_lon
                ],

                popup="目的地点",

                tooltip="目的地点"

            ).add_to(m)


            # =================================================
            # 交通情報を考慮した経路
            # =================================================

            folium.PolyLine(

                route_points,

                weight=6,

                tooltip=
                    "交通情報を考慮した経路"

            ).add_to(m)


            # =================================================
            # 経路全体を表示
            # =================================================

            m.fit_bounds(
                route_points
            )


            # =================================================
            # 地図をWebページ内に表示
            # =================================================

            map_html = m._repr_html_()


        except Exception as e:

            error = str(e)


    # =========================================================
    # HTML表示
    # =========================================================

    return render_template_string(

        HTML,

        distance=distance,

        travel_time_min=travel_time_min,

        error=error,

        map_html=map_html,

        start_lat=start_lat,

        start_lon=start_lon,

        end_lat=end_lat,

        end_lon=end_lon
    )


# =========================================================
# ローカル実行
# =========================================================

if __name__ == "__main__":

    port = int(

        os.environ.get(
            "PORT",
            5000
        )
    )


    app.run(

        host="0.0.0.0",

        port=port,

        debug=False
    )