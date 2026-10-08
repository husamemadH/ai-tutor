release: ai-tutor init-db && python scripts/migrate_lms.py
web: uvicorn ai_tutor.api.main:app --host 0.0.0.0 --port $PORT --workers 1 --no-access-log
