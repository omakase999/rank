# -*- coding: utf-8 -*-
"""
후순위 업체 랜덤 추출기
- 키워드 시트 A열의 키워드로 adrank 검색
- 60등~180등(또는 마지막 등수) 사이에서 랜덤 1곳 선택
- B열에 상호명 기록
"""

import time
import json
import os
import re
import random
from datetime import datetime


CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

scheduled_start_time = None
gui_enter_event = None


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def connect_sheet(config):
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
    wb = gc.open_by_url(config["keyword_sheet_url"])
    return wb.worksheet(config["keyword_sheet_name"])


# 브라우저 관련 로직은 main.py(리뉴얼 사이트 대응)를 그대로 재사용
import main as _main


def setup_browser():
    return _main.setup_browser()


def wait_for_login(driver):
    global scheduled_start_time
    # GUI가 이 모듈에 걸어준 예약시각/Enter 이벤트를 main 쪽으로 전달
    _main.scheduled_start_time = scheduled_start_time
    _main.gui_enter_event = gui_enter_event
    scheduled_start_time = None
    _main.wait_for_login(driver)


def search_keyword(driver, keyword):
    return _main.search_keyword(driver, keyword)


def extract_left_number(text):
    text = text.strip()
    if not text:
        return ""
    match = re.match(r'^(\d+\.?\d*)', text)
    return match.group(1) if match else text


def _extract_once(driver):
    """페이지에서 한 번 추출 시도. (results, mid_count) 반환 — main의 테이블 파서 재사용"""
    _, raw, mid_count = _main._extract_once(driver)
    results = []
    for item in raw:
        try:
            rank_str = item["rank"]
            rank_num = int(rank_str) if rank_str and rank_str.isdigit() else 0
            results.append({
                "rank": rank_num,
                "name": item["name"],
                "score": item.get("score", ""),
                "kw_list": item.get("kw_list", ""),  # 리뉴얼 사이트: 주소
            })
        except Exception:
            continue
    return results, mid_count


def extract_results(driver):
    results = []
    try:
        # 1차 즉시 추출
        results, mid_count = _extract_once(driver)

        if results and mid_count == 0:
            # 링크가 아직 로드 안 됨 → 최대 10초 폴링
            for retry in range(10):
                time.sleep(1)
                results, mid_count = _extract_once(driver)
                if mid_count > 0:
                    print(f"  -> 플레이스 링크 로드 완료 (+{retry+1}초)")
                    break
            else:
                print(f"  -> 플레이스 링크 없음 (10초 대기 후 진행)")

        print(f"  -> {len(results)}개 업체 추출 (최고 순위~{max((r['rank'] for r in results), default=0)}등)")

    except Exception as e:
        print(f"  [오류] 결과 추출 실패: {e}")

    return results


# ─────────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────────
def run():
    RANK_MIN = 60
    RANK_MAX = 180

    print("\n" + "=" * 60)
    print("   후순위 업체 랜덤 추출기")
    print("=" * 60)

    config = load_config()

    # [1] 시트 연결
    print("\n[1/3] 구글 시트 연결 중...")
    sheet = connect_sheet(config)
    print("  -> 연결 성공")

    # [2] A열 키워드 읽기 (B열이 비어있는 것만)
    print("\n[2/3] 키워드 목록 읽기...")
    all_values = sheet.get_all_values()
    keywords = []
    for idx in range(1, len(all_values)):  # 1행은 헤더
        row = all_values[idx]
        keyword = row[0].strip() if len(row) > 0 else ""
        existing_biz = row[1].strip() if len(row) > 1 else ""
        if not keyword:
            break
        if existing_biz:
            print(f"  -> {idx+1}행 '{keyword}' : 이미 '{existing_biz}' 있음 → 스킵")
            continue
        keywords.append({"keyword": keyword, "row": idx + 1})

    print(f"  -> 검색 대상: {len(keywords)}개 키워드")

    if not keywords:
        print("\n  처리할 키워드가 없습니다. (B열이 모두 채워져 있음)")
        return

    # [3] 브라우저 시작 + adrank 검색
    print("\n[3/3] 브라우저 시작...")
    driver = setup_browser()

    try:
        wait_for_login(driver)

        results_summary = []

        for i, kw_info in enumerate(keywords, 1):
            keyword = kw_info["keyword"]
            row_num = kw_info["row"]
            print(f"\n{'─'*50}")
            print(f"  [{i}/{len(keywords)}] '{keyword}' 검색 (→ {row_num}행)")

            if not search_keyword(driver, keyword):
                print(f"    검색 실패, 스킵")
                continue

            all_results = extract_results(driver)

            if not all_results:
                print(f"    결과 없음, 스킵")
                continue

            # 상호명이 비어있는 항목은 후보에서 제외
            named_results = [r for r in all_results if r["name"].strip()]
            if len(named_results) < len(all_results):
                print(f"    (상호명 없는 {len(all_results) - len(named_results)}개 제외)")
            if not named_results:
                print(f"    상호명 있는 업체 없음, 스킵")
                continue

            total_count = len(named_results)
            max_rank = max(r["rank"] for r in named_results)

            # 60등~최대등수 사이에서 필터
            upper_bound = min(RANK_MAX, max_rank)
            candidates = [r for r in named_results if RANK_MIN <= r["rank"] <= upper_bound]

            if not candidates:
                # 60등 미만밖에 없으면 → 후반부 1/3에서 선택
                cutoff = max(1, total_count * 2 // 3)
                candidates = sorted(named_results, key=lambda r: r["rank"])[cutoff:]
                if not candidates:
                    candidates = named_results[-1:]
                print(f"    {RANK_MIN}~{upper_bound}등 업체 없음 → 후반부에서 선택 ({len(candidates)}개)")

            chosen = random.choice(candidates)
            print(f"    ★ 선택: {chosen['name']} (순위: {chosen['rank']}등)")

            # 시트 B열에 상호, F열에 키워드목록 기록
            sheet.update_cell(row_num, 2, chosen["name"])
            kw_list = chosen.get("kw_list", "")
            if kw_list:
                sheet.update_cell(row_num, 6, kw_list)
            print(f"    -> B{row_num}: '{chosen['name']}' / F{row_num}: '{kw_list}'  기록 완료")

            results_summary.append({
                "keyword": keyword,
                "chosen": chosen["name"],
                "rank": chosen["rank"],
                "total": total_count,
            })

            # 시트 기록 후 바로 다음 검색 진행 (대기 없음)

        # 결과 요약
        print("\n" + "=" * 60)
        print("  완료! 결과 요약")
        print("=" * 60)
        for r in results_summary:
            print(f"  {r['keyword']} → {r['chosen']} ({r['rank']}등 / 전체 {r['total']}개)")

    except KeyboardInterrupt:
        print("\n\n사용자가 중단했습니다.")
    except Exception as e:
        print(f"\n[오류] {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            driver.quit()
        except:
            pass


if __name__ == "__main__":
    run()
    input("\nPress any key to continue . . . ")
