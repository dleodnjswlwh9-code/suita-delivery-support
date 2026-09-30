import json
import urllib.request
import os
import polyline
import folium


# =========================================================
# Google Maps APIキー
# =========================================================

API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

if not API_KEY:
    print("GOOGLE_MAPS_API_KEYが設定されていません。")
    exit()


# =========================================================
# 出発地点・目的地点の入力
# =========================================================

print("出発地点を入力してください。")

start_lat = float(
    input("出発地点の緯度：")
)

start_lon = float(
    input("出発地点の経度：")
)


print("\n目的地点を入力してください。")

end_lat = float(
    input("目的地点の緯度：")
)

end_lon = float(
    input("目的地点の経度：")
)


# =========================================================
# Google Routes API
# =========================================================

url = "https://routes.googleapis.com/directions/v2:computeRoutes"


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

    # 現在の交通状況を考慮
    "routingPreference": "TRAFFIC_AWARE_OPTIMAL",

    "computeAlternativeRoutes": False,

    "languageCode": "ja",

    "units": "METRIC"
}


headers = {

    "Content-Type": "application/json",

    "X-Goog-Api-Key": API_KEY,

    "X-Goog-FieldMask":
        "routes.duration,"
        "routes.distanceMeters,"
        "routes.polyline.encodedPolyline"
}


request = urllib.request.Request(
    url,
    data=json.dumps(data).encode("utf-8"),
    headers=headers,
    method="POST"
)


# =========================================================
# 経路計算
# =========================================================

try:

    with urllib.request.urlopen(request) as response:

        result = json.loads(
            response.read().decode("utf-8")
        )


    route = result["routes"][0]


    # -----------------------------------------------------
    # 経路距離
    # -----------------------------------------------------

    distance_km = (
        route["distanceMeters"] / 1000
    )


    # -----------------------------------------------------
    # 推定移動時間
    # -----------------------------------------------------

    duration_text = route["duration"]

    duration_seconds = float(
        duration_text.replace("s", "")
    )

    duration_minutes = (
        duration_seconds / 60
    )


    # -----------------------------------------------------
    # Google経路データ
    # -----------------------------------------------------

    encoded_polyline = (
        route["polyline"]["encodedPolyline"]
    )

    route_points = polyline.decode(
        encoded_polyline
    )


    # =====================================================
    # 計算結果
    # =====================================================

    print("\n==============================")

    print("交通情報を考慮した経路計算結果")

    print("==============================")

    print(
        f"経路距離：{distance_km:.1f} km"
    )

    print(
        f"推定移動時間：{duration_minutes:.1f} 分"
    )


    # =====================================================
    # 地図作成
    # =====================================================

    map_center_lat = (
        start_lat + end_lat
    ) / 2

    map_center_lon = (
        start_lon + end_lon
    ) / 2


    m = folium.Map(

        location=[
            map_center_lat,
            map_center_lon
        ],

        zoom_start=14,

        tiles="OpenStreetMap"
    )


    # -----------------------------------------------------
    # 出発地点
    # -----------------------------------------------------

    folium.Marker(

        [
            start_lat,
            start_lon
        ],

        popup="出発地点",

        tooltip="出発地点"

    ).add_to(m)


    # -----------------------------------------------------
    # 目的地点
    # -----------------------------------------------------

    folium.Marker(

        [
            end_lat,
            end_lon
        ],

        popup="目的地点",

        tooltip="目的地点"

    ).add_to(m)


    # -----------------------------------------------------
    # 交通情報を考慮した経路
    # -----------------------------------------------------

    folium.PolyLine(

        route_points,

        weight=6,

        tooltip="交通情報を考慮した経路"

    ).add_to(m)


    # -----------------------------------------------------
    # 経路全体を表示
    # -----------------------------------------------------

    m.fit_bounds(
        route_points
    )


    # =====================================================
    # 地図保存
    # =====================================================

    output_file = (
        r"C:\Render\google_traffic_route.html"
    )

    m.save(
        output_file
    )


    print("\n地図を保存しました。")

    print(
        f"保存先：{output_file}"
    )


# =========================================================
# エラー処理
# =========================================================

except Exception as e:

    print("\nエラーが発生しました。")

    print(e)