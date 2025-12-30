from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.api import api_router
from app.database import engine, Base
from app.models import Email, PlacementDrive, SyncState

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(
    title="Placement Pipeline",
    description="Automated extraction of placement info from emails",
    version="1.0.0"
)

origins = [
    "https://iiit-bbsr-network.vercel.app",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """Create database tables on startup."""
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created/verified")


app.include_router(api_router)


@app.get("/")
def health_check():
    return {"status": "ok"}
