吹田市 救援物資配送支援システム v3

이번 데이터:
- 避難所: 123施設
- 輸送拠点: 2施設

지도:
- Google Maps JavaScript API 필요
- Excel에 위도/경도가 없기 때문에 Google Geocoding API도 필요
- 첫 로드 때 피난처명을 좌표로 변환
- 변환 좌표는 브라우저 localStorage에 저장하여 다음 로드부터 재사용

실행:
1) PowerShell
   cd "C:\Users\이대원\Render\suita_delivery_support_v3"

2) API키 설정
   $env:GOOGLE_MAPS_API_KEY="새 API 키"

3) 실행
   & "C:\Users\이대원\AppData\Local\Python\pythoncore-3.14-64\python.exe" app.py

4) 브라우저
   http://127.0.0.1:5000/plan

주의:
- Google Cloud에서 Maps JavaScript API와 Geocoding API를 둘 다 활성화해야 함.


v4 변경사항
- 홈 배경은 v3 그대로 유지
- Google 지도 표시 언어를 일본어(language=ja, region=JP)로 고정
- 홈 화면 하단 3개 메뉴 글자 크기를 확대
- 전체 UI 폰트를 Yu Gothic / Meiryo 계열로 통일
