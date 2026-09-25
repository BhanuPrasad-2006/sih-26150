# Security

What the tool protects, how, what it does not protect, and what the examiner must do. Written against the code as built.
**No software is unhackable.** This is a hardened single-examiner forensic workstation tool, not an internet-facing service.

## 1. Threat model

| Asset | Threats considered |
|---|---|
| Evidence images | Modification during analysis; substitution; tampering after acquisition |
| Case data, exports, reports | Reading or altering them without the examiner; altering a report after it was issued |
| Audit trail | Deleting or rewriting entries to hide actions |
| Biometric data (face embeddings) | Theft of the database (e.g. a cloud Supabase project or a copied `forensic.db`) |
| The workstation | A hostile disk image or video file exploiting a parser; a malicious web page talking to the local server; stolen or guessed password |

Out of scope: an attacker with administrator rights on the workstation (they can read memory, keys and evidence), physical theft of an unencrypted disk, a malicious examiner, nation-state supply-chain compromise of Python or FFmpeg themselves.

## 2. Controls

| Area | Control | Where |
|---|---|---|
| Network | Binds to `127.0.0.1` only; Host header must be a local name (DNS-rebinding defence); `SIH_ALLOWED_HOSTS` for deliberate exceptions | `main.py`, `security.py` |
| Cross-site | Cookie `HttpOnly` + `SameSite=Strict`; POST/PUT/PATCH/DELETE with a foreign `Origin`, `Origin: null` or `Sec-Fetch-Site: cross-site` are refused | `security.py` |
| Browser hardening | CSP with `script-src 'self'` (no inline script anywhere in the UI, enforced by a test), `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'none'`, `form-action 'self'`; `X-Frame-Options: DENY`, `nosniff`, no-referrer | `security.py` |
| Output escaping | Every server/user string is HTML-escaped before it reaches the page; tests fail if risky fields are interpolated raw | `frontend/js`, `test_security.py` |
| Login | bcrypt password (12+ characters), 5 failures → 60 s lock, 30-minute idle timeout, identical error for every failure | `auth.py` |
| **Two-factor** | Optional TOTP (RFC 6238, tested against the RFC vectors); a code can be used once (replay refused); wrong password and wrong code give the same reply; the secret is encrypted in the database; enabling/disabling is audit-logged and needs a valid code | `totp.py`, `auth.py` |
| API surface | API docs and the OpenAPI schema need a session; optional path allow-list `FORENSIC_EVIDENCE_ROOTS` for evidence, original-image and imaging-source paths; upload size cap `SIH_MAX_UPLOAD_GB` (default 200) | `main.py`, `security.py` |
| Evidence integrity | Read-only memory map; SHA-256 + MD5 on open; re-hash after every scan and on demand | `acquisition.py` |
| **Hostile input: parsers** | Seeded mutation fuzzing of every disk parser (random and structure-aware corruption of partition tables, descriptors, index entries, record headers). Contract: never raise, bounded time and memory. 4,000 mutated images run clean; a 200-case subset runs in the test suite; a long-run driver is provided | `tests/fuzz_lib.py`, `test_fuzz_parsers.py` |
| **Hostile input: FFmpeg** | `ffmpeg`/`ffprobe` run through `sandbox.py`: timeout kill, memory cap (Windows job object / `RLIMIT_AS`), no child processes (Windows), scrubbed environment (no database URL, keys or tokens), `-nostdin`, `-protocol_whitelist file,pipe`; OpenCV's FFmpeg limited to local files | `sandbox.py`, `exporter.py`, `accuracy.py` |
| **Audit trail** | Hash chain **plus** an HMAC seal of the chain head and count with a key stored outside the database; truncation or a full database rewrite is detected; head hash printed in the report | `audit.py`, `audit_seal.py` |
| **Reports** | Each PDF gets a detached **Ed25519 signature**; its SHA-256 and key id are written into the audit chain; `GET /api/cases/{id}/report/verify` and `python -m backend.report_signing verify report.pdf` check it; the public key is published at `/api/report-signing-key` for pinning | `report_signing.py` |
| **Data at rest** | Face embeddings and the 2FA secret are AES-encrypted (Fernet: AES-128-CBC + HMAC-SHA256) before they reach the database, so a stolen database alone does not expose them | `secure_store.py` |
| Models | The three ONNX models are SHA-256-pinned; a changed file is refused | `model_integrity.py` |
| Supply chain | `requirements.lock.txt` pins tested versions; `pip-audit` clean (it found and we fixed issues in `starlette`, `python-multipart` and `cryptography`) | `requirements*.txt` |
| Drive imaging | Off by default; write-blocker attestation logged; refuses overwrite and device destinations | `imaging.py` |

## 3. Keys: what they are and how to keep them

All keys live **outside the database**, in `SIH_KEY_DIR` (default `~/.sih_forensic/`), created on first use with owner-only permissions, or come from environment variables.

| Key | File / variable | Protects | If lost |
|---|---|---|---|
| Audit seal key | `audit.key` / `SIH_AUDIT_KEY` | Detecting audit truncation/rewrite | Existing seals read as "tampered"; re-seal after an investigation |
| Data key | `data.key` / `SIH_DATA_KEY` | Face embeddings, 2FA secret | Embeddings unreadable (re-run face detection). **2FA secret unrecoverable: an administrator clears `totp_secret` from the `auth_state` table** |
| Report signing key | `report_signing.key` / `SIH_REPORT_SIGNING_KEY` | Report signatures | Old reports still verify against the published public key; new reports get a new key id |

Back these up **separately from the case database**; if one place holds both the key and the database, the protection is lost. Never commit them (the `.gitignore` covers `.env`; key files live in the home folder).

## 4. What is still NOT protected

1. **A compromised workstation.** Someone with admin rights, or with the key folder and the case folder, can read or change everything and forge the seal and signatures.
2. **Evidence images, exports and PDFs are not encrypted.** Use full-disk encryption (BitLocker / LUKS) on the case drive. Only embeddings and the 2FA secret are encrypted by the application.
3. **Sandboxing is process-level, not a container.** The tools are memory- and time-limited and secret-free, but they can still read files the tool's user can read and use the network. For stronger isolation run the tool in a VM, container or a dedicated low-privilege account.
4. **Fuzzing is bounded evidence, not proof.** 4,000+ mutated images found nothing, and native parsers inside FFmpeg/OpenCV were not fuzzed by us.
5. **The PDF signature is detached** (a `.sig.json` beside the PDF), not embedded (PAdES), and it proves the file's integrity and origin, not a person's identity.
6. **Single examiner.** No roles, no per-user attribution.
7. **Style attributes** are still allowed by the CSP (`style-src 'unsafe-inline'`).
8. **No independent penetration test** has been done. Commission one before relying on the tool for high-stakes work.

## 5. Deployment checklist

- [ ] Run on a dedicated, patched workstation; disk encryption on the drive holding cases
- [ ] Keep the default localhost binding; do **not** expose the port
- [ ] Turn on **Two-factor** (Dashboard → 🔐 Two-factor) and store the setup key safely
- [ ] Set `SIH_KEY_DIR` to an encrypted location and back the key folder up separately from the database
- [ ] Pin the report public key: record `GET /api/report-signing-key` somewhere outside the machine
- [ ] Print or store the **audit head hash** from each report
- [ ] Set `FORENSIC_EVIDENCE_ROOTS` if anyone other than you can reach the server
- [ ] Use a hardware write blocker for any drive imaging
- [ ] Run `pip-audit -r requirements.lock.txt` before each release; keep FFmpeg updated
- [ ] Consider running the tool inside a VM for hostile media

## 6. Verifying things yourself

```bash
python -m pytest backend/tests/test_security.py backend/tests/test_security_level2.py backend/tests/test_sandbox.py backend/tests/test_fuzz_parsers.py
python backend/tests/manual/fuzz_parsers.py 2000          # long fuzz run
pip-audit -r requirements.lock.txt
python -m backend.report_signing verify path/to/report.pdf
```
