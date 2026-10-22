v40 버전 검사 수정 / 전체 프로젝트

- 기존 v39 배분·배송 계산 코드와 화면을 유지하고 데이터 버전 검사 불일치(v34/v39)를 수정했습니다.
- 배분계획의 성공 시 사용한 차량 수/배송횟수/δ를 세션 저장소에 함께 저장합니다.
- 배송경로 화면이 재계산을 요구하는 이유를 구분해서 표시합니다.
- 버전 문자열은 suita_delivery_support/app.py 의 ALLOCATION_SCHEMA_VERSION 한 곳에서 관리합니다.

Render 설정 방법 (루트 디렉터리 없음):
Root Directory: (빈칸)
Build Command: pip install -r requirements.txt
Start Command: gunicorn --chdir suita_delivery_support app:app --bind 0.0.0.0:$PORT

Render 설정 방법 (Root Directory = suita_delivery_support):
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app --bind 0.0.0.0:$PORT

실행 순서: 배분계획 계산 -> 배송경로 계산. 배송계획 조건을 수정한 경우, 조건 저장 -> 배분계획 재계산 -> 배송경로 계산.
Render 재배포 후 Ctrl+F5로 새로고침하고 같은 탭에서 실행해주세요.
※ 연구용 모델의 P0와 긴급교통로 우선 배송 기능은 기존처럼 미구현 상태입니다.
