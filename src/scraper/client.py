import asyncio
import logging
import re
from typing import Optional, Dict, Any, List
import httpx
from bs4 import BeautifulSoup

from src.config import BOT_ROOT, settings
from src.scraper.parsers import (
    extract_csrf_token,
    parse_dashboard_metrics,
    parse_tables,
    parse_hangeul_live_dashboard,
    parse_hangeul_live_students,
    parse_consultation_requests,
    consultation_table,
    scan_verified_students,
    parse_pending_payments,
    parse_window_applications,
    count_under_review,
    parse_calendar_events
)
from src.scraper.ocr_validator import validate_passport_data, AUDIT_REGISTRY
from src.scraper.mock_data import MOCK_DASHBOARD_STATS, MOCK_APPLICATIONS, MOCK_INQUIRIES

logger = logging.getLogger("hangeul.client")

# students.php lists 50 students a page; a cap so a misread "Page 1 of N" can never loop for long.
STUDENTS_PER_PAGE = 50
MAX_STUDENT_PAGES = 40
# A portal page read may take its time downloading (consult_requests.php is ~2 MB), but a host
# that does not even take the connection is given up on quickly.
CONNECT_TIMEOUT = 10.0


def _error_text(e: Exception) -> str:
    """An exception as text that is never empty (str(httpx.ReadTimeout('')) is '')."""
    return str(e) or type(e).__name__

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
        """Fetch the login page and extract the CSRF token and cookies."""
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
            logger.error(f"Failed to fetch login page: {e}")
            return {"error": str(e), "mock": False}

    async def login(self, username: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
        """Authenticate with the admin portal using CSRF token and credentials."""
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
            # If still on login page or containing 'error', login failed
            if "login.php" in str(resp.url) and ("Invalid" in resp.text or "error" in resp.text.lower()):
                self.is_authenticated = False
                return {"success": False, "error": "Invalid credentials or login rejected by portal"}
                
            self.is_authenticated = True
            return {
                "success": True,
                "status_code": resp.status_code,
                "redirected_url": str(resp.url),
                "message": "Authentication successful"
            }
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return {"success": False, "error": str(e)}

    async def get_dashboard(self) -> Dict[str, Any]:
        """Fetch and parse dashboard summary statistics."""
        if self.mock_mode:
            return MOCK_DASHBOARD_STATS
            
        if not self.is_authenticated:
            auth_res = await self.login()
            if not auth_res.get("success"):
                return {"error": "Authentication failed", "details": auth_res}
                
        url = f"{self.base_url}/index.php"
        try:
            resp = await self.client.get(url)
            # If redirected back to login, session expired
            if "login.php" in str(resp.url):
                self.is_authenticated = False
                await self.login()
                resp = await self.client.get(url)
                
            return parse_hangeul_live_dashboard(resp.text)
        except Exception as e:
            logger.error(f"Failed to fetch dashboard: {_error_text(e)}")
            return {"error": _error_text(e)}

    async def get_applications(self, status: Optional[str] = None, intake: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve student applications and visa statuses."""
        if self.mock_mode:
            apps = MOCK_APPLICATIONS
            if status:
                apps = [a for a in apps if status.lower() in a["status"].lower()]
            if intake:
                apps = [a for a in apps if intake.lower() in a["target_intake"].lower()]
            return apps
            
        if not self.is_authenticated:
            await self.login()
            
        url = f"{self.base_url}/students.php"
        try:
            resp = await self.client.get(url)
            # If redirected back to login, session expired
            if "login.php" in str(resp.url):
                self.is_authenticated = False
                await self.login()
                resp = await self.client.get(url)

            apps = parse_hangeul_live_students(resp.text)
            if status:
                apps = [a for a in apps if status.lower() in a["status"].lower()]
            if intake:
                apps = [a for a in apps if intake.lower() in a["target_intake"].lower()]
            return apps
        except Exception as e:
            logger.error(f"Error fetching applications: {e}")
            return []

    async def get_admitted_students(self, query: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve admitted students from students.php?status=admitted."""
        if not self.is_authenticated:
            await self.login()

        url = f"{self.base_url}/students.php?status=admitted"
        if query:
            url += f"&q={query}"
        try:
            resp = await self.client.get(url)
            if "login.php" in str(resp.url):
                self.is_authenticated = False
                await self.login()
                resp = await self.client.get(url)

            apps = parse_hangeul_live_students(resp.text)
            if query and not apps:
                resp_all = await self.client.get(f"{self.base_url}/students.php?status=admitted")
                all_apps = parse_hangeul_live_students(resp_all.text)
                q_low = query.lower()
                apps = [a for a in all_apps if any(q_low in str(v).lower() for v in a.values())]
            return apps
        except Exception as e:
            logger.error(f"Error fetching admitted students: {e}")
            return []

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

    async def fetch_html(self, path: str, timeout: float = 60.0) -> str:
        """One read-only GET of a portal page, logging in again if the session expired -> its HTML.
        Raises when the page cannot be fetched, so a caller can say "not available" instead of 0."""
        if not self.is_authenticated:
            await self.login()
        url = f"{self.base_url}/{path.lstrip('/')}"
        limits = httpx.Timeout(timeout, connect=min(timeout, CONNECT_TIMEOUT))
        resp = await self.client.get(url, timeout=limits)
        if "login.php" in str(resp.url):
            self.is_authenticated = False
            await self.login()
            resp = await self.client.get(url, timeout=limits)
        if "login.php" in str(resp.url):
            raise RuntimeError(f"{path}: the portal sent the login page")
        resp.raise_for_status()
        return resp.text

    async def read_consultations(self) -> Optional[List[Dict[str, Any]]]:
        """Every row of consult_requests.php, read by column name. None when the page has no table,
        or a table with rows in a layout the parser does not recognise; [] when it is empty.
        All the parsing (the page is ~2 MB) runs in a worker thread."""
        html = await self.fetch_html("consult_requests.php")
        return await asyncio.to_thread(consultation_table, html)

    async def read_verified_students(self, target_date: Optional[str] = "today",
                                     all_pages: bool = True) -> List[Dict[str, Any]]:
        """Students whose payment was verified on target_date, from students.php: every page
        ("Page 1 of N", ?pg=N) when all_pages, since a student registered weeks ago and verified
        today sits on a later page; else the first page only. Parsing runs in a worker thread
        (a page is ~1 MB). Raises when a page cannot be read, and when the list cannot be read
        whole or its layout is not recognised, so a caller says "not available" instead of 0:
        a full first page with no "Page 1 of N" (the later pages could not be found), or student
        rows with no "Payment verified by" line on any page (the line's wording changed)."""
        found, seen = [], set()
        page, pages = 1, 1
        students = markers = 0
        while page <= pages:
            html = await self.fetch_html("students.php" + (f"?pg={page}" if page > 1 else ""))
            if page == 1 and "<table" not in html:
                raise RuntimeError("students.php has no student table")
            scan = await asyncio.to_thread(scan_verified_students, html, target_date)
            if all_pages:
                m = re.search(r"Page \d+ of (\d+)", html)
                if m:
                    pages = min(int(m.group(1)), MAX_STUDENT_PAGES)
                elif page == 1 and scan["students"] >= STUDENTS_PER_PAGE:
                    raise RuntimeError(f"students.php shows {scan['students']} students but no "
                                       "'Page 1 of N', so its later pages cannot be found")
            students += scan["students"]
            markers += scan["markers"]
            for s in scan["verified"]:
                key = s.get("uid") or (s.get("name"), s.get("verified_time"), s.get("amount"))
                if key not in seen:     # a row can shift onto the next page while we read
                    seen.add(key)
                    found.append(s)
            page += 1
        if students and not markers:
            raise RuntimeError(f"students.php: {students} student rows but no 'Payment verified by' "
                               "line on any of them (layout not recognised)")
        return found

    async def get_verified_students(self, target_date: Optional[str] = "today") -> List[Dict[str, Any]]:
        """Retrieve students whose payment was verified on target_date (first page of students.php)."""
        try:
            return await self.read_verified_students(target_date, all_pages=False)
        except Exception as e:
            logger.error(f"Error fetching verified students: {e}")
            return []

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
        """Validate passport scan live from portal using local OCR and ICAO checksum."""
        import os
        import glob

        # Fetch full profile (father_name, mother_name, address, etc.) live from student_edit.php
        full_prof = await self.get_student_full_profile(student_id, force_live=force_live)
        if full_prof:
            for k, v in full_prof.items():
                if force_live or not form_data.get(k):
                    form_data[k] = v

        # If doc_filename is not passed, discover it directly from the live portal
        if not doc_filename:
            if not self.is_authenticated:
                await self.login()
            try:
                import re
                resp = await self.client.get(f"{self.base_url}/student_edit.php?id={student_id}")
                doc_m = re.search(r'view_doc\.php\?f=(passport_[^"\'\s&]+)', resp.text)
                if doc_m:
                    doc_filename = doc_m.group(1)
                else:
                    # Fallback: discover from students.php
                    resp_s = await self.client.get(f"{self.base_url}/students.php")
                    doc_m2 = re.search(rf'view_doc\.php\?f=(passport_{student_id}_[^"\'\s&]+)', resp_s.text)
                    if doc_m2:
                        doc_filename = doc_m2.group(1)
            except Exception as e:
                logger.error(f"Error discovering doc filename for {student_id}: {e}")

        # Check / download file from live portal
        local_path = None
        passports_dir = os.path.join(BOT_ROOT, "passports")
        os.makedirs(passports_dir, exist_ok=True)

        if doc_filename:
            local_path = os.path.join(passports_dir, f"{student_id}_{doc_filename}")
            if not os.path.exists(local_path) or os.path.getsize(local_path) < 1000:
                if not self.is_authenticated:
                    await self.login()
                doc_url = f"{self.base_url}/view_doc.php?f={doc_filename}"
                try:
                    resp = await self.client.get(doc_url)
                    # Look again now the GET is back: another audit of this student (the watcher
                    # and a /crosscheck) may have saved the scan while we waited, and its OCR
                    # thread may be reading it. The check, the write and the rename never yield
                    # the loop, so a scan is saved once and never rewritten under a reader, and
                    # the rename means a reader finds either no scan or the whole one.
                    if (resp.status_code == 200 and len(resp.content) > 1000
                            and (not os.path.exists(local_path) or os.path.getsize(local_path) < 1000)):
                        part_path = os.path.join(passports_dir, f".{student_id}_{doc_filename}.part")
                        with open(part_path, "wb") as f:
                            f.write(resp.content)
                        os.replace(part_path, local_path)
                except Exception as e:
                    logger.error(f"Error downloading passport doc for {student_id}: {e}")
        else:
            matches = glob.glob(os.path.join(passports_dir, f"{student_id}_*"))
            img_matches = [m for m in matches if not m.endswith(".pdf")]
            if img_matches:
                local_path = img_matches[0]
            elif matches:
                local_path = matches[0]

        # EasyOCR on the CPU plus the MRZ and image work take seconds per scan. Run them in a
        # worker thread so the bot keeps answering Telegram (Jennie's voice notes included)
        # while the 30-minute passport watcher audits every student. Same function, same
        # arguments, same result; the portal GETs above stay on the event loop.
        return await asyncio.to_thread(
            validate_passport_data, student_id, form_data, local_path, live_audit=force_live
        )




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
