# -*- coding: utf-8 -*-
"""
길찾기/유입 동기화 스크립트
- 키워드 시트 D열(길찾기), E열(유입) 읽기
- 결과 시트에서 키워드+상호 매칭
- 결과 시트 C열 base+2행에 길찾기, base+3행에 유입 기입
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
    print("  길찾기/유입 동기화 도구")
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

    # 키워드 시트에서 길찾기/유입 읽기
    print("\n키워드 시트에서 길찾기/유입 수집 중...")
    kw_values = keyword_sheet.get_all_values()
    traffic_data = {}  # (상호, 키워드) → (길찾기, 유입)

    for row_idx in range(1, len(kw_values)):
        row = kw_values[row_idx]
        kw = row[0].strip() if len(row) > 0 else ""
        name = row[1].strip() if len(row) > 1 else ""
        gilchajgi = row[3].strip() if len(row) > 3 else ""  # D열
        yuip = row[4].strip() if len(row) > 4 else ""       # E열

        if not kw and not name:
            break

        if gilchajgi or yuip:
            traffic_data[(name, kw)] = (gilchajgi, yuip)
            print(f"  {name} [{kw}] -> 길찾기={gilchajgi}, 유입={yuip}")

    print(f"  -> {len(traffic_data)}개 업체 데이터")

    if not traffic_data:
        print("\n기입할 데이터가 없습니다.")
        return

    # 결과 시트에서 매칭 후 기입
    print("\n결과 시트에 기입 중...")
    result_values = result_sheet.get_all_values()
    sheet_title = result_sheet.title

    write_cells = []
    idx = start_row - 1
    while idx < len(result_values):
        row = result_values[idx]
        biz_name = row[1].strip() if len(row) > 1 else ""
        if not biz_name:
            break

        biz_keyword = row[2].strip() if len(row) > 2 else ""
        base_row = idx + 1  # 1-based

        # 키워드 시트와 매칭
        data = traffic_data.get((biz_name, biz_keyword))
        if not data:
            # 상호명만으로도 매칭 시도
            for (name, kw), val in traffic_data.items():
                if name == biz_name:
                    data = val
                    break

        if data:
            gilchajgi, yuip = data
            if gilchajgi:
                cell_label = gspread.utils.rowcol_to_a1(base_row + 2, 3)  # C열 base+2
                write_cells.append({
                    "range": f"'{sheet_title}'!{cell_label}",
                    "values": [[gilchajgi]],
                })
            if yuip:
                cell_label = gspread.utils.rowcol_to_a1(base_row + 3, 3)  # C열 base+3
                write_cells.append({
                    "range": f"'{sheet_title}'!{cell_label}",
                    "values": [[yuip]],
                })
            print(f"  -> {biz_name}: 길찾기={gilchajgi}, 유입={yuip} ({base_row}행)")

        idx += row_interval

    if write_cells:
        result_sheet.spreadsheet.values_batch_update(
            {"valueInputOption": "USER_ENTERED", "data": write_cells}
        )
        print(f"\n  -> {len(write_cells)}개 셀 기입 완료")
    else:
        print("\n  -> 기입할 데이터 없음")

    print("\n" + "=" * 50)
    print("  완료!")
    print("=" * 50)


if __name__ == "__main__":
    run()
    input("\nEnter를 누르면 종료합니다...")
