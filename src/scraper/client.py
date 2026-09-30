import asyncio
import logging
import re
from collections import Counter
from datetime import timedelta
from typing import Optional, Dict, Any, List
from urllib.parse import parse_qs, urlsplit
import httpx
from bs4 import BeautifulSoup

from src.config import BOT_ROOT, settings
from src.dates import parse_portal_date, parse_stamp
from src.scraper.parsers import (
    ADMITTED_STAGE,
    StudentListLayoutError,
    extract_csrf_token,
    is_admitted,
    parse_dashboard_metrics,
    parse_tables,
    parse_hangeul_live_dashboard,
    parse_students_page,
    parse_consultation_requests,
    consultation_table,
    consultation_view,
    parse_pending_payments,
    parse_window_applications,
    count_under_review,
    parse_calendar_events,
    student_matches,
    student_pager,
    student_uids,
    verified_between,
    verified_on_day,
    target_day,
)
from src.scraper.ocr_validator import unchecked_result, validate_passport_data
from src.scraper.mock_data import MOCK_DASHBOARD_STATS, MOCK_APPLICATIONS, MOCK_INQUIRIES

logger = logging.getLogger("hangeul.client")

# students.php lists 50 students a page; a cap so a misread "Page 1 of N" can never loop for long.
STUDENTS_PER_PAGE = 50
MAX_STUDENT_PAGES = 40
# A portal page read may take its time downloading (consult_requests.php is ~2 MB), but a host
# that does not even take the connection is given up on quickly.
CONNECT_TIMEOUT = 10.0
# consult_requests.php lists at most this many requests under its status tabs (newest first); the
# tabs themselves count every request. The lightest view whose tabs still count every request:
# a status tab opened without a date filter (a handful of rows instead of the ~2 MB full list).
CONSULT_LIST_LIMIT = 500
CONSULT_TOTALS_VIEW = {"status": "file_opened"}
# A window of days longer than the list shows is read again in parts (read_consultation_range);
# a cap so a list that keeps changing can never loop for long.
CONSULT_RANGE_MAX_READS = 16


def _error_text(e: Exception) -> str:
    """An exception as text that is never empty (str(httpx.ReadTimeout('')) is '')."""
    return str(e) or type(e).__name__


class PortalUnavailable(RuntimeError):
    """The portal could not be read, so nothing may be reported as a figure (never a 0, "none" or
    an empty list). Raised by HangeulAdminClient.portal_get / fetch_html and every reader built on
    them: a failed login, a page that still ends on login.php after logging in again (session
    expired), an HTTP error status, a timeout or refused connection (`unreachable` True: the
    portal did not answer at all), or a page whose layout is not recognised.
    str(e) / e.reason is a short plain-English reason for the reply."""

    def __init__(self, reason: str, *, unreachable: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.unreachable = unreachable


def portal_error_reason(e: Exception) -> str:
    """A failed portal read as a short reason for a reply: PortalUnavailable's own reason, "the
    portal did not answer in time" for a timeout, "could not connect to the portal" for a refused
    connection; anything else as its type and text."""
    if isinstance(e, PortalUnavailable):
        return e.reason
    if isinstance(e, (asyncio.TimeoutError, httpx.TimeoutException)):
        return "the portal did not answer in time"
    if isinstance(e, httpx.TransportError):
        return f"could not connect to the portal ({type(e).__name__})"
    return f"{type(e).__name__}: {_error_text(e)}"


def _ended_on_login(resp: httpx.Response) -> bool:
    """Whether a response ended on the login page (a redirect there: the session expired)."""
    return resp.url.path.rstrip("/").endswith("login.php")


def _span(first, last) -> str:
    """'28 Sep 2026' for one day, '01 Sep 2026 – 29 Sep 2026' for a window of days."""
    return f"{first:%d %b %Y}" if first == last else f"{first:%d %b %Y} – {last:%d %b %Y}"


class _ListChanged(PortalUnavailable):
    """consult_requests.php read in parts did not add up: the list changed between the reads."""


def _stamp_guard(students: List[Dict[str, Any]]) -> None:
    """Raise PortalUnavailable when the list's payment-verification stamps cannot be read: student
    rows but no "Payment verified by" line on any of them (the line's wording changed), or a line
    whose date the bot cannot read. Then no day's verifications can be told, not even "none"."""
    lines = [s for s in students if s.get("verified_line")]
    if students and not lines:
        raise PortalUnavailable(f"students.php: {len(students)} student rows but no 'Payment verified by' "
                                "line on any of them (layout not recognised)")
    unreadable = [s for s in lines if parse_stamp(s.get("verified_stamp", "")) is None]
    if unreadable:
        raise PortalUnavailable(f"students.php: {len(unreadable)} verification line(s) with a date the bot "
                                "cannot read (layout not recognised)")

class HangeulAdminClient:
    """HTTP Client for Hangeul Admin with session persistence, CSRF handling & mock support."""

    def __init__(self):
        self.base_url = settings.HANGEUL_BASE_URL.rstrip("/")
        self.username = settings.HANGEUL_USERNAME
        self.password = settings.HANGEUL_PASSWORD
        self.mock_mode = settings.MOCK_MODE
        
        # User-Agent mimicking a modern browser
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        self.client = httpx.AsyncClient(
            headers=self.headers,
            follow_redirects=True,
            timeout=15.0,
            verify=False  # Allow flexible SSL handling
        )
        self.is_authenticated = False

    async def close(self):
        await self.client.aclose()

    async def get_login_page(self) -> Dict[str, Any]:
        """Fetch the login page and extract the CSRF token and cookies. On failure -> {"error",
        "unreachable" (the portal did not answer at all)}."""
        if self.mock_mode:
            return {
                "csrf_token": "mock-csrf-token-12345",
                "session_active": False,
                "mock": True
            }

        url = f"{self.base_url}/login.php"
        try:
            resp = await self.client.get(url, timeout=30.0)
            csrf_token = extract_csrf_token(resp.text)
            return {
                "status_code": resp.status_code,
                "current_url": str(resp.url),
                "csrf_token": csrf_token,
                "cookies": dict(self.client.cookies),
                "mock": False
            }
        except Exception as e:
            logger.error(f"Failed to fetch login page: {_error_text(e)}")
            return {"error": portal_error_reason(e), "unreachable": isinstance(e, httpx.TransportError),
                    "mock": False}

    async def login(self, username: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
        """Log in to the portal: the login page's CSRF token, then the one POST the bot ever makes
        (login.php). -> {"success": True, ...}, or {"success": False, "error": why, "unreachable":
        True when the portal did not answer at all}. A POST whose response still ends on login.php
        is a refused login, whatever the page says."""
        uname = username or self.username
        pword = password or self.password

        if self.mock_mode:
            self.is_authenticated = True
            return {
                "success": True,
                "message": f"Successfully authenticated in Mock Mode as '{uname}'",
                "role": "admin",
                "mock": True
            }

        login_info = await self.get_login_page()
        if login_info.get("error"):
            return {"success": False, "error": f"the login page could not be opened ({login_info['error']})",
                    "unreachable": bool(login_info.get("unreachable"))}
        csrf_token = login_info.get("csrf_token")

        if not csrf_token:
            return {"success": False, "error": "Could not extract CSRF token from login page"}

        payload = {
            "_csrf": csrf_token,
            "username": uname,
            "password": pword
        }

        post_url = f"{self.base_url}/login.php"
        try:
            resp = await self.client.post(post_url, data=payload)
            # Still on the login page after the POST: the login was refused.
            if _ended_on_login(resp):
                self.is_authenticated = False
                return {"success": False, "error": "the portal refused the login (wrong username or password?)"}

            self.is_authenticated = True
            return {
                "success": True,
                "status_code": resp.status_code,
                "redirected_url": str(resp.url),
                "message": "Authentication successful"
            }
        except Exception as e:
            logger.error(f"Login failed: {_error_text(e)}")
            return {"success": False, "error": portal_error_reason(e),
                    "unreachable": isinstance(e, httpx.TransportError)}

    async def get_dashboard(self) -> Dict[str, Any]:
        """Fetch and parse dashboard summary statistics (index.php, parse_hangeul_live_dashboard).
        Never raises: a page that cannot be read gives {"error": why}, which every caller shows as
        "not available"."""
        if self.mock_mode:
            return MOCK_DASHBOARD_STATS
        try:
            return parse_hangeul_live_dashboard(await self.fetch_html("index.php", timeout=30.0))
        except Exception as e:
            logger.error(f"Failed to fetch dashboard: {portal_error_reason(e)}")
            return {"error": portal_error_reason(e)}

    async def get_applications(self, status: Optional[str] = None, intake: Optional[str] = None) -> List[Dict[str, Any]]:
        """Students from students.php (parse_students_page records: the real stage, intake,
        university...), optionally only those whose stage contains `status` / whose intake contains
        `intake`. Without a filter it is the first page, the 50 newest applications (the "recent"
        list /students and the LLM context show); with one, every page, since the answer depends on
        every student. Raises PortalUnavailable when the list cannot be read: never an empty list
        standing in for "could not read"."""
        if self.mock_mode:
            apps = MOCK_APPLICATIONS
            if status:
                apps = [a for a in apps if status.lower() in a["status"].lower()]
            if intake:
                apps = [a for a in apps if intake.lower() in a["target_intake"].lower()]
            return apps

        apps = await self.read_students(all_pages=bool(status or intake))
        if status:
            apps = [a for a in apps if status.lower() in a["status"].lower()]
        if intake:
            apps = [a for a in apps if intake.lower() in a["target_intake"].lower()]
        return apps

    async def get_admitted_students(self, query: Optional[str] = None) -> Dict[str, Any]:
        """The admitted students, read from every page of students.php and picked in code: the
        portal ignores ?status=admitted (it sends the whole list), so a student counts as admitted
        when their stage (the "Stage · Applied" column) is the stage the dashboard's own Admitted
        tile links to (students.php?stage=Admitted / Completed; ADMITTED_STAGE when the dashboard
        cannot be read). `query` then narrows them in code by name, HNG id, university, program or
        intake (student_matches), since the portal's own search does not cover universities or
        programs; nothing of it goes into a URL.

        -> {"students": the admitted students matching the query, "admitted": how many are
            admitted in all, "checked": how many students were read, "stage": the stage used,
            "tile": the dashboard's Admitted figure (None when not read), "query": query}
        Raises PortalUnavailable when the list cannot be read whole."""
        stage, tile = ADMITTED_STAGE, None
        if self.mock_mode:
            students = MOCK_APPLICATIONS
        else:
            dash = await self.get_dashboard()
            for t in dash.get("tiles") or []:
                if re.sub(r"[^a-z]", "", t.get("label", "").lower()) == "admitted" and "students.php" in t.get("href", ""):
                    tile = t.get("value")
                    named = parse_qs(urlsplit(t["href"]).query).get("stage")
                    stage = named[0].strip() if named and named[0].strip() else ADMITTED_STAGE
                    break
            students = await self.read_students()
        admitted = [s for s in students if is_admitted(s, stage)]
        matching = [s for s in admitted if student_matches(s, query)] if query else admitted
        return {"students": matching, "admitted": len(admitted), "checked": len(students),
                "stage": stage, "tile": tile, "query": query}

    async def get_consultation_requests(self, target_date: Optional[str] = "today") -> List[Dict[str, Any]]:
        """Retrieve student consultation requests from consult_requests.php, optionally filtered by date."""
        if not self.is_authenticated:
            await self.login()

        url = f"{self.base_url}/consult_requests.php"
        try:
            resp = await self.client.get(url)
            if "login.php" in str(resp.url):
                self.is_authenticated = False
                await self.login()
                resp = await self.client.get(url)

            return parse_consultation_requests(resp.text, target_date=target_date)
        except Exception as e:
            logger.error(f"Error fetching consultation requests: {e}")
            return []

    async def get_inquiries(self) -> List[Dict[str, Any]]:
        """Retrieve student inquiry leads from consult_requests.php."""
        if self.mock_mode:
            return MOCK_INQUIRIES
            
        return await self.get_consultation_requests(target_date="today")

    async def _ensure_session(self) -> None:
        """Log in when there is no session; raise PortalUnavailable when the login fails."""
        if self.is_authenticated:
            return
        result = await self.login()
        if not result.get("success"):
            raise PortalUnavailable(f"couldn't log in to the portal: {result.get('error') or 'no reason given'}",
                                    unreachable=bool(result.get("unreachable")))

    async def ensure_session(self) -> None:
        """Log in now when there is no session (raises PortalUnavailable when that fails), so reads
        that then run side by side share one session instead of each logging in."""
        await self._ensure_session()

    async def _get_once(self, path: str, params, limits) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            return await self.client.get(url, params=params, timeout=limits)
        except httpx.TimeoutException as e:
            raise PortalUnavailable(f"{path}: the portal did not answer in time ({type(e).__name__})",
                                    unreachable=True) from e
        except httpx.TransportError as e:
            raise PortalUnavailable(f"{path}: could not connect to the portal ({type(e).__name__})",
                                    unreachable=True) from e

    async def portal_get(self, path: str, params: Optional[Dict[str, Any]] = None,
                         timeout: float = 60.0) -> httpx.Response:
        """The one way to read a portal page: one read-only GET of `path` (`params` are URL-encoded
        by httpx, so "Admission & Tuition" stays one value). It logs in first when there is no
        session and checks that the login worked; a response that ended on login.php (the session
        expired) logs in again once and repeats the GET. A host that does not take the connection
        is given up on after CONNECT_TIMEOUT seconds; a slow page gets `timeout`.

        Raises PortalUnavailable (never returns a login page or an error page as data): the login
        failed; the page still ended on login.php after logging in again; the portal answered an
        HTTP error; or it did not answer (a timeout or refused connection: .unreachable is True)."""
        await self._ensure_session()
        limits = httpx.Timeout(timeout, connect=min(timeout, CONNECT_TIMEOUT))
        resp = await self._get_once(path, params, limits)
        if _ended_on_login(resp):
            self.is_authenticated = False            # the session expired: one fresh login
            await self._ensure_session()
            resp = await self._get_once(path, params, limits)
            if _ended_on_login(resp):
                self.is_authenticated = False
                raise PortalUnavailable(f"{path}: the portal kept sending its login page after a fresh login")
        if resp.status_code >= 400:
            raise PortalUnavailable(f"{path}: the portal answered HTTP {resp.status_code}")
        return resp

    async def fetch_html(self, path: str, timeout: float = 60.0, params: Optional[Dict[str, Any]] = None) -> str:
        """portal_get(path, params, timeout) -> the page's HTML. Raises PortalUnavailable when the
        page cannot be read, so a caller says "not available" instead of 0."""
        return (await self.portal_get(path, params=params, timeout=timeout)).text

    async def read_consultations(self) -> Optional[List[Dict[str, Any]]]:
        """Every row of consult_requests.php, read by column name. None when the page has no table,
        or a table with rows in a layout the parser does not recognise; [] when it is empty.
        All the parsing (the page is ~2 MB) runs in a worker thread."""
        html = await self.fetch_html("consult_requests.php")
        return await asyncio.to_thread(consultation_table, html)

    async def read_consultation_view(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """One read-only GET of consult_requests.php with `params` (the query its own status-tab
        links and GET search form use: status, from, to), parsed in a worker thread
        (parsers.consultation_view: rows, tabs, status, from, to, listed). Raises PortalUnavailable
        when the page cannot be read or its layout is not recognised: no status tabs with counts,
        or a table whose rows cannot be read."""
        if self.mock_mode:
            raise PortalUnavailable("the bot is in mock mode, so there is no live portal to read")
        html = await self.fetch_html("consult_requests.php", params=params)
        view = await asyncio.to_thread(consultation_view, html)
        if view["tabs"] is None:
            raise PortalUnavailable("consult_requests.php: its status tabs (All, New, ...) and their counts were "
                                    "not found (layout not recognised)")
        if view["rows"] is None:
            raise PortalUnavailable("consult_requests.php: the requests table's layout is not recognised")
        return view

    async def read_consultation_totals(self) -> Dict[str, int]:
        """The portal's own all-time request counts, from consult_requests.php's status tabs, e.g.
        {"All": 999, "New": 8, "No Answer": 153, "Wrong Number": 40, "Consulted": 792,
        "File Opened": 6}. The tabs count every request whichever tab is open (only a date filter
        narrows them), while the list under them shows only the newest CONSULT_LIST_LIMIT: so the
        lightest tab (CONSULT_TOTALS_VIEW, a handful of rows instead of the ~2 MB list) is read.
        Raises PortalUnavailable, also when the page did not open that tab or shows a date filter
        (its counts would then not be all-time)."""
        view = await self.read_consultation_view(CONSULT_TOTALS_VIEW)
        if view["status"] != CONSULT_TOTALS_VIEW["status"] or view["from"] or view["to"]:
            raise PortalUnavailable("consult_requests.php did not open the tab asked for, so its counts "
                                    "may not be all-time (layout not recognised)")
        return view["tabs"]

    async def read_consultation_day(self, day) -> Dict[str, Any]:
        """The consultation requests received on `day` (a date, or text such as "27 Sep 2026"),
        from the portal's own date filter, consult_requests.php?status=all&from=DAY&to=DAY (a GET,
        as the page's tab links and search form use it). Any day is read this way, not only the
        days among the newest CONSULT_LIST_LIMIT requests the unfiltered list shows.

        -> {"day": the date,
            "counts": that day's status-tab counts ("All" is how many were received),
            "rows": the day's listed requests (consultation_rows' records), newest first,
            "complete": whether every one of them is listed (the portal lists at most a few hundred)}
        Raises ValueError for a day that is not a date, and PortalUnavailable when the page cannot
        be read or does not add up: its search form does not show the day as its filter (the
        filter was not applied), a listed request is from another day or has a date the bot cannot
        read, or the list holds another number of requests, or statuses, than its own tabs and
        caption count."""
        day = target_day(day)
        iso = day.isoformat()
        view = await self.read_consultation_view({"status": "all", "from": iso, "to": iso})
        shown = f"{day:%d %b %Y}"
        if view["from"] != iso or view["to"] != iso or view["status"] != "all":
            raise PortalUnavailable(f"consult_requests.php did not apply the date filter for {shown} "
                                    "(layout not recognised)")
        rows, counts, listed = view["rows"], view["tabs"], view["listed"]
        other = [r for r in rows if parse_portal_date(r.get("received_date") or "") != day]
        if other:
            raise PortalUnavailable(f"consult_requests.php's filter for {shown} listed {len(other)} request(s) "
                                    "from another day or with a date the bot cannot read")
        if listed is not None and listed != len(rows):
            raise PortalUnavailable(f"consult_requests.php says it lists {listed} requests for {shown} but "
                                    f"{len(rows)} could be read (layout not recognised)")
        if len(rows) > counts["All"] or (len(rows) < counts["All"] and listed is None
                                         and len(rows) < CONSULT_LIST_LIMIT):
            raise PortalUnavailable(f"consult_requests.php counts {counts['All']} requests on {shown} but "
                                    f"{len(rows)} could be read (layout not recognised)")
        complete = len(rows) == counts["All"]
        if complete:
            got = Counter(r.get("status", "") for r in rows)
            want = Counter({k: v for k, v in counts.items() if k != "All" and v})
            if got != want:
                raise PortalUnavailable(f"consult_requests.php: the statuses of the {len(rows)} requests on {shown} "
                                        "do not match its own status counts (layout not recognised)")
        return {"day": day, "counts": counts, "rows": rows, "complete": complete}

    async def read_consultation_range(self, first, last) -> Dict[str, Any]:
        """The consultation requests received from `first` to `last` (dates, or text such as "1 Sep
        2026"; both days included), from the portal's own date filter,
        consult_requests.php?status=all&from=FIRST&to=LAST (a GET, as its search form sends it).

        The status tabs under the filter count every request of the window, while the list under
        them shows only the newest CONSULT_LIST_LIMIT (a month holds more). When the list stops at
        its limit, its rows are newest first, so every day after the oldest one it reached is whole:
        those rows are kept, and the days from `first` to that oldest one are read again as a window
        of their own, until every request is listed. The parts must add up to the window's own
        count, and the rows' statuses to its status tabs (a list that changed between the reads is
        read once more). Each read gets the checks read_consultation_day makes: the filter echoed,
        every row from inside the window, the caption and the tabs agreeing with the rows.

        -> {"first", "last": the window,
            "counts": the window's own status-tab counts ("All" is how many were received),
            "rows": every request of the window (consultation_rows' records), newest first,
            "complete": whether every one is listed (False only when one day holds more requests
                        than the list shows),
            "consultant_column": whether every page read has a Consultant column (a row's
                        "Unassigned" is then the portal's "—", not a column that is missing),
            "reads": how many pages were read}
        Raises ValueError for a day that is not a date or a window that ends before it starts, and
        PortalUnavailable when a page cannot be read or does not add up."""
        first, last = target_day(first), target_day(last)
        if last < first:
            raise ValueError(f"the window ends ({last:%d %b %Y}) before it starts ({first:%d %b %Y})")
        for attempt in range(2):
            try:
                return await self._consultation_window_read(first, last)
            except _ListChanged as e:
                if attempt:
                    raise PortalUnavailable(e.reason) from e
                logger.info(f"Consultations {_span(first, last)} read again: {e.reason}")

    async def _consultation_window_read(self, first, last) -> Dict[str, Any]:
        reads: List[tuple] = []
        columns: List[bool] = []

        async def window(a, b):
            if len(reads) >= CONSULT_RANGE_MAX_READS:
                raise PortalUnavailable(f"consult_requests.php: reading {_span(first, last)} took more than "
                                        f"{CONSULT_RANGE_MAX_READS} pages (the list kept changing)")
            reads.append((a, b))
            view = await self.read_consultation_view({"status": "all", "from": a.isoformat(), "to": b.isoformat()})
            columns.append("consultant" in (view.get("columns") or ()))
            shown = _span(a, b)
            if view["from"] != a.isoformat() or view["to"] != b.isoformat() or view["status"] != "all":
                raise PortalUnavailable(f"consult_requests.php did not apply the date filter for {shown} "
                                        "(layout not recognised)")
            rows, counts, listed = view["rows"], view["tabs"], view["listed"]
            days = [parse_portal_date(r.get("received_date") or "") for r in rows]
            outside = sum(1 for d in days if d is None or not a <= d <= b)
            if outside:
                raise PortalUnavailable(f"consult_requests.php's filter for {shown} listed {outside} request(s) "
                                        "from outside it or with a date the bot cannot read")
            if listed is not None and listed != len(rows):
                raise PortalUnavailable(f"consult_requests.php says it lists {listed} requests for {shown} but "
                                        f"{len(rows)} could be read (layout not recognised)")
            if len(rows) > counts["All"] or (len(rows) < counts["All"] and listed is None
                                             and len(rows) < CONSULT_LIST_LIMIT):
                raise PortalUnavailable(f"consult_requests.php counts {counts['All']} requests for {shown} but "
                                        f"{len(rows)} could be read (layout not recognised)")
            if len(rows) == counts["All"]:
                return rows, counts, True
            # The list stopped at its limit (newest first): the days after the oldest one it reached
            # are whole; that oldest day and the ones before it are read again on their own.
            oldest = min(days)
            if oldest == b:                     # the window's last day alone holds more than the list
                if a == b:
                    return rows, counts, False
                rest, _, _ = await window(a, b - timedelta(days=1))
                return rows + rest, counts, False
            kept = [r for r, d in zip(rows, days) if d > oldest]
            rest, rest_counts, rest_complete = await window(a, oldest)
            if len(kept) + rest_counts["All"] != counts["All"]:
                raise _ListChanged(f"consult_requests.php counts {counts['All']} requests for {shown}, but read "
                                   f"in parts they are {len(kept) + rest_counts['All']} (the list changed while "
                                   "it was read)")
            return kept + rest, counts, rest_complete

        rows, counts, complete = await window(first, last)
        if complete:
            got = Counter(r.get("status", "") for r in rows)
            want = Counter({k: v for k, v in counts.items() if k != "All" and v})
            if got != want:
                why = (f"consult_requests.php: the statuses of the {len(rows)} requests for {_span(first, last)} "
                       "do not match its own status counts")
                if len(reads) > 1:
                    raise _ListChanged(why + " (the list changed while it was read)")
                raise PortalUnavailable(why + " (layout not recognised)")
        return {"first": first, "last": last, "counts": counts, "rows": rows, "complete": complete,
                "consultant_column": all(columns), "reads": len(reads)}

    async def read_student_pages(self, params: Optional[Dict[str, Any]] = None, *,
                                 all_pages: bool = True) -> List[str]:
        """The HTML of every page of students.php for `params` (e.g. {"q": "Kim"} or
        {"status": "pending"}; kept on every page), in order; only the first page when not
        all_pages (the 50 newest applications).

        It follows the pager ("Page 1 of 7 · 330 students", ?pg=2..7), checks each page is the one
        asked for, follows a page count that grows while reading (a student registered meanwhile:
        rows shift down, and consumers de-duplicate by uid), and checks the pages hold every student
        the first page counts. Raises PortalUnavailable when the list cannot be read whole: a page
        with no student table, a full first page with no pager (its later pages cannot be found),
        a page other than the one asked for, more than MAX_STUDENT_PAGES pages, or fewer students
        than the pager says (the list shrank while being read, or rows went unrecognised)."""
        base = {k: v for k, v in (params or {}).items() if v not in (None, "") and k != "pg"}
        found: List[str] = []
        uids: Dict[str, None] = {}
        page, pages, total = 1, 1, None
        while page <= pages:
            query = {**base, "pg": page} if page > 1 else base
            html = await self.fetch_html("students.php", params=query or None)
            if "<table" not in html:
                raise PortalUnavailable("students.php has no student table (its layout is not recognised)")
            pager, on_page = student_pager(html), student_uids(html)
            if page == 1:
                if pager["pages"] is None:
                    if len(on_page) >= STUDENTS_PER_PAGE:
                        raise PortalUnavailable(f"students.php shows {len(on_page)} students but no "
                                                "'Page 1 of N', so its later pages cannot be found")
                else:
                    pages, total = pager["pages"], pager["total"]
            if pager["page"] is not None and pager["page"] != page:
                raise PortalUnavailable(f"students.php sent page {pager['page']} when asked for page {page} "
                                        "(the list changed while it was read)")
            pages = max(pages, pager["pages"] or 0)
            if pages > MAX_STUDENT_PAGES:
                raise PortalUnavailable(f"students.php says it has {pages} pages, more than the "
                                        f"{MAX_STUDENT_PAGES} the bot reads")
            found.append(html)
            uids.update(dict.fromkeys(on_page))
            if not all_pages:
                break
            page += 1
        if all_pages and total is not None and len(uids) < total:
            raise PortalUnavailable(f"the student list says {total} students but its {pages} pages hold "
                                    f"{len(uids)} (it changed while it was read, or rows were not recognised)")
        return found

    async def read_students(self, params: Optional[Dict[str, Any]] = None, *,
                            all_pages: bool = True) -> List[Dict[str, Any]]:
        """Every student on students.php for `params` (read_student_pages), each read by
        parse_students_page (by the header's column names, with the details row's fields) and
        listed once, by uid, in the list's order. Parsing runs in a worker thread (a page is
        ~1 MB). Raises PortalUnavailable when the list cannot be read whole or a page's layout is
        not recognised."""
        found: List[Dict[str, Any]] = []
        seen = set()
        for html in await self.read_student_pages(params, all_pages=all_pages):
            try:
                parsed = await asyncio.to_thread(parse_students_page, html)
            except StudentListLayoutError as e:
                raise PortalUnavailable(f"students.php: {e}") from e
            for s in parsed["students"]:
                key = s.get("uid") or ("row", s.get("student_id"), s.get("student_name"), s.get("applied_date"))
                if key not in seen:         # a row can shift onto the next page while we read
                    seen.add(key)
                    found.append(s)
        return found

    async def read_verified_students(self, target_date="today", all_pages: bool = True) -> List[Dict[str, Any]]:
        """Students whose payment was verified on target_date (a date, or text such as "today" or
        "27 Sep 2026"), from students.php: every page when all_pages, since a student registered
        weeks ago and verified today sits on a later page; else the first page only. Each is
        parsers.verification's dict (name, program, amount, method, verified_by, verified_time,
        uid, student_id), matched on the row's own "Payment verified by NAME · 27 Sep, 17:19"
        stamp (whole day and month; the stamp has no year, so first reject a day a year or more
        back with src.dates.yearless_day_problem).

        Raises ValueError for a target date that is not a date, and PortalUnavailable when a page
        cannot be read, the list cannot be read whole, or its layout is not recognised: student
        rows with no "Payment verified by" stamp on any of them (the line's wording changed), or a
        verification line whose date cannot be read."""
        day = target_day(target_date)
        students = await self.read_students(all_pages=all_pages)
        _stamp_guard(students)
        return verified_on_day(students, day)

    async def read_verified_window(self, first, last) -> Dict[str, Any]:
        """The payment verifications from `first` to `last` (dates, or text such as "1 Sep 2026";
        both days included), from ONE read of every page of students.php for the whole window, not
        one per day. Each student counts once, on the day of the row's own "Payment verified by
        NAME · 27 Sep, 17:19" stamp (parsers.verified_between: whole day and month tokens, a stamp's
        own year when it has one, never before the student applied). The stamps have no year, so the
        caller first rejects a window reaching a year or more back, or past today
        (src.dates.yearless_day_problem on both ends).

        -> {"verified": parsers.verification's dicts, each with its "day", in list order,
            "students": how many students the list holds (every one was read)}
        Raises ValueError for a day that is not a date or a window that ends before it starts, and
        PortalUnavailable as read_verified_students does."""
        if self.mock_mode:
            raise PortalUnavailable("the bot is in mock mode, so there is no live portal to read")
        first, last = target_day(first), target_day(last)
        if last < first:
            raise ValueError(f"the window ends ({last:%d %b %Y}) before it starts ({first:%d %b %Y})")
        students = await self.read_students()
        _stamp_guard(students)
        return {"verified": verified_between(students, first, last), "students": len(students)}

    async def get_verified_students(self, target_date="today") -> List[Dict[str, Any]]:
        """The /verified commands' read: read_verified_students over every page of students.php.
        Raises (PortalUnavailable, ValueError) instead of returning [] when it cannot read, so a
        failed read is never reported as "no payments were verified"."""
        return await self.read_verified_students(target_date, all_pages=True)

    async def read_pending_payments(self) -> Optional[Dict[str, Any]]:
        """Pending payments from students.php?status=pending ({"count", "listed", "badge"}), or None
        when the page cannot be read. Kept apart from window applications under review."""
        if self.mock_mode:
            return None
        html = await self.fetch_html("students.php?status=pending")
        return await asyncio.to_thread(parse_pending_payments, html)

    async def read_window_apps_under_review(self) -> Optional[int]:
        """How many window applications are under review (window_applications.php?status=under_review,
        counted by each row's own status), or None when the page's table is not recognised."""
        if self.mock_mode:
            return None
        html = await self.fetch_html("window_applications.php?status=under_review")
        rows = await asyncio.to_thread(parse_window_applications, html)
        return None if rows is None else count_under_review(rows)

    async def get_calendar_events(self) -> Dict[str, Any]:
        """Retrieve calendar events, university application windows, and reminders from calendar.php."""
        if self.mock_mode:
            return {"today_reminders": [], "upcoming_events": []}

        if not self.is_authenticated:
            await self.login()

        url = f"{self.base_url}/calendar.php"
        try:
            resp = await self.client.get(url)
            if "login.php" in str(resp.url):
                self.is_authenticated = False
                await self.login()
                resp = await self.client.get(url)

            return parse_calendar_events(resp.text)
        except Exception as e:
            # Never an empty error: a timeout's text is '', which read as "no error, 0 reminders".
            logger.error(f"Error fetching calendar events: {_error_text(e)}")
            return {"today_reminders": [], "upcoming_events": [], "error": _error_text(e), "layout_ok": False}

    async def get_student_full_profile(self, student_id: str, force_live: bool = True) -> Dict[str, Any]:
        """Retrieve student profile details (Father, Mother, Address, DOB, etc.) via read-only GET."""
        if not student_id:
            return {}
        stu_id_clean = str(student_id).strip()
        if not force_live and hasattr(self, "_profile_cache") and stu_id_clean in self._profile_cache:
            return self._profile_cache[stu_id_clean]

        if not hasattr(self, "_profile_cache"):
            self._profile_cache = {}

        if not self.is_authenticated:
            await self.login()

        url = f"{self.base_url}/student_edit.php?id={stu_id_clean}"
        try:
            resp = await self.client.get(url)
            if "login.php" in str(resp.url):
                self.is_authenticated = False
                await self.login()
                resp = await self.client.get(url)

            soup = BeautifulSoup(resp.text, "html.parser")
            profile = {}
            for inp in soup.find_all(["input", "textarea", "select"]):
                name = inp.get("name") or inp.get("id")
                val = inp.get("value")
                if val is None:
                    val = inp.get_text(strip=True)
                if name and val:
                    profile[name.strip()] = val.strip()

            self._profile_cache[stu_id_clean] = profile
            return profile
        except Exception as e:
            logger.error(f"Error fetching student profile for {stu_id_clean}: {e}")
            return {}

    async def audit_student_passport(
        self,
        student_id: str,
        form_data: Dict[str, Any],
        doc_filename: Optional[str] = None,
        force_live: bool = True
    ) -> Dict[str, Any]:
        """Check one student's passport scan against the portal, live: the profile (father, mother,
        address...) read from student_edit.php and merged into form_data (over it when
        force_live), the scan `doc_filename` (the passport_... file of the student's students.php
        row; when not given, the profile page's own link, if it has one) downloaded from
        view_doc.php unless this exact file is already saved, then local OCR and the MRZ check
        digits (ocr_validator.validate_passport_data, in a worker thread).

        A student with no scan on the portal is MISSING_DOCUMENT; an older scan saved on this PC is
        never checked in its place. When the profile or the scan cannot be read (session expired
        and not renewed, timeout, a web page instead of the file), the result is
        ocr_validator.unchecked_result (PORTAL_UNREADABLE, the reason in its verdict), never a
        verdict about fields that were not read."""
        import os
        sid = str(student_id).strip()

        # The full profile (father_name, mother_name, address, etc.), live from student_edit.php.
        try:
            html = await self.fetch_html(f"student_edit.php?id={sid}", timeout=30.0)
        except PortalUnavailable as e:
            return unchecked_result(sid, f"the student's profile (student_edit.php?id={sid}) could not be read: {e.reason}")
        full_prof = self._profile_fields(html)
        if not (full_prof.get("name") or full_prof.get("full_name")):
            return unchecked_result(sid, f"student_edit.php?id={sid} shows no student profile")
        if not hasattr(self, "_profile_cache"):
            self._profile_cache = {}
        self._profile_cache[sid] = full_prof
        for k, v in full_prof.items():
            if force_live or not form_data.get(k):
                form_data[k] = v

        if not doc_filename:
            doc_m = re.search(r'view_doc\.php\?f=(passport_[^"\'\s&<>]+)', html)
            doc_filename = doc_m.group(1) if doc_m else None

        local_path = None
        if doc_filename:
            if not re.fullmatch(r"[A-Za-z0-9._-]+", doc_filename) or ".." in doc_filename:
                return unchecked_result(sid, f"the scan's file name {doc_filename!r} is not one the bot can save")
            passports_dir = os.path.join(BOT_ROOT, "passports")
            os.makedirs(passports_dir, exist_ok=True)
            # The file name carries the upload time, so a saved copy is this very upload.
            local_path = os.path.join(passports_dir, f"{sid}_{doc_filename}")

            def saved() -> bool:              # a whole scan, never a login page saved long ago
                if not os.path.exists(local_path) or os.path.getsize(local_path) < 1000:
                    return False
                with open(local_path, "rb") as fh:
                    return fh.read(200).lstrip()[:1] != b"<"

            if not saved():
                try:
                    resp = await self.portal_get(f"view_doc.php?f={doc_filename}", timeout=60.0)
                except PortalUnavailable as e:
                    return unchecked_result(sid, f"the passport scan could not be downloaded: {e.reason}")
                content = resp.content or b""
                if content[:200].lstrip()[:1] == b"<" or b"<html" in content[:1000].lower():
                    return unchecked_result(sid, "the portal sent a web page instead of the passport scan")
                if len(content) <= 1000:
                    return unchecked_result(sid, f"the passport scan the portal sent is only {len(content)} bytes")
                # Look again now the GET is back: another audit of this student (the watcher
                # and a /crosscheck) may have saved the scan while we waited, and its OCR
                # thread may be reading it. The check, the write and the rename never yield
                # the loop, so a scan is saved once and never rewritten under a reader, and
                # the rename means a reader finds either no scan or the whole one.
                if not saved():
                    part_path = os.path.join(passports_dir, f".{sid}_{doc_filename}.part")
                    with open(part_path, "wb") as f:
                        f.write(content)
                    os.replace(part_path, local_path)

        # EasyOCR on the CPU plus the MRZ and image work take seconds per scan. Run them in a
        # worker thread so the bot keeps answering Telegram (Jennie's voice notes included)
        # while the 30-minute passport watcher audits every student. Same function, same
        # arguments, same result; the portal GETs above stay on the event loop.
        return await asyncio.to_thread(
            validate_passport_data, sid, form_data, local_path, live_audit=force_live
        )

    @staticmethod
    def _profile_fields(html: str) -> Dict[str, str]:
        """student_edit.php's form as {field name: value}: an input's value, a textarea's text, a
        select's chosen option (never the text of all its options); empty fields left out."""
        soup = BeautifulSoup(html or "", "html.parser")
        profile: Dict[str, str] = {}
        for inp in soup.find_all(["input", "textarea", "select"]):
            name = (inp.get("name") or inp.get("id") or "").strip()
            if not name or name == "_csrf" or inp.get("type") in ("password", "submit", "button"):
                continue
            if inp.name == "select":
                opt = inp.find("option", selected=True)
                val = (opt.get("value") or opt.get_text(strip=True)) if opt is not None else ""
            elif inp.name == "textarea":
                val = inp.get_text(strip=True)
            else:
                val = inp.get("value") or ""
            if val.strip():
                profile.setdefault(name, val.strip())
        return profile




    async def crawl_page(self, path: str) -> Dict[str, Any]:
        """Crawl and parse any internal admin page tables and forms."""
        cleaned_path = path.lstrip("/")
        if self.mock_mode:
            return {
                "mock": True,
                "requested_path": cleaned_path,
                "status": "success",
                "tables": [
                    {
                        "table_id": "mock_data_table",
                        "columns": ["ID", "Title", "Date", "Status"],
                        "row_count": 2,
                        "rows": [
                            {"ID": "1", "Title": "Sample Record A", "Date": "2026-09-01", "Status": "Active"},
                            {"ID": "2", "Title": "Sample Record B", "Date": "2026-09-05", "Status": "Completed"}
                        ]
                    }
                ]
            }
            
        if not self.is_authenticated:
            await self.login()
            
        target_url = f"{self.base_url}/{cleaned_path}"
        try:
            resp = await self.client.get(target_url)
            return {
                "status_code": resp.status_code,
                "url": str(resp.url),
                "tables": parse_tables(resp.text),
                "dashboard_summary": parse_dashboard_metrics(resp.text)
            }
        except Exception as e:
            return {"error": str(e)}

# Singleton client instance
admin_client = HangeulAdminClient()
