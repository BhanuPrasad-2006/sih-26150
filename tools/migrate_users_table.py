import os
import json
import psycopg2
import bcrypt
from dotenv import load_dotenv

load_dotenv(r"c:\Users\Bhanu Prasad\OneDrive\Desktop\sih-2\sih-26150\.env")
dsn = os.environ.get("DATABASE_URL")
if not dsn:
    print("No DATABASE_URL found.")
    exit(1)

conn = psycopg2.connect(dsn)
conn.autocommit = True
cur = conn.cursor()

print("1. Creating 'users' table in Supabase...")
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT UNIQUE NOT NULL,
    full_name TEXT,
    email TEXT,
    role TEXT NOT NULL DEFAULT 'EXAMINER',
    agency TEXT,
    badge_number TEXT,
    password_hash TEXT NOT NULL,
    totp_secret TEXT,
    totp_recovery TEXT,
    failure_count INTEGER DEFAULT 0,
    lockout_until NUMERIC DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now(),
    last_login TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow anon all on users" ON users;
CREATE POLICY "Allow anon all on users" ON users FOR ALL USING (true) WITH CHECK (true);
""")
print("   Users table and RLS policies created.")

print("2. Syncing users from auth_state...")
cur.execute("SELECT value FROM auth_state WHERE key = 'users';")
row = cur.fetchone()
users_dict = {}
if row and row[0]:
    try:
        users_dict = json.loads(row[0])
    except Exception as e:
        print("   Error parsing users JSON:", e)

# Standard default password hash for seeded accounts: "Examiner@2026!"
default_pw_hash = bcrypt.hashpw(b"Examiner@2026!", bcrypt.gensalt()).decode("utf-8")

seed_users = [
    {
        "username": "BHANU",
        "full_name": "Bhanu Prasad",
        "role": "LEAD_EXAMINER",
        "agency": "Forensic Investigation Unit",
        "badge_number": "INV-001",
        "password_hash": users_dict.get("bhanu", {}).get("password_hash") or default_pw_hash
    },
    {
        "username": "Raj",
        "full_name": "Inspector Raj Kumar",
        "role": "EXAMINER",
        "agency": "State Cyber Crime Branch",
        "badge_number": "POL-4412",
        "password_hash": default_pw_hash
    },
    {
        "username": "ashu",
        "full_name": "Examiner Ashu Singh",
        "role": "EXAMINER",
        "agency": "Digital Evidence Lab",
        "badge_number": "LAB-882",
        "password_hash": default_pw_hash
    },
    {
        "username": "asHISH",
        "full_name": "Det. Ashish Sharma",
        "role": "EXAMINER",
        "agency": "CBI Forensic Division",
        "badge_number": "CBI-109",
        "password_hash": default_pw_hash
    }
]

for u in seed_users:
    cur.execute("""
        INSERT INTO users (username, full_name, role, agency, badge_number, password_hash)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (username) DO UPDATE
        SET full_name = EXCLUDED.full_name,
            role = EXCLUDED.role,
            agency = EXCLUDED.agency,
            badge_number = EXCLUDED.badge_number;
    """, (u["username"], u["full_name"], u["role"], u["agency"], u["badge_number"], u["password_hash"]))
print("   Seeded 4 examiner user accounts in 'users' table.")

print("3. Backfilling existing cases with user scoping and forensic details...")
cases_updates = [
    ("FIR-2026-001", "BHANU", "CCTV Tampering Investigation", "Forensic Investigation Unit", "FIR-2026-001", "HIGH", "ACTIVE"),
    ("FIR-2026-191", "BHANU", "CBI DVR Video Recovery", "CBI Forensic Division", "FIR-2026-191", "CRITICAL", "ACTIVE"),
    ("FIR-2026-121", "Raj", "Bank ATM Surveillance Analysis", "State Cyber Crime Branch", "FIR-2026-121", "MEDIUM", "ACTIVE"),
    ("FIR-2026-261", "Raj", "Retail Store Intrusion Footage", "State Cyber Crime Branch", "FIR-2026-261", "LOW", "ACTIVE"),
    ("FIR-1016-262", "ashu", "Warehouse Incident Analysis", "Digital Evidence Lab", "FIR-1016-262", "MEDIUM", "ACTIVE"),
    ("FIR-2026-263", "asHISH", "Highway Toll DVR Evidence", "CBI Forensic Division", "FIR-2026-263", "HIGH", "ACTIVE"),
]

for case_num, created_by, title, agency, fir, priority, status in cases_updates:
    cur.execute("""
        UPDATE cases
        SET created_by = %s,
            case_title = %s,
            agency = %s,
            fir_number = %s,
            priority = %s,
            status = %s
        WHERE case_number = %s;
    """, (created_by, title, agency, fir, priority, status, case_num))
print("   Cases backfilled.")

print("4. Adding foreign key constraint from cases.created_by to users.username...")
cur.execute("""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_cases_created_by'
    ) THEN
        ALTER TABLE cases
        ADD CONSTRAINT fk_cases_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(username)
        ON UPDATE CASCADE
        ON DELETE SET NULL;
    END IF;
END $$;
""")
print("   Foreign key constraint added.")

# Update auth_state users JSON so local auth matches
updated_auth_users = users_dict.copy()
for u in seed_users:
    key = u["username"].strip().lower()
    if key not in updated_auth_users:
        updated_auth_users[key] = {
            "username": u["username"],
            "password_hash": u["password_hash"],
            "totp_secret": None,
            "totp_pending": None,
            "totp_last_counter": None,
            "totp_recovery": None,
            "failure_count": 0,
            "lockout_until": 0.0,
            "created_at": 1790616065.0
        }
cur.execute("UPDATE auth_state SET value = %s WHERE key = 'users';", (json.dumps(updated_auth_users),))
print("   Updated auth_state users JSON.")

print("\n=== VERIFICATION ===")
cur.execute("SELECT username, full_name, role, agency FROM users ORDER BY username;")
print("USERS IN SUPABASE:")
for row in cur.fetchall():
    print("  -", row)

cur.execute("SELECT case_number, created_by, case_title, agency, priority FROM cases ORDER BY case_number;")
print("CASES IN SUPABASE:")
for row in cur.fetchall():
    print("  -", row)
