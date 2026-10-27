GitHub / Render 적용 안내 - v53 (2026-10-27)

변경 내용:
- 홈 상단 배너에 吹田市救援物資配分・配送支援システム 및 일본 날짜 표시
- 홈과 配分計画 사이 データ 메뉴 추가
- 피난소 / 긴급교통로 / 구원물자 배분용 기초 데이터 원본 3개 공개 열람·다운로드
- 操作の流れ 삭제
- セット充足率 -> 1日分セット供給可能率 명칭 변경
- 설명 말풍선(주석)의 줄바꿈 및 설명 정리
- 계산 로직(P0/P1/P2)과 데이터 스키마 변경 없음

GitHub 반영:
1) ZIP을 PC에서 압축 해제
2) GitHub 저장소의 Add file > Upload files 클릭
3) 압축 해제한 폴더의 '내용물'을 선택해 업로드
   - suita_delivery_support/ (전체 폴더 및 파일)
   - requirements.txt
   - README_UPLOAD.txt
   - README_v53_수정안내.txt
4) 기존 파일은 같은 경로로 덮어쓰고 Commit changes

주의: ZIP 파일 자체를 GitHub 앱 파일로 올리지 말 것.
주의: suita_delivery_support 폴더를 중첩해서 생성하지 말 것.

Render 권장 설정 (GitHub 저장소 루트 기준):
Root Directory: (비워두기)
Build Command: pip install -r requirements.txt
Start Command: gunicorn --chdir suita_delivery_support app:app --bind 0.0.0.0:$PORT

공개 데이터: 데이터 페이지에서 누구나 원본 xlsx 파일을 볼 수 있고 다운로드할 수 있습니다.
외부 공개 전에 출처 표시와 재배포 권한을 확인하세요.
