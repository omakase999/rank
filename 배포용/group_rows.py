# -*- coding: utf-8 -*-
"""
결과 시트 그룹화 전용 스크립트
- 4행 단위로 기준행+1 ~ 기준행+3을 그룹화
- 이미 그룹화된 행은 스킵
"""

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def connect_result_sheet(config):
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
    wb = gc.open_by_url(config["result_sheet_url"])
    return wb.get_worksheet_by_id(config["result_sheet_gid"])


def get_row_count(result_sheet):
    """시트 전체 행 수"""
    meta = result_sheet.spreadsheet.fetch_sheet_metadata()
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == result_sheet.id:
            return s["properties"]["gridProperties"]["rowCount"]
    return 1000


def flatten_all_row_groups(result_sheet, max_iter=30):
    """모든 행 그룹을 완전히 제거(평탄화).
    deleteDimensionGroup을 전체 범위에 반복 적용 — 한 번에 depth 1단계씩 제거됨.
    ※ fetch_sheet_metadata는 dimensionGroups를 신뢰성 있게 반환하지 않으므로
      batch_update '응답'에 담긴 남은 그룹 수로 판단한다."""
    sid = result_sheet.id
    ss = result_sheet.spreadsheet
    rows = get_row_count(result_sheet)
    for i in range(max_iter):
        try:
            resp = ss.batch_update({"requests": [{
                "deleteDimensionGroup": {
                    "range": {"sheetId": sid, "dimension": "ROWS",
                              "startIndex": 1, "endIndex": rows}
                }
            }]})
        except Exception:
            # 제거할 그룹이 더 없음
            return i
        remaining = 0
        for rep in resp.get("replies", []):
            if "deleteDimensionGroup" in rep:
                remaining = len(rep["deleteDimensionGroup"].get("dimensionGroups", []))
        if remaining == 0:
            return i + 1
    return max_iter


def rebuild_groups(result_sheet, base_rows):
    """업체 기준행마다 (기준행+1 ~ 기준행+3) 단일 그룹 생성. 먼저 전부 평탄화."""
    sid = result_sheet.id
    ss = result_sheet.spreadsheet

    cleared = flatten_all_row_groups(result_sheet)
    print(f"  기존 그룹 평탄화: {cleared}단계 제거")

    requests = []
    for base_row in base_rows:
        # 0-based: 기준행+1(=base_row) ~ 기준행+3, endIndex 배타적
        requests.append({
            "addDimensionGroup": {
                "range": {
                    "sheetId": sid,
                    "dimension": "ROWS",
                    "startIndex": base_row,
                    "endIndex": base_row + 3,
                }
            }
        })

    if not requests:
        return 0

    # 여러 번에 나눠 보내면 중간에 인접 병합/중첩이 생길 수 있어 한 번에 전송
    resp = ss.batch_update({"requests": requests})
    # 응답에서 최종 그룹/최대 depth 확인 (마지막 add 응답에 전체 상태가 담김)
    final_groups = []
    for rep in resp.get("replies", []):
        if "addDimensionGroup" in rep:
            final_groups = rep["addDimensionGroup"].get("dimensionGroups", [])
    max_depth = max((g.get("depth", 1) for g in final_groups), default=0)
    print(f"  그룹 생성 완료: {len(requests)}개 요청, 최종 그룹 {len(final_groups)}개, 최대 depth={max_depth}")
    return len(requests)


def run():
    print("=" * 50)
    print("  결과 시트 그룹화 도구")
    print("=" * 50)

    config = load_config()
    start_row = config.get("data_start_row", 3)
    row_interval = config.get("row_interval", 4)

    print("\n시트 연결 중...")
    result_sheet = connect_result_sheet(config)
    print("  -> 연결 성공")

    # 업체 행 파악 (상호명 있는 행만, 빈 행에서 중단)
    all_values = result_sheet.get_all_values()
    base_rows = []
    idx = start_row - 1
    while idx < len(all_values):
        row = all_values[idx]
        biz_name = row[1].strip() if len(row) > 1 else ""
        if not biz_name:
            break
        base_rows.append(idx + 1)  # 1-based
        idx += row_interval

    print(f"\n총 {len(base_rows)}개 업체 확인")

    print("\n그룹 재생성 중 (기존 중첩 제거 후 4행 단위 단일 그룹)...")
    rebuild_groups(result_sheet, base_rows)

    print("\n" + "=" * 50)
    print("  완료!")
    print("=" * 50)


if __name__ == "__main__":
    run()
    input("\nEnter를 누르면 종료합니다...")
