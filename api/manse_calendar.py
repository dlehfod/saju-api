from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from korean_lunar_calendar import KoreanLunarCalendar
import json
import re

# 천간/지지
STEMS = ['갑','을','병','정','무','기','경','신','임','계']
BRANCHES = ['자','축','인','묘','진','사','오','미','신','유','술','해']

# 시주 천간 시작점(자시 기준): 갑/기=0, 을/경=2, 병/신=4, 정/임=6, 무/계=8
HOUR_START = {'갑':0,'기':0,'을':2,'경':2,'병':4,'신':4,'정':6,'임':6,'무':8,'계':8}

# 2시간 단위 시간 코드 → 시지 인덱스
TIME_MAP = {'00':0,'02':1,'04':2,'06':3,'08':4,'10':5,'12':6,'14':7,'16':8,'18':9,'20':10,'22':11,'24':0}

def hhmm_to_index(hhmm: str):
    """
    "HH:mm" → 시지 인덱스(0..11)
    자시(23:30~01:29) 경계 포함
    """
    m = re.match(r'^(\d{1,2}):(\d{2})$', hhmm or '')
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))

    # 23:30~23:59 → 자(0)
    if hh == 23 and mm >= 30:
        return 0

    blocks = [
        (23,30, 1,29), (1,30, 3,29), (3,30, 5,29), (5,30, 7,29),
        (7,30, 9,29), (9,30,11,29), (11,30,13,29), (13,30,15,29),
        (15,30,17,29), (17,30,19,29), (19,30,21,29), (21,30,23,29)
    ]
    cur = hh*60 + mm
    for idx, (sH,sM,eH,eM) in enumerate(blocks):
        s = (sH*60+sM) % (24*60)
        e = (eH*60+eM) % (24*60)
        if s <= e:
            if s <= cur <= e:
                return idx
        else:
            # 자시 경계(23:30~01:29)
            if cur >= s or cur <= e:
                return idx

    # 00:00~01:29 → 자(0)
    if 0 <= hh <= 1 and cur <= 89:
        return 0
    return None

def extract_ymd_pairs(ganji_kr: str):
    """
    "계유년 임오월 병인일" → ("계유","임오","병인", "병")
    """
    y = re.search(r'([갑을병정무기경신임계][자축인묘진사오미신유술해])년', ganji_kr or '')
    m = re.search(r'([갑을병정무기경신임계][자축인묘진사오미신유술해])월', ganji_kr or '')
    d = re.search(r'([갑을병정무기경신임계][자축인묘진사오미신유술해])일', ganji_kr or '')
    day_stem = re.search(r'([갑을병정무기경신임계])[^\s]*일', ganji_kr or '')
    return (
        y.group(1) if y else None,
        m.group(1) if m else None,
        d.group(1) if d else None,
        (day_stem.group(1) if day_stem else None)
    )

# 라이브러리 버전 호환 래퍼
def set_solar(cal: KoreanLunarCalendar, y: int, m: int, d: int):
    if hasattr(cal, "setSolar"):
        cal.setSolar(y, m, d)
    elif hasattr(cal, "setSolarDate"):
        cal.setSolarDate(y, m, d)
    else:
        raise AttributeError("KoreanLunarCalendar: setSolar/setSolarDate not found")

def set_lunar(cal: KoreanLunarCalendar, y: int, m: int, d: int, is_leap: bool):
    if hasattr(cal, "setLunar"):
        cal.setLunar(y, m, d, is_leap)
    elif hasattr(cal, "setLunarDate"):
        cal.setLunarDate(y, m, d, is_leap)
    else:
        raise AttributeError("KoreanLunarCalendar: setLunar/setLunarDate not found")

def get_ganji(cal: KoreanLunarCalendar) -> str:
    if hasattr(cal, "getGanji"):
        return cal.getGanji()
    # 일부 구버전 대응(없으면 빈 문자열)
    return ""

def compute_hour_pillar(day_stem_kr: str, hour_idx: int):
    """
    일간 + 시지 인덱스 → 시주(천간+지지)
    """
    if day_stem_kr not in HOUR_START:
        return None
    stem_idx = (HOUR_START[day_stem_kr] + hour_idx) % 10
    stem = STEMS[stem_idx]
    branch = BRANCHES[hour_idx]
    return stem + branch

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            # 쿼리
            birthday = (qs.get('birthday') or [''])[0]      # "YYYYMMDD"
            time_code = (qs.get('timeCode') or [''])[0]     # "00".."24" or "99"
            time_hhmm = (qs.get('time') or [''])[0]         # "HH:mm"
            birthday_type = (qs.get('birthdayType') or ['SOLAR'])[0].upper()  # SOLAR|LUNAR
            gender = (qs.get('gender') or [''])[0]          # 미사용
            is_leap = ((qs.get('isLeap') or ['false'])[0].lower() == 'true')

            # 입력 검증
            if not re.match(r'^\d{8}$', birthday or ''):
                return self._json(400, {"error":"bad_request","message":"birthday must be YYYYMMDD"})

            y, m, d = int(birthday[:4]), int(birthday[4:6]), int(birthday[6:8])

            # 만세력 설정
            cal = KoreanLunarCalendar()
            if birthday_type == "LUNAR":
                set_lunar(cal, y, m, d, is_leap)
            else:
                set_solar(cal, y, m, d)

            ganji_kr = get_ganji(cal)
            ypair, mpair, dpair, day_stem = extract_ymd_pairs(ganji_kr)
            if not (ypair and mpair and dpair):
                return self._json(500, {"error":"calc_failed","message":"failed to parse pillars"})

            # 시주 인덱스
            hour_idx = None
            if time_code in TIME_MAP:
                hour_idx = TIME_MAP[time_code]
            if hour_idx is None and time_hhmm:
                hour_idx = hhmm_to_index(time_hhmm)

            # 결과 문자열
            result = f"{ypair}년 {mpair}월 {dpair}일"
            if hour_idx is not None and day_stem:
                hpair = compute_hour_pillar(day_stem, hour_idx)
                if hpair:
                    result += f" {hpair}시"

            return self._json(200, {"result": result})

        except Exception as e:
            return self._json(500, {"error":"exception","message":str(e)})

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return
