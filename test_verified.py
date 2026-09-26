import asyncio
import re
import sys
from bs4 import BeautifulSoup
from src.scraper.client import admin_client
from datetime import datetime, timedelta

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def parse_verified_students(html: str, target_date: str = "today"):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []

    t_low = (target_date or "today").lower().strip()
    now = datetime.now()
    if t_low == "today":
        d_str = now.strftime("%d %b")
    elif t_low == "yesterday":
        d_str = (now - timedelta(days=1)).strftime("%d %b")
    else:
        d_str = target_date

    day_num = d_str.split(" ")[0].lstrip("0")
    month_name = d_str.split(" ")[1] if " " in d_str else "Sep"
    date_regex = rf"0?{day_num}\s+{month_name}"

    verified = []
    for tr in table.find_all("tr"):
        text = tr.get_text(" ", strip=True)
        m_ver = re.search(rf"Payment verified by\s+([A-Za-z\s\.]+?)\s*·\s*({date_regex}[^<\n]*)", text, re.IGNORECASE)
        if m_ver:
            name_m = re.search(r"Full Name\s+([A-Za-z\s\.]+?)(?:DOB|$)", text)
            stu_id_m = re.search(r"HNG-\d{4}-\d+", text)
            prog_m = re.search(r"Program\s+([A-Za-z\s\(\)\']+?)(?:Preferred|$)", text)
            amt_m = re.search(r"Verified income:\s*([\d,]+\.?\d*\s*BDT)", text)
            method_m = re.search(r"Paid:\s*([\d,]+\.?\d*\s*BDT\s*[A-Za-z\s]+?)(?:Verified|$)", text)

            raw_time = m_ver.group(2).strip()
            clean_time_m = re.search(rf"({date_regex}(?:,\s*\d{{1,2}}:\d{{2}})?)", raw_time, re.IGNORECASE)
            clean_time = clean_time_m.group(1) if clean_time_m else raw_time[:15]

            verified.append({
                "student_id": stu_id_m.group(0) if stu_id_m else "",
                "name": name_m.group(1).strip() if name_m else "Student",
                "program": prog_m.group(1).strip() if prog_m else "",
                "amount": amt_m.group(1) if amt_m else "20,000.00 BDT",
                "method": method_m.group(1).strip() if method_m else "",
                "verified_by": m_ver.group(1).strip(),
                "verified_time": clean_time
            })
    return verified

async def main():
    await admin_client.login()
    resp = await admin_client.client.get('https://hangeul.com.bd/admin/students.php')
    v = parse_verified_students(resp.text, 'today')
    print(f"Verified Today: {len(v)}")
    for item in v:
        print(item)

if __name__ == '__main__':
    asyncio.run(main())
