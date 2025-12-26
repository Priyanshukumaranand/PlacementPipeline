# 📧 PlacementPipeline

> **Real-time campus placement intelligence system** that monitors emails, extracts placement drive information, and powers a live dashboard.

[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com/)
[![Supabase](https://img.shields.io/badge/Supabase-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)](https://supabase.com/)

---

## ✅ Completed Tasks

- [x] **Gmail API Integration** - OAuth 2.0 read-only access configured
- [x] **Real-time Email Monitoring** - Gmail Pub/Sub push notifications
- [x] **Email Extraction Pipeline** - Extract company, batch, dates from emails
- [x] **Database Schema** - PostgreSQL with Email & PlacementDrive models
- [x] **Deduplication Logic** - Upsert by (company, batch, role)
- [x] **History API Sync** - Incremental email fetching with persistent historyId
- [x] **Dashboard API** - RESTful endpoints for frontend integration
- [x] **Supabase Integration** - Cloud-hosted PostgreSQL database
- [x] **Docker Support** - Containerized deployment ready

---

## 🚀 Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/Priyanshukumaranand/PlacementPipeline.git
cd PlacementPipeline

# Create .env file
cp .env.example .env
# Edit .env with your DATABASE_URL and GCP_PROJECT_ID

# Run with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f
```

### Option 2: Local Development

```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn main:app --reload
```

Visit **http://localhost:8000/docs** for API documentation.

---

## 📡 API Endpoints

### Dashboard API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/drives` | List all placement drives (paginated, filterable) |
| `GET` | `/api/v1/drives/{id}` | Get drive details (expanded view) |
| `GET` | `/api/v1/drives/filters/options` | Get filter dropdown options |

### Gmail Integration

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/gmail/watch/start` | Start real-time email monitoring |
| `POST` | `/api/v1/gmail/events` | Pub/Sub webhook receiver |
| `GET` | `/api/v1/debug/gmail/extract-all` | Manual email extraction |

### Example

```bash
# Get all drives for batch 2026
curl "http://localhost:8000/api/v1/drives?batch=2026"
```

---

## 📦 Project Structure

```
PlacementPipeline/
├── app/
│   ├── api/v1/
│   │   ├── endpoints/
│   │   │   ├── drives.py          # Dashboard API
│   │   │   ├── gmail_events.py    # Webhook handler
│   │   │   ├── gmail_watch.py     # Watch registration
│   │   │   └── debug.py           # Dev utilities
│   │   └── api.py
│   ├── models/
│   │   ├── email.py               # Email model
│   │   ├── placement_drive.py     # Drive model
│   │   └── sync_state.py          # Sync state model
│   ├── services/
│   │   ├── gmail_service.py       # Gmail API + History API
│   │   ├── email_extractor.py     # NLP extraction
│   │   └── db_service.py          # Database operations
│   └── database.py
├── main.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env
```

---

## 🔧 Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+psycopg2://user:pass@host:5432/db` |
| `GCP_PROJECT_ID` | Google Cloud Project ID | `my-project-123` |

---

## 🏗️ Architecture

```
Gmail Inbox → Pub/Sub → FastAPI Webhook → Extraction → Supabase → Dashboard API
```

---

## 👨‍💻 Author

**Priyanshu Kumar Anand** - [@Priyanshukumaranand](https://github.com/Priyanshukumaranand)

---

<p align="center">
  <b>Built with ❤️ for college students who deserve better placement tracking</b>
</p>
