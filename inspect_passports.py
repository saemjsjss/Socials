import asyncio
import sys
import re
from bs4 import BeautifulSoup
from src.scraper.client import admin_client

async def list_students():
    await admin_client.login()
    resp = await admin_client.client.get('https://hangeul.com.bd/admin/students.php')
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    rows = soup.find_all('tr')
    students = []
    
    for r in rows:
        text = r.get_text(' ', strip=True)
        passport_link = None
        for a in r.find_all('a'):
            href = a.get('href') or ''
            if 'passport_' in href and 'view_doc.php' in href:
                passport_link = href
                break
        if passport_link:
            name_m = re.search(r'Full Name\s+([A-Za-z\s\.]+?)(?:DOB|$)', text)
            dob_m = re.search(r'DOB\s+([\d\-]+)', text)
            pass_no_m = re.search(r'Passport No\s+([A-Za-z0-9]+)', text)
            pass_exp_m = re.search(r'Passport Expiry\s+([\d\-]+)', text)
            surname_m = re.search(r'Surname\s+([A-Za-z\s\.]+?)(?:Given Name|$)', text)
            given_m = re.search(r'Given Name\s+([A-Za-z\s\.]+?)(?:Full Name|$)', text)
            student_id_m = re.search(r'student_edit\.php\?id=(\d+)', str(r))
            
            students.append({
                'id': student_id_m.group(1) if student_id_m else 'N/A',
                'name': name_m.group(1).strip() if name_m else 'Unknown',
                'surname': surname_m.group(1).strip() if surname_m else '',
                'given_name': given_m.group(1).strip() if given_m else '',
                'dob': dob_m.group(1).strip() if dob_m else '',
                'passport_no': pass_no_m.group(1).strip() if pass_no_m else '',
                'expiry': pass_exp_m.group(1).strip() if pass_exp_m else '',
                'doc_url': passport_link
            })
            
    print(f"Found {len(students)} students with uploaded passports on students.php:\n")
    for idx, s in enumerate(students):
        print(f"{idx+1:2d}. [ID {s['id']}] {s['name']} | Pass: {s['passport_no']} | Exp: {s['expiry']} | DOB: {s['dob']}")
        print(f"    URL: {s['doc_url']}")

if __name__ == '__main__':
    asyncio.run(list_students())
