from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.api import api_router
from app.database import engine, Base, SessionLocal
from app.models import Email, PlacementDrive, SyncState
import os
from datetime import datetime, timedelta

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
    """Create database tables and check Gmail watch status on startup."""
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created/verified")
    
    # Check and renew Gmail watch if needed
    try:
        check_and_renew_gmail_watch()
    except Exception as e:
        print(f"⚠️  Gmail watch check failed (non-critical): {str(e)}")


def check_and_renew_gmail_watch():
    """
    Check if Gmail watch is active and renew if expired or expiring soon.
    
    Gmail watches expire after ~7 days. This function:
    1. Checks if watch expiration is stored in DB
    2. If expired or expiring within 24 hours, renews it
    3. Saves new expiration to DB
    """
    project_id = os.getenv("GCP_PROJECT_ID")
    
    if not project_id or project_id == "YOUR_PROJECT_ID_HERE":
        print("⚠️  GCP_PROJECT_ID not configured - skipping Gmail watch check")
        return
    
    db = SessionLocal()
    try:
        from app.services import db_service
        from app.services.gmail_service import get_gmail_service, register_gmail_watch
        
        # Get stored watch expiration
        watch_expiration = db_service.get_sync_state(db, "gmail_watch_expiration")
        
        should_renew = False
        
        if not watch_expiration:
            # No watch registered, need to create one
            print("📧 No Gmail watch found - will register on first email")
            should_renew = False  # Don't auto-register, let user do it manually
        else:
            # Check if expired or expiring soon (within 24 hours)
            try:
                expiration_timestamp = int(watch_expiration) / 1000  # Convert ms to seconds
                expiration_date = datetime.fromtimestamp(expiration_timestamp)
                time_until_expiry = expiration_date - datetime.now()
                
                if time_until_expiry < timedelta(hours=24):
                    print(f"⏰ Gmail watch expiring soon ({time_until_expiry}) - renewing...")
                    should_renew = True
                else:
                    print(f"✅ Gmail watch active until {expiration_date.strftime('%Y-%m-%d %H:%M:%S')}")
                    should_renew = False
            except (ValueError, OSError):
                # Invalid expiration format, renew to be safe
                print("⚠️  Invalid watch expiration format - renewing...")
                should_renew = True
        
        if should_renew:
            try:
                service = get_gmail_service()
                response = register_gmail_watch(service, project_id)
                
                new_expiration = response.get("expiration")
                new_history_id = response.get("historyId")
                
                # Save to database
                db_service.set_sync_state(db, "gmail_watch_expiration", new_expiration)
                if new_history_id:
                    db_service.set_sync_state(db, "gmail_history_id", new_history_id)
                
                expiration_date = datetime.fromtimestamp(int(new_expiration) / 1000)
                print(f"✅ Gmail watch renewed - expires {expiration_date.strftime('%Y-%m-%d %H:%M:%S')}")
                
            except Exception as e:
                print(f"❌ Failed to renew Gmail watch: {str(e)}")
                print("   You can manually renew using: POST /api/v1/gmail/watch/start")
        
    except Exception as e:
        print(f"⚠️  Error checking Gmail watch: {str(e)}")
    finally:
        db.close()


app.include_router(api_router)


@app.get("/")
def health_check():
    return {"status": "ok"}
