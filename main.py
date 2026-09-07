import json
import re
import webbrowser
from datetime import UTC, date, datetime, time, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5
from webbrowser import Error as BrowserError
from zoneinfo import ZoneInfo

import httpx
from google.auth.exceptions import GoogleAuthError
from google_auth_oauthlib.flow import InstalledAppFlow, WSGITimeoutError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from httplib2 import HttpLib2Error
from icalendar import Alarm, Calendar, Event
from oauthlib.oauth2 import OAuth2Error
from requests.exceptions import RequestException


TIMEZONE = ZoneInfo("Asia/Shanghai")
# Tangerine：日历预设为 4，事件预设为 6。
CALENDAR_COLOR_ID = "4"
CALENDAR_COLOR = "#F4511E"
URL = "https://jw.jnu.edu.cn/jwapp/sys/wdkb/modules/xskcb/xskcb.do"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}
# 来源：https://cybsec.jnu.edu.cn/2023/1117/c39719a781573/page.htm
PERIODS = [
    ("08:00", "08:45"), ("08:55", "09:40"), ("10:00", "10:45"),
    ("10:55", "11:40"), ("12:40", "13:25"), ("13:35", "14:20"),
    ("14:30", "15:15"), ("15:25", "16:10"), ("16:20", "17:05"),
    ("17:15", "18:00"), ("19:00", "19:45"), ("19:55", "20:40"),
    ("20:50", "21:35"),
]
LOCATIONS = {
    "三楼机房1": "暨南大学实验楼C30-06（三楼机房1）",
    "电子技术基础实验室": "暨南大学实验楼1-407（电子技术基础实验室）",
    "阶梯4": "暨南大学教学楼阶梯教室4",
}
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist",
]
CALLBACK_PATH = "/a_very_long_path_to_prevent_token_leak_and_you_should_never_screenshare_this/"
GOOGLE_ERRORS = (HttpError, GoogleAuthError, HttpLib2Error, OAuth2Error, RequestException,
                 WSGITimeoutError, BrowserError, OSError, ValueError)


def google_event_body(event):
    recurrence = ["RRULE:" + event["rrule"].to_ical().decode("ascii")]
    excluded = event.get("exdate", [])
    if not isinstance(excluded, list):
        excluded = [excluded]
    for group in excluded:
        values = [entry.dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ") for entry in group.dts]
        recurrence.append("EXDATE:" + ",".join(values))
    return {
        "iCalUID": str(event["uid"]),
        "summary": str(event["summary"]),
        "description": str(event["description"]),
        "location": str(event["location"]),
        "start": {"dateTime": event.decoded("dtstart").isoformat(), "timeZone": "Asia/Shanghai"},
        "end": {"dateTime": event.decoded("dtend").isoformat(), "timeZone": "Asia/Shanghai"},
        "recurrence": recurrence,
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 15}]},
    }


def optional_google_import(calendar):
    def read_choice(prompt, choices, default):
        while True:
            answer = input(prompt).strip().lower() or default
            if answer in choices:
                return answer
            print(f"输入无效。请输入 {' / '.join(choices)}。")

    def google_error_message(error):
        if isinstance(error, WSGITimeoutError):
            return "等待 Google 授权超时。请重新运行，并在 3 分钟内完成授权。"
        if isinstance(error, BrowserError):
            return "无法打开浏览器。请设置默认浏览器后重新运行。"
        if isinstance(error, HttpError):
            status = error.resp.status
            if status == 403:
                return "Google 拒绝访问。请检查 Calendar API、授权权限和目标日历的写入权限。"
            if status == 401:
                return "Google 授权无效。请重新运行并授权。"
            if status == 429:
                return "Google 请求过于频繁。请稍后重试。"
            return f"Google 请求失败，HTTP 状态码为 {status}。请稍后重试。"
        if isinstance(error, (GoogleAuthError, OAuth2Error)):
            return "Google 授权未完成。请检查测试用户和授权权限后重试。"
        if isinstance(error, json.JSONDecodeError):
            return "credentials.json 不是有效的 JSON 文件。请重新下载桌面应用凭据。"
        if isinstance(error, (RequestException, HttpLib2Error, OSError)):
            return "Google 连接或文件操作失败。请检查网络、凭据文件和本机回调端口。"
        return str(error)

    def find_events(uid):
        matches = []
        page_token = None
        while True:
            page = service.events().list(
                calendarId=calendar_id, iCalUID=uid, singleEvents=False,
                showDeleted=False, pageToken=page_token,
            ).execute()
            matches.extend(item for item in page.get("items", [])
                           if item.get("status") != "cancelled" and not item.get("recurringEventId"))
            page_token = page.get("nextPageToken")
            if not page_token:
                return matches

    service = None
    started = False
    counts = {"新增": 0, "覆盖": 0, "修复": 0, "跳过": 0, "失败": 0}
    color_ok = False
    conflict_action = None
    try:
        if read_choice("是否导入 Google Calendar 并设置提醒和颜色？[y/N]：", ("y", "n"), "n") == "n":
            return 0

        # 每次重新授权，令牌仅保留在内存中。
        config = json.loads(Path("credentials.json").read_text(encoding="utf-8-sig"))
        installed = config.get("installed") if isinstance(config, dict) else None
        if not isinstance(installed, dict) or not all(installed.get(key) for key in (
            "client_id", "client_secret", "auth_uri", "token_uri",
        )):
            raise ValueError("credentials.json 必须是 Google 桌面应用的 OAuth 凭据。")
        flow = InstalledAppFlow.from_client_config(config, GOOGLE_SCOPES)
        callback_response = None

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                nonlocal callback_response
                target = urlsplit(self.path)
                if target.path != CALLBACK_PATH:
                    self.send_response(404)
                    self.end_headers()
                    return
                if target.query:
                    callback_response = flow.redirect_uri + "?" + target.query
                page = (
                    '<!doctype html><meta charset="utf-8">'
                    '<script>history.replaceState(null, "", location.pathname);</script>'
                    '<p>请返回终端查看授权结果。</p>'
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)

            def log_message(self, format, *args):
                pass

        # SDK 默认使用根路径，此处保留其 state 和 PKCE 流程，仅替换回调服务。
        with HTTPServer(("127.0.0.1", 9028), CallbackHandler) as server:
            flow.redirect_uri = f"http://127.0.0.1:9028{CALLBACK_PATH}"
            auth_url, _ = flow.authorization_url(access_type="online", prompt="consent select_account")
            if not webbrowser.open(auth_url, new=1):
                raise BrowserError()
            print("请在 3 分钟内完成浏览器授权。")
            deadline = monotonic() + 180
            server.timeout = 1
            while callback_response is None:
                if monotonic() >= deadline:
                    raise WSGITimeoutError()
                server.handle_request()
        flow.fetch_token(authorization_response=callback_response.replace("http://", "https://", 1), timeout=30)
        credentials = flow.credentials
        granted = credentials.granted_scopes if credentials.granted_scopes is not None else credentials.scopes
        if not set(GOOGLE_SCOPES).issubset(granted or []):
            raise ValueError("未获得全部日历权限。请重新授权并同意两项权限。")
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

        # 用户选择可写日历后，才开始修改。
        calendars = []
        page_token = None
        while True:
            page = service.calendarList().list(
                minAccessRole="writer", showHidden=True, pageToken=page_token,
            ).execute()
            calendars.extend(item for item in page.get("items", [])
                             if item.get("accessRole") in ("writer", "owner") and not item.get("deleted"))
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        if not calendars:
            print("该账号没有可写日历。请在 Google Calendar 中创建日历后重试。")
            return 0
        for number, item in enumerate(calendars, 1):
            print(f"{number}. {item.get('summaryOverride') or item.get('summary', '未命名日历')} [{item['id']}]")
        while True:
            answer = input("请输入目标日历编号，输入 0 取消：").strip()
            if answer == "0":
                print("Google 导入已取消。已保留 calendar.ics。")
                return 0
            if answer.isascii() and answer.isdigit() and 1 <= int(answer) <= len(calendars):
                calendar_id = calendars[int(answer) - 1]["id"]
                break
            print("编号无效。请重新输入。")

        started = True
        try:
            service.calendarList().patch(
                calendarId=calendar_id,
                body={"colorId": CALENDAR_COLOR_ID},
            ).execute()
            entry = service.calendarList().get(calendarId=calendar_id).execute()
            if entry.get("colorId") != CALENDAR_COLOR_ID:
                raise ValueError("Google 返回的日历颜色不是 Tangerine。请在网页中核对。")
            color_ok = True
        except GOOGLE_ERRORS as error:
            print(f"颜色设置未通过验证：{google_error_message(error)}")
        for event in calendar.walk("VEVENT"):
            body = google_event_body(event)
            try:
                matches = find_events(body["iCalUID"])
                if len(matches) > 1:
                    print(f"同一 UID 对应多个系列，已跳过：{body['summary']}")
                    counts["跳过"] += 1
                    continue
                action = "新增"
                if matches:
                    choice = conflict_action
                    if choice is None:
                        print(f"课程已存在：{body['summary']}，开始时间：{body['start']['dateTime']}")
                        choice = read_choice(
                            "请选择：(s)kip 跳过 / (o)verride 覆盖 / (f)ix 修复提醒，后加 a 应用于全部冲突 [s]：",
                            ("s", "o", "f", "sa", "oa", "fa"), "s",
                        )
                        if choice.endswith("a"):
                            conflict_action = choice = choice[0]
                    if choice == "s":
                        counts["跳过"] += 1
                        continue
                    changes = ({key: value for key, value in body.items() if key != "iCalUID"}
                               if choice == "o" else {"reminders": body["reminders"]})
                    result = service.events().patch(
                        calendarId=calendar_id, eventId=matches[0]["id"], body=changes,
                        sendUpdates="none",
                    ).execute()
                    action = "覆盖" if choice == "o" else "修复"
                else:
                    try:
                        result = service.events().import_(calendarId=calendar_id, body=body).execute()
                    except (HttpError, GoogleAuthError, HttpLib2Error, RequestException, OSError) as error:
                        if isinstance(error, HttpError) and error.resp.status < 500 and error.resp.status != 409:
                            raise
                        # 导入响应丢失时先查询 UID，避免再次创建相同课程。
                        matches = find_events(body["iCalUID"])
                        if len(matches) != 1:
                            raise ValueError("导入结果无法确认。未再次创建课程，请稍后重新运行并检查重复课程。") from None
                        result = matches[0]
                saved = service.events().get(calendarId=calendar_id, eventId=result["id"]).execute()
                if saved.get("reminders") != body["reminders"]:
                    raise ValueError("日程已写入，但提前 15 分钟的提醒未通过验证。")
                if action != "修复":
                    # 系列写入成功不代表首个实例存在，回读实际展开结果。
                    expected_start = event.decoded("dtstart")
                    expected_end = event.decoded("dtend")
                    stored_start = saved.get("start", {}).get("dateTime")
                    if not stored_start or datetime.fromisoformat(stored_start) != expected_start:
                        raise ValueError(f"系列开始时间不一致。预期 {expected_start.isoformat()}，返回 {stored_start or '缺失'}。")
                    first_instances = service.events().instances(
                        calendarId=calendar_id, eventId=result["id"],
                        originalStart=expected_start.isoformat(),
                        showDeleted=True,
                    ).execute().get("items", [])
                    cancelled = [item for item in first_instances
                                 if item.get("status") == "cancelled"
                                 and item.get("recurringEventId") == result["id"]
                                 and item.get("originalStartTime", {}).get("dateTime")
                                 and datetime.fromisoformat(item["originalStartTime"]["dateTime"]) == expected_start]
                    if len(cancelled) > 1:
                        raise ValueError("首个时段对应多个已取消实例。请检查远端日历。")
                    if cancelled:
                        # 覆盖系列不会清除已取消的例外，需恢复确切的首个实例。
                        instance_id = cancelled[0]["id"]
                        instance_body = {key: body[key] for key in (
                            "summary", "description", "location", "start", "end", "reminders",
                        )}
                        instance_body["status"] = "confirmed"
                        service.events().patch(
                            calendarId=calendar_id, eventId=instance_id,
                            body=instance_body, sendUpdates="none",
                        ).execute()
                        restored = service.events().get(calendarId=calendar_id, eventId=instance_id).execute()
                        if restored.get("status") == "cancelled" or restored.get("reminders") != body["reminders"]:
                            raise ValueError("首个时段恢复后仍未通过状态或提醒验证。")
                        first_instances = service.events().instances(
                            calendarId=calendar_id, eventId=result["id"],
                            originalStart=expected_start.isoformat(), showDeleted=True,
                        ).execute().get("items", [])
                    first = next((item for item in first_instances
                                  if item.get("start", {}).get("dateTime")
                                  and datetime.fromisoformat(item["start"]["dateTime"]) == expected_start
                                  and item.get("status") != "cancelled"), None)
                    if first is None:
                        cancelled = any(item.get("status") == "cancelled" for item in first_instances)
                        detail = "返回了已取消实例" if cancelled else "未返回对应实例"
                        raise ValueError(f"首个上课时段缺失：{expected_start.isoformat()}（{detail}，系列 ID：{result['id']}）。")
                    stored_end = first.get("end", {}).get("dateTime")
                    if not stored_end or datetime.fromisoformat(stored_end) != expected_end:
                        raise ValueError(f"首个上课时段结束时间不一致：{expected_start.isoformat()}。")
                counts[action] += 1
                print(f"已{action}：{body['summary']}")
            except GOOGLE_ERRORS as error:
                counts["失败"] += 1
                print(f"课程处理失败：{body['summary']}。{google_error_message(error)}")
        return 0 if color_ok and not counts["失败"] else 1
    except (EOFError, KeyboardInterrupt):
        print("\nGoogle 导入已取消。已保留 calendar.ics，远端已完成的修改不会撤销。")
    except GOOGLE_ERRORS as error:
        print(f"Google 导入未完成：{google_error_message(error)} 已保留 calendar.ics。")
    finally:
        if started:
            print("Google 导入结果：" + "，".join(f"{key} {value}" for key, value in counts.items()) + "。")
        if service is not None:
            service.close()
    return 1


def semester_for(today):
    year = today.year
    if today >= date(year, 9, 1):
        return f"{year}-{year + 1}-1"
    term = 2 if today >= date(year, 2, 15) else 1
    return f"{year - 1}-{year}-{term}"


def read_cookies(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict) and isinstance(data.get("cookies"), list):
        data = data["cookies"]
    pairs = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                raise ValueError("Cookie 数组格式无效。请重新导出 Cookie。")
            domain = item.get("domain", "")
            if not isinstance(domain, str):
                raise ValueError("Cookie 域名必须是字符串。请重新导出 Cookie。")
            domain = domain.lstrip(".").lower()
            if domain and not ("jw.jnu.edu.cn" == domain or "jw.jnu.edu.cn".endswith("." + domain)):
                continue
            pairs.append((item.get("name"), item.get("value")))
    elif isinstance(data, dict):
        pairs = list(data.items())
    else:
        raise ValueError("Cookie 格式无效。请提供数组或名称到值的映射。")
    if not pairs:
        raise ValueError("未找到课表网站的 Cookie。请重新导出 Cookie。")
    for name, value in pairs:
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("Cookie 名称和值必须是字符串。")
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
            raise ValueError("Cookie 名称无效。请重新导出 Cookie。")
        if any(ord(char) < 32 or ord(char) >= 127 or char == ";" for char in value):
            raise ValueError("Cookie 值格式无效。请重新导出 Cookie。")
    return "; ".join(f"{name}={value}" for name, value in pairs)


def read_start_date():
    while True:
        raw = input("请输入教学第 1 周的周一日期（YYYY-MM-DD）：").strip()
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                raise ValueError
            start = date.fromisoformat(raw)
            if start.weekday() != 0:
                raise ValueError
            return start
        except ValueError:
            print("日期无效或不是周一。请按 YYYY-MM-DD 格式重新输入。")


def fetch_rows(client, semester):
    rows = []
    total = None
    page = 1
    while total is None or len(rows) < total:
        response = client.post(URL, data={
            "XNXQDM": semester, "pageSize": "100", "pageNumber": str(page),
        })
        if response.status_code in (301, 302, 303, 307, 308, 401, 403):
            raise ValueError("登录已失效或访问受限。请更新 cookies.json。")
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError:
            raise ValueError("接口未返回 JSON。请检查 cookies.json 是否已失效。") from None
        if not isinstance(data, dict) or str(data.get("code")) != "0":
            raise ValueError("课表请求失败。请检查登录状态和当前学期。")
        try:
            result = data["datas"]["xskcb"]
            batch = result["rows"]
            count = int(result["totalSize"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("课表响应缺少有效的 rows 或 totalSize 字段。") from None
        if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch) or count < 0:
            raise ValueError("课表记录格式无效。请检查接口响应。")
        if total is not None and count != total:
            raise ValueError("分页期间课表总数发生变化。请重新运行。")
        total = count
        if (not batch and len(rows) < total) or len(rows) + len(batch) > total:
            raise ValueError("接口返回的记录数不完整。请重新运行。")
        if any(str(row.get("XNXQDM")) != semester for row in batch):
            raise ValueError("返回课表与请求学期不一致。请检查接口响应。")
        rows.extend(batch)
        page += 1
    return rows


def text_field(row, name):
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"排课缺少有效的 {name} 字段。请检查接口响应。")
    return value.strip()


def course_times(row):
    first, last = int(row["KSJC"]), int(row["JSJC"])
    if first < 1 or last < first:
        raise ValueError("课程节次范围无效。请检查接口响应。")
    actual_start, actual_end = row.get("SKKSSJ"), row.get("SKJSSJ")
    if actual_start or actual_end:
        try:
            start, end = time.fromisoformat(actual_start), time.fromisoformat(actual_end)
        except (TypeError, ValueError):
            raise ValueError("课程实际时间无效。需要 HH:MM 或 HH:MM:SS 格式。") from None
        if start.tzinfo or end.tzinfo:
            raise ValueError("课程实际时间应为北京时间，不应包含时区偏移。")
    else:
        if last > len(PERIODS):
            raise ValueError("节次超出内置作息表。请补充脚本中的 PERIODS。")
        start = time.fromisoformat(PERIODS[first - 1][0])
        end = time.fromisoformat(PERIODS[last - 1][1])
    if end <= start:
        raise ValueError("课程结束时间必须晚于开始时间。")
    # 剔除作息表中至少 30 分钟的长休息，保留普通课间。
    segments = [(start, end)]
    for previous, following in zip(PERIODS, PERIODS[1:]):
        break_start = time.fromisoformat(previous[1])
        break_end = time.fromisoformat(following[0])
        gap = (break_end.hour * 60 + break_end.minute) - (break_start.hour * 60 + break_start.minute)
        if gap < 30:
            continue
        remaining = []
        for segment_start, segment_end in segments:
            if segment_end <= break_start or segment_start >= break_end:
                remaining.append((segment_start, segment_end))
            else:
                if segment_start < break_start:
                    remaining.append((segment_start, break_start))
                if segment_end > break_end:
                    remaining.append((break_end, segment_end))
        segments = remaining
    if not segments:
        raise ValueError("课程时间全部落在长休息内。请检查接口响应。")
    return segments


def course_location(row, known):
    name = str(row.get("JASMC") or "").strip()
    code = str(row.get("JASDM") or "").strip()
    key = (name, code)
    if key in known:
        return known[key]
    if name in LOCATIONS:
        return LOCATIONS[name]
    for candidate in (name, code):
        for pattern, building in (
            (r"(?:实验楼|实)\s*([A-Za-z]?\d+(?:-\d+)*)", "实验楼"),
            (r"(?:教学楼|教)\s*([A-Za-z]?\d+(?:-\d+)*)", "教学楼"),
            (r"阶梯(?:教室)?\s*(\d+)", "教学楼阶梯教室"),
        ):
            match = re.search(pattern, candidate)
            if match:
                return f"暨南大学{building}{match.group(1)}"
    print(f"无法识别地点：{name or '未提供'}。教室代码：{code or '未提供'}。")
    while True:
        location = input("请输入完整地点（包含学校、楼栋和教室）：").strip()
        if location:
            known[key] = location
            return location
        print("地点不能为空。请重新输入。")


def build_calendar(rows, start_date, semester):
    calendar = Calendar()
    calendar.add("prodid", "-//Jinan University Class Calendar//CN")
    calendar.add("version", "2.0")
    calendar.add("x-wr-calname", f"暨南大学课表 {semester}")
    calendar.add("x-wr-timezone", "Asia/Shanghai")
    calendar.add("x-apple-calendar-color", CALENDAR_COLOR)
    total = 0
    last_date = start_date
    known = {}
    identities = set()
    for index, row in enumerate(rows, 1):
        try:
            name = text_field(row, "KCM")
            number = text_field(row, "KCH")
            schedule = text_field(row, "SKSJ")
            bitmap = text_field(row, "SKZC")
            if not re.fullmatch(r"[01]+", bitmap) or "1" not in bitmap:
                raise ValueError("上课周次必须是至少包含一个 1 的位图。")
            weekday = int(row["SKXQ"])
            if weekday not in range(1, 8):
                raise ValueError("上课星期必须为 1 至 7。")
            weeks = [week for week, active in enumerate(bitmap, 1) if active == "1"]
            segments = course_times(row)
            days = [start_date + timedelta(weeks=week - 1, days=weekday - 1) for week in weeks]
            last_date = max(last_date, days[-1])
            identity = json.dumps([
                semester, start_date.isoformat(), row.get("KBID") or row.get("WID"),
                number, row.get("JXBID"), weekday, row["KSJC"], row["JSJC"],
                bitmap, row.get("JASDM"), row.get("JASMC"), row.get("SKJS"),
            ], ensure_ascii=False)
            if identity in identities:
                raise ValueError("接口返回重复排课记录。请重新请求课表。")
            identities.add(identity)
            location = course_location(row, known)
            for segment_index, (start_time, end_time) in enumerate(segments):
                # 第一段沿用旧 UID，覆盖导入时可修正已有的整段日程。
                segment_identity = identity if segment_index == 0 else f"{identity}|segment:{segment_index}"
                event = Event()
                event.add("uid", str(uuid5(NAMESPACE_URL, segment_identity)) + "@class-calendar.local")
                event.add("dtstamp", datetime.now(TIMEZONE))
                event.add("dtstart", datetime.combine(days[0], start_time, TIMEZONE))
                event.add("dtend", datetime.combine(days[0], end_time, TIMEZONE))
                event.add("summary", f"课程-{name}")
                teacher = str(row.get("SKJS") or "")
                original_location = str(row.get("JASMC") or "")
                event.add("description", f"{number}-{name}\n{teacher}\n{schedule},{original_location}")
                event.add("location", location)
                gaps = {b - a for a, b in zip(weeks, weeks[1:])}
                interval = 2 if gaps == {2} else 1
                span = (weeks[-1] - weeks[0]) // interval + 1
                event.add("rrule", {"freq": "weekly", "interval": interval, "count": span})
                active_weeks = set(weeks)
                for week in range(weeks[0], weeks[-1] + 1, interval):
                    if week not in active_weeks:
                        day = start_date + timedelta(weeks=week - 1, days=weekday - 1)
                        event.add("exdate", datetime.combine(day, start_time, TIMEZONE))
                alarm = Alarm()
                alarm.add("action", "DISPLAY")
                alarm.add("trigger", timedelta(minutes=-15))
                alarm.add("description", f"课程-{name}")
                event.add_component(alarm)
                calendar.add_component(event)
                total += len(weeks)
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"第 {index} 条排课无法转换：{error}") from None
    calendar.add_missing_timezones(first_date=start_date, last_date=last_date)
    return calendar, total


def main():
    try:
        cookies = read_cookies(Path("cookies.json"))
        start_date = read_start_date()
        semester = semester_for(start_date)
        print(f"所选学期：{semester}。正在请求课表。")
        with httpx.Client(headers={**HEADERS, "Cookie": cookies}, timeout=30, follow_redirects=False) as client:
            rows = fetch_rows(client, semester)
        if not rows:
            print("所选学期没有排课记录。未生成日历。")
            return 0
        calendar, count = build_calendar(rows, start_date, semester)
        payload = calendar.to_ical()
        temporary = Path("calendar.ics.tmp")
        try:
            temporary.write_bytes(payload)
            temporary.replace("calendar.ics")
        finally:
            temporary.unlink(missing_ok=True)
        print(f"已生成 calendar.ics：{len(calendar.walk('VEVENT'))} 个日程系列，共 {count} 个上课时段。")
        return optional_google_import(calendar)
    except httpx.HTTPStatusError as error:
        print(f"请求失败，HTTP 状态码为 {error.response.status_code}。请检查登录状态后重试。")
    except httpx.RequestError:
        print("网络请求失败或超时。请检查网络后重试。")
    except json.JSONDecodeError:
        print("cookies.json 不是有效的 JSON 文件。请重新导出 Cookie。")
    except UnicodeError:
        print("文件编码无效。请使用 UTF-8 编码。")
    except OSError as error:
        print(f"文件操作失败：{error.filename or '当前目录'}。请检查文件是否存在及访问权限。")
    except ValueError as error:
        print(f"错误：{error}")
    except (EOFError, KeyboardInterrupt):
        print("\n输入已取消。未生成日历。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
