# -*- coding: utf-8 -*-
"""
애드랭크 패킷(HTTP) 클라이언트 — 브라우저/크롬 없이 로그인·순위 조회

- 로그인: POST /api/auth/login {"id","pwd"} → data.serviceToken
- 조회:   POST /api/place/searchPlaceAnalyze {"keyword","cnt","targetDate"}
          헤더 Authorization: Bearer <serviceToken>, pathName: /place/analyze
  응답 list의 업체별 rankOld = targetDate 날짜에 기록된 순위
  (플레이스 모니터링 '일자별 순위'와 같은 값. 아직 기록이 없는 날짜면 rankOld 자체가 없음)
"""

import re
import time

import requests

BASE_URL = "https://adrank.co.kr"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")


class AdrankError(Exception):
    pass


class AdrankClient:
    def __init__(self, user_id, password):
        self.user_id = user_id
        self.password = password
        self.token = None
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        })

    def login(self):
        res = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"id": self.user_id, "pwd": self.password},
            headers={"pathName": "/login", "Referer": f"{BASE_URL}/login"},
            timeout=30,
        )
        body = res.json()
        token = (body.get("data") or {}).get("serviceToken") if isinstance(body.get("data"), dict) else None
        if not token:
            raise AdrankError(f"로그인 실패: {body.get('responseMsg') or res.status_code}")
        self.token = token
        return True

    def search(self, keyword, target_date=None, cnt=180):
        """키워드 분석 결과(data dict) 반환. target_date: datetime/date 또는 'YYYY.MM.DD'.
        세션 만료(401)면 재로그인 후 재시도.
        애드랭크가 분석 개수 한도를 낮추면(예: '180개까지') 그 숫자로 자동 재시도."""
        body = {"keyword": keyword, "cnt": cnt}
        if target_date is not None:
            body["targetDate"] = target_date if isinstance(target_date, str) else target_date.strftime("%Y.%m.%d")

        for attempt in range(4):
            if not self.token:
                self.login()
            try:
                res = self.session.post(
                    f"{BASE_URL}/api/place/searchPlaceAnalyze",
                    json=body,
                    headers={"Authorization": f"Bearer {self.token}", "pathName": "/place/analyze",
                             "Referer": f"{BASE_URL}/place/analyze"},
                    timeout=90,
                )
                data = res.json()
            except (requests.RequestException, ValueError) as e:
                if attempt == 3:
                    raise AdrankError(f"조회 실패: {e}")
                time.sleep(3)
                continue
            if data.get("responseCode") == 401 or res.status_code == 401:
                self.token = None          # 재로그인 후 재시도
                continue
            if not data.get("result"):
                msg = data.get("responseMsg") or ""
                # "분석 개수는 180개까지 고를 수 있어요." → 한도 숫자로 자동 재시도
                m = re.search(r"(\d+)\s*개까지", msg)
                if m and int(m.group(1)) < body["cnt"]:
                    body["cnt"] = int(m.group(1))
                    continue
                raise AdrankError(f"조회 실패: {msg}")
            return data.get("data") or {}
        raise AdrankError("조회 실패: 로그인 세션을 유지할 수 없습니다")


def parse_rows(items):
    """API list → 업체 dict 목록.
    rank: 현재(최신) 순위, record: targetDate 날짜에 기록된 순위(없으면 None)"""
    rows = []
    for item in items or []:
        place_id = item.get("placeId")
        record = item.get("rankOld")
        rows.append({
            "rank": str(item.get("rank", "")),
            "record": None if record in (None, "") else str(record),
            "name": (item.get("name") or "").strip(),
            "score": "",                                  # 애드랭크 점수 제공 중단
            "kw_list": (item.get("formattedAddress") or "").strip(),  # 주소
            "mid": str(place_id) if place_id else "",
            "url": f"https://m.place.naver.com/place/{place_id}/home" if place_id else "",
        })
    return rows
