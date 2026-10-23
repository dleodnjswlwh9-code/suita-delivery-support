# v42 – P2 Google 실제 도로 경로 표시

## 변경 사항

- v41의 피난소 초록색 고정 크기 6px 충족률 마커를 유지했습니다.
- 기존 P2 Google 지도는 **여러 차량을 동시에 표시할 때 거점/피난소 좌표를 직선 점선으로 연결**했습니다. v42에서는 이를 제거했습니다.
- **모든 표시 대상 차량**에 대해 Google Maps JavaScript Routes Library `Route.computeRoutes` (`DRIVING`)로 실제 도로 형상을 요청하고, `createPolylines`로 결과를 표시합니다.
- 복수 차량/배송 회차 필터, 차량 카드 선택, 거점으로 되돌아오는 순서가 유지됩니다.
- 피난소 25개 초과 방문 시에는 Google Routes API의 경유지 제한에 맞게 경로를 분할하여 연결합니다. 임의 직선 연결은 사용하지 않습니다.
- 경로 요청은 순차적으로 처리하고 동일 화면 안에서 재사용되는 결과를 일시적으로 캐시합니다. Google API는 요청량에 따라 과금될 수 있습니다.
- 경로 요청 실패 시 Google 지도에 직선을 대신 그리지 않고 오류를 표시합니다. API 키가 없는 대체 SVG의 선은 '개략도'라고 명시합니다.

## 실제 도로 경로 표시를 위한 설정

1. Google Cloud Console 프로젝트에서 **Maps JavaScript API**와 **Routes API**를 사용 설정하고 결제를 활성화합니다.
2. Render > Service > Environment에 `GOOGLE_MAPS_API_KEY` 환경변수를 등록합니다.
3. Google Cloud의 API 키에서 웹사이트 도메인(예: `https://your-service.onrender.com/*`)을 **HTTP 리퍼러**에 허용하고 API 제한이 Maps JavaScript API와 Routes API의 호출을 막지 않는지 확인합니다.
4. 서비스를 재배포하고 페이지를 `Ctrl+F5`로 새로고침합니다.
5. 배분계획(P1)→물자수송경로(P2) 계산 후 지도 위의 `Google 道路経路 n/n件`를 확인합니다.

기존 배포/시작 명령은 `README_DEPLOY_KR.txt`를 따릅니다.

## 중요한 연구상 구분

- **이제 지도 선은 실제 도로를 따라갑니다.** 단, 방문순서는 기존 P2 최적화 결과를 그대로 사용합니다.
- **기존 P2의 F2 배송시간, GA 탐색, 도로별 비용행렬과 계산 로직은 변경하지 않았습니다.** Google 실도로 주행시간이나 실시간 교통정체를 F2에 반영한 것은 아닙니다.
- 긴급교통로 우선 선택(P0/β)도 아직 미구현입니다.
- 외부 Google API 키/Cloud 서비스는 이 파일에 포함되지 않습니다. API 키 설정 및 실제 API 호출의 성공 여부는 사용자의 배포 환경에서 검증해야 합니다.
