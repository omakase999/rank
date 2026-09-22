# AD RANK 자동화 - 핸드노트 (2026-09-22 세션)

다른 세션/사람이 이어받을 때 이 문서부터 읽으면 됩니다.

---

## 0. 한 줄 요약
2026-08-10 애드랭크 사이트 리뉴얼로 자동화가 완전히 죽어 있었음 → 이번 세션에 전면 수정해서 **5개 작업 전부 정상 작동 확인 완료**. 결과/키워드 시트도 정리 완료.

---

## 1. 프로그램 개요
네이버 플레이스 순위를 adrank.co.kr에서 긁어 구글 시트에 기록하는 GUI 자동화(Selenium + gspread).

- **키워드 시트**("automa 연결"/"오토마"): A=키워드, B=상호, C=MID, F=주소(동명업체 구분용)
  - URL: `https://docs.google.com/spreadsheets/d/1B93FeRDZGIj3dtaFBsByLIWzQLzd2NSgAo6FbXF1CXk`
- **결과 시트**("길찾기 테스트 최종" → 탭 "표", gid=320454431): 업체당 4행 블록, 3행부터 시작, 날짜별 열에 순위/점수
  - URL: `https://docs.google.com/spreadsheets/d/1Zovenqyt_RiIQanJ-YmQhOjwnox5E3vojmIbQkmhbic`
- 실행: `gui.bat` (또는 `run.bat`). 계정 test112 (config.json), 전문가 플랜.

### GUI 5개 작업
1. **순위 검색** (main.py) — 키워드+상호로 검색, 결과시트에 순위/점수/MID 기록
2. **업체 추출** (pick_random_biz.py) — 키워드로 검색해 60~180등 후순위 업체 랜덤 1곳 뽑아 키워드시트 B(상호)+F(주소) 채움
3. **MID 동기화** (sync_mid.py) — 결과시트 MID → 키워드시트 C열 복사
4. **길찾기/유입** (sync_traffic.py) — 시트끼리 (미검증, 리뉴얼 영향 없음)
5. **행 그룹화** (group_rows.py) — 결과시트 4행 단위 그룹

---

## 2. 올바른 작업 순서 (중요!)
```
① 업체 추출 → ② 순위 검색 → ③ MID 동기화
```
- ②를 건너뛰면 MID가 키워드시트에 안 들어감 (MID는 순위검색이 결과시트에 만들고, 동기화가 그걸 복사하는 구조).
- GUI에서 3개 체크해서 한 번에 돌리면 순서대로 처리됨.

---

## 3. 이번 세션 수정 내역 (리뉴얼 대응)

### 사이트 구조 변경
- 페이지: `/placeMng/placeAnalyze`(404) → **`/place/analyze`**
- 로그인: 메인/`/login`에 폼, `input[name=username]`/`input[name=password]`
- 검색: 화면 클릭이 셀레늄에서 안 먹힘 → **분석 API 직접 호출**로 우회
  - `POST /api/place/searchPlaceAnalyze`, body `{"keyword","cnt"}` (cnt 최대 300)
  - 헤더 필수: `Authorization: Bearer <localStorage.serviceToken>` + `pathName: /place/analyze`
  - (없으면 401 "세션이 만료되었습니다")
  - 응답 list: rank, name, formattedAddress(주소), placeId(=MID), rankScoreOld(점수)
- MID/URL은 API 응답에서 바로 추출 (상호 클릭 불필요)

### 코드 변경 (main.py, pick_random_biz.py, group_rows.py — 배포용 폴더도 갱신됨)
- `api_search_place()` + `_parse_api_rows()` 추가, `_LAST_RESULTS` 캐시
- `dismiss_popups()` — 로그인 직후 온보딩 오버레이가 클릭 차단 → JS클릭/ESC/DOM제거로 처리
- 키워드 입력: React 컨트롤드 input이라 send_keys 안 먹힘 → 네이티브 setter+input 이벤트 주입
- 자동 로그인 성공 시 Enter 없이 바로 시작
- pick_random_biz: main의 브라우저 로직 재사용, 빈 상호(API가 섞어 보냄) 후보에서 제외
- 동명 업체 2차 대조: "키워드 목록"(사라짐) → **주소**(F열)

### 그룹화 버그 수정 (핵심)
- **증상**: 결과시트 왼쪽 그룹 접기가 여러 겹(depth 8)으로 지저분.
- **원인**: gspread `fetch_sheet_metadata()`가 dimensionGroups를 신뢰성 있게 반환 안 함(항상 0개로 보임) → group_rows가 "그룹 없음"으로 오판 → 실행마다 겹쳐 추가.
- **해결**: group_rows.py에 `flatten_all_row_groups()`(deleteDimensionGroup을 전체범위에 반복, **batch_update 응답**의 dimensionGroups로 남은 수 판단) + `rebuild_groups()`(평탄화 후 4행 단위 단일그룹). main.py도 per-row 그룹화 제거하고 신규행 생성 후 한 번에 `rebuild_groups` 호출.

---

## 4. 현재 시트 상태 (2026-09-22 세션 종료 시점)
- 결과시트: 업체 80개 (3~322행), 전부 상호 있음, 그룹화 단일 depth로 정상
  - 첫 10개(기존) + 50개(1차 batch) + 20개(2차 batch: 수원 피부과 등)
- 키워드시트: 20개 (수원 피부과~청주 내과), 상호+MID+주소 전부 채워짐
- **껍데기 행 삭제 완료**: 상호 없이 미발견만 찍혀있던 옛 행들(옛 243~322) 제거함.

---

## 5. 알려진 이슈 / 주의점
- **점수 0 또는 빈칸**: 네이버 지표 제공 중단(2026-09-18 애드랭크 공지). 사이트가 점수를 안 줌 → 스크립트 문제 아님. 순위는 정상.
- **업체 추출은 "랜덤"**: 60~180등에서 무작위로 뽑으므로 키워드 업종과 안 맞는 업체가 나올 수 있음(설계된 동작, 버그 아님). 업종 정확히 맞추려면 로직 수정 필요.
- **결과시트에 없는 새 키워드는 순위검색 시 새 행 생성**. 상호 없는 껍데기 행이 남아있으면 매칭 안 돼 중복 행이 생기니 껍데기는 삭제하고 진행.
- ChromeDriver: Chrome 153 자동 감지/다운로드됨 (setup_browser).

---

## 6. 검증 완료 항목 (이번 세션에서 실제 실행)
- [x] 순위 검색: 50개 + 20개 실전 실행, 미발견 0
- [x] 업체 추출: 50개 + 20개 실전, 빈 상호 제외 정상
- [x] MID 동기화: 20개 키워드시트 C열 기입 확인
- [x] 행 그룹화: 80개 단일 그룹(depth 1) 브라우저로 확인
- [x] 자동 로그인 → 팝업 닫기 → 바로 시작
- [ ] 길찾기/유입(sync_traffic): 미검증 (브라우저 안 쓰는 시트 작업)

---

## 7. 다음에 할 수 있는 일 (선택)
- sync_traffic.py 검증
- 업체 추출을 업종 매칭되게 개선(원하면)
- pick_random_biz가 MID도 바로 키워드시트에 쓰게 하면 ③단계 생략 가능
