import asyncio
import re
import sys
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from bs4 import BeautifulSoup
from src.scraper.client import admin_client

async def fetch_consultation_requests(target_date: str = "today"):
    """
    Fetch consultation requests from https://hangeul.com.bd/admin/consult_requests.php
    target_date can be:
      - 'today' (defaults to current date e.g. '10 Sep 2026')
      - 'yesterday'
      - A date string, e.g. '10 Sep 2026', '2026-09-10', '09 Sep'
    """
    await admin_client.login()
    resp = await admin_client.client.get(f"{admin_client.base_url}/consult_requests.php")
    if resp.status_code != 200:
        print(f"Error fetching consult_requests.php: status {resp.status_code}")
        return "", []

    soup = BeautifulSoup(resp.text, 'html.parser')
    table = soup.find('table')
    if not table:
        print("No consultation requests table found.")
        return "", []

    now = datetime.now()
    if target_date.lower() == "today":
        target_str = now.strftime("%d %b %Y")
    elif target_date.lower() == "yesterday":
        from datetime import timedelta
        target_str = (now - timedelta(days=1)).strftime("%d %b %Y")
    else:
        try:
            parsed = datetime.strptime(target_date, "%Y-%m-%d")
            target_str = parsed.strftime("%d %b %Y")
        except ValueError:
            target_str = target_date

    results = []
    rows = table.find_all('tr')
    for r in rows[1:]:
        cols = r.find_all(['td', 'th'])
        if len(cols) >= 8:
            received = cols[6].get_text(' ', strip=True)
            if target_str.lower() in received.lower():
                name = cols[0].get_text(' ', strip=True)
                contact = cols[1].get_text(' ', strip=True).replace('[email protected]', '').strip()
                city = cols[2].get_text(' ', strip=True)
                prog = cols[3].get_text(' ', strip=True)
                consultant = cols[4].get_text(' ', strip=True)
                details = cols[5].get_text(' ', strip=True).replace('View', '').strip()
                status = cols[7].get_text(' ', strip=True)
                
                results.append({
                    'name': name,
                    'contact': contact,
                    'city': city,
                    'program': prog,
                    'consultant': consultant,
                    'received': received,
                    'status': status,
                    'details': details
                })
    return target_str, results

def print_report(target_str, results):
    print("=" * 80)
    print(f"📋 CONSULTATION REQUESTS BRIEF: {target_str}")
    print("=" * 80)

    total_came = len(results)
    done_leads = []
    no_answer_leads = []
    pending_leads = []

    consultant_stats = {}

    for r in results:
        status_raw = r.get('status', '').strip()
        status_low = status_raw.lower()
        c = r['consultant'] or 'Unassigned'
        if c not in consultant_stats:
            consultant_stats[c] = {'total': 0, 'done': 0, 'no_answer': 0, 'pending': 0}
        consultant_stats[c]['total'] += 1

        if 'consulted' in status_low or 'done' in status_low or 'file opened' in status_low:
            done_leads.append(r)
            consultant_stats[c]['done'] += 1
        elif 'no answer' in status_low:
            no_answer_leads.append(r)
            consultant_stats[c]['no_answer'] += 1
        else:
            pending_leads.append(r)
            consultant_stats[c]['pending'] += 1

    completion_rate = (len(done_leads) / total_came * 100) if total_came > 0 else 0

    print(f"\n📊 EXECUTIVE SUMMARY:")
    print(f"  • Total Came (Inquiries Received):  {total_came}")
    print(f"  • Total Done (Consulted):           {len(done_leads)}  ({completion_rate:.1f}%)")
    print(f"  • Attempted (No Answer / Callback): {len(no_answer_leads)}")
    print(f"  • Pending / Unhandled (New):        {len(pending_leads)}")

    print(f"\n👥 COUNSELOR WORKLOAD & COMPLETION:")
    for c, s in sorted(consultant_stats.items(), key=lambda x: -x[1]['total']):
        print(f"  • {c:20} | Total: {s['total']} | Done: {s['done']} | No Answer: {s['no_answer']} | Pending: {s['pending']}")

    by_program = {}
    for r in results:
        p = r['program'] or 'Unspecified'
        by_program[p] = by_program.get(p, 0) + 1

    print("\n🎓 INQUIRIES BY PROGRAM:")
    for p, cnt in sorted(by_program.items(), key=lambda x: -x[1]):
        print(f"  • {p}: {cnt}")

    if pending_leads:
        print("\n⏳ PENDING / NEW LEADS WAITING FOR CONTACT:")
        for i, r in enumerate(pending_leads, 1):
            print(f"  {i}. {r['name']} ({r['contact']}) - {r['city']}")
            print(f"     Program: {r['program']} | Received: {r['received']} | Assigned: {r['consultant']}")

    if done_leads:
        print("\n✅ COMPLETED CONSULTATIONS TODAY:")
        for i, r in enumerate(done_leads, 1):
            print(f"  {i}. {r['name']} | Program: {r['program']} | Consultant: {r['consultant']} | Status: {r['status']}")

    if no_answer_leads:
        print("\n📞 NO ANSWER (NEEDS FOLLOW-UP):")
        for i, r in enumerate(no_answer_leads, 1):
            print(f"  {i}. {r['name']} ({r['contact']}) | Consultant: {r['consultant']} | Received: {r['received']}")


if __name__ == '__main__':
    query_date = sys.argv[1] if len(sys.argv) > 1 else "today"
    target_str, res = asyncio.run(fetch_consultation_requests(query_date))
    print_report(target_str, res)
