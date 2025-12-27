from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.api import api_router
from app.database import engine, Base
from app.models import Email, PlacementDrive, SyncState

app = FastAPI(
    title="Placement Pipeline",
    description="Automated extraction of placement info from emails",
    version="1.0.0"
)

# CORS middleware - Allow frontend to access the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (for dev). In production, specify your frontend URL
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

