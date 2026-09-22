# -*- coding: utf-8 -*-
"""
AD RANK 자동화 스크립트 v2.0
- 구글 시트에서 키워드/상호명 읽기 (4행 단위 구조)
- adrank.co.kr 플레이스 분석에서 검색
- 순위(왼쪽 숫자), 종합점수(왼쪽 숫자) 추출
- 상호 클릭 → 네이버 URL에서 MID 추출
- 결과를 구글 시트에 날짜별로 기록
"""

import time
import json
import os
import re
from datetime import datetime

# ─────────────────────────────────────────────
# 1. 설정
# ─────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

# ─────────────────────────────────────────────
# 2. 구글 시트 연결
# ─────────────────────────────────────────────
def connect_sheets(config):
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(
        config["google_credentials_file"], scopes=scopes
    )
    gc = gspread.authorize(creds)
    workbook = gc.open_by_url(config["google_sheet_url"])
    return workbook


def read_businesses(workbook, config):
    """
    4행 단위로 업체 정보를 읽어옵니다.
    Row 3,7,11,15...: B=상호명, C=키워드
    Row 5,9,13,17...: B=MID (비어있을 수 있음)
    Row 6,10,14,18..: B=네이버URL (비어있을 수 있음)
    """
    sheet = workbook.worksheet(config["sheet_name"])
    all_values = sheet.get_all_values()

    businesses = []
    start_row = config.get("data_start_row", 3)  # 실제 시트 행번호 (1-based)
    row_interval = config.get("row_interval", 4)

    idx = start_row - 1  # 0-based index
    while idx < len(all_values):
        row = all_values[idx]
        business_name = row[1].strip() if len(row) > 1 else ""  # B열
        keyword = row[2].strip() if len(row) > 2 else ""        # C열

        if not business_name and not keyword:
            break  # 더 이상 데이터 없음

        # MID 확인 (2행 아래)
        mid_value = ""
        if idx + 2 < len(all_values):
            mid_row = all_values[idx + 2]
            mid_value = mid_row[1].strip() if len(mid_row) > 1 else ""

        businesses.append({
            "name": business_name,
            "keyword": keyword,
            "mid": mid_value,
            "sheet_row": idx + 1,  # 1-based 행번호
        })

        idx += row_interval

    return businesses, sheet


def find_today_column(sheet, config):
    """
    1행에서 오늘 날짜에 해당하는 열을 찾습니다.
    없으면 다음 빈 열에 오늘 날짜를 추가합니다.
    반환: 열 번호 (1-based)
    """
    row1 = sheet.row_values(1)
    today = datetime.now()

    # 다양한 날짜 포맷으로 매칭 시도
    today_formats = [
        today.strftime("%-m/%-d"),       # 5/30 (Linux)
        today.strftime("%m/%d"),          # 05/30
        today.strftime("%-m/%-d"),       # 5/30
        f"{today.month}/{today.day}",    # 5/30 (확실한 방법)
        today.strftime("%Y.%m.%d"),      # 2026.05.30
        today.strftime("%m.%d"),          # 05.30
    ]

    # 1행에서 오늘 날짜 찾기 (G열=7번째부터)
    date_start_col = config.get("date_start_column", 7)  # G열 = 7

    for col_idx, cell_value in enumerate(row1):
        if col_idx < date_start_col - 1:  # G열 이전은 건너뛰기
            continue
        cell_clean = cell_value.strip()
        for fmt in today_formats:
            if cell_clean == fmt:
                return col_idx + 1  # 1-based

    # 못 찾으면 다음 빈 열에 추가
    next_col = len(row1) + 1
    if next_col < date_start_col:
        next_col = date_start_col

    today_str = f"{today.month}/{today.day}"
    sheet.update_cell(1, next_col, today_str)

    # 2행에 요일 추가
    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"]
    sheet.update_cell(2, next_col, weekday_kr[today.weekday()])

    print(f"  → {next_col}열에 오늘 날짜({today_str}) 추가됨")
    return next_col


# ─────────────────────────────────────────────
# 3. Selenium 브라우저
# ─────────────────────────────────────────────
def setup_browser():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    try:
        import chromedriver_autoinstaller
        chromedriver_autoinstaller.install()
    except ImportError:
        pass

    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)
    return driver


def wait_for_login(driver):
    driver.get("https://adrank.co.kr")
    print("\n" + "=" * 60)
    print("  AD RANK 사이트가 열렸습니다.")
    print("  1. 브라우저에서 로그인해주세요.")
    print("  2. '플레이스 분석' 메뉴로 이동해주세요.")
    print("  3. 준비되면 여기로 돌아와서 Enter를 눌러주세요.")
    print("=" * 60)
    input("\n>>> Enter를 눌러 시작합니다... ")


# ─────────────────────────────────────────────
# 4. AD RANK 검색 및 데이터 추출
# ─────────────────────────────────────────────
def extract_left_number(text):
    """
    '1↑3' → '1', '50.2↑0.5' → '50.2', '48.5↓0.6' → '48.5'
    화살표/특수문자 왼쪽의 숫자만 추출
    """
    text = text.strip()
    if not text:
        return ""
    # 숫자와 소수점만 앞에서부터 추출
    match = re.match(r'^(\d+\.?\d*)', text)
    if match:
        return match.group(1)
    return text


def search_keyword(driver, keyword, wait_seconds=5):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys

    try:
        # 키워드 입력 필드 찾기
        input_field = None
        selectors = [
            (By.CSS_SELECTOR, "input[placeholder*='키워드']"),
            (By.CSS_SELECTOR, "input[placeholder*='입력']"),
            (By.XPATH, "//label[contains(text(),'키워드')]/..//input"),
            (By.CSS_SELECTOR, "input[type='text']"),
        ]

        for by, selector in selectors:
            try:
                input_field = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((by, selector))
                )
                if input_field:
                    break
            except:
                continue

        if not input_field:
            print(f"  [오류] 키워드 입력 필드를 찾을 수 없습니다.")
            return False

        # 기존 텍스트 지우고 새 키워드 입력
        input_field.click()
        time.sleep(0.3)
        input_field.send_keys(Keys.CONTROL + "a")
        input_field.send_keys(Keys.DELETE)
        time.sleep(0.2)
        input_field.send_keys(keyword)
        time.sleep(0.5)

        # 검색 버튼 클릭
        search_btn = None
        btn_selectors = [
            (By.CSS_SELECTOR, "button[type='submit']"),
            (By.XPATH, "//button[contains(@class,'search')]"),
            (By.XPATH, "//button[.//svg]"),
            (By.CSS_SELECTOR, "button.MuiButton-root"),
        ]

        for by, selector in btn_selectors:
            try:
                candidates = driver.find_elements(by, selector)
                for btn in candidates:
                    if btn.is_displayed():
                        search_btn = btn
                        break
                if search_btn:
                    break
            except:
                continue

        if search_btn:
            search_btn.click()
        else:
            input_field.send_keys(Keys.ENTER)

        print(f"  '{keyword}' 검색 중... ({wait_seconds}초 대기)")
        time.sleep(wait_seconds)
        return True

    except Exception as e:
        print(f"  [오류] 검색 실패: {e}")
        return False


def extract_results(driver):
    """
    결과 테이블에서 순위, 상호, 종합점수를 추출합니다.
    순위/종합점수는 화살표 왼쪽 숫자만 추출합니다.
    """
    from selenium.webdriver.common.by import By

    results = []
    try:
        rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
        if not rows:
            rows = driver.find_elements(By.XPATH, "//table//tr[td]")

        for row in rows:
            try:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) < 9:
                    continue

                # 컬럼: 0:이력, 1:진단, 2:순위, 3:상호, 4:주소,
                #       5:카테고리, 6:방문자리뷰, 7:블로그리뷰,
                #       8:종합점수, 9:연관도, 10:순위점수
                rank_raw = cells[2].text.strip()
                name_text = cells[3].text.strip()
                score_raw = cells[8].text.strip()

                rank = extract_left_number(rank_raw)
                score = extract_left_number(score_raw)

                # 상호 클릭용 엘리먼트 저장
                name_element = cells[3]

                results.append({
                    "rank": rank,
                    "name": name_text,
                    "score": score,
                    "name_element": name_element,
                    "row_element": row,
                })

            except Exception:
                continue

        print(f"  → {len(results)}개 업체 추출 완료")

    except Exception as e:
        print(f"  [오류] 결과 추출 실패: {e}")

    return results


def extract_naver_url(driver, name_element):
    """
    상호명을 클릭하여 네이버 플레이스 URL과 MID를 추출합니다.
    """
    from selenium.webdriver.common.by import By

    try:
        original_window = driver.current_window_handle
        original_handles = set(driver.window_handles)

        # 상호명 클릭 (새 탭이 열림)
        try:
            # 상호 셀 안의 링크 또는 클릭 가능한 요소 찾기
            link = name_element.find_element(By.TAG_NAME, "a")
            link.click()
        except:
            # 링크가 없으면 셀 자체를 클릭
            name_element.click()

        time.sleep(3)

        # 새 탭으로 전환
        new_handles = set(driver.window_handles) - original_handles

        if not new_handles:
            print("    ⚠ 새 탭이 열리지 않았습니다.")
            return None, None

        new_window = new_handles.pop()
        driver.switch_to.window(new_window)
        time.sleep(2)

        # URL에서 MID 추출
        current_url = driver.current_url
        # https://m.place.naver.com/hospital/1200780480/home
        # https://m.place.naver.com/place/1027978575/home
        mid_match = re.search(r'/(\d{5,})', current_url)
        mid = mid_match.group(1) if mid_match else ""

        # 새 탭 닫고 원래 탭으로 복귀
        driver.close()
        driver.switch_to.window(original_window)
        time.sleep(1)

        return mid, current_url

    except Exception as e:
        print(f"    [오류] 네이버 URL 추출 실패: {e}")
        # 안전하게 원래 탭으로 복귀 시도
        try:
            if len(driver.window_handles) > 1:
                driver.switch_to.window(driver.window_handles[-1])
                driver.close()
            driver.switch_to.window(driver.window_handles[0])
        except:
            pass
        return None, None


# ─────────────────────────────────────────────
# 5. 구글 시트에 결과 쓰기
# ─────────────────────────────────────────────
def write_results(sheet, biz, rank, score, mid, naver_url, date_col):
    """
    업체 데이터를 구글 시트에 기록합니다.

    biz["sheet_row"] = 기준 행 (1-based, 예: 3, 7, 11...)
    - D열(4): 순위, E열(5): 점수  (현재 값)
    - date_col열, 기준행: 순위
    - date_col열, 기준행+1: 점수
    - B열, 기준행+2: MID 숫자
    - B열, 기준행+3: 네이버 URL
    """
    base_row = biz["sheet_row"]

    try:
        # 현재 순위/점수 (D, E열)
        sheet.update_cell(base_row, 4, rank)      # D열 = 순위
        sheet.update_cell(base_row, 5, score)      # E열 = 점수

        # 날짜별 순위/점수
        sheet.update_cell(base_row, date_col, rank)      # 순위
        sheet.update_cell(base_row + 1, date_col, score)  # 점수

        # MID와 네이버 URL (비어있을 때만 기록)
        if mid and not biz.get("mid"):
            sheet.update_cell(base_row + 2, 2, mid)           # B열 MID
        if naver_url and not biz.get("mid"):
            sheet.update_cell(base_row + 3, 2, naver_url)     # B열 URL

        print(f"  ✓ 시트 기록 완료: 순위={rank}, 점수={score}")

    except Exception as e:
        print(f"  [오류] 시트 기록 실패: {e}")


# ─────────────────────────────────────────────
# 6. 메인 실행
# ─────────────────────────────────────────────
def run():
    print("\n" + "=" * 60)
    print("   AD RANK 자동화 프로그램 v2.0")
    print("=" * 60)

    config = load_config()
    wait_time = config.get("search_wait_seconds", 5)

    # 구글 시트 연결
    print("\n[1/5] 구글 시트 연결 중...")
    workbook = connect_sheets(config)
    print("  ✓ 구글 시트 연결 성공")

    # 업체 목록 읽기
    print("\n[2/5] 업체 목록 읽는 중...")
    businesses, sheet = read_businesses(workbook, config)
    print(f"  ✓ {len(businesses)}개 업체 로드 완료")

    for i, biz in enumerate(businesses, 1):
        mid_status = "MID 있음" if biz["mid"] else "MID 없음"
        print(f"     {i}. [{biz['keyword']}] {biz['name']} ({mid_status})")

    # 오늘 날짜 열 찾기
    print("\n[3/5] 오늘 날짜 열 확인 중...")
    date_col = find_today_column(sheet, config)
    print(f"  ✓ 오늘 날짜 열: {date_col}열")

    # 브라우저 실행
    print("\n[4/5] 브라우저 실행 중...")
    driver = setup_browser()

    try:
        wait_for_login(driver)

        # 키워드별 그룹핑 (같은 키워드는 한 번만 검색)
        keyword_groups = {}
        for biz in businesses:
            kw = biz["keyword"]
            if kw not in keyword_groups:
                keyword_groups[kw] = []
            keyword_groups[kw].append(biz)

        print(f"\n[5/5] 검색 시작! (키워드 {len(keyword_groups)}개)")
        print("-" * 60)

        kw_total = len(keyword_groups)
        for kw_idx, (keyword, biz_list) in enumerate(keyword_groups.items(), 1):
            print(f"\n[키워드 {kw_idx}/{kw_total}] '{keyword}'")

            if not search_keyword(driver, keyword, wait_time):
                print(f"  ✗ 검색 실패, 건너뜁니다.")
                continue

            results = extract_results(driver)

            if not results:
                print(f"  ✗ 결과 없음")
                continue

            # 각 업체 매칭
            for biz in biz_list:
                target_name = biz["name"]
                print(f"\n  ▶ 상호 찾는 중: '{target_name}'")

                matched = None
                for r in results:
                    if target_name in r["name"] or r["name"] in target_name:
                        matched = r
                        break

                if not matched:
                    # 부분 매칭 시도
                    for r in results:
                        if any(part in r["name"] for part in target_name.split() if len(part) >= 2):
                            matched = r
                            break

                if matched:
                    rank = matched["rank"]
                    score = matched["score"]
                    print(f"    → 순위: {rank}, 종합점수: {score}")

                    # MID가 없으면 네이버 URL 추출
                    mid = biz.get("mid", "")
                    naver_url = ""

                    if not mid:
                        print(f"    → MID 추출 중 (상호 클릭)...")
                        mid, naver_url = extract_naver_url(
                            driver, matched["name_element"]
                        )
                        if mid:
                            print(f"    → MID: {mid}")
                        else:
                            print(f"    ⚠ MID 추출 실패")

                    # 시트에 기록
                    write_results(sheet, biz, rank, score, mid, naver_url, date_col)

                else:
                    print(f"    ✗ '{target_name}'을(를) 결과에서 찾지 못함")
                    # 미발견도 기록
                    write_results(sheet, biz, "미발견", "미발견", "", "", date_col)

            # 다음 키워드 전 대기
            if kw_idx < kw_total:
                delay = config.get("between_search_delay", 3)
                print(f"\n  ⏳ {delay}초 대기...")
                time.sleep(delay)

        print("\n" + "=" * 60)
        print("  ✅ 모든 작업 완료!")
        print("  구글 시트를 확인해주세요.")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\n사용자가 중단했습니다.")
    except Exception as e:
        print(f"\n[오류] {e}")
        import traceback
        traceback.print_exc()
    finally:
        input("\nEnter를 누르면 브라우저를 닫습니다...")
        driver.quit()


if __name__ == "__main__":
    run()
