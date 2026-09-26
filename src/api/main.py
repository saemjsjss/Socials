import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.scraper.client import admin_client
from src.api.routes import auth, dashboard, applications, crawler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("hangeul.api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting Hangeul Admin API (Mock Mode: {settings.MOCK_MODE})")
    yield
    await admin_client.close()
    logger.info("Hangeul Admin API shut down cleanly.")

app = FastAPI(
    title="Hangeul Korean Language & Visa — Admin API",
    description="REST API wrapper converting https://hangeul.com.bd/admin/ into structured endpoints with CSRF, session handling, and auto-table parsing.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Enable CORS for easy web integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register sub-routers
app.include_router(auth.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(crawler.router, prefix="/api")

@app.get("/", summary="Root Status Endpoint")
async def root():
    return {
        "portal": "Hangeul Korean Language & Visa - Admin API",
        "docs_url": "/docs",
        "mock_mode": settings.MOCK_MODE,
        "target_url": settings.HANGEUL_BASE_URL,
        "endpoints": [
            "/api/auth/csrf",
            "/api/auth/login",
            "/api/auth/status",
            "/api/dashboard/stats",
            "/api/dashboard/alerts",
            "/api/applications",
            "/api/applications/inquiries",
            "/api/applications/consultations",
            "/api/crawler/parse-page"
        ]
    }

@app.get("/healthz", summary="Health Check")
async def health_check():
    return {"status": "ok", "mock_mode": settings.MOCK_MODE}
