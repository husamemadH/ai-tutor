from sqlalchemy import text

from ai_tutor.db import engine


def migrate() -> None:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS student_id VARCHAR(24)"))
        conn.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(24)"))
        conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS source_metadata JSONB"))
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_sessions_lms_owner ON sessions (tenant_id, student_id)"
            )
        )


if __name__ == "__main__":
    migrate()
    print("LMS session ownership migration complete.")
