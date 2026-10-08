"""
애드랭크 순위 갱신 시각 확인 도구 (읽기 전용 — 시트에 아무것도 쓰지 않음)

키워드 시트의 업체 일부를 정해진 간격으로 반복 조회해서
rank_watch.csv 에 (시각, 키워드, 상호, MID, 순위)를 쌓는다.
회차마다 직전 회차 대비 순위가 바뀐 업체 수를 출력하므로,
많이 바뀐 회차의 시각 = 애드랭크 갱신 시각.

사용: rank_watch.bat 실행 후 창을 켜둔 채로 두기. 끝내려면 창 닫기(또는 Ctrl+C).
"""

import csv
import os
import random
import sys
import time
from datetime import datetime

import main

INTERVAL_MINUTES = 30   # 조회 간격
SAMPLE_SIZE = 20        # 매 회차 조회할 업체 수 (키워드 시트에서 무작위 고정)
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rank_watch.csv")


def pick_sample(config):
    keyword_sheet, _ = main.connect_sheets(config)
    businesses = [b for b in main.read_keywords(keyword_sheet) if b["keyword"] and b["name"]]
    mids = {}
    for row in keyword_sheet.get_all_values()[1:]:
        if len(row) > 2 and row[1].strip():
            mids[(row[0].strip(), row[1].strip())] = row[2].strip()
    random.seed(1)  # 매번 같은 업체를 보도록 고정
    sample = random.sample(businesses, min(SAMPLE_SIZE, len(businesses)))
    for b in sample:
        b["mid"] = mids.get((b["keyword"], b["name"]), "")
    return sample


def login(driver, config):
    driver.get("https://adrank.co.kr/")
    main.auto_fill_login(driver, config)
    time.sleep(5)
    main.dismiss_popups(driver)


def find_rank(rows, biz):
    for r in rows:
        if biz["mid"] and r["mid"] == biz["mid"]:
            return r["rank"]
    for r in rows:
        if r["name"] == biz["name"]:
            return r["rank"]
    return "미발견"


def run():
    config = main.load_config()
    print("키워드 시트에서 확인할 업체 고르는 중...")
    sample = pick_sample(config)
    print(f"  -> {len(sample)}개 업체, {INTERVAL_MINUTES}분 간격으로 조회")
    print(f"  -> 결과 파일: {OUT_FILE}\n")

    new_file = not os.path.exists(OUT_FILE)
    driver = main.setup_browser()
    login(driver, config)
    previous = {}
    try:
        while True:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            current = {}
            for biz in sample:
                res = main.api_search_place(driver, biz["keyword"])
                if not (isinstance(res, dict) and res.get("result")):
                    login(driver, config)  # 세션 만료 시 재로그인 후 한 번 더
                    res = main.api_search_place(driver, biz["keyword"])
                items = (res.get("data") or {}).get("list") or [] if isinstance(res, dict) else []
                current[biz["name"]] = find_rank(main._parse_api_rows(items), biz) if items else "조회실패"
                time.sleep(3)

            with open(OUT_FILE, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                if new_file:
                    w.writerow(["시각", "키워드", "상호", "MID", "순위"])
                    new_file = False
                for biz in sample:
                    w.writerow([now, biz["keyword"], biz["name"], biz["mid"], current[biz["name"]]])

            if previous:
                changed = sum(1 for k, v in current.items() if previous.get(k) != v)
                print(f"[{now}] 조회 완료 — 직전 대비 순위 바뀐 업체: {changed}/{len(sample)}")
            else:
                print(f"[{now}] 첫 조회 완료")
            previous = current
            time.sleep(INTERVAL_MINUTES * 60)
    except KeyboardInterrupt:
        print("\n중단했습니다.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    run()
