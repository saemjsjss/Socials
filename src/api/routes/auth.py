from fastapi import APIRouter, HTTPException
from src.api.schemas import LoginRequest, LoginResponse
from src.scraper.client import admin_client

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.get("/csrf", summary="Extract CSRF Token from Portal")
async def get_csrf():
    """Fetches the live login page of Hangeul Admin and extracts the CSRF token and session cookies."""
    return await admin_client.get_login_page()

@router.post("/login", response_model=LoginResponse, summary="Authenticate Admin Session")
async def login(req: LoginRequest):
    """Logs into the admin panel using CSRF token and provided or environment credentials."""
    res = await admin_client.login(username=req.username, password=req.password)
    if not res.get("success"):
        raise HTTPException(status_code=401, detail=res.get("error", "Authentication failed"))
    return res

@router.get("/status", summary="Session Authentication Status")
async def auth_status():
    """Returns whether the current admin client session is authenticated."""
    return {
        "authenticated": admin_client.is_authenticated,
        "mock_mode": admin_client.mock_mode,
        "base_url": admin_client.base_url
    }
