import asyncio
import os
import re
from bs4 import BeautifulSoup
from src.scraper.client import admin_client

os.makedirs('passports', exist_ok=True)

async def download_all_passports():
    await admin_client.login()
    resp = await admin_client.client.get('https://hangeul.com.bd/admin/students.php')
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    rows = soup.find_all('tr')
    downloaded = 0
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
            
            s_info = {
                'id': student_id_m.group(1) if student_id_m else 'unknown',
                'name': name_m.group(1).strip() if name_m else 'Unknown',
                'surname': surname_m.group(1).strip() if surname_m else '',
                'given_name': given_m.group(1).strip() if given_m else '',
                'dob': dob_m.group(1).strip() if dob_m else '',
                'passport_no': pass_no_m.group(1).strip() if pass_no_m else '',
                'expiry': pass_exp_m.group(1).strip() if pass_exp_m else '',
                'doc_url': passport_link
            }
            students.append(s_info)

    print(f"Total students to process: {len(students)}")
    
    for s in students:
        fname = s['doc_url'].split('f=')[-1]
        local_path = os.path.join('passports', f"{s['id']}_{fname}")
        if not os.path.exists(local_path):
            try:
                res = await admin_client.client.get(f"https://hangeul.com.bd/admin/{s['doc_url']}")
                if res.status_code == 200 and len(res.content) > 100:
                    with open(local_path, 'wb') as f:
                        f.write(res.content)
                    downloaded += 1
                    print(f"Downloaded ID {s['id']}: {fname} ({len(res.content)} bytes)")
                else:
                    print(f"Failed ID {s['id']}: status {res.status_code}")
            except Exception as e:
                print(f"Error ID {s['id']}: {e}")
        else:
            print(f"Already cached ID {s['id']}: {local_path}")
            
    print(f"Done. Downloaded {downloaded} new files.")

if __name__ == '__main__':
    asyncio.run(download_all_passports())
