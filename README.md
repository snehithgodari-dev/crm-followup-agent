# CRM Follow-Up Agent

AI-powered quotation-to-cash CRM. It keeps customers, quotations, purchase orders, deliveries, invoices and payments in one place, reads PO and invoice PDFs with an LLM, chases overdue payments by email, and lets you ask questions in plain English through a chatbot.

> **Design rule:** the LLM reads documents and talks; deterministic Python decides. Every status change, amount check and payment limit is plain, testable code.

## Features

- **Quotations:** create with server-side tax arithmetic, generate a PDF, email it, record Accept / Decline.
- **Purchase orders:** upload the customer's PDF. Fields are extracted by an LLM, validated, and the PO total must match the accepted quotation.
- **Delivery:** `NOT_STARTED -> IN_PROCESS -> COMPLETED`. Completed deliveries are locked.
- **Invoices:** upload the invoice PDF only after delivery is completed. The due date is derived from invoice terms, PO terms, or a 10-day default.
- **Payments:** full or partial payments, overpayment rejected, no reversal after a payment.
- **Reminders:** payment reminder emails for overdue invoices, with a follow-up history.
- **AI assistant:** a chatbot with 13 CRM tools (11 read-only, 2 that change data), available as a floating panel on every page.

## Architecture

```text
Flask UI (5000)  -->  FastAPI (8001, 19 REST endpoints)  -->  services  -->  SQLite (data/crm.db)
                                  |
                                  +--> Groq LLM (PO / invoice extraction)

Chat agent v1:  LangGraph  -->  MCP server (8000, streamable HTTP)  -->  CRM tools
Chat agent v2:  Google ADK  -->  13 in-process Python tools
```

| Layer | Technology |
|---|---|
| Web UI | Flask, Jinja templates, HTML / CSS / JavaScript |
| API | FastAPI + Uvicorn |
| Database | SQLite via SQLAlchemy (10 tables) |
| Document reading | pypdf (text PDFs, no OCR) + Groq `openai/gpt-oss-20b` with a strict JSON schema |
| Validation | Pydantic v2 + rule validators |
| Agent v1 | LangGraph + Model Context Protocol (MCP) |
| Agent v2 | Google Agent Development Kit (ADK) with a Gemini model |
| PDF / email | ReportLab, Gmail SMTP |

## Workflow

```text
Quotation -> Purchase Order -> Delivery -> Invoice -> Payment -> Reminder / Follow-up
```

The UI shows only the next valid step, so a user cannot skip one.

## Getting started

### 1. Clone and install

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in your own values. **Never commit `.env`.**

```text
GROQ_API_KEY=your_groq_key
EMAIL_ADDRESS=your_gmail_address
EMAIL_APP_PASSWORD=your_gmail_app_password
MCP_SERVER_URL=http://127.0.0.1:8000/mcp
GOOGLE_API_KEY=your_gemini_key        # only for the ADK agent
```

Use a Gmail **app password**, not your normal password.

### 3. Create demo data (optional)

```bash
python import_excel.py        # loads sample.xlsx into the database
```

### 4. Run the services (separate terminals)

```bash
python backend.py             # FastAPI on http://127.0.0.1:8001
python mcp_server.py          # MCP server on http://127.0.0.1:8000  (needed by the LangGraph agent only)
python ui.py                  # Flask UI on http://127.0.0.1:5000
```

Open <http://127.0.0.1:5000>.

## Try it

1. Click **New Quotation**, add items, save, and download the PDF.
2. Open the quotation and click **Accept**.
3. Upload `sample_po.pdf` on the PO page.
4. Set delivery to **In Process**, then **Completed**.
5. Upload `sample_invoice.pdf`.
6. Record a **Partial** payment, then use **Send Payment Reminder** once the invoice is overdue.
7. Click the sparkle button and ask: *"What are the overdue invoices?"*

## Project structure

```text
crm-followup-agent/
├── ui.py                    Flask web app (port 5000)
├── backend.py               FastAPI app (port 8001); its /chat endpoint calls agent.run_agent
├── agent.py                 Chat agent v1: LangGraph + Groq, talks to the MCP server
├── mcp_server.py            MCP server exposing CRM tools (port 8000)
├── mcp_client.py            MCP client used by agent.py
├── tools.py                 13 in-process CRM tools used by the ADK agent
├── import_excel.py          Loads sample.xlsx into the database
├── crm_adk_agent/           Chat agent v2: Google ADK (Gemini)
│   ├── __init__.py
│   └── agent.py
├── database/                SQLAlchemy models and session, seed script, early invoice/PO helpers
├── documents/               PDF text extraction, LLM schemas, validators, extraction samples (JSON)
├── services/                Quotation, PO, delivery, invoice, payment, reminder, follow-up logic
├── templates/               Jinja pages (dashboard, quotation, PO, delivery, invoice, payment, chatbot)
├── static/                  style.css and fonts/DejaVuSans.ttf
├── data/                    SQLite database is created here (crm.db, not committed)
├── docs/                    Presentation and IEEE report
├── sample.xlsx, sample_po.pdf, sample_invoice.pdf
├── requirements.txt, .env.example, .gitignore
└── README.md
```

The `test_*.py` files inside `database/`, `documents/` and `services/` are small manual scripts that print results; they contain no assertions.

### Choosing the chat agent

`backend.py` imports `run_agent` from the top-level `agent.py`, which is the LangGraph + MCP version. To use the Google ADK version instead, set `GOOGLE_API_KEY`, and replace the top-level `agent.py` with `crm_adk_agent/agent.py`. Its `run_agent` is asynchronous, so check how `backend.py` calls it (it currently runs `run_agent` in a worker thread).

## Known limitations

- No login or roles yet; anyone who can open the app can use every screen.
- Scanned PDFs are not supported (no OCR).
- LLM extraction accuracy has not been measured on a large set of real documents.
- Some checks are incomplete: invoices are not fully reconciled with their PO, and payment status can be set by the caller. See the project report for details.
- The Flask secret key and CORS settings are for local use only. Change them before any deployment.

## Roadmap

Automatic email scheduling, payment-delay prediction, WhatsApp reminders, role-based access, cloud deployment, voice queries and automated reports.

## Contributing

Issues and pull requests are welcome. Please open an issue first for large changes.



