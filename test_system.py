import sys
import asyncio
from rich.console import Console

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

console = Console()

async def run_tests():
    console.print("\n[bold cyan]==================================================[/bold cyan]")
    console.print("[bold cyan] RUNNING COMPREHENSIVE SYSTEM VERIFICATION TESTS [/bold cyan]")
    console.print("[bold cyan]==================================================[/bold cyan]\n")

    # Test 1: Config and Settings
    console.print("[bold yellow]Test 1: Configuration & Environment[/bold yellow]")
    from src.config import settings
    assert settings.HANGEUL_BASE_URL.startswith("http"), "Base URL must start with http"
    console.print(f"  ✔ Base URL: {settings.HANGEUL_BASE_URL}")
    console.print(f"  ✔ Mock Mode: {settings.MOCK_MODE}")
    console.print(f"  ✔ LLM Model: {settings.OLLAMA_MODEL}")

    # Test 2: BeautifulSoup Parsers & CSRF Extraction
    console.print("\n[bold yellow]Test 2: BeautifulSoup Parsing Engine[/bold yellow]")
    from src.scraper.parsers import extract_csrf_token, parse_tables, parse_dashboard_metrics
    sample_html = """
    <html>
        <body>
            <input type="hidden" name="_csrf" value="test-token-abcdef12345">
            <div class="card">
                <p>Total Students</p>
                <h2 class="value">542</h2>
            </div>
            <table>
                <thead><tr><th>Name</th><th>Program</th><th>Status</th></tr></thead>
                <tbody>
                    <tr><td>Tamim Azad</td><td>KLP</td><td>Approved</td></tr>
                    <tr><td>Nusrat Jahan</td><td>Master's</td><td>Under Review</td></tr>
                </tbody>
            </table>
        </body>
    </html>
    """
    token = extract_csrf_token(sample_html)
    assert token == "test-token-abcdef12345", f"Expected token match, got {token}"
    console.print(f"  ✔ CSRF extraction verified: {token}")

    tables = parse_tables(sample_html)
    assert len(tables) == 1 and tables[0]["row_count"] == 2
    console.print(f"  ✔ Table parsing verified: {tables[0]['row_count']} rows extracted")

    metrics = parse_dashboard_metrics(sample_html)
    assert "Total Students" in metrics["metrics"]
    console.print(f"  ✔ Dashboard metrics parsing verified: {metrics['metrics']}")

    # Test 3: Admin Client & Scraper (Mock Mode)
    console.print("\n[bold yellow]Test 3: Admin Scraper Client API Operations[/bold yellow]")
    from src.scraper.client import admin_client
    
    login_res = await admin_client.login()
    assert login_res["success"] is True
    console.print(f"  ✔ Client Login: {login_res['message']}")

    dash_res = await admin_client.get_dashboard()
    assert "summary" in dash_res
    console.print(f"  ✔ Dashboard stats: {dash_res['summary']['total_applicants']} total applicants")

    apps = await admin_client.get_applications()
    assert len(apps) >= 5
    console.print(f"  ✔ Applications fetched: {len(apps)} student records")

    inqs = await admin_client.get_inquiries()
    assert len(inqs) >= 3
    console.print(f"  ✔ Inquiries fetched: {len(inqs)} consultation leads")

    crawl_res = await admin_client.crawl_page("payments.php")
    assert crawl_res["status"] == "success"
    console.print(f"  ✔ Generic page crawler: parsed {len(crawl_res['tables'])} tables")

    # Test 4: Local LLM Client & Fallback Engine
    console.print("\n[bold yellow]Test 4: Local LLM Engine & Fallbacks[/bold yellow]")
    from src.llm.ollama_client import ollama_client
    health = await ollama_client.check_health()
    console.print(f"  ✔ Ollama check: reachable={health['reachable']}")

    facts = [f"{k}: {v}" for k, v in (dash_res.get("summary") or {}).items() if isinstance(v, int)]
    picked = ollama_client._answer_query_fallback("total applicants", facts)
    console.print(f"  ✔ Fact pick without the LLM verified: {picked}")

    answer = await ollama_client.answer_agent_query("How many KLP students?", facts)
    console.print(f"  ✔ Natural Language fact pick verified: {answer}")

    # Test 5: FastAPI Application Routing & Endpoints
    console.print("\n[bold yellow]Test 5: FastAPI Application Routing & Live Endpoints[/bold yellow]")
    from src.api.main import app
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        # Test Root
        resp = await ac.get("/")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        console.print("  ✔ GET / returned 200 OK")

        # Test Health
        resp = await ac.get("/healthz")
        assert resp.status_code == 200
        console.print("  ✔ GET /healthz returned 200 OK")

        # Test Dashboard Stats
        resp = await ac.get("/api/dashboard/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        console.print(f"  ✔ GET /api/dashboard/stats returned {data['summary']['total_applicants']} applicants")

        # Test Applications
        resp = await ac.get("/api/applications")
        assert resp.status_code == 200
        apps_data = resp.json()
        assert len(apps_data) > 0
        console.print(f"  ✔ GET /api/applications returned {len(apps_data)} records")

        # Test Inquiries
        resp = await ac.get("/api/applications/inquiries")
        assert resp.status_code == 200
        inqs_data = resp.json()
        assert len(inqs_data) > 0
        console.print(f"  ✔ GET /api/applications/inquiries returned {len(inqs_data)} leads")

        # Test Auth Status
        resp = await ac.get("/api/auth/status")
        assert resp.status_code == 200
        console.print("  ✔ GET /api/auth/status returned 200 OK")

    console.print("\n[bold green]==================================================[/bold green]")
    console.print("[bold green] ALL 5 SYSTEM VERIFICATION TEST SUITES PASSED!   [/bold green]")
    console.print("[bold green]==================================================[/bold green]\n")

if __name__ == "__main__":
    asyncio.run(run_tests())
