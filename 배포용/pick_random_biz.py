# -*- coding: utf-8 -*-
"""
후순위 업체 랜덤 추출기
- 키워드 시트 A열의 키워드로 adrank 검색
- GUI '추출 순위 범위'(config.json pick_rank_min~pick_rank_max, 기본 60~180) 사이에서 랜덤 1곳 선택
  (결과가 범위 끝까지 안 나오면 마지막 등수까지, 범위에 아무도 없으면 뒤쪽 1/3에서 선택)
- B열에 상호명 기록
"""

import time
import json
import os
import sys
import re
import random
from datetime import datetime


CONFIG_PATH = os.path.join((os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))), "config.json")

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


# 애드랭크 조회는 패킷(HTTP) — 로그인/예약 대기는 main.connect_adrank 재사용
import main as _main
from adrank_api import AdrankError, parse_rows


def connect_adrank(config):
    global scheduled_start_time
    # GUI가 이 모듈에 걸어준 예약시각을 main 쪽으로 전달
    _main.scheduled_start_time = scheduled_start_time
    scheduled_start_time = None
    return _main.connect_adrank(config)


def search_results(client, keyword):
    """키워드 조회 → [{rank(int), name, kw_list}] (현재 순위 기준)"""
    rows = parse_rows(client.search(keyword).get("list"))
    results = [{"rank": int(r["rank"]) if r["rank"].isdigit() else 0,
                "name": r["name"], "kw_list": r["kw_list"]} for r in rows]
    print(f"  -> {len(results)}개 업체 추출 (최고 순위~{max((r['rank'] for r in results), default=0)}등)")
    return results


# ─────────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────────
def run():
    print("\n" + "=" * 60)
    print("   후순위 업체 랜덤 추출기")
    print("=" * 60)

    config = load_config()
    # 추출 순위 범위 (GUI '추출 순위 범위' 칸에서 저장한 값, 없으면 60~180)
    RANK_MIN = int(config.get("pick_rank_min", 60))
    RANK_MAX = int(config.get("pick_rank_max", 180))
    print(f"\n  추출 순위 범위: {RANK_MIN}~{RANK_MAX}위")

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

    # [3] 애드랭크 로그인 + 검색 (패킷)
    print("\n[3/3] 애드랭크 로그인 중...")
    client = connect_adrank(config)

    try:

        results_summary = []

        for i, kw_info in enumerate(keywords, 1):
            keyword = kw_info["keyword"]
            row_num = kw_info["row"]
            print(f"\n{'─'*50}")
            print(f"  [{i}/{len(keywords)}] '{keyword}' 검색 (→ {row_num}행)")

            try:
                all_results = search_results(client, keyword)
            except AdrankError as e:
                print(f"    {e}, 스킵")
                continue
            time.sleep(float(config.get("api_delay", 1.5)))

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

            # 지정 범위(RANK_MIN~RANK_MAX)에서 필터 — 결과가 RANK_MAX까지 안 나오면 마지막 등수까지
            upper_bound = min(RANK_MAX, max_rank)
            candidates = [r for r in named_results if RANK_MIN <= r["rank"] <= upper_bound]

            if candidates:
                print(f"    {RANK_MIN}~{upper_bound}위 후보 {len(candidates)}개")
            else:
                # 범위에 업체가 없으면(결과가 RANK_MIN위까지 안 나옴) → 뒤쪽 1/3에서 선택
                cutoff = max(1, total_count * 2 // 3)
                candidates = sorted(named_results, key=lambda r: r["rank"])[cutoff:]
                if not candidates:
                    candidates = named_results[-1:]
                print(f"    {RANK_MIN}~{RANK_MAX}위 업체 없음(마지막 {max_rank}위) → 뒤쪽 1/3"
                      f"({candidates[0]['rank']}~{candidates[-1]['rank']}위)에서 선택")

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


if __name__ == "__main__":
    run()
    input("\nPress any key to continue . . . ")
