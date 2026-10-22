import sys
sys.path.insert(0, '.')
from fastapi.testclient import TestClient
from backend.main import app, db

client = TestClient(app)

print("--- 1. Testing /api/auth/status ---")
r = client.get('/api/auth/status')
print("Status code:", r.status_code)
status = r.json()
print("Auth status:", status)
assert status["has_account"] is True, "has_account must be True"

print("\n--- 2. Testing /api/auth/auto-login ---")
r = client.get('/api/auth/auto-login')
print("Auto-login code:", r.status_code)
auto_res = r.json()
print("Auto-login response:", auto_res)
assert auto_res["authenticated"] is True, "auto-login must succeed for remembered examiner"
cookies = r.cookies
print("Session cookie set:", bool(cookies.get("sih_session")))

print("\n--- 3. Testing /api/auth/quick-access ---")
client2 = TestClient(app) # clean cookies
r2 = client2.post('/api/auth/quick-access')
print("Quick-access code:", r2.status_code)
qa_res = r2.json()
print("Quick-access response:", qa_res)
assert qa_res["authenticated"] is True, "quick-access must succeed"
assert qa_res["username"] == "RAJU", "quick-access user should be RAJU"
cookies2 = r2.cookies
print("Quick-access session cookie set:", bool(cookies2.get("sih_session")))

print("\n--- 4. Testing GET /api/cases (Supabase Cloud DB) ---")
r = client2.get('/api/cases', cookies=cookies2)
print("GET /api/cases status:", r.status_code)
cases = r.json()
print(f"Total cases returned from cloud DB: {len(cases)}")
assert len(cases) >= 6, f"Expected at least 6 cases from Supabase, got {len(cases)}"
for c in cases[:3]:
    print(f"  - [{c.get('case_number')}] {c.get('case_title') or c.get('title')} (Created by: {c.get('created_by')})")

print("\n--- 5. Testing POST /api/cases (Case Registration in Supabase) ---")
import uuid
new_case_num = "FIR-2026-TEST-" + uuid.uuid4().hex[:4].upper()
payload = {
    "case_number": new_case_num,
    "case_title": "Automated End-to-End Verification Case",
    "agency": "Forensic Verification Unit",
    "examiner": "RAJU",
    "fir_number": new_case_num,
    "priority": "HIGH",
    "status": "ACTIVE",
    "target_device": "Hikvision 8-ch NVR",
    "notes": "End-to-end backend verification test"
}
r = client2.post('/api/cases', json=payload, cookies=cookies2)
print("Create case status:", r.status_code)
assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
created = r.json()
case_id = created["case_id"]
print(f"Case registered successfully in Supabase! Case ID: {case_id}, Number: {created['case_number']}")

print("\n--- 6. Testing GET /api/cases/{case_id} (Dossier / Details) ---")
r = client2.get(f'/api/cases/{case_id}', cookies=cookies2)
print("Get case detail status:", r.status_code)
assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
detail = r.json()
print(f"Case detail retrieved: {detail['case_number']} - {detail.get('case_title')}")
print(f"Evidence list: {len(detail.get('evidence', []))} items")
print(f"Segments list: {len(detail.get('segments', []))} items")

print("\n--- 7. Cleanup verification test case from Supabase ---")
if hasattr(db, '_table'):
    db._table('cases').delete().eq('case_id', case_id).execute()
    print("Test case cleaned up from Supabase.")

print("\n==========================================")
print("ALL BACKEND VERIFICATION TESTS PASSED 100%!")
print("==========================================")
