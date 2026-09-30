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


v5 변경사항
- 홈 중앙 배경을 완전한 흰색으로 변경
- 초원/도시 일러스트 제거
- 홈 하단 3개 메뉴 글자 크기 확대 유지
- 북부거점만 표시되는 문제를 진단할 수 있도록 지도 상태표시 개선
- 북부거점은 고정 좌표
- 남부거점 및 피난처 123개는 Google Geocoding API로 위치 취득
- Geocoding API 비활성화 시 화면에 원인 메시지 표시
- 연속 요청 속도를 낮춰 OVER_QUERY_LIMIT 가능성을 줄임

Google Cloud에서 반드시 활성화:
1. Maps JavaScript API
2. Geocoding API


v6 변경사항
- 北部輸送拠点（パナソニックスタジアム吹田）の座標を修正
  緯度: 34.80275
  経度: 135.53815
- 輸送拠点マーカーを少し大きくして見やすく変更


v7 변경사항
- Excel 입력을 3개에서 2개로 정리
  1) 避難所状況表（収容人数 + 避難所備蓄量）
  2) 輸送拠点現況表（北部・南部輸送拠点の物資保有量）
- Excel 파일을 선택해도 Google 지도는 갱신/이동하지 않음
- 지도는 초기 고정 데이터(避難所 + 輸送拠点)만 표시
- Excel은 향후「配送計画を作成する」버튼 실행 시 계산 데이터로 사용 예정
- sample_data 폴더에 이번에 제공받은 2개 Excel 파일 포함
