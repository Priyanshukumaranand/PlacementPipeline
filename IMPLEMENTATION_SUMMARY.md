# Live Gmail Integration Implementation Summary

## Overview
This document summarizes the changes made to connect the placement pipeline to live Gmail notifications via Google Pub/Sub and improve extraction accuracy using the LangGraph pipeline.

## Changes Made

### 1. **Updated Gmail Events Webhook (`app/api/v1/endpoints/gmail_events.py`)**
   - **Replaced** simple `extract_placement_info()` with full **LangGraph pipeline**
   - **Added** proper error handling and logging for each email processed
   - **Improved** deduplication by fetching existing drives from database
   - **Enhanced** date parsing to handle ISO format strings
   - **Added** comprehensive status tracking (filtered, duplicate, failed, success)
   - **Improved** response format with detailed statistics

### 2. **Improved Placement Email Detection (`app/services/langgraph_pipeline.py`)**
   - **Enhanced** `filter_sender_node()` with:
     - More flexible sender checking (domain-based)
     - Expanded keyword list (30+ placement-related keywords)
     - Body preview checking (first 500 chars) in addition to subject
     - Company name pattern matching in subject lines
     - Better handling of email format variations

### 3. **Enhanced Gemini Extraction (`app/services/gemini_extractor.py`)**
   - **Improved** extraction prompt with:
     - Detailed field-by-field extraction rules
     - Clear format specifications
     - Better examples and guidance
     - More structured instructions for accurate extraction

### 4. **Auto-Renewal of Gmail Watch (`main.py`)**
   - **Added** startup task to check Gmail watch expiration
   - **Automatic renewal** if watch expires within 24 hours
   - **Database storage** of watch expiration for tracking
   - **Graceful handling** if Gmail service unavailable

### 5. **Updated Manual Processing Endpoint**
   - **Migrated** `/process-now` endpoint to use LangGraph pipeline
   - **Consistent** processing logic across all endpoints
   - **Better** error reporting and statistics

## How It Works Now

### Live Email Processing Flow

1. **Gmail Watch Registration**
   - Call `POST /api/v1/gmail/watch/start` to register watch
   - Watch expires in ~7 days (auto-renewed on startup if <24h remaining)

2. **Pub/Sub Notification**
   - When new email arrives, Gmail sends notification to Pub/Sub
   - Pub/Sub pushes to `POST /api/v1/gmail/events` webhook

3. **Email Processing Pipeline**
   ```
   Pub/Sub → /gmail/events → Gmail History API → Fetch Messages
   → LangGraph Pipeline (10 steps):
     1. Filter Sender (improved detection)
     2. HTML → Text
     3. Remove Noise
     4. Token Safety
     5. Extract Sections
     6. Regex Extract
     7. Gemini Enhance
     8. Validate
     9. Deduplication
     10. Map to Model
   → Save to Database
   ```

4. **Database Updates**
   - All emails saved for audit trail
   - Placement drives created/updated with smart upsert
   - History ID tracked for incremental sync

## Key Improvements

### Detection Accuracy
- **Before**: Simple keyword matching in subject only
- **After**: 
  - Multi-level filtering (sender + subject + body preview)
  - 30+ placement keywords
  - Company name pattern recognition
  - Domain-based sender validation

### Extraction Quality
- **Before**: Basic regex extraction
- **After**:
  - 10-step LangGraph pipeline
  - Regex + Gemini AI hybrid approach
  - Better validation and normalization
  - Confidence scoring

### Error Handling
- Individual email error tracking
- Continues processing even if one email fails
- Detailed error messages in response
- Graceful degradation if Gemini unavailable

## Testing the Implementation

### 1. Start the Server
```bash
uvicorn main:app --reload
```

### 2. Register Gmail Watch
```bash
curl -X POST http://localhost:8000/api/v1/gmail/watch/start
```

### 3. Test with Manual Processing
```bash
curl -X POST http://localhost:8000/api/v1/gmail/process-now
```

### 4. Monitor Logs
Watch the console for:
- `📧 Gmail notification received`
- `✅ Saved drive: [Company Name]`
- `🚫 Filtered (not placement)`
- `🔄 Duplicate drive`

### 5. Verify Database
Check that:
- New emails are saved in `emails` table
- Placement drives created in `placement_drives` table
- History ID updated in `sync_state` table

## Environment Variables Required

```env
# Gmail API
GCP_PROJECT_ID=your-project-id
GOOGLE_API_KEY=your-gemini-api-key

# Database
DATABASE_URL=postgresql+psycopg2://user:pass@host:port/dbname
```

## Pub/Sub Setup

1. **Create Pub/Sub Topic**
   ```bash
   gcloud pubsub topics create gmail-placement-events
   ```

2. **Grant Gmail Publisher Permission**
   ```bash
   gcloud pubsub topics add-iam-policy-binding gmail-placement-events \
     --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
     --role="roles/pubsub.publisher"
   ```

3. **Create Push Subscription**
   ```bash
   gcloud pubsub subscriptions create gmail-placement-sub \
     --topic=gmail-placement-events \
     --push-endpoint=https://your-domain.com/api/v1/gmail/events
   ```

## Monitoring

### Check Watch Status
The startup logs will show:
- `✅ Gmail watch active until [date]` - Watch is good
- `⏰ Gmail watch expiring soon - renewing...` - Auto-renewal triggered
- `⚠️ Gmail watch check failed` - Non-critical error

### Check Processing Status
The `/gmail/events` endpoint returns:
```json
{
  "status": "processed",
  "emails_saved": 5,
  "filtered": 2,
  "drives_saved": 3,
  "errors": 0,
  "drives": [...]
}
```

## Troubleshooting

### Emails Not Processing
1. Check Gmail watch is active: Look for startup log message
2. Verify Pub/Sub subscription is configured correctly
3. Check webhook URL is accessible from Google Cloud
4. Review logs for error messages

### Low Detection Rate
1. Check if emails are from allowed senders (see `ALLOWED_SENDERS` in `langgraph_pipeline.py`)
2. Verify subject/body contains placement keywords
3. Check filter logs for "Filtered (not placement)" messages

### Extraction Issues
1. Ensure `GOOGLE_API_KEY` is set for Gemini enhancement
2. Check Gemini API quota/limits
3. Review validation errors in response
4. Check confidence scores (low = needs review)

## Next Steps

1. **Deploy to Production**
   - Set up proper webhook URL (not ngrok)
   - Configure Pub/Sub push subscription
   - Set up monitoring/alerts

2. **Monitor Performance**
   - Track processing times
   - Monitor error rates
   - Review confidence scores

3. **Fine-tune Detection**
   - Add more keywords if needed
   - Adjust sender filters
   - Improve regex patterns

4. **Scale if Needed**
   - Add background job queue for processing
   - Implement retry logic
   - Add rate limiting

## Files Modified

- `app/api/v1/endpoints/gmail_events.py` - Main webhook handler
- `app/services/langgraph_pipeline.py` - Improved filtering
- `app/services/gemini_extractor.py` - Better prompts
- `main.py` - Auto-renewal on startup

## Notes

- The system now processes emails in real-time when they arrive
- All emails are saved for audit trail, even if not placement-related
- Duplicate detection prevents creating multiple drives for same company/role
- The LangGraph pipeline provides much better extraction accuracy than simple regex
- Auto-renewal ensures the watch stays active without manual intervention

