# migrate_todo_v1_to_v2.py
import json
from sqlalchemy import create_engine, text

DB_URL = "sqlite:///app.db"

engine = create_engine(DB_URL)

def migrate():
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT
                id,
                assignee_id,
                creator_id,
                progress
            FROM todos
        """)).fetchall()

        print(f"Found {len(rows)} todos to migrate")

        for r in rows:
            todo_id = r.id
            assignee_id = r.assignee_id
            creator_id = r.creator_id
            old_progress = r.progress or 0

            # 1️⃣ assignee_ids
            assignee_ids = [assignee_id] if assignee_id else []

            # 2️⃣ progress map
            progress_map = {}

            if assignee_id:
                progress_map[assignee_id] = old_progress

            # 3️⃣ creator 永远保留自己的视角
            if creator_id and creator_id not in progress_map:
                progress_map[creator_id] = old_progress

            conn.execute(
                text("""
                    UPDATE todos
                    SET assignee_ids = :assignee_ids,
                        progress = :progress_json
                    WHERE id = :id
                """),
                {
                    "id": todo_id,
                    "assignee_ids": json.dumps(assignee_ids),
                    "progress_json": json.dumps(progress_map),
                }
            )

        print("✅ Migration finished successfully")

if __name__ == "__main__":
    migrate()
