from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ai_tutor.db import engine

app = FastAPI(title="AI Tutor", version="0.1.0")


@app.get("/health")
def health() -> dict:
    database = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        database = True
    except SQLAlchemyError:
        database = False
    return {"status": "ok" if database else "degraded", "database": database}