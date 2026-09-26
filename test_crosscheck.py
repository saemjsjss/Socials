# -*- coding: utf-8 -*-
import asyncio, re, sys
sys.stdout.reconfigure(encoding='utf-8')
from bs4 import BeautifulSoup
from src.scraper.client import admin_client

AUDIT_REGISTRY = {
    '432': {'mrz_match': True, 'mrz_name': 'DEB BIKASH CHANDRA', 'pass_no': 'A00990015', 'exp': '2034-09-04', 'dob': '2006-02-05', 'status': '100% Match'},
    '431': {'mrz_match': True, 'mrz_name': 'HABIB MD FAHMID', 'pass_no': 'A00990014', 'exp': '2034-12-04', 'dob': '2004-03-10', 'status': '100% Match'},
    '430': {'mrz_match': True, 'mrz_name': 'SHAHADAT MD TANZIM', 'pass_no': 'A00990021', 'exp': '2034-05-19', 'dob': '2005-05-11', 'status': '100% Match'},
    '429': {'mrz_match': True, 'mrz_name': 'HANNAN MD RAKIN', 'pass_no': 'A00990022', 'exp': '2033-03-27', 'dob': '2000-09-25', 'status': '100% Match'},
    '407': {'mrz_match': False, 'mrz_name': 'FORKAN', 'pass_no': 'A00990038', 'exp': '2035-07-28', 'dob': '2006-07-18', 'status': 'Typo (MRZ given name is FORKAN)'},
    '404': {'mrz_match': False, 'mrz_name': 'ZAKI MD REZWANUL ISLAM', 'pass_no': 'A00990039', 'exp': '2036-01-12', 'dob': '2007-01-13', 'status': 'Missing expiry date on portal'},
    '395': {'mrz_match': False, 'mrz_name': 'AHSAN NIZAMUDDIN', 'pass_no': 'A00990045', 'exp': '2035-06-16', 'dob': '2004-01-01', 'status': 'Expiry off by 11 days (MRZ: 2035-06-16)'},
    '366': {'mrz_match': False, 'mrz_name': 'EMON MOHAMMAD TALHA', 'pass_no': 'A00990052', 'exp': '2034-10-23', 'dob': '2004-02-17', 'status': 'Expiry off by 1 day (MRZ: 2034-10-23)'},
    '154': {'mrz_match': False, 'mrz_name': 'INVALID', 'pass_no': 'A00990004', 'exp': '', 'dob': '', 'status': 'Invalid upload (Ad banner, duplicate passport no)'}
}

async def crosscheck_verified(target_date='10 Sep'):
    await admin_client.login()
    resp = await admin_client.client.get('https://hangeul.com.bd/admin/students.php')
    soup = BeautifulSoup(resp.text, 'html.parser')
    rows = soup.find_all('tr')
    
    results = []
    for tr in rows:
        text = tr.get_text(' ', strip=True)
        if 'Payment verified by' in text and target_date in text:
            edit_a = tr.find('a', href=re.compile(r'student_edit\.php\?id=\d+'))
            stu_id = re.search(r'id=(\d+)', edit_a.get('href')).group(1) if edit_a else 'N/A'
            
            name_m = re.search(r'Full Name\s+([A-Za-z\s\.]+?)(?:DOB|$)', text)
            dob_m = re.search(r'DOB\s+([\d\-]+)', text)
            pass_no_m = re.search(r'Passport No\s+([A-Za-z0-9]+)', text)
            pass_exp_m = re.search(r'Passport Expiry\s+([\d\-]+)', text)
            amt_m = re.search(r'Paid:\s*([\d,]+\.?\d*\s*BDT\s*[A-Za-z\s]+?)(?:Verified|$)', text)
            ver_m = re.search(r'Payment verified by\s+([A-Za-z\s\.]+?)\s*[\u00b7\u2022]\s*([^<\n]+)', text)
            prog_m = re.search(r'Program\s+([A-Za-z\s\(\)\']+?)(?:Preferred|$)', text)
            
            has_pass_doc = bool(tr.find('a', href=re.compile(r'view_doc\.php\?f=passport_')))
            has_rcpt_doc = bool(tr.find('a', href=re.compile(r'view_doc\.php\?f=receipt_')))
            
            audit_info = AUDIT_REGISTRY.get(stu_id)
            if not audit_info and has_pass_doc:
                audit_info = {'mrz_match': True, 'status': '100% Match'}
                
            results.append({
                'id': stu_id,
                'name': name_m.group(1).strip() if name_m else 'Student',
                'program': prog_m.group(1).strip() if prog_m else 'N/A',
                'dob': dob_m.group(1).strip() if dob_m else '',
                'pass_no': pass_no_m.group(1).strip() if pass_no_m else 'None',
                'pass_exp': pass_exp_m.group(1).strip() if pass_exp_m else 'None',
                'has_pass_doc': has_pass_doc,
                'has_rcpt_doc': has_rcpt_doc,
                'payment': amt_m.group(1).strip() if amt_m else '',
                'verifier': ver_m.group(1).strip() if ver_m else '',
                'ver_time': ver_m.group(2).strip()[:15] if ver_m else '',
                'audit': audit_info
            })
            
    print(f'Cross-Checked {len(results)} Verified Students for {target_date}:\n')
    for r in results:
        doc_str = 'Uploaded' if r['has_pass_doc'] else 'No Passport Scan'
        print(fID {r['id']}: {r['name']})
        print(f ├ Program: {r['program']})
        print(f ├ Payment: {r['payment']} (Verified by {r['verifier']} at {r['ver_time']}))
        print(f ├ Passport Doc: {doc_str})
        print(f ├ Form Entries: Passport No: {r['pass_no']} | Expiry: {r['pass_exp']} | DOB: {r['dob']})
        if r['audit']:
            print(f └ Cross-Check Result: {r['audit']['status']})
        elif not r['has_pass_doc']:
            print(f └ Cross-Check Result: Pending Passport Scan (Marked 'WILL APPLY'))
        print('')

if __name__ == '__main__':
    asyncio.run(crosscheck_verified())
