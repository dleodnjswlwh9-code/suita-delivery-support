수정판(v2)

변경점
1. 왼쪽 메뉴와 홈 카드의 이모티콘/아이콘 삭제
2. 홈 배경을 더 자연스러운 배경 이미지(svg)로 교체
3. 配送計画の作成 화면 하단에 Google 지도 추가
4. 지도에는 북부/남부 수송거점 + 피난처 샘플 마커 표시

중요
- 실제 Google 지도를 보려면 app.py 에 API 키를 넣거나
  환경변수 GOOGLE_MAPS_API_KEY 를 설정해야 함
- 현재 마커 데이터는 app.py 안의 LOCATIONS 에 임시로 들어 있음
- 나중에 Excel 데이터 읽기로 바꾸면 됨

실행
1. python -m pip install -r requirements.txt
2. python app.py
3. http://127.0.0.1:5000
