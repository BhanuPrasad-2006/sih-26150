import os
from dotenv import load_dotenv
from backend.db_postgres import PostgresDatabase

load_dotenv()

db = PostgresDatabase(os.environ["DATABASE_URL"])
tables = ["cases", "evidence", "segments", "audit_log", "auth_state", "face_embeddings", "log_events"]

with db._connect() as conn:
    for t in tables:
        conn.execute(f'DROP POLICY IF EXISTS "anon_all_{t}" ON {t};')
        conn.execute(f'CREATE POLICY "anon_all_{t}" ON {t} FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);')
        print(f"Policy applied to {t}")

print("All policies applied successfully!")
