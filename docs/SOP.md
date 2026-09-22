# Standard Operating Procedure: DVR/NVR Evidence Recovery

## Purpose and scope

Use this procedure to create a case, process a **forensically acquired raw disk image**, review recovered video, and produce the application's case documentation. The application accepts raw-image files with the extensions `.dd`, `.img`, `.raw`, or `.bin`; it deliberately refuses live physical-drive paths. Acquire the source media with an approved acquisition process before using this tool. Do not use a synthetic test image as real evidence.

1. **Sign in as the examiner.**
   - Open the application. On first use, create the access password; it must be at least 12 characters long. The application signs you in after the initial password is set.
   - On later use, enter the existing access password on the login screen. A successful login opens the case dashboard. Failed login attempts are recorded in the access audit trail; passwords themselves are not recorded.

2. **Create the case before loading evidence.**
   - Select **Register New Case** from the dashboard.
   - Enter the case/reference number, investigator name, agency/organisation, and any relevant case summary or seizure notes. Case numbers must be unique and may contain letters, numbers, dashes, slashes, and underscores.
   - Select **Create Case & Add Evidence**. Check the case details page shows the correct case number, examiner, and notes before proceeding.

3. **Attach the acquired disk image.**
   - In the case, select **Load Disk Image**.
   - Enter the absolute local path of the forensic image. Use a file with an allowed raw-image extension (`.dd`, `.img`, `.raw`, or `.bin`). Do not enter a live-drive path such as `\\.\PhysicalDrive0`; the application rejects it to avoid operating on live media.
   - Select **Load & Calculate Hashes**. The image is registered as case evidence and the application opens **Acquisition & Scan**. Record the source path and evidence identifier in the case record as appropriate.
   - Important: attaching the image registers it; the actual SHA-256 and MD5 baseline calculation occurs at the beginning of the forensic scan in step 5. The evidence-loading event is added to the case audit log.

4. **Prepare to verify evidence integrity.**
   - On **Acquisition & Scan**, confirm that the displayed image path is the intended acquired copy. Do not modify, mount read/write, or replace that image during processing.
   - The scan creates SHA-256 and MD5 acquisition values, displays them on this page, and performs a second SHA-256 check before it completes. Once a scan has loaded the image, use **Verify Image Hashes** to request an additional comparison against the acquisition baseline.
   - Treat a **MATCH** result as confirmation that the image matches the recorded baseline at the time checked. If the application reports a mismatch, stop using that evidence output, preserve the discrepancy, and investigate or reacquire a verified image before relying on results.

5. **Run brand detection and the carving scan.**
   - Select **Start Carving Scan**. The application first opens the image and calculates its baseline SHA-256 and MD5 values, then runs its available format detectors and shows the detected brand and confidence on the same page.
   - A low-confidence or unsupported result stops processing; do not relabel it manually as a supported recorder. Preserve the detection result and seek a validated workflow for that media.
   - For a supported/accepted result, leave the scan running. The live progress panel reports hashing, brand detection, index reading where available, carving, reconstruction, and final hash re-verification. Do not close the application or change the source image while it is running.
   - When the tool reports completion, select **View Recordings** (or allow the automatic transition) to open the reconstructed segments. If the scan reports an error, record the message in the case notes and resolve it before treating any prior output as final.

6. **Review reconstructed segments and their status labels.**
   - In **Carved Video Segments**, review each camera number, UTC time range, frame count, gap/rationale text, and displayed SHA-256 prefix. Confirm the timeline and labels are plausible for the investigation.
   - Interpret the labels conservatively:
     - **COMPLETE** — all frames were recovered with no detected gaps; high evidentiary confidence.
     - **PARTIAL** — frames are missing or gaps were detected; moderate confidence. Identify and report the gaps.
     - **UNCERTAIN** — significant corruption or missing data; low confidence. Corroborate independently and do not present it as complete footage.
   - The labels describe recovery quality, not the truth or relevance of the recorded scene. Document any material limitation before export or reporting.

7. **Export the clips selected for review or disclosure.**
   - For each required segment, select **Export MP4**. Wait for the success dialog rather than assuming an export was produced.
   - Record the displayed output path and SHA-256 value. Review the displayed `ffprobe` validation result: a valid MP4 container is a technical validation, not a statement about content accuracy or recovery completeness.
   - Keep the exported file with its recorded hash under the case's evidence-handling controls. The export action and associated details are appended to the case audit log.

8. **Generate the forensic report and certificate helper.**
   - From the recordings screen, select **Export PDF Forensic Report**, then select **Generate PDF Report**. The browser downloads a timestamped PDF and the application stores it in the case report area.
   - Review the PDF before use. It includes case and chain-of-custody information, integrity hashes, brand-detection results, segment and gap information, exported-file hashes, the audit trail, and a Section 63(4) Bharatiya Sakshya Adhiniyam 2023 certificate helper.
   - The certificate helper pre-fills technical fields in Part A. Complete Part B's physical-seizure, custody, and signature information outside the automated fields as required by the applicable legal process. It is a draft helper and not legal advice. Reports made from synthetic data are watermarked **DRAFT — SYNTHETIC DATA** and must not be used as evidence.

9. **Review the hash-chained audit log before closing the case.**
   - Open **Hash-Chained Audit Log** from the case navigation. Confirm it displays **CHAIN VALID** and review the sequence of evidence loading, hashing, detection, scanning, verification, export, and report events.
   - Each entry is chained as `SHA-256(Time | Action | Parameters | Previous Hash)`. Check the action details against your work notes and retain the report/audit output with the case file.
   - If the screen displays **TAMPERING DETECTED** or a chain error, stop relying on the log as intact evidence. Preserve the result, document the error, and escalate according to laboratory or agency procedure.
