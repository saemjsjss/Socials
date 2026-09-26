import sys
import os
from pathlib import Path

# When running with pythonw.exe (windowless background mode), sys.stdout and sys.stderr are None.
# Redirect them to log files to ensure complete stability and no crashes.
LOG_DIR = Path(__file__).resolve().parent
if sys.stdout is None:
    sys.stdout = open(LOG_DIR / "hangeul_stdout.log", "a", encoding="utf-8", buffering=1)
else:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

if sys.stderr is None:
    sys.stderr = open(LOG_DIR / "hangeul_stderr.log", "a", encoding="utf-8", buffering=1)
else:
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import asyncio
import logging
import uvicorn
from rich.console import Console
from rich.panel import Panel

from src.config import settings
from src.net_fix import apply_telegram_dns_fix
from src.bot.telegram_bot import build_telegram_application, post_init
from src.llm.ollama_client import ollama_client

console = Console(file=sys.stdout)

handlers = [logging.FileHandler(LOG_DIR / "hangeul_bot.log", encoding="utf-8")]
if sys.stdout:
    handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=handlers
)
logger = logging.getLogger("hangeul.main")

async def check_ollama_status():
    """Verify local Ollama service status."""
    health = await ollama_client.check_health()
    if health.get("reachable"):
        if health.get("target_model_ready"):
            console.print(f"[bold green]✔ Local LLM Ready:[/bold green] Ollama running with '{settings.OLLAMA_MODEL}'")
        else:
            console.print(f"[bold yellow]⚠ Ollama Running:[/bold yellow] Target model '{settings.OLLAMA_MODEL}' not found. Run: [cyan]ollama pull {settings.OLLAMA_MODEL}[/cyan]")
    else:
        console.print("[bold yellow]ℹ Ollama Standby:[/bold yellow] Ollama not detected at http://localhost:11434. Operating with internal intelligent reporting engine.")

async def start_all():
    banner = f"""[bold cyan]Hangeul Korean Language & Visa[/bold cyan]
[bold white]Website-to-API + Local Qwen2.5-7B LLM + Telegram Agent[/bold white]

[dim]• Operating Mode :[/dim] [{'yellow' if settings.MOCK_MODE else 'green'}]{'MOCK MODE (Testing/Offline)' if settings.MOCK_MODE else 'LIVE MODE (hangeul.com.bd)'}[/]
[dim]• REST API Server:[/dim] [link=http://localhost:{settings.API_PORT}/docs]http://localhost:{settings.API_PORT}/docs[/link]
[dim]• Telegram Bot   :[/dim] [{'green' if settings.TELEGRAM_BOT_TOKEN and 'your_' not in settings.TELEGRAM_BOT_TOKEN else 'yellow'}]{'Active' if settings.TELEGRAM_BOT_TOKEN and 'your_' not in settings.TELEGRAM_BOT_TOKEN else 'Token not set in .env (API still fully operational)'}[/]
[dim]• Local Model    :[/dim] {settings.OLLAMA_MODEL} on RTX 5060
"""
    console.print(Panel(banner, border_style="cyan", title="System Startup"))

    # Work around blocked Telegram DNS answer on this network (no admin needed)
    tg_ip = apply_telegram_dns_fix()
    if tg_ip:
        console.print(f"[bold yellow]⚠ Telegram DNS override:[/bold yellow] api.telegram.org -> {tg_ip}")

    # Check Ollama
    await check_ollama_status()

    # Configure Uvicorn server
    config = uvicorn.Config(
        "src.api.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_level="info"
    )
    server = uvicorn.Server(config)

    # Initialize Telegram Bot if configured
    telegram_app = build_telegram_application()

    if telegram_app:
        console.print("[bold green]✔ Starting Telegram Bot listener...[/bold green]")
        async with telegram_app:
            await telegram_app.start()
            await post_init(telegram_app)
            await telegram_app.updater.start_polling()
            try:
                await server.serve()
            finally:
                await telegram_app.updater.stop()
                await telegram_app.stop()
    else:
        console.print("[bold blue]ℹ Running REST API Server (visit http://localhost:8000/docs)...[/bold blue]")
        await server.serve()

if __name__ == "__main__":
    try:
        asyncio.run(start_all())
    except (KeyboardInterrupt, SystemExit):
        console.print("\n[bold red]Shutdown requested. Exiting.[/bold red]")
        sys.exit(0)
