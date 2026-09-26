# Security

What the tool protects, how, what it does not protect, and what the examiner must do. Written against the code as built.
**No software is unhackable.** This is a hardened single-examiner forensic workstation tool, not an internet-facing service.
A live self-check of the points below is available at `/api/security/status` (log in first; there is no dashboard button for it).

## 1. Threat model

| Asset | Threats considered |
|---|---|
| Evidence images | Modification during analysis; substitution; tampering after acquisition |
| Case data, exports, reports | Reading or altering them without the examiner; altering a report after it was issued |
| Audit trail | Deleting or rewriting entries to hide actions (per case and for logins) |
| Biometric data (face embeddings) | Theft of the database (a cloud Supabase project, a copied `forensic.db`) |
| The workstation | A hostile disk image or video exploiting a parser; a malicious web page talking to the local server; stolen or guessed password; sniffing on loopback |

Out of scope: an attacker with administrator rights on the workstation (memory, keys and evidence are all readable), physical theft of an unencrypted disk, a malicious examiner, compromise of Python or FFmpeg themselves.

## 2. Controls

| Area | Control | Where |
|---|---|---|
| Network | Binds to `127.0.0.1` only; Host header must be a local name (DNS-rebinding defence); `SIH_ALLOWED_HOSTS` for deliberate exceptions | `main.py`, `security.py` |
| **Transport** | Optional **HTTPS** (`SIH_TLS=1`): self-signed localhost certificate (or your own via `SIH_TLS_CERT`/`SIH_TLS_KEY`), `Secure` cookie and `Strict-Transport-Security` on HTTPS | `tls.py`, `serve.py`, `security.py` |
| Cross-site | Cookie `HttpOnly` + `SameSite=Strict`; state-changing requests with a foreign `Origin`, `Origin: null` or `Sec-Fetch-Site: cross-site` are refused | `security.py` |
| Browser hardening | CSP with `script-src 'self'`, `style-src 'self'` (no inline script or style attributes anywhere in the UI, enforced by automated tests), `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'none'`, `form-action 'self'`; `X-Frame-Options: DENY`, `nosniff`, no-referrer | `security.py` |
| Output escaping | Every server/user string is HTML-escaped before it reaches the page; tests fail if risky fields are interpolated raw | `frontend/js`, `test_security.py` |
| Login | bcrypt password (12+ characters), 5 failures → 60 s lock (the count and lock time are saved in the database, so restarting the server does not reset them), 30-minute idle timeout **and a 12-hour absolute session lifetime** (`SESSION_MAX_HOURS`), identical error for every failure | `auth.py` |
| **Two-factor** | Optional TOTP (RFC 6238, tested against the RFC vectors); a code works once (replay refused); wrong password and wrong code give the same reply; the code is only consumed after the password is right; secret encrypted in the database; every other session ends when it is switched on or off | `totp.py`, `auth.py` |
| **Lost phone** | 10 one-time **recovery codes** shown once at enrolment; only salted hashes are stored (encrypted); each works once; use is audit-logged; regenerating needs password + a code and voids the old set | `auth.py` |
| API surface | API docs and OpenAPI schema need a session; optional path allow-list `FORENSIC_EVIDENCE_ROOTS`; upload cap `SIH_MAX_UPLOAD_GB` (default 200) | `main.py`, `security.py` |
| Evidence integrity | Read-only memory map; SHA-256 + MD5 on open; re-hash after every scan and on demand | `acquisition.py` |
| Hostile input: parsers | Seeded mutation fuzzing of every disk parser (random and structure-aware corruption). Contract: never raise, bounded time and memory. 4,000 mutated images run clean; a subset runs in the test suite | `tests/fuzz_lib.py`, `test_fuzz_parsers.py` |
| Hostile input: FFmpeg | `ffmpeg`/`ffprobe` via `sandbox.py`: timeout kill, memory cap (Windows job object / `RLIMIT_AS`), no child processes (Windows), scrubbed environment, `-nostdin`, `-protocol_whitelist file,pipe`; OpenCV's FFmpeg limited to local files | `sandbox.py` |
| **Container option** | `Dockerfile` + `docker-compose.yml`: non-root user, read-only root filesystem, all capabilities dropped, `no-new-privileges`, PID/memory limits, evidence mounted read-only, port published to loopback only. **Not tested in this repository's environment (no Docker available): try on a scratch case first** | `Dockerfile`, `docker-compose.yml` |
| Audit trail | Hash chain **plus** an HMAC seal of the head and count with a key outside the database, for **every case log and for the login log**; truncation or a full database rewrite is detected; head hash printed in the report | `audit.py`, `audit_seal.py` |
| **Reports** | (1) **Embedded PDF signature** (ECDSA P-256, self-signed certificate; viewers such as Acrobat show it and flag any change); (2) **detached Ed25519 signature** over the final file; (3) SHA-256 + key id in the audit chain. Verify at `GET /api/cases/{id}/report/verify`, `python -m backend.report_signing verify report.pdf`; certificate at `/api/report-signing-cert`, public key at `/api/report-signing-key` | `pdf_signing.py`, `report_signing.py` |
| **Hand-over** | **Encrypted case package** (`.sihpkg`): the case's exports, signed reports, analyses and audit log (not the evidence images) in one file, AES-256-GCM with a scrypt-derived key; chunk index and a final flag are authenticated, so modification, truncation and reordering are detected; opened with `python -m backend.case_package decrypt` | `case_package.py` |
| Data at rest | Face embeddings and the 2FA secret are AES-encrypted (Fernet) before they reach the database, with a key outside it | `secure_store.py` |
| Models | The three ONNX models are SHA-256-pinned; a changed file is refused | `model_integrity.py` |
| Supply chain and code | `requirements.lock.txt` pins tested versions; `pip-audit` (direct **and** transitive dependencies) clean; **bandit** static analysis clean at medium/high severity; a GitHub Actions workflow runs tests, pip-audit and bandit on every push and weekly | `.github/workflows/security.yml`, `.bandit` |
| Drive imaging | Off by default; write-blocker attestation logged; refuses overwrite and device destinations | `imaging.py` |

## 3. Keys: what they are and how to keep them

All keys live **outside the database**, in `SIH_KEY_DIR` (default `~/.sih_forensic/`), created on first use with owner-only permissions, or come from environment variables.

| Key | File / variable | Protects | If lost |
|---|---|---|---|
| Audit seal key | `audit.key` / `SIH_AUDIT_KEY` | Detecting audit truncation/rewrite | Existing seals read as "tampered"; re-seal after an investigation |
| Data key | `data.key` / `SIH_DATA_KEY` | Face embeddings, 2FA secret | Embeddings unreadable (re-run face detection). 2FA: use a recovery code; if none, an administrator clears `totp_secret` and `totp_recovery` from the `auth_state` table |
| Report signing (detached) | `report_signing.key` / `SIH_REPORT_SIGNING_KEY` | Detached signatures | Old reports still verify against the published public key; new ones get a new key id |
| Report signing (embedded) | `report_signer_key.pem` + `report_signer_cert.pem` | PDF-embedded signatures | Old PDFs still verify against the saved certificate |
| TLS | `tls/server.key`, `tls/server.crt` | HTTPS | Regenerated automatically (browser asks to trust again) |

Back these up **separately from the case database**: if one place holds both the key and the database, the protection is lost. Never commit them (key files live in the home folder; `.gitignore` covers `.env`).

## 4. What is still NOT protected

1. **A compromised workstation.** Someone with admin rights, or with the key folder and the case folder, can read or change everything and forge the seal and signatures.
2. **Evidence images, exports and PDFs are not encrypted by the application** (they are multi-gigabyte, memory-mapped and handed to FFmpeg). Use full-disk encryption (BitLocker / LUKS) on the case drive; the security self-check (`/api/security/status`) tells you whether it can see it. The encrypted case package covers hand-over and archiving, not the working copy.
3. **Sandboxing is process-level.** The container profile is stronger but untested here. For truly hostile media use a disposable VM.
4. **Fuzzing is bounded evidence, not proof.** Native parsers inside FFmpeg/OpenCV were not fuzzed by us.
5. **Self-signed certificates.** The PDF signature proves integrity and origin of the file, not a person's identity, and viewers show the signer as "unknown" until the certificate is trusted. A certificate from a public or organisational CA would fix that (bring your own key/certificate).
6. **Single examiner.** No roles, no per-user attribution; adding them means a different data model, not a patch.
7. **No independent penetration test** has been done. Automated checks (tests, fuzzing, pip-audit, bandit) are not a substitute; commission one before high-stakes use.

## 5. Deployment checklist

- [ ] Dedicated, patched workstation; **disk encryption on the drive holding cases**
- [ ] Keep the default localhost binding; do **not** expose the port
- [ ] `SIH_TLS=1` for HTTPS (or run through the container profile)
- [ ] Turn on **Two-factor** and store the recovery codes offline
- [ ] `SIH_KEY_DIR` on an encrypted location; back the key folder up separately from the database
- [ ] Record the report public key / certificate somewhere outside the machine
- [ ] Print or store the **audit head hash** from each report
- [ ] Set `FORENSIC_EVIDENCE_ROOTS` if anyone other than you can reach the server
- [ ] Hardware write blocker for any drive imaging
- [ ] Open `/api/security/status` after logging in; resolve every amber item you can
- [ ] Keep `pip-audit` (CI runs it weekly) and FFmpeg current; run hostile media in a VM

## 6. Verifying things yourself

```bash
python -m pytest backend/tests                              # includes the security, sandbox and fuzz tests
python backend/tests/manual/fuzz_parsers.py 2000            # long fuzz run
pip-audit -r requirements.lock.txt
bandit -r backend --ini .bandit -ll
python -m backend.report_signing verify path/to/report.pdf
```
