from fastapi import APIRouter
from src.scraper.client import admin_client

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/stats", summary="Get Dashboard Overview & Metrics")
async def get_dashboard_stats():
    """Returns overall application counts, visa pipeline stages, active students, and recent activity logs."""
    return await admin_client.get_dashboard()

@router.get("/alerts", summary="Get Urgent Alerts & Action Items")
async def get_dashboard_alerts():
    """Returns pending embassy appointment reminders, expiring document warnings, and tuition notices."""
    dash = await admin_client.get_dashboard()
    alerts = dash.get("urgent_alerts") or dash.get("alerts", [])
    return {"alerts": alerts}
