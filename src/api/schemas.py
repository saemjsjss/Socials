from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    username: Optional[str] = Field(None, description="Admin or staff username")
    password: Optional[str] = Field(None, description="Password")

class LoginResponse(BaseModel):
    success: bool
    message: str
    role: Optional[str] = None
    mock: Optional[bool] = False
    error: Optional[str] = None

class DashboardSummary(BaseModel):
    total_applicants: int
    active_applications: int
    visa_approved_ytd: int
    pending_document_verification: int
    klp_language_students: int
    degree_programs: Dict[str, int]
    monthly_new_inquiries: int
    intake_pipeline: Dict[str, int]

class ActivityItem(BaseModel):
    timestamp: str
    action: str
    student: str
    program: str

class AlertItem(BaseModel):
    level: str
    message: str

class DashboardResponse(BaseModel):
    status: str
    portal: str
    last_synced: str
    summary: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, Any]] = None
    recent_activities: Optional[List[Dict[str, Any]]] = None
    urgent_alerts: Optional[List[Dict[str, Any]]] = None

class ApplicationItem(BaseModel):
    id: str
    student_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    program: str
    target_university: str
    target_intake: str
    topik_level: Optional[str] = None
    visa_type: Optional[str] = None
    status: str
    documents_verified: Optional[bool] = None
    financial_solvency: Optional[str] = None
    created_at: Optional[str] = None

class InquiryItem(BaseModel):
    id: str
    lead_name: str
    phone: str
    email: Optional[str] = None
    interested_program: str
    status: str
    consultant_assigned: Optional[str] = None
    inquiry_date: str

class CrawlRequest(BaseModel):
    path: str = Field(..., description="Relative sub-path inside admin panel, e.g. 'payments.php' or 'students.php'")

class CrawlResponse(BaseModel):
    requested_path: str
    status: str
    tables: List[Dict[str, Any]]
    mock: Optional[bool] = False
