# User Manual

For forensic examiners using the DVR/NVR Forensic Analysis Tool. For the strict procedure to follow on a live case, use [SOP.md](SOP.md); this manual explains every screen and what each result means.

> **Read this first.** The tool has been tested on disk images generated from public specifications, not on a real recorder disk. Treat every recovered video as a *lead to be corroborated*, and read the status labels in §7 before you cite anything.

## 1. Installing and starting

**Needs:** Python 3.11+, FFmpeg and ffprobe on `PATH`, Windows 10/11, Linux or macOS.

| System | Install | Start |
|---|---|---|
| Windows | `install.bat` | `run.bat` |
| Linux / macOS | `chmod +x install.sh run.sh && ./install.sh` | `./run.sh` |

The installer creates `.venv` and installs `requirements.txt`; the start script checks Python and FFmpeg and serves the app at **http://127.0.0.1:8000** (local machine only).

**Optional settings** (environment variables, or a `.env` file copied from `.env.example`):

| Variable | Effect |
|---|---|
| `DATABASE_URL` | Store cases in Supabase/Postgres instead of local SQLite. Use the *session pooler* string; percent-encode special characters (`@` → `%40`) |
| `FORENSIC_CASE_DIR` | Folder for case data, exports and reports |
| `FORENSIC_ALLOW_LOCAL_ACQUISITION=1` | Enables drive imaging (see §5) |
| `OBJECT_MODEL_PATH` | Alternative YOLOX ONNX model |
| `SESSION_TIMEOUT_MINUTES` | Idle timeout, default 30 |

## 2. Signing in

On first launch you create the examiner password (at least 12 characters); it is stored only as a bcrypt hash. Afterwards, sign in with it. After 5 wrong attempts the login locks for 60 seconds (a countdown is shown). After 30 idle minutes you are signed out. There is one examiner account; there is no password-reset email — if the password is lost, the stored hash must be cleared by whoever administers the database (this is deliberate: no recovery path is a back door).

## 3. Dashboard and cases

- **Dashboard**: lists cases with their number, examiner and status. **Register New Case** opens the form.
- **New case**: case/reference number (unique, 1–64 characters: letters, digits, `-`, `/`, `_`), examiner name (at least 2 characters), agency and notes.
- **Case overview**: details, attached evidence, and buttons for evidence, scan, recordings, timeline, report and audit log (left navigation).

## 4. Attaching evidence

Click **Load Disk Image** in the case. Three options:

1. **Choose a file** from your computer (uploaded into the case folder; suited to small and medium images).
2. **Local server file path**: an absolute path on the machine running the tool. Recommended for multi-GB images. Allowed types: raw images (`.dd`, `.img`, `.raw`, `.bin` and similar). Live-drive paths such as `\\.\PhysicalDrive0` are refused here.
3. **Create an image from a drive** — see §5.

Optionally enter the **device clock offset from UTC** in minutes (for example `330` for IST). Enter it only if you have independently confirmed the recorder's time zone; otherwise recorded times are shown as raw device times and never assumed to be UTC.

## 5. Imaging a drive (optional)

Available only when the tool runs on your own workstation with `FORENSIC_ALLOW_LOCAL_ACQUISITION=1`.

1. Connect the source through a **hardware write blocker** (or read-only mount). The software cannot enforce this.
2. Pick the drive in the list or type a path, tick the write-blocker confirmation, and click **Start imaging**. Progress shows bytes read. Raw devices usually need administrator/root rights.
3. When finished you see the SHA-256 and either *Image verified and bit-exact* or *Not bit-exact* (unreadable sectors were zero-filled and are listed in `<image>.acquisition.json`). The image becomes the case evidence and the scan screen opens.

Status: verified on ordinary files including simulated bad sectors; **not yet run on a physical drive**. Try it on a scratch disk first.

## 6. Scanning

On **Acquisition & Scan** you see the image path, SHA-256 and MD5 (computed at scan start), file size and format. **Start Carving Scan** runs, with live progress:

| Phase | Meaning |
|---|---|
| Hashing | Opening hash of the image |
| Detecting | Every brand plugin scores the image; the best score ≥ 0.6 wins, otherwise the generic carver is used |
| Index read | Reads the recorder's own index where the format has one (Dahua DHFS, Hikvision HIKBTREE) |
| Carving | Finds frames/records by structure and validates them |
| Reconstructing | Groups frames into per-camera segments and labels them |
| Done | Evidence is re-hashed and compared with the opening hash |

**Brand detection card:** shows the brand, confidence and the plugin's own trust wording (for example "unvalidated on hardware"). *Unknown* means no plugin recognised the disk; the generic standards-based carver still runs and may find standard streams. **Verify Image Hashes** re-hashes the image on demand and reports MATCH or a mismatch.

## 7. Recordings and status labels

Each row is a segment: camera, time range (UTC when an offset was set), frame count, status, notes, hash prefix and actions.

| Status | Meaning | What to do |
|---|---|---|
| **PARTIAL** | The export decodes with ffprobe but frames may be missing or gaps exist | Report the gaps; corroborate |
| **UNCERTAIN** | Could not be decoded, or too little evidence, or an experimental carving path | Do not present as footage; corroborate independently |
| **COMPLETE** | Never assigned by carving alone | — |

The notes column states the basis (indexed / carved, whether timestamps came from the disk, anything unavailable). Actions per segment:

- **Export MP4** — lossless stream copy (no re-encoding) with `ffprobe` validation and a file hash. Analytics require an export first.
- **Check Motion** — frame differencing; shows *Basic Motion Detection*, not AI.
- **Check Faces** — YuNet face detection (presence and count only, no identity) and indexing for search.
- **Check Objects** — YOLOX object classes (or the person-only fallback) with sampled-frame counts, first-seen time and best score.

All analytics are aids for human review. Frames are sampled, small or dark subjects can be missed, and "none found" does not mean "none present".

**Search for a person:** upload a reference photo; segments already checked with *Check Faces* are ranked by similarity. Scores are *candidates for human review*, never confirmed matches.

## 8. Measuring accuracy (test scenarios)

Use **Accuracy Against Ground Truth** when you have something to compare against — for example a test where you recorded video, deleted it on the recorder, recovered it, and kept the original.

| Supply | Result |
|---|---|
| A known-good video | Frames recovered, frames that are right, frames in correct order, byte-identical yes/no |
| A recording log (JSON) | Time coverage and start/end offsets (times in the recorder's clock, or UTC with the evidence offset) |
| The original pre-deletion image path | Original bytes recovered and bytes from the right place |

Choose *Exact* when the ground-truth video is the same stream only re-wrapped, *Perceptual* when a vendor player re-encoded it (an upper bound). Anything not supplied shows **not measured**. Without ground truth the tool never states a recovery percentage. Full explanation: [accuracy_measurement.md](accuracy_measurement.md).

Log format:
```json
{"recordings":[{"name":"front door","camera":1,"start":"2026-03-01T10:00:00Z","end":"2026-03-01T11:00:00Z"}]}
```

## 9. Timeline and correlation

The timeline shows segments per camera on a common time axis, and groups segments whose time windows overlap across two or more cameras into events. If segments have no timestamps (some formats carry none) the screen says so instead of drawing a misleading axis. Correlation is time proximity only, not content analysis.

## 10. Report and audit log

- **Report & Certificate** generates the PDF: cover, integrity hashes, segments, cross-camera events, accuracy (or "NOT MEASURED"), object detection, method and limitations, the audit log, and the BSA 2023 §63(4) certificate template. Review it, complete the parts that need your declaration and signature, and keep it with the case file. It supports the examiner; it is not legal advice.
- **Hash Audit Log** shows every recorded action with its chain hash and a **CHAIN VALID** or **TAMPERING DETECTED** banner. If tampering is shown, stop relying on the log, preserve the result and escalate per your procedure.

## 11. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Start script stops at a check | Python < 3.11 or FFmpeg/ffprobe not on `PATH` |
| "Failed to fetch" | The server is not running or you opened a different address; use http://127.0.0.1:8000 |
| Brand *Unknown* | No plugin recognised the disk. Check the source; generic carving may still yield video |
| Export marked UNCERTAIN | The carved stream did not decode. Try another segment; corroborate |
| Verify shows mismatch | The image file changed. Stop; preserve; re-acquire |
| Drive imaging option says disabled | Server not started with `FORENSIC_ALLOW_LOCAL_ACQUISITION=1` |
| Imaging: permission denied | Raw devices need administrator/root rights |
| Object detection uses the person-only method | `cv_models/object_detection_yolox_2022nov.onnx` is missing |
| Accuracy: "segment not exported" | Export the segment first |
| Case created in the wrong database | `DATABASE_URL` is set; unset it to use local SQLite |

## 12. Limits you must know

No real-disk validation; four vendors (TP-Link, Godrej, Uniview, Matrix) have no vendor-specific parser; Honeywell rests on one paper about one model; CP Plus on an unverified assumption; drive imaging is untested on real drives; analytics were checked on a few photos only. See the [README limitations](../README.md#-known-limitations) and [format_verification.md](format_verification.md).
