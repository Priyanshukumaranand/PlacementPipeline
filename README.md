# 📧 PlacementPipeline

> **Real-time campus placement intelligence system** that monitors emails, extracts placement drive information using NLP, and powers a live dashboard.

[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org/)
[![Gmail API](https://img.shields.io/badge/Gmail_API-EA4335?style=for-the-badge&logo=gmail&logoColor=white)](https://developers.google.com/gmail/api)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-CC2927?style=for-the-badge&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)

---

## 🎯 Problem Statement

College placement cells send **100+ emails per semester** about campus recruitment drives. Students often miss critical deadlines or opportunities buried in their inbox. PlacementPipeline solves this by:

- **Automatically monitoring** incoming placement emails in real-time
- **Extracting key information** (company, role, deadline, eligibility, CTC) using NLP
- **Populating a live dashboard** that students can filter and browse

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 📬 **Real-time Email Monitoring** | Gmail Pub/Sub integration for instant notifications when new emails arrive |
| 🤖 **Intelligent Extraction** | NLP-powered extraction of company names, roles, deadlines, eligibility criteria |
| 📊 **Dashboard-Ready API** | RESTful endpoints optimized for frontend card/list views |
| 🔍 **Smart Filtering** | Filter drives by batch, company, status, and drive type |
| 📅 **Deadline Tracking** | Automatic deadline badge calculation and status updates |
| 🔐 **Secure OAuth** | Google OAuth 2.0 for secure Gmail access |

---

## 🏗️ Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Gmail Inbox   │────▶│  Google Pub/Sub  │────▶│  PlacementPipeline  │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                        ┌─────────────────────────────────┼─────────────────────────────────┐
                        │                                 ▼                                 │
                        │  ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐    │
                        │  │ Email Parser │───▶│  NLP Extraction  │───▶│   Database   │    │
                        │  └──────────────┘    └──────────────────┘    └──────┬───────┘    │
                        │                                                      │            │
                        │                                                      ▼            │
                        │                                              ┌──────────────┐     │
                        │                                              │  REST API    │     │
                        │                                              └──────┬───────┘     │
                        └─────────────────────────────────────────────────────┼─────────────┘
                                                                              │
                                                                              ▼
                                                                    ┌──────────────────┐
                                                                    │ Frontend Dashboard │
                                                                    └──────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend Framework** | FastAPI (Python 3.10+) |
| **Database** | SQLAlchemy ORM (SQLite / PostgreSQL) |
| **Email Integration** | Gmail API with OAuth 2.0 |
| **Real-time Updates** | Google Cloud Pub/Sub |
| **NLP / Parsing** | BeautifulSoup4, Regex patterns |
| **API Documentation** | Swagger UI (auto-generated) |

---

## 📦 Project Structure

```
PlacementPipeline/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   ├── drives.py        # Dashboard API endpoints
│   │       │   ├── gmail_events.py  # Pub/Sub webhook handler
│   │       │   ├── gmail_watch.py   # Watch registration
│   │       │   └── debug.py         # Development utilities
│   │       └── api.py               # Route aggregator
│   ├── models/
│   │   ├── email.py                 # Email model (internal)
│   │   └── placement_drive.py       # Drive model (dashboard-facing)
│   ├── services/
│   │   ├── gmail_service.py         # Gmail API interactions
│   │   ├── email_extractor.py       # NLP extraction logic
│   │   └── db_service.py            # Database operations
│   └── database.py                  # SQLAlchemy configuration
├── main.py                          # FastAPI application entry
├── requirements.txt                 # Python dependencies
└── .env                             # Environment variables (not committed)
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Google Cloud Project with Gmail API enabled
- Pub/Sub topic for real-time notifications

### Installation

```bash
# Clone the repository
git clone https://github.com/Priyanshukumaranand/PlacementPipeline.git
cd PlacementPipeline

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### Configuration

1. **Create `.env` file:**
```env
DATABASE_URL=sqlite:///./placement.db
GCP_PROJECT_ID=your-gcp-project-id
```

2. **Set up Google OAuth:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create OAuth 2.0 credentials
   - Download as `credentials.json` in project root

### Run the Server

```bash
uvicorn main:app --reload
```

Visit **http://localhost:8000/docs** for interactive API documentation.

---

## 📡 API Endpoints

### Dashboard Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/drives` | List all placement drives (paginated) |
| `GET` | `/api/v1/drives/{id}` | Get drive details (expanded view) |
| `GET` | `/api/v1/drives/filters/options` | Get filter dropdown options |

### Gmail Integration

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/gmail/watch/start` | Start real-time email monitoring |
| `POST` | `/api/v1/gmail/watch/stop` | Stop email monitoring |
| `POST` | `/api/v1/gmail/events` | Pub/Sub webhook (receives notifications) |

### Example Request

```bash
# Get all open drives for batch 2026
curl "http://localhost:8000/api/v1/drives?batch=2026&status=open"
```

### Example Response

```json
{
  "total": 12,
  "skip": 0,
  "limit": 50,
  "drives": [
    {
      "id": 1,
      "company_name": "Google",
      "company_logo": "https://logo.clearbit.com/google.com",
      "role": "SDE Intern",
      "drive_type": "internship",
      "batch": "2026",
      "registration_deadline": "2025-01-15T23:59:00",
      "status": "open"
    }
  ]
}
```

---

## 🔧 How It Works

### 1️⃣ Email Monitoring (Real-time)
- Gmail Pub/Sub watch notifies the server instantly when new emails arrive
- Webhook receives notification and fetches full email content

### 2️⃣ Intelligent Extraction
```python
# Placement keywords detection
PLACEMENT_KEYWORDS = ["placement", "recruitment", "campus", "drive", "hiring", "intern"]

# Subject line parsing (expected format)
"Campus Recruitment Drive || Google || 2026" → company="Google", batch="2026"

# Date extraction from body
"Registration deadline: 15th January 2025" → deadline="2025-01-15"
```

### 3️⃣ Dashboard Update
- Extracted data is stored in the database
- Frontend polls or receives updates via API
- Students see real-time placement opportunities

---

## 🔐 Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | SQLAlchemy connection string | Yes |
| `GCP_PROJECT_ID` | Google Cloud Project ID | Yes |

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## 📄 License

This project is open source and available under the [MIT License](LICENSE).

---

## 👨‍💻 Author

**Priyanshu Kumar Anand**

- GitHub: [@Priyanshukumaranand](https://github.com/Priyanshukumaranand)

---

<p align="center">
  <b>Built with ❤️ for college students who deserve better placement tracking</b>
</p>
