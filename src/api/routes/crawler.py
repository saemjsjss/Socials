from fastapi import APIRouter
from src.api.schemas import CrawlRequest
from src.scraper.client import admin_client

router = APIRouter(prefix="/crawler", tags=["Generic Table & Page Crawler"])

@router.post("/parse-page", summary="Crawl & Parse Any Internal Admin Page")
async def crawl_admin_page(req: CrawlRequest):
    """Dynamically fetches any internal page in the admin portal (e.g. 'payments.php', 'settings.php')
    and parses all HTML tables and widgets into structured JSON objects.
    """
    return await admin_client.crawl_page(req.path)
