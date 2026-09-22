# -*- coding: utf-8 -*-
"""
MID 동기화 스크립트
- 결과 시트에서 상호/키워드/MID 읽기
- 키워드 시트에서 상호+키워드 일치하는 행의 C열에 MID 기입
"""

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def run():
    import gspread
    from google.oauth2.service_account import Credentials

    print("=" * 50)
    print("  MID 동기화 도구")
    print("=" * 50)

    config = load_config()
    row_interval = config.get("row_interval", 4)
    start_row = config.get("data_start_row", 3)

    # 시트 연결
    print("\n시트 연결 중...")
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
    print("  -> 연결 성공")

    # 결과 시트에서 상호/키워드/MID 읽기
    print("\n결과 시트에서 MID 수집 중...")
    result_values = result_sheet.get_all_values()
    mid_map = {}  # (상호, 키워드) → MID

    idx = start_row - 1
    while idx < len(result_values):
        row = result_values[idx]
        biz_name = row[1].strip() if len(row) > 1 else ""
        if not biz_name:
            break

        biz_keyword = row[2].strip() if len(row) > 2 else ""
        mid_value = ""
        if idx + 2 < len(result_values):
            mid_row = result_values[idx + 2]
            mid_value = mid_row[1].strip() if len(mid_row) > 1 else ""

        if mid_value and biz_keyword:
            mid_map[(biz_name, biz_keyword)] = mid_value
            print(f"  {biz_name} [{biz_keyword}] -> MID: {mid_value}")

        idx += row_interval

    print(f"  -> MID 보유 업체: {len(mid_map)}개")

    # 키워드 시트에서 매칭 후 C열 기입
    print("\n키워드 시트에 MID 기입 중...")
    kw_values = keyword_sheet.get_all_values()
    sheet_title = keyword_sheet.title

    write_cells = []
    for row_idx in range(1, len(kw_values)):
        row = kw_values[row_idx]
        kw = row[0].strip() if len(row) > 0 else ""
        name = row[1].strip() if len(row) > 1 else ""
        current_mid = row[2].strip() if len(row) > 2 else ""

        if not kw and not name:
            break

        if current_mid:
            continue

        mid = mid_map.get((name, kw), "")
        if mid:
            cell_label = gspread.utils.rowcol_to_a1(row_idx + 1, 3)
            write_cells.append({
                "range": f"'{sheet_title}'!{cell_label}",
                "values": [[mid]],
            })
            print(f"  -> {name} [{kw}]: MID={mid}")

    if write_cells:
        keyword_sheet.spreadsheet.values_batch_update(
            {"valueInputOption": "USER_ENTERED", "data": write_cells}
        )
        print(f"\n  -> {len(write_cells)}개 MID 기입 완료")
    else:
        print("\n  -> 기입할 MID 없음 (이미 모두 채워져 있거나 매칭 없음)")

    print("\n" + "=" * 50)
    print("  완료!")
    print("=" * 50)


if __name__ == "__main__":
    run()
    input("\nEnter를 누르면 종료합니다...")
