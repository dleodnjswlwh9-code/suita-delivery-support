GitHub / Render 적용 안내 - v53.3 (2026-10-27)

변경 내용:
- 기존 홈 배너 이미지를 그대로 사용(중앙 제목·날짜 흰색 상자 제거)
- 시스템명과 일본 날짜는 상단 헤더에 표시
- 홈과 配分計画 사이 データ 메뉴 추가
- 피난소 / 긴급교통로 / 구원물자 배분용 기초 데이터 원본 3개 공개 열람·다운로드
- 操作の流れ 삭제
- セット充足率 → 総合充足率 명칭 변경
- 데이터 화면 설명 문장 삭제 및 파일명·버튼 확대
- 설명 말풍선(주석)의 줄바꿈 및 설명 정리
- 계산 로직(P0/P1/P2)과 데이터 스키마 변경 없음

GitHub 반영:
1) ZIP을 PC에서 압축 해제
2) GitHub 저장소의 Add file > Upload files 클릭
3) 압축 해제한 폴더의 '내용물'을 선택해 업로드
   - suita_delivery_support/ (전체 폴더 및 파일)
   - requirements.txt
   - README_UPLOAD.txt
   - README_v53.3_수정안내.txt
4) 기존 파일은 같은 경로로 덮어쓰고 Commit changes

주의: ZIP 파일 자체를 GitHub 앱 파일로 올리지 말 것.
주의: suita_delivery_support 폴더를 중첩해서 생성하지 말 것.

Render 권장 설정 (GitHub 저장소 루트 기준):
Root Directory: (비워두기)
Build Command: pip install -r requirements.txt
Start Command: gunicorn --chdir suita_delivery_support app:app --bind 0.0.0.0:$PORT

공개 데이터: 데이터 페이지에서 누구나 원본 xlsx 파일을 볼 수 있고 다운로드할 수 있습니다.
외부 공개 전에 출처 표시와 재배포 권한을 확인하세요.

공개 다운로드 파일명 수정:
- 避難所データ.xlsx
- 緊急交通路データ.xlsx
- 吹田市救援物資配分用基礎データ.xlsx
GitHub에 업로드할 때 기존 public_data 폴더의 (10), (2), (1)이 붙은 이전 파일 3개는 별도로 삭제하세요. 그렇지 않으면 저장소에 이전 파일이 남지만 다운로드 경로에서는 사용되지 않습니다.

Google Maps 오류 시: Chrome F12 > Console의 Google Maps JavaScript API error 코드 확인 후 Google Cloud 프로젝트의 결제, Maps JavaScript API 사용 설정 및 GOOGLE_MAPS_API_KEY의 허용 웹사이트에 https://suita-delivery-support.onrender.com/* 등록을 점검하세요. API 키는 GitHub에 업로드하지 마세요.
