v44: Google 실제 도로 P2 전체경로·7호차 우회 진단 개선

1) ZIP을 풀어 GitHub 저장소에 업로드합니다. suita_delivery_support 폴더를 유지하세요.
2) Render Root Directory = (빈칸) 설정 시:
   Build Command: pip install -r requirements.txt
   Start Command: gunicorn --chdir suita_delivery_support app:app --bind 0.0.0.0:$PORT
   Render Root Directory = suita_delivery_support 설정 시:
   Build Command: pip install -r requirements.txt
   Start Command: gunicorn app:app --bind 0.0.0.0:$PORT
3) Render GOOGLE_MAPS_API_KEY를 유지하고 Google Cloud에서 Maps JavaScript API, Routes API 및 결제 설정을 활성화하세요.
4) P1 배분계획 실행 -> P2 물자수송경로 계산 -> 第1回 7号車 선택 -> 全経路を表示.
   Google 방문순 재정렬 및 高速・有料道路を避ける 모드를 비교해 보세요.
5) 자세한 수정 사항 및 한계: suita_delivery_support/README_v44_配送経路改良_KR.md

※ 7호차의 실제 도로 우회는 Google 서버 실호출/사용자의 세션 데이터가 없어 수정 전후 실측 검증하지 못했습니다.
※ Google waypoint 최적화 및 실시간 교통 API 이용량에 따라 비용이 발생할 수 있습니다.
