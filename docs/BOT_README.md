# 🌐 Hangeul Admin: Website-to-API, Local LLM & Telegram Reporting Bot

Convert `https://hangeul.com.bd/admin/index.php` into a robust, authenticated REST API paired with a local LLM (**Qwen2.5 7B** accelerated on **NVIDIA GeForce RTX 5060**) and an agentic Telegram bot for natural language queries, metric lookups, and automated daily executive briefings.

---

## 🚀 Key Highlights

1. **Website-to-API Layer**:
   - Automated CSRF token extraction from `login.php`.
   - Async session cookie handling (`PHPSESSID`) via `httpx.AsyncClient`.
   - BeautifulSoup auto-table parser that converts any table or dashboard view into structured JSON.
   - Interactive OpenAPI documentation at [`http://localhost:8000/docs`](http://localhost:8000/docs).
2. **Local LLM Intelligence (RTX 5060 + 32GB RAM)**:
   - Powered by **Ollama** running `qwen2.5:7b`.
   - Native GPU acceleration for instant summarization and structured analysis.
   - Resilient Fallback Engine: If Ollama is offline or starting, an internal intelligent reporting engine formats full executive briefings without interruption.
3. **Agentic Telegram Bot & Scheduled Dispatcher**:
   - **Slash Commands**: `/report`, `/stats`, `/students`, `/inquiries`, `/alerts`, `/help`.
   - **Natural Language Q&A**: Ask plain questions like *"How many students registered this week?"* or *"Show pending visa applications"*.
   - **Scheduled Executive Digests**: Configurable daily morning briefing (via APScheduler) sent directly to your Telegram chat.
4. **Mock vs. Live Seamless Toggle**:
   - Out of the box, `MOCK_MODE=true` allows instant offline testing with realistic student and visa data.
   - Switch `MOCK_MODE=false` in `.env` to connect directly to the live portal.

---

## 📁 Project Architecture

```
e:\BOT\
├── .env.example              # Environment template
├── .env                      # Active configuration (Mock mode, credentials, tokens)
├── requirements.txt          # Python dependencies
├── start.bat                 # 1-Click Windows batch launcher
├── run.py                    # Unified startup orchestrator
├── test_system.py            # Complete 5-suite verification test runner
├── README.md                 # Documentation
└── src/
    ├── config.py             # Pydantic Settings & environment loader
    ├── api/
    │   ├── main.py           # FastAPI app & CORS configuration
    │   ├── schemas.py        # Pydantic request & response models
    │   └── routes/
    │       ├── auth.py       # CSRF extraction & login endpoints
    │       ├── dashboard.py  # KPI metrics & urgent alert feeds
    │       ├── applications.py# Student applications & inquiry leads
    │       └── crawler.py    # Auto-table parser for any internal admin page
    ├── scraper/
    │   ├── client.py         # HTTPX session client with CSRF & mock fallback
    │   ├── parsers.py        # BeautifulSoup HTML table & metric extractors
    │   └── mock_data.py      # High-fidelity realistic student & intake data
    ├── llm/
    │   ├── ollama_client.py  # Ollama async client & fallback intelligence
    │   └── prompts.py        # System prompts for study-in-Korea executive briefs
    └── bot/
        ├── telegram_bot.py   # Telegram agent with commands & natural language Q&A
        └── scheduler.py      # Background cron scheduler for daily reports
```

---

## ⚡ Quickstart

### 1. Launch the System
Double click **`start.bat`** or run:
```powershell
C:\Users\User\AppData\Local\Programs\Python\Python311\python.exe run.py
```

Open your browser at:
- **Interactive Swagger API Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc Documentation:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Check:** [http://localhost:8000/healthz](http://localhost:8000/healthz)

### 2. Run Verification Tests
```powershell
$env:PYTHONIOENCODING="utf-8"
C:\Users\User\AppData\Local\Programs\Python\Python311\python.exe test_system.py
```

---

## 🤖 Configuring the Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, choose a name and username, and copy the **API Token**.
3. Open `e:\BOT\.env` and set:
   ```env
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   ```
4. Optional: Set `TELEGRAM_ADMIN_CHAT_ID` with your chat ID from [@userinfobot](https://t.me/userinfobot) (if left empty, the bot automatically authorizes the first user who sends `/start`).
5. Restart `start.bat` or `run.py`.

---

## 🦙 Enabling Local LLM (Ollama + RTX 5060)

1. Ensure Ollama is running (`http://localhost:11434`).
2. Pull the model into your RTX 5060:
   ```bash
   ollama pull qwen2.5:7b
   ```
3. The system will automatically detect the local model and use it for all Telegram reports and natural language questions!

---

## 🌐 Connecting to Live Admin Portal

1. Open `e:\BOT\.env`.
2. Toggle `MOCK_MODE`:
   ```env
   MOCK_MODE=false
   HANGEUL_BASE_URL=https://hangeul.com.bd/admin
   HANGEUL_USERNAME=your_live_username
   HANGEUL_PASSWORD=your_live_password
   ```
3. Restart the service. The client will automatically fetch live CSRF tokens, authenticate via `login.php`, and scrape live records.
