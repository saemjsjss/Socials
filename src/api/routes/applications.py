from typing import Optional, List
from fastapi import APIRouter, Query
from src.scraper.client import admin_client

router = APIRouter(prefix="/applications", tags=["Applications & Leads"])

@router.get("", summary="List Student Applications")
async def get_applications(
    status: Optional[str] = Query(None, description="Filter by status, e.g. 'Approved', 'Review'"),
    intake: Optional[str] = Query(None, description="Filter by intake, e.g. 'Fall 2026', 'Spring 2027'")
):
    """Retrieves student application records including university, program, visa type, and status."""
    return await admin_client.get_applications(status=status, intake=intake)

@router.get("/inquiries", summary="List Inquiries & Consultation Leads")
async def get_inquiries():
    """Retrieves recent student leads and consultation requests from prospective study-in-Korea applicants."""
    return await admin_client.get_inquiries()

@router.get("/consultations", summary="List Consultation Requests by Date")
async def get_consultations(
    date: Optional[str] = Query("today", description="Filter by date, e.g. 'today', 'yesterday', '10 Sep 2026', or '2026-09-09'")
):
    """Retrieves consultation requests submitted by students from consult_requests.php."""
    return await admin_client.get_consultation_requests(target_date=date)

