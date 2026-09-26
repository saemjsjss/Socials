from datetime import datetime, date

MOCK_DASHBOARD_STATS = {
    "status": "success",
    "portal": "Hangeul Korean Language & Visa - Admin Dashboard",
    "last_synced": datetime.now().isoformat(),
    "summary": {
        "total_applicants": 542,
        "active_applications": 87,
        "visa_approved_ytd": 142,
        "pending_document_verification": 19,
        "klp_language_students": 230,
        "degree_programs": {
            "bachelors": 185,
            "masters": 92,
            "phd": 35
        },
        "monthly_new_inquiries": 64,
        "intake_pipeline": {
            "Spring 2027": 45,
            "Fall 2026": 38,
            "Winter 2026": 4
        }
    },
    "consultations_today": {
        "total": 14,
        "by_counselor": {
            "Sarah": "6 consultations (4 KLP, 2 Bachelor's)",
            "Tanvir": "5 consultations (3 Master's, 2 KLP)",
            "Unassigned / Queue": "3 leads"
        },
        "special_cases": [
            "⚠️ Md. Nabil (Sarah): 4-year study gap after HSC (2022); recommended KLP pathway at Chonnam.",
            "⚠️ Raisa Islam (Tanvir): CGPA 2.9/4.0; needs IELTS 6.5 English-track or TOPIK 3 for conditional admission."
        ]
    },
    "performance": {
        "pipeline_summary": "Fall 2026 (38 active) | Spring 2027 (45 active)",
        "visas_approved_ytd": 142,
        "weekly_conversion_rate": "28.4%"
    },
    "verified_admissions_today": {
        "count": 2,
        "students": [
            {
                "student_name": "Farzana Akter",
                "university": "Konkuk Univ (Fall 2026)",
                "form_data": "Name: Farzana Akter | Passport: A00990030 | DOB: 2003-04-12",
                "check_result": "Matched ✅ (Exact match across all fields)"
            },
            {
                "student_name": "Mehedi Hasan",
                "university": "Pusan National Univ (Fall 2026)",
                "form_data": "Name: Mehedi Hasan | Passport: B00990003 | DOB: 2002-11-05",
                "check_result": "Discrepancy ⚠️ (Typed 'Mehedi Hasan', Passport MRZ reads 'MD MEHEDI HASAN')"
            }
        ]
    },
    "pending_payments": {
        "count": 5,
        "total_outstanding": "৳ 4,80,000",
        "items": [
            "Sabbir Hossain (Konkuk): Tuition wire transfer pending confirmation (Due: 12 Sep)",
            "Nusrat Jahan (Yonsei): Embassy visa processing fee unconfirmed"
        ]
    },
    "recent_activities": [
        {"timestamp": "10 minutes ago", "action": "New visa approval letter uploaded", "student": "Tamim Azad", "program": "KLP (Chonnam National Univ)"},
        {"timestamp": "35 minutes ago", "action": "Bank solvency document submitted", "student": "Nusrat Jahan", "program": "Master's (Yonsei Univ)"},
        {"timestamp": "2 hours ago", "action": "New online consultation inquiry", "student": "Sabbir Hossain", "program": "Bachelor's (Konkuk Univ)"},
        {"timestamp": "3 hours ago", "action": "Apostille verification requested", "student": "Mehedi Hasan", "program": "KLP (Busan Univ)"},
        {"timestamp": "5 hours ago", "action": "Tuition invoice generated", "student": "Farzana Akter", "program": "Bachelor's (Hanyang Univ)"}
    ],
    "urgent_alerts": [
        {"level": "warning", "message": "3 visa submissions for Fall 2026 intake require embassy appointment slot confirmation."},
        {"level": "info", "message": "Tuition wire transfer pending confirmation for 2 university admission offers."}
    ]
}

MOCK_APPLICATIONS = [
    {
        "id": "HNG-2026-941",
        "student_name": "Tamim Azad",
        "email": "tamim.azad@example.com",
        "phone": "+8801711001122",
        "program": "KLP (Korean Language Program)",
        "target_university": "Chonnam National University",
        "target_intake": "Fall 2026",
        "topik_level": "Level 2",
        "visa_type": "D-4-1",
        "status": "Visa Approved",
        "documents_verified": True,
        "financial_solvency": "Verified",
        "created_at": "2026-08-15"
    },
    {
        "id": "HNG-2026-942",
        "student_name": "Nusrat Jahan",
        "email": "nusrat.jahan@example.com",
        "phone": "+8801819223344",
        "program": "Master's in Computer Science",
        "target_university": "Yonsei University",
        "target_intake": "Spring 2027",
        "topik_level": "Level 4",
        "visa_type": "D-2-3",
        "status": "Under Embassy Review",
        "documents_verified": True,
        "financial_solvency": "Pending Final Statement",
        "created_at": "2026-08-20"
    },
    {
        "id": "HNG-2026-943",
        "student_name": "Sabbir Hossain",
        "email": "sabbir.h@example.com",
        "phone": "+8801912334455",
        "program": "Bachelor's in Business Administration",
        "target_university": "Konkuk University",
        "target_intake": "Fall 2026",
        "topik_level": "Level 3",
        "visa_type": "D-2-2",
        "status": "Awaiting Certificate of Admission",
        "documents_verified": True,
        "financial_solvency": "Verified",
        "created_at": "2026-08-28"
    },
    {
        "id": "HNG-2026-944",
        "student_name": "Mehedi Hasan",
        "email": "mehedi.hasan@example.com",
        "phone": "+8801615556677",
        "program": "KLP (Korean Language Program)",
        "target_university": "Pusan National University",
        "target_intake": "Fall 2026",
        "topik_level": "Beginner",
        "visa_type": "D-4-1",
        "status": "Document Review Pending",
        "documents_verified": False,
        "financial_solvency": "In Progress",
        "created_at": "2026-09-02"
    },
    {
        "id": "HNG-2026-945",
        "student_name": "Farzana Akter",
        "email": "farzana.akter@example.com",
        "phone": "+8801718889900",
        "program": "Bachelor's in Electronic Engineering",
        "target_university": "Hanyang University",
        "target_intake": "Spring 2027",
        "topik_level": "IELTS 6.5 (English Track)",
        "visa_type": "D-2-2",
        "status": "Admission Offer Received",
        "documents_verified": True,
        "financial_solvency": "Verified",
        "created_at": "2026-09-05"
    },
    {
        "id": "HNG-2026-946",
        "student_name": "Amina Rahman",
        "email": "amina.rahman@example.com",
        "phone": "+8801514443322",
        "program": "PhD in Artificial Intelligence",
        "target_university": "KAIST",
        "target_intake": "Spring 2027",
        "topik_level": "English Track / TOPIK 3",
        "visa_type": "D-2-4",
        "status": "Professor Interview Scheduled",
        "documents_verified": True,
        "financial_solvency": "Full Scholarship (GKS)",
        "created_at": "2026-09-08"
    }
]

MOCK_INQUIRIES = [
    {
        "id": "INQ-501",
        "lead_name": "Md. Rakib Khan",
        "phone": "+8801722331100",
        "email": "rakib.khan@example.com",
        "interested_program": "KLP -> Bachelor's pathway",
        "hsc_passing_year": 2024,
        "gpa": "4.85 / 5.0",
        "status": "Consultation Booked",
        "consultant_assigned": "Staff Sarah",
        "inquiry_date": "2026-09-08"
    },
    {
        "id": "INQ-502",
        "lead_name": "Sadia Islam",
        "phone": "+8801833442211",
        "email": "sadia.islam@example.com",
        "interested_program": "Master's with GKS Scholarship",
        "bachelor_cgpa": "3.72 / 4.0",
        "status": "Follow-up Required",
        "consultant_assigned": "Admin",
        "inquiry_date": "2026-09-09"
    },
    {
        "id": "INQ-503",
        "lead_name": "Shahriar Ahmed",
        "phone": "+8801944553322",
        "email": "shahriar.ahmed@example.com",
        "interested_program": "KLP Language Training Only",
        "hsc_passing_year": 2025,
        "gpa": "4.50 / 5.0",
        "status": "New Lead",
        "consultant_assigned": "Unassigned",
        "inquiry_date": "2026-09-09"
    }
]
