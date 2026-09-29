# -*- coding: utf-8 -*-
"""
AD RANK 자동화 스크립트 v3.0 (2026-08 리뉴얼 사이트 대응)
- 키워드 시트에서 키워드/상호명 읽기
- adrank.co.kr/place/analyze 플레이스 분석에서 검색
- 결과 테이블에서 순위, 종합점수, 주소 추출
- 매장명 링크 href에서 네이버 MID 바로 추출 (클릭 불필요)
- 결과 시트에 날짜별로 기록 (4행 단위)
"""

import time
import json
import os
import re
from datetime import datetime

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# GUI 예약 실행 시 설정됨 — 이 시각까지 대기 후 자동 시작
scheduled_start_time = None
# GUI에서 실행 시 threading.Event — 버튼 클릭으로 대기 해제
gui_enter_event = None


def retry_on_quota(func, *args, max_retries=3, **kwargs):
    """429 Quota 에러 시 대기 후 재시도"""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                print(f"      ⏳ API 한도 초과, {wait}초 대기 후 재시도...")
                time.sleep(wait)
            else:
                raise

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


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

    keyword_wb = gc.open_by_url(config["keyword_sheet_url"])
    keyword_sheet = keyword_wb.worksheet(config["keyword_sheet_name"])

    result_wb = gc.open_by_url(config["result_sheet_url"])
    result_sheet = result_wb.get_worksheet_by_id(config["result_sheet_gid"])

    return keyword_sheet, result_sheet


def read_keywords(keyword_sheet):
    all_values = keyword_sheet.get_all_values()
    businesses = []
    for idx in range(1, len(all_values)):
        row = all_values[idx]
        keyword = row[0].strip() if len(row) > 0 else ""
        name = row[1].strip() if len(row) > 1 else ""
        if not keyword and not name:
            break
        match_keywords = row[5].strip() if len(row) > 5 else ""
        businesses.append({"keyword": keyword, "name": name, "match_keywords": match_keywords})
    return businesses


def read_result_sheet(result_sheet, config):
    all_values = result_sheet.get_all_values()
    start_row = config.get("data_start_row", 3)
    row_interval = config.get("row_interval", 4)

    existing = {}
    last_used_row = start_row - row_interval
    idx = start_row - 1
    while idx < len(all_values):
        row = all_values[idx]
        biz_name = row[1].strip() if len(row) > 1 else ""
        if not biz_name:
            break

        mid_value = ""
        if idx + 2 < len(all_values):
            mid_row = all_values[idx + 2]
            mid_value = mid_row[1].strip() if len(mid_row) > 1 else ""
        biz_keyword = row[2].strip() if len(row) > 2 else ""

        base_key = f"{biz_name}|{biz_keyword}"
        biz_key = base_key
        dup_idx = 1
        while biz_key in existing:
            dup_idx += 1
            biz_key = f"{base_key}|{dup_idx}"
        existing[biz_key] = {
            "sheet_row": idx + 1,
            "mid": mid_value,
            "keyword": biz_keyword,
            "name": biz_name,
        }
        last_used_row = idx + 1
        idx += row_interval

    existing["_next_row"] = last_used_row + row_interval
    return existing


def find_today_column(sheet, config):
    row1 = sheet.row_values(1)
    today = datetime.now()
    date_start_col = config.get("date_start_column", 7)

    for col_idx, cell_value in enumerate(row1):
        if col_idx < date_start_col - 1:
            continue
        cell_clean = cell_value.strip().replace(" ", "")
        if not cell_clean:
            continue
        m = re.match(r'^(\d{1,2})[/.\-](\d{1,2})', cell_clean)
        if m and int(m.group(1)) == today.month and int(m.group(2)) == today.day:
            return col_idx + 1

    next_col = len(row1) + 1
    if next_col < date_start_col:
        next_col = date_start_col

    try:
        sheet.update_cell(1, next_col, f"{today.month}/{today.day}")
    except Exception:
        sheet.add_cols(10)
        sheet.update_cell(1, next_col, f"{today.month}/{today.day}")

    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"]
    sheet.update_cell(2, next_col, weekday_kr[today.weekday()])
    print(f"  -> {next_col}열에 오늘 날짜 추가됨")
    return next_col


def batch_write(result_sheet, cells):
    """여러 셀을 한번에 쓰기. cells = [(row, col, value), ...]"""
    if not cells:
        return
    import gspread.utils
    sheet_title = result_sheet.title
    batch_data = []
    for row, col, value in cells:
        cell_label = gspread.utils.rowcol_to_a1(row, col)
        batch_data.append({
            "range": f"'{sheet_title}'!{cell_label}",
            "values": [[value]],
        })
    retry_on_quota(
        result_sheet.spreadsheet.values_batch_update,
        {"valueInputOption": "USER_ENTERED", "data": batch_data}
    )


def ensure_rows(result_sheet, needed_row, count=4):
    """시트 행 수가 부족하면 확장"""
    sheet_id = result_sheet.id
    meta = retry_on_quota(result_sheet.spreadsheet.fetch_sheet_metadata)
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == sheet_id:
            current_rows = s["properties"]["gridProperties"]["rowCount"]
            required = needed_row - 1 + count
            if required > current_rows:
                retry_on_quota(
                    result_sheet.spreadsheet.batch_update,
                    {"requests": [{
                        "appendDimension": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "length": required - current_rows,
                        }
                    }]}
                )
            break


def copy_rows(result_sheet, src_row, dst_row, count=4):
    """직전 행 복사 (서식 + 값 전체), 이후 필요한 셀만 덮어쓰기"""
    ensure_rows(result_sheet, dst_row, count)
    sheet_id = result_sheet.id
    req = {
        "copyPaste": {
            "source": {
                "sheetId": sheet_id,
                "startRowIndex": src_row - 1,
                "endRowIndex": src_row - 1 + count,
            },
            "destination": {
                "sheetId": sheet_id,
                "startRowIndex": dst_row - 1,
                "endRowIndex": dst_row - 1 + count,
            },
            "pasteType": "PASTE_NORMAL",
        }
    }
    retry_on_quota(result_sheet.spreadsheet.batch_update, {"requests": [req]})


def group_rows(result_sheet, base_row):
    """기준행+1 ~ 기준행+3 (3행)을 그룹화. 이미 그룹화되어 있으면 스킵."""
    sheet_id = result_sheet.id
    grp_start = base_row       # 0-based, 기준행+1
    grp_end = base_row + 3     # 기준행+3까지

    # 기존 그룹 확인
    meta = retry_on_quota(result_sheet.spreadsheet.fetch_sheet_metadata)
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == sheet_id:
            for g in s.get("dimensionGroups", []):
                rng = g.get("range", {})
                if rng.get("dimension") == "ROWS":
                    if rng["startIndex"] == grp_start and rng["endIndex"] == grp_end:
                        return  # 이미 그룹화됨
            break

    req = {
        "addDimensionGroup": {
            "range": {
                "sheetId": sheet_id,
                "dimension": "ROWS",
                "startIndex": grp_start,
                "endIndex": grp_end,
            }
        }
    }
    retry_on_quota(result_sheet.spreadsheet.batch_update, {"requests": [req]})


# ─────────────────────────────────────────────
# Selenium
# ─────────────────────────────────────────────
def setup_browser():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    import site

    # 실제 Chrome 버전 감지 (파일 버전 기반)
    chrome_exe = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    chromedriver_path = None

    try:
        import struct
        # Chrome 실행파일에서 메이저 버전 추출
        import subprocess
        result = subprocess.run(
            ["powershell", "-Command",
             f'(Get-Item "{chrome_exe}").VersionInfo.FileVersion'],
            capture_output=True, text=True, timeout=10
        )
        chrome_ver = result.stdout.strip()
        major = chrome_ver.split(".")[0]
        print(f"  Chrome 버전: {chrome_ver} (메이저: {major})")

        # 해당 메이저 버전의 chromedriver 찾기
        # 사용자 설치(pip --user) 경로도 포함 — AppData\Roaming\Python\...\site-packages
        search_dirs = list(site.getsitepackages())
        try:
            search_dirs.append(site.getusersitepackages())
        except Exception:
            pass
        for sp in search_dirs:
            candidate = os.path.join(sp, "chromedriver_autoinstaller", major, "chromedriver.exe")
            if os.path.exists(candidate):
                chromedriver_path = candidate
                break

        # 없으면 chromedriver_autoinstaller로 다운로드 시도
        if not chromedriver_path:
            import chromedriver_autoinstaller
            chromedriver_path = chromedriver_autoinstaller.install()
    except Exception as e:
        print(f"  ChromeDriver 자동 설정 실패: {e}")

    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if chromedriver_path and os.path.exists(chromedriver_path):
        print(f"  ChromeDriver 경로: {chromedriver_path}")
        service = Service(executable_path=chromedriver_path)
        try:
            return webdriver.Chrome(service=service, options=options)
        except Exception as e:
            # 크롬이 업데이트 대기 중이면 드라이버와 버전이 어긋남 → Selenium이 맞는 드라이버를 직접 받게 함
            if "only supports Chrome version" not in str(e):
                raise
            print("  ChromeDriver 버전 불일치 → 크롬 버전에 맞는 드라이버로 재시도")
    return webdriver.Chrome(options=options)


def auto_fill_login(driver, config):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    adrank_id = config.get("adrank_id", "")
    adrank_pw = config.get("adrank_pw", "")
    if not adrank_id or not adrank_pw:
        return

    try:
        # 리뉴얼 사이트는 SPA — 로그인 폼 렌더링을 잠시 기다린 후 판단
        try:
            WebDriverWait(driver, 8).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, "input[type='password']")
            )
        except Exception:
            return  # 비밀번호 필드 없음 = 이미 로그인 상태

        # 입력 필드 찾기 (여러 방식 시도)
        id_field = None
        pw_field = None

        selectors = [
            ("input[placeholder*='아이디']", "input[placeholder*='비밀번호']"),
            ("input[type='text']", "input[type='password']"),
            ("input[name*='id']", "input[name*='pass']"),
            ("input[name*='Id']", "input[name*='Pass']"),
        ]
        for id_sel, pw_sel in selectors:
            try:
                id_field = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, id_sel))
                )
                pw_field = driver.find_element(By.CSS_SELECTOR, pw_sel)
                if id_field and pw_field:
                    print(f"  -> 입력 필드 발견 ({id_sel})")
                    break
            except:
                id_field = None
                pw_field = None
                continue

        # 그래도 못 찾으면 input 태그 순서로 시도
        if not id_field or not pw_field:
            inputs = driver.find_elements(By.TAG_NAME, "input")
            visible = [inp for inp in inputs if inp.is_displayed()]
            if len(visible) >= 2:
                id_field = visible[0]
                pw_field = visible[1]
                print(f"  -> 입력 필드 발견 (input 순서, {len(visible)}개)")

        if not id_field or not pw_field:
            print("  -> 로그인 입력 필드를 찾을 수 없습니다.")
            return

        id_field.click()
        time.sleep(0.2)
        id_field.clear()
        id_field.send_keys(adrank_id)
        time.sleep(0.2)

        pw_field.click()
        time.sleep(0.2)
        pw_field.clear()
        pw_field.send_keys(adrank_pw)
        print("  -> 아이디/비밀번호 자동 입력 완료")
        time.sleep(0.3)

        # 로그인 버튼 찾기
        login_btn = None
        btn_selectors = [
            (By.XPATH, "//button[contains(text(),'로그인')]"),
            (By.XPATH, "//button[contains(@class,'login')]"),
            (By.CSS_SELECTOR, "button[type='submit']"),
            (By.CSS_SELECTOR, "form button"),
        ]
        for by, sel in btn_selectors:
            try:
                login_btn = driver.find_element(by, sel)
                if login_btn and login_btn.is_displayed():
                    break
            except:
                login_btn = None
                continue

        if login_btn:
            login_btn.click()
            print("  -> 로그인 클릭")
            time.sleep(3)

            # 로그인 성공 = 비밀번호 필드가 사라짐
            WebDriverWait(driver, 10).until(
                lambda d: not d.find_elements(By.CSS_SELECTOR, "input[type='password']")
            )
            print("  -> 로그인 성공!")

            driver.get("https://adrank.co.kr/place/analyze")
            time.sleep(2)
            dismiss_popups(driver)
        else:
            print("  -> 로그인 버튼을 찾을 수 없습니다. 수동으로 클릭해주세요.")
    except Exception as e:
        print(f"  -> 자동 로그인 실패 (수동 로그인 필요): {e}")


OVERLAY_SELECTOR = "[data-slot='sheet-overlay'],[data-slot='dialog-overlay'],[data-slot='sheet-content'],[data-slot='dialog-content'],[role='dialog']"


def dismiss_popups(driver):
    """로그인 직후 뜨는 온보딩 투어/안내 팝업 닫기.
    일반 클릭은 오버레이에 가로채이므로 JS 클릭 → ESC → DOM 강제 제거 순으로 처리."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    for _ in range(5):
        # 오버레이가 없으면 끝
        try:
            visible_overlays = [
                o for o in driver.find_elements(By.CSS_SELECTOR, OVERLAY_SELECTOR)
                if o.is_displayed()
            ]
        except Exception:
            visible_overlays = []
        if not visible_overlays:
            return

        # 1) 닫기류 버튼을 JS로 클릭 (오버레이 무시하고 동작)
        clicked = False
        try:
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                try:
                    txt = (btn.text or "").strip()
                    if txt in ("다음에 하기", "닫기", "Close", "건너뛰기", "오늘 하루 보지 않기"):
                        driver.execute_script("arguments[0].click();", btn)
                        print(f"  -> 팝업 닫음 ('{txt}')")
                        clicked = True
                        time.sleep(0.8)
                        break
                except Exception:
                    continue
        except Exception:
            pass
        if clicked:
            continue

        # 2) ESC 키
        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            time.sleep(0.5)
        except Exception:
            pass

        # 3) 그래도 남으면 오버레이 DOM 강제 제거
        try:
            driver.execute_script("""
                document.querySelectorAll(arguments[0]).forEach(function(e){ e.remove(); });
                document.querySelectorAll('[data-base-ui-inert]').forEach(function(e){
                    e.removeAttribute('data-base-ui-inert');
                });
                if (document.body) { document.body.style.pointerEvents = 'auto'; }
            """, OVERLAY_SELECTOR)
            print("  -> 팝업 오버레이 강제 제거")
            time.sleep(0.5)
        except Exception:
            pass


def is_logged_in(driver):
    """로그인 완료 + 플레이스 분석 페이지 준비 여부"""
    from selenium.webdriver.common.by import By
    try:
        if driver.find_elements(By.CSS_SELECTOR, "input[type='password']"):
            return False
        return bool(driver.find_elements(
            By.XPATH, "//button[contains(., '분석하기')]"
        ))
    except Exception:
        return False


def wait_for_login(driver):
    global scheduled_start_time
    config = load_config()
    from selenium.webdriver.support.ui import WebDriverWait
    driver.get("https://adrank.co.kr/place/analyze")
    WebDriverWait(driver, 30).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    auto_fill_login(driver, config)
    dismiss_popups(driver)

    logged_in = is_logged_in(driver)

    print("\n" + "=" * 60)
    print("  AD RANK 사이트가 열렸습니다.")
    if logged_in:
        print("  -> 자동 로그인 성공, 플레이스 분석 페이지 준비 완료")
    elif config.get("adrank_id"):
        print("  -> 자동 로그인 실패. 브라우저에서 직접 로그인해주세요.")
    else:
        print("  1. 브라우저에서 로그인해주세요.")
        print("  2. '플레이스 분석' 페이지가 보이는지 확인해주세요.")

    # 자동 로그인 성공 + 예약 아님 → 대기 없이 바로 시작
    if logged_in and not scheduled_start_time:
        print("  -> 바로 검색을 시작합니다!")
        print("=" * 60)
        return

    if scheduled_start_time:
        target = scheduled_start_time
        scheduled_start_time = None
        print(f"\n  ⏰ 예약 모드: {target.strftime('%H:%M:%S')}에 자동 시작됩니다.")
        print("     그 전에 로그인을 완료해주세요.")
        print("=" * 60)
        while datetime.now() < target:
            remaining = (target - datetime.now()).total_seconds()
            mins, secs = divmod(int(remaining), 60)
            print(f"  ⏳ 시작까지 {mins:02d}분 {secs:02d}초 남음...")
            time.sleep(1)
        print(f"\n  ✅ {target.strftime('%H:%M:%S')} — 검색을 시작합니다!")
    elif gui_enter_event:
        print("  3. 로그인 후 [Enter] 버튼을 눌러주세요.")
        print("=" * 60)
        print("\n>>> [Enter] 버튼 대기 중...")
        gui_enter_event.wait()
        print(">>> 시작합니다!")
    else:
        print("  3. 준비되면 여기로 돌아와서 Enter를 눌러주세요.")
        print("=" * 60)
        input("\n>>> Enter를 눌러 시작합니다... ")


def extract_left_number(text):
    text = text.strip()
    if not text:
        return ""
    match = re.match(r'^(\d+\.?\d*)', text)
    return match.group(1) if match else text


# 마지막 검색의 API 결과 캐시 (extract_results/_extract_once가 사용)
_LAST_RESULTS = None


def api_search_place(driver, keyword, cnt=300):
    """플레이스 분석 API 직접 호출.
    인증: localStorage.serviceToken → Authorization Bearer 헤더."""
    driver.set_script_timeout(90)
    script = """
        var done = arguments[arguments.length - 1];
        var keyword = arguments[0], cnt = arguments[1];
        var token = '';
        try { token = window.localStorage.getItem('serviceToken') || ''; } catch (e) {}
        fetch('/api/place/searchPlaceAnalyze', {
            method: 'POST',
            headers: {
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token,
                'pathName': '/place/analyze'
            },
            body: JSON.stringify({ keyword: keyword, cnt: cnt }),
            credentials: 'include'
        }).then(function(r) { return r.json(); })
          .then(function(j) { done(j); })
          .catch(function(e) { done({ result: false, responseMsg: String(e) }); });
    """
    return driver.execute_async_script(script, keyword, cnt)


def _parse_api_rows(items):
    rows = []
    for item in items:
        try:
            place_id = item.get("placeId", "")
            score = item.get("rankScoreOld", "")
            rows.append({
                "rank": str(item.get("rank", "")),
                "name": (item.get("name") or "").strip(),
                "score": "" if score in (None, "") else str(score),
                "kw_list": (item.get("formattedAddress") or "").strip(),  # 주소
                "mid": str(place_id) if place_id else "",
                "url": f"https://m.place.naver.com/place/{place_id}/home" if place_id else "",
            })
        except Exception:
            continue
    return rows


def search_keyword(driver, keyword):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys

    global _LAST_RESULTS
    _LAST_RESULTS = None

    # 1차: 분석 API 직접 호출 (셀레늄에서 화면 클릭이 무시되는 문제 대응)
    try:
        print(f"  '{keyword}' 분석 API 호출...")
        res = api_search_place(driver, keyword)
        if isinstance(res, dict) and res.get("result"):
            items = (res.get("data") or {}).get("list") or []
            _LAST_RESULTS = _parse_api_rows(items)
            print(f"  -> API 성공 ({len(_LAST_RESULTS)}개 업체)")
            return True
        else:
            msg = res.get("responseMsg", res) if isinstance(res, dict) else res
            print(f"  ! 분석 API 실패 ({msg}) → 화면 클릭 방식으로 재시도")
    except Exception as e:
        print(f"  ! 분석 API 오류 ({e}) → 화면 클릭 방식으로 재시도")

    # 2차: 기존 화면 클릭 방식 (폴백)
    try:
        # 스크롤 최상단으로 이동
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.5)
        dismiss_popups(driver)

        input_field = None
        selectors = [
            (By.CSS_SELECTOR, "input[placeholder*='강남']"),
            (By.CSS_SELECTOR, "input[placeholder*='예:']"),
            (By.CSS_SELECTOR, "input[placeholder*='키워드']"),
            (By.CSS_SELECTOR, "main input[type='text']"),
            (By.CSS_SELECTOR, "input[type='text']"),
        ]
        for by, selector in selectors:
            try:
                WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((by, selector))
                )
                # 같은 셀렉터에 여러 개 걸리면 화면에 보이는 것 우선
                candidates = driver.find_elements(by, selector)
                visible = [c for c in candidates if c.is_displayed()]
                input_field = visible[0] if visible else (candidates[0] if candidates else None)
                if input_field:
                    break
            except:
                continue

        if not input_field:
            print(f"  [오류] 키워드 입력 필드를 찾을 수 없습니다.")
            return False

        try:
            input_field.click()
        except Exception:
            # 오버레이에 가로채인 경우: 팝업 제거 후 JS로 포커스
            dismiss_popups(driver)
            driver.execute_script("arguments[0].click(); arguments[0].focus();", input_field)
        time.sleep(0.3)

        # React 컨트롤드 입력: 네이티브 setter + input 이벤트로 값 주입
        driver.execute_script("""
            var el = arguments[0], val = arguments[1];
            var setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            setter.call(el, val);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        """, input_field, keyword)
        time.sleep(0.5)

        # 값 반영 확인, 실패 시 타이핑 폴백
        if (input_field.get_attribute("value") or "").strip() != keyword:
            input_field.send_keys(Keys.CONTROL + "a")
            input_field.send_keys(Keys.DELETE)
            time.sleep(0.2)
            for ch in keyword:
                input_field.send_keys(ch)
                time.sleep(0.05)
            time.sleep(0.5)

        cur_val = (input_field.get_attribute("value") or "").strip()
        if cur_val != keyword:
            print(f"  [오류] 키워드 입력 실패 (현재 값: {cur_val!r})")
            return False

        RESULT_LINK = 'table tbody a[href*="place.naver.com"]'

        # 검색 전 기존 첫 번째 결과 링크 기억 (갱신 감지용)
        old_first_href = ""
        try:
            old_links = driver.find_elements(By.CSS_SELECTOR, RESULT_LINK)
            if old_links:
                old_first_href = old_links[0].get_attribute("href")
        except:
            pass

        # '분석하기' 버튼 클릭 (없으면 Enter)
        analyze_btn = None
        try:
            analyze_btn = driver.find_element(
                By.XPATH, "//button[contains(., '분석하기')]"
            )
        except:
            pass
        if analyze_btn:
            # 키워드 입력 반영 후 버튼 활성화 대기
            for _ in range(10):
                if analyze_btn.is_enabled():
                    break
                time.sleep(0.5)
            if not analyze_btn.is_enabled():
                print(f"  [오류] 분석하기 버튼이 활성화되지 않음")
                return False
            try:
                analyze_btn.click()
            except Exception:
                dismiss_popups(driver)
                driver.execute_script("arguments[0].click();", analyze_btn)
        else:
            input_field.send_keys(Keys.ENTER)
        print(f"  '{keyword}' 검색 실행...")

        # 1단계: 결과 갱신 대기
        for i in range(15):
            time.sleep(1)
            try:
                cur_links = driver.find_elements(By.CSS_SELECTOR, RESULT_LINK)
                if len(cur_links) == 0:
                    break
                if old_first_href and cur_links:
                    if cur_links[0].get_attribute("href") != old_first_href:
                        time.sleep(2)
                        break
            except:
                break
        else:
            time.sleep(3)

        # 2단계: 새 결과 나타나면 바로 진행
        for i in range(30):
            time.sleep(1)
            try:
                links = driver.find_elements(By.CSS_SELECTOR, RESULT_LINK)
                if len(links) > 0:
                    print(f"  -> 결과 나타남 ({i+1}초, {len(links)}개)")
                    break
            except:
                pass
        else:
            print(f"  -> 30초 대기 후에도 결과 없음")

        return True
    except Exception as e:
        print(f"  [오류] 검색 실패: {e}")
        return False


JS_EXTRACT = """
    // 리뉴얼 사이트: 정식 <table> 구조.
    // 헤더: 액션 | 순위 | 매장명 | 주소 | 방문 리뷰 | 블로그 리뷰 | 저장 수 | 종합점수 | 연관도 | 순위점수
    var table = null;
    for (var t of document.querySelectorAll('table')) {
        if (t.querySelector('tbody a[href*="place.naver.com"]')) { table = t; break; }
    }
    if (!table) return { rows: [], headers: [] };

    var headers = Array.from(table.querySelectorAll('thead th'))
        .map(function(th) { return th.textContent.trim(); });
    function colIdx(name) {
        for (var i = 0; i < headers.length; i++) {
            if (headers[i].indexOf(name) === 0) return i;
        }
        for (var i = 0; i < headers.length; i++) {
            if (headers[i].indexOf(name) !== -1) return i;
        }
        return -1;
    }
    var rankI = colIdx('순위');
    var nameI = colIdx('매장명');
    var addrI = colIdx('주소');
    var scoreI = colIdx('종합점수');

    var results = [];
    for (var row of table.querySelectorAll('tbody tr')) {
        var cells = row.children;
        if (cells.length < 4) continue;
        function firstLine(i) {
            if (i < 0 || i >= cells.length) return '';
            return cells[i].innerText.trim().split('\\n')[0];
        }
        var link = (nameI >= 0 && cells[nameI])
            ? cells[nameI].querySelector('a[href*="place.naver.com"]') : null;
        if (!link) link = row.querySelector('a[href*="place.naver.com"]');

        var name = link ? link.textContent.trim() : firstLine(nameI);
        name = name.replace(/^MY\\s*/, '').trim();

        var url = link ? link.href : '';
        var mid = '';
        var m = url.match(/place\\/(\\d{5,})/);
        if (m) mid = m[1];

        var addr = (addrI >= 0 && cells[addrI]) ? cells[addrI].innerText.trim() : '';

        results.push({
            name: name,
            rank: firstLine(rankI),
            score: firstLine(scoreI),
            addr: addr,
            mid: mid,
            url: url
        });
    }
    return { rows: results, headers: headers };
"""


def _extract_once(driver):
    """페이지에서 한 번 추출. (data, results, mid_count) 반환"""
    # API 결과가 있으면 그대로 사용
    if _LAST_RESULTS is not None:
        mid_count = sum(1 for r in _LAST_RESULTS if r.get("mid"))
        return {}, list(_LAST_RESULTS), mid_count

    data = driver.execute_script(JS_EXTRACT)
    results = []
    mid_count = 0
    for item in data["rows"]:
        try:
            if item.get("mid"):
                mid_count += 1
            results.append({
                "rank": extract_left_number(item["rank"]),
                "name": item["name"],
                "score": extract_left_number(item["score"]),
                "kw_list": item.get("addr", "").strip(),  # 주소로 동명 업체 구분
                "mid": item.get("mid", ""),
                "url": item.get("url", ""),
            })
        except Exception:
            continue
    return data, results, mid_count


def extract_results(driver):
    # API 결과가 있으면 바로 반환
    if _LAST_RESULTS is not None:
        results = list(_LAST_RESULTS)
        print(f"  -> {len(results)}개 업체 추출")
        if results:
            print(f"  [1위] {results[0]['name']} 순위={results[0]['rank']} 점수={results[0]['score']}")
        return results

    results = []
    try:
        data, results, mid_count = _extract_once(driver)

        # 테이블은 떴는데 링크(MID)가 아직 안 채워진 경우 잠시 대기
        if results and mid_count == 0:
            for retry in range(10):
                time.sleep(1)
                data, results, mid_count = _extract_once(driver)
                if mid_count > 0:
                    print(f"  -> 플레이스 링크 로드 완료 (+{retry+1}초)")
                    break
            else:
                print(f"  -> 플레이스 링크 없음 (10초 대기 후 진행)")

        print(f"  -> {len(results)}개 업체 추출")
        if results:
            print(f"  [1위] {results[0]['name']} 순위={results[0]['rank']} 점수={results[0]['score']}")

    except Exception as e:
        print(f"  [오류] 결과 추출 실패: {e}")

    return results


def extract_naver_url(driver, name_element):
    """(구버전 호환용) 리뉴얼 사이트에서는 링크 href로 MID를 바로 얻으므로 사용하지 않음"""
    from selenium.webdriver.common.by import By

    try:
        original_window = driver.current_window_handle
        original_handles = set(driver.window_handles)

        try:
            name_element.find_element(By.TAG_NAME, "a").click()
        except:
            name_element.click()

        time.sleep(3)
        new_handles = set(driver.window_handles) - original_handles

        if not new_handles:
            return None, None

        driver.switch_to.window(new_handles.pop())
        time.sleep(2)

        current_url = driver.current_url
        mid_match = re.search(r'/(\d{5,})', current_url)
        mid = mid_match.group(1) if mid_match else ""

        driver.close()
        driver.switch_to.window(original_window)
        time.sleep(1)
        return mid, current_url

    except Exception as e:
        print(f"    [오류] URL 추출 실패: {e}")
        try:
            if len(driver.window_handles) > 1:
                driver.switch_to.window(driver.window_handles[-1])
                driver.close()
            driver.switch_to.window(driver.window_handles[0])
        except:
            pass
        return None, None


# ─────────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────────
def run():
    print("\n" + "=" * 60)
    print("   AD RANK 자동화 프로그램 v3.0 (리뉴얼 사이트 대응)")
    print("=" * 60)

    config = load_config()
    row_interval = config.get("row_interval", 4)

    # [1] 시트 연결
    print("\n[1/5] 구글 시트 연결 중...")
    keyword_sheet, result_sheet = connect_sheets(config)
    print("  -> 연결 성공")

    # [2] 키워드 시트에서 전체 업체 수집
    print("\n[2/5] 키워드 시트에서 업체 목록 수집...")
    businesses = read_keywords(keyword_sheet)
    print(f"  -> {len(businesses)}개 업체")

    # 상호(B열)가 빈 행은 검색 불가 — 빈 상호는 API의 이름 없는 업체와 잘못 매칭됨
    no_name = [b for b in businesses if not b["name"]]
    if no_name:
        businesses = [b for b in businesses if b["name"]]
        print(f"  ! 상호 빈칸 {len(no_name)}개 제외 (업체 추출을 먼저 실행하세요): "
              + ", ".join(b["keyword"] for b in no_name[:5])
              + (" ..." if len(no_name) > 5 else ""))
    if not businesses:
        print("  X 검색할 업체가 없습니다. 키워드 시트 B열(상호)을 채워주세요.")
        return

    # [3] 결과 시트 확인 → 기존/신규 분류
    print("\n[3/5] 결과 시트 확인 중...")
    existing = read_result_sheet(result_sheet, config)
    date_col = find_today_column(result_sheet, config)
    print(f"  -> 오늘 날짜 열: {date_col}열")

    # 기존 업체의 오늘 순위+점수 일괄 확인
    today_data = {}
    key_counter = {}
    for biz in businesses:
        base_key = f"{biz['name']}|{biz['keyword']}"
        key_counter[base_key] = key_counter.get(base_key, 0) + 1
        biz_key = base_key if key_counter[base_key] == 1 else f"{base_key}|{key_counter[base_key]}"
        biz["_key"] = biz_key
        ex = existing.get(biz_key, {})
        if ex.get("sheet_row"):
            try:
                rank_val = result_sheet.cell(ex["sheet_row"], date_col).value or ""
                score_val = result_sheet.cell(ex["sheet_row"] + 1, date_col).value or ""
                today_data[biz_key] = (rank_val, score_val)
            except:
                pass

    new_businesses = []    # 결과 시트에 아예 없음 → 새 행 생성
    fill_businesses = []   # 결과 시트에 있지만 키워드/MID 등 빈칸 → 보완
    skip_businesses = []   # 오늘 데이터 완비 → 스킵
    work_businesses = []   # 실제 검색 대상 (fill + new + 재작업)

    for biz in businesses:
        biz_key = biz["_key"]
        ex = existing.get(biz_key, {})
        rank_val, score_val = today_data.get(biz_key, ("", ""))

        if ex.get("sheet_row"):
            # 결과 시트에 상호명 존재
            rank_is_num = bool(re.match(r'^\d+\.?\d*$', rank_val))
            score_is_num = bool(re.match(r'^\d+\.?\d*$', score_val))
            has_keyword = bool(ex.get("keyword"))
            has_mid = bool(ex.get("mid"))

            if rank_is_num and score_is_num and has_keyword and has_mid:
                skip_businesses.append(biz)
            else:
                # 키워드 비어있으면 채워넣기
                if not has_keyword:
                    fill_businesses.append(biz)
                work_businesses.append(biz)
        else:
            # 결과 시트에 없음 → 새 행 생성
            new_businesses.append(biz)
            work_businesses.append(biz)

    print(f"  -> 스킵(완비): {len(skip_businesses)}개")
    print(f"  -> 보완(키워드/MID 등 채우기): {len(fill_businesses)}개")
    print(f"  -> 신규: {len(new_businesses)}개")
    print(f"  -> 검색 대상: {len(work_businesses)}개")

    # [3-2] 신규 업체 행 일괄 생성
    if new_businesses:
        print(f"\n  신규 업체 행 생성 중...")
        for biz in new_businesses:
            new_row = existing["_next_row"]
            prev_row = new_row - row_interval
            print(f"    -> {new_row}행: {biz['name']} [{biz['keyword']}]")

            # 직전 4행 복사 (서식+값), 이후 B/C만 덮어쓰기
            try:
                copy_rows(result_sheet, prev_row, new_row, row_interval)
            except Exception as e:
                print(f"    ! 복사 실패: {e}")

            # (그룹화는 신규행 전체 생성 후 한 번에 처리 — 중첩 방지)

            # 덮어쓰기할 셀들 (한번에)
            today = datetime.now()
            date_str = f"DATE({today.year},{today.month},{today.day})"
            formula = f'="진행일 : " & (TODAY() - {date_str}+1)'
            batch_write(result_sheet, [
                (new_row, 2, biz["name"]),        # B: 상호
                (new_row, 3, biz["keyword"]),      # C: 키워드
                (new_row + 1, 2, ""),              # B+1 비우기
                (new_row + 2, 2, ""),              # B+2 MID 비우기
                (new_row + 3, 2, ""),              # B+3 URL 비우기
                (new_row, 6, formula),             # F: 진행일 (오늘자)
            ])

            existing[biz["_key"]] = {
                "sheet_row": new_row, "mid": "",
                "keyword": biz["keyword"],
                "name": biz["name"],
            }
            existing["_next_row"] = new_row + row_interval
            time.sleep(1)

        print(f"  -> 신규 행 생성 완료")

        # 신규행 추가 후 그룹화 한 번에 (기존 중첩 제거 후 4행 단위 단일 그룹)
        try:
            import group_rows as _grp
            all_values_now = result_sheet.get_all_values()
            base_rows = []
            idx = config.get("data_start_row", 3) - 1
            while idx < len(all_values_now):
                bn = all_values_now[idx][1].strip() if len(all_values_now[idx]) > 1 else ""
                if not bn:
                    break
                base_rows.append(idx + 1)
                idx += row_interval
            _grp.rebuild_groups(result_sheet, base_rows)
        except Exception as grp_err:
            print(f"  ! 그룹화 실패(무시): {grp_err}")

    # [3-3] 기존 항목 보완 (키워드 채우기)
    if fill_businesses:
        print(f"\n  기존 항목 키워드 보완 중...")
        fill_cells = []
        for biz in fill_businesses:
            ex = existing.get(biz["_key"], {})
            row = ex["sheet_row"]
            fill_cells.append((row, 3, biz["keyword"]))  # C열: 키워드
            ex["keyword"] = biz["keyword"]
            print(f"    -> {row}행 {biz['name']}: 키워드='{biz['keyword']}'")
        batch_write(result_sheet, fill_cells)
        print(f"  -> {len(fill_cells)}개 키워드 보완 완료")

    # [4] 브라우저 실행
    print("\n[4/5] 브라우저 실행 중...")
    driver = setup_browser()

    try:
        wait_for_login(driver)

        # 키워드별 그룹핑 (작업 대상만)
        keyword_groups = {}
        for biz in work_businesses:
            kw = biz["keyword"]
            if kw not in keyword_groups:
                keyword_groups[kw] = []
            keyword_groups[kw].append(biz)

        skipped_businesses = []

        print(f"\n[5/5] 검색 시작! (키워드 {len(keyword_groups)}개)")
        print("-" * 60)

        kw_total = len(keyword_groups)
        for kw_idx, (keyword, biz_list) in enumerate(keyword_groups.items(), 1):
            print(f"\n[키워드 {kw_idx}/{kw_total}] '{keyword}'")

            if not search_keyword(driver, keyword):
                print(f"  X 검색 실패, 건너뜁니다.")
                continue

            results = extract_results(driver)
            if not results:
                print(f"  X 결과 없음")
                continue

            for biz in biz_list:
                target_name = biz["name"]
                biz_match_kw = biz.get("match_keywords", "")
                print(f"\n  >> '{target_name}' 찾는 중...")

                # 매칭 (정확한 순서: 완전일치 → 포함 매칭)
                matched = None
                match_count = 0

                # 1순위: 완전 일치
                for r in results:
                    if r["name"] == target_name:
                        match_count += 1
                        if not matched:
                            matched = r

                # 2순위: target이 result에 포함 (결과에 지점명 등이 붙은 경우)
                if not matched:
                    match_count = 0
                    for r in results:
                        if target_name in r["name"]:
                            match_count += 1
                            if not matched:
                                matched = r

                # 3순위: 부분 매칭 (띄어쓰기 단위)
                if not matched:
                    match_count = 0
                    for r in results:
                        parts = [p for p in target_name.split() if len(p) >= 2]
                        if parts and all(p in r["name"] for p in parts):
                            match_count += 1
                            if not matched:
                                matched = r

                # 동일 상호명이 여러 개일 때
                if match_count > 1:
                    if biz_match_kw:
                        # 주소로 2차 대조 (키워드 시트 F열에 주소 입력)
                        print(f"    ! 동일 상호 {match_count}개 → 주소로 2차 대조")
                        my_text = biz_match_kw.replace(",", "").replace(",", "").replace(" ", "")

                        candidates = [r for r in results if target_name == r["name"] or target_name in r["name"]]
                        if not candidates:
                            candidates = [r for r in results if all(p in r["name"] for p in target_name.split() if len(p) >= 2)]

                        # 쉼표/공백 제거 후 주소 포함 여부로 대조
                        exact_matches = []
                        for r in candidates:
                            r_text = r.get("kw_list", "").replace(",", "").replace(",", "").replace(" ", "")
                            if r_text and my_text and (my_text in r_text or r_text in my_text):
                                exact_matches.append(r)

                        if len(exact_matches) == 1:
                            matched = exact_matches[0]
                            print(f"    -> 주소 일치로 매칭 성공")
                        elif len(exact_matches) > 1:
                            print(f"    ! 주소까지 동일한 업체 {len(exact_matches)}개, 스킵")
                            matched = None
                            skipped_businesses.append(f"{target_name} ({keyword}) - 주소 중복")
                        else:
                            print(f"    ! 주소 일치하는 업체 없음, 스킵")
                            matched = None
                            skipped_businesses.append(f"{target_name} ({keyword}) - 주소 불일치")
                    else:
                        print(f"    ! 동일 상호 {match_count}개 발견, 스킵")
                        matched = None
                        skipped_businesses.append(f"{target_name} ({keyword}) - 동일 상호 {match_count}개")

                ex = existing.get(biz["_key"], {})
                sheet_row = ex.get("sheet_row")
                if not sheet_row:
                    print(f"    X 결과 시트 행 없음, 건너뜀")
                    continue

                if matched:
                    rank = matched["rank"]
                    score = matched["score"]
                    print(f"    -> 순위: {rank}, 점수: {score}")

                    mid = ex.get("mid", "")
                    naver_url = ""
                    if not mid:
                        # 리뉴얼 사이트: 매장명 링크 href에 MID 포함 (클릭 불필요)
                        mid = matched.get("mid", "")
                        naver_url = matched.get("url", "")
                        if mid:
                            print(f"    -> MID: {mid}")

                    # 결과 일괄 쓰기
                    write_cells = [
                        (sheet_row, date_col, rank),
                        (sheet_row + 1, date_col, score),
                    ]
                    if mid and not ex.get("mid"):
                        write_cells.append((sheet_row + 2, 2, mid))
                    if naver_url and not ex.get("mid"):
                        write_cells.append((sheet_row + 3, 2, naver_url))

                    batch_write(result_sheet, write_cells)
                    print(f"    -> 기록 완료")
                else:
                    print(f"    X '{target_name}' 미발견")
                    batch_write(result_sheet, [
                        (sheet_row, date_col, "미발견"),
                        (sheet_row + 1, date_col, "미발견"),
                    ])

            # 시트 기록 완료 후 바로 다음 키워드 진행

        print("\n" + "=" * 60)
        print("  검색 작업 완료!")
        print("=" * 60)

        if skipped_businesses:
            print(f"\n[스킵된 업체 목록] ({len(skipped_businesses)}개)")
            print("-" * 60)
            for s in skipped_businesses:
                print(f"  - {s}")
            print("-" * 60)
            print("  → 키워드 시트 F열에 매장 주소(예: 수원 영통구 이의동)를 입력하면 매칭할 수 있습니다.")
        else:
            print("\n  스킵된 업체 없음 (모두 매칭 성공)")

    except KeyboardInterrupt:
        print("\n\n사용자가 중단했습니다.")
    except Exception as e:
        print(f"\n[오류] {e}")
        import traceback
        traceback.print_exc()
    finally:
        if gui_enter_event:
            print("\n브라우저를 닫습니다...")
        else:
            input("\nEnter를 누르면 브라우저를 닫습니다...")
        try:
            driver.quit()
        except:
            pass

    print("\n" + "=" * 60)
    print("  모든 작업 완료!")
    print("  구글 시트를 확인해주세요.")
    print("=" * 60)


if __name__ == "__main__":
    run()
