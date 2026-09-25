/**
 * ExportReportScreen.js — Generate PDF Forensic Report and Section 63(4) Certificate.
 */
async function renderExportReportScreen(params) {
  const { caseId, evidenceId } = params;
  const root = document.getElementById('content-root');

  // ── Loading state ─────────────────────────────────────────────────────────
  root.innerHTML = `
    <div class="loading-state">
      <div class="spinner"></div>
      <p>Loading reporting options…</p>
    </div>`;

  let ev;
  try {
    ev = await API.getEvidence(caseId, evidenceId);
  } catch (err) {
    root.innerHTML = `
      <div class="page-header">
        <div class="page-title">Forensic Report &amp; Legal Certificate</div>
      </div>
      <div class="error-banner">
        <div class="error-banner-icon">⚠️</div>
        <div class="error-banner-body">
          <div class="error-banner-title">Failed to load reporting options</div>
          <div class="error-banner-msg">${escapeHtml(err.message)}</div>
        </div>
      </div>`;
    return;
  }

  root.innerHTML = `
    <div class="page-header">
      <div class="page-header-row">
        <div>
          <div class="page-title">Forensic Report &amp; Legal Certificate</div>
          <div class="page-subtitle">Generate verified PDF documentation for evidence <strong>${escapeHtml(ev.evidence_label || ev.path?.split(/[\\/]/).pop() || ev.evidence_id)}</strong>.</div>
        </div>
        <button id="btn-generate-pdf" class="btn btn-primary">📄 Generate PDF Report</button>
      </div>
    </div>

    <div class="notice-card">
      <h3>⚠️ Draft Certificate Notice</h3>
      <p>The Section 63(4) legal certificate pages carry a <strong>"DRAFT — NOT LEGAL ADVICE"</strong> watermark until reviewed and signed by a qualified expert.</p>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
      <div class="card">
        <div class="card-title">Included Report Sections</div>
        <ul style="font-size: 13px; color: var(--text-muted); padding-left: 18px; line-height: 2.0; list-style-type: disc;">
          <li>Cover Page with Case Reference &amp; Chain of Custody</li>
          <li>Evidence Integrity Hashes (Acquisition vs Pre-Scan)</li>
          <li>Brand Detection Results &amp; Confidence Breakdown</li>
          <li>Channel &amp; Timestamp Summary Table</li>
          <li>Identified Timeline Gaps &amp; Rationale</li>
          <li>Exported File Hashes &amp; Re-verification Log</li>
          <li>Section 63(4) BSA Certificate (Part A)</li>
          <li>Cryptographic Hash-Chained Audit Log</li>
        </ul>
      </div>

      <div class="card">
        <div class="card-title">Legal Certificate Details</div>
        <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px; line-height:1.6;">
          Under Bharatiya Sakshya Adhiniyam 2023 Section 63(4) (formerly Indian Evidence Act Section 65B):
        </p>
        <div style="background: rgba(0,0,0,0.3); padding: 14px 16px; border-radius: 8px; font-size: 12px; font-family: var(--font-mono); color: var(--text-muted); line-height:1.8; border-left:3px solid var(--border-glow);">
          • <strong>Part A</strong> (Tool Automated): Hashes, software version, algorithm details.<br>
          • <strong>Part B</strong> (Investigator): Physical seizure, custody dates, signature line.
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Encrypted Case Package</div>
      <p style="font-size:12px; color:var(--text-muted); margin:0 0 10px; line-height:1.6;">
        A single passphrase-encrypted file (AES-256-GCM) with this case's exports, signed reports, analyses and audit log,
        for archiving or hand-over. Evidence images are not included. Any change to the file is detected when it is opened
        (<code>python -m backend.case_package decrypt file.sihpkg out.zip</code>). Lose the passphrase and it cannot be opened.
      </p>
      <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
        <input type="password" id="pkg-pass" class="form-control" style="max-width:320px;" placeholder="Passphrase (12+ characters)" autocomplete="new-password">
        <button id="btn-package" class="btn btn-secondary">🔒 Create encrypted package</button>
        <span id="pkg-msg" style="font-size:12px; color:var(--text-muted);"></span>
      </div>
    </div>

    <!-- Result panel — hidden until generation completes -->
    <div id="report-result-card" style="display:none;"></div>

    <!-- Generation error — hidden until an error occurs -->
    <div id="report-error-card" style="display:none;"></div>
  `;

  document.getElementById('btn-package').onclick = async () => {
    const msg = document.getElementById('pkg-msg');
    const pass = document.getElementById('pkg-pass').value;
    if (pass.length < 12) { msg.textContent = 'Use a passphrase of at least 12 characters.'; return; }
    msg.textContent = 'Encrypting…';
    try {
      const r = await API.downloadCasePackage(caseId, pass);
      msg.textContent = `Downloaded (${(r.size_bytes / 1024).toFixed(0)} KB). Keep the passphrase safe.`;
      document.getElementById('pkg-pass').value = '';
    } catch (e) { msg.textContent = e.message; }
  };

  // ── Generate PDF ───────────────────────────────────────────────────────────
  const genBtn = document.getElementById('btn-generate-pdf');
  genBtn.onclick = async () => {
    genBtn.disabled = true;
    genBtn.innerHTML = '<span class="btn-spinner"></span> Generating…';

    document.getElementById('report-result-card').style.display = 'none';
    document.getElementById('report-error-card').style.display  = 'none';

    try {
      const res = await API.generateReport(caseId, evidenceId);

      // Success — show inline result card
      const resultCard = document.getElementById('report-result-card');
      resultCard.innerHTML = `
        <div class="card" style="border-color:rgba(16,185,129,0.35);">
          <div class="card-title" style="color:var(--status-complete);">✅ PDF Report Generated &amp; Downloaded</div>
          <div style="font-size:13px; display:flex; flex-direction:column; gap:10px;">
            <div class="success-inline" style="border-radius:6px; border-left:none; border:1px solid rgba(16,185,129,0.4);">
              Your browser has been triggered to download the PDF report.
            </div>
            <div>
              <div class="meta-label">Filename</div>
              <div style="font-family:var(--font-mono); font-size:12px; color:var(--text-main); word-break:break-all; margin-top:4px;">${escapeHtml(res.filename)}</div>
            </div>
            <div>
              <div class="meta-label">File Size</div>
              <div class="meta-value">${(res.size_bytes / 1024).toFixed(1)} KB</div>
            </div>
          </div>
        </div>`;
      resultCard.style.display = 'block';

      genBtn.disabled = false;
      genBtn.innerHTML = '📄 Regenerate PDF Report';

    } catch (err) {
      const errCard = document.getElementById('report-error-card');
      errCard.innerHTML = `
        <div class="error-banner">
          <div class="error-banner-icon">⚠️</div>
          <div class="error-banner-body">
            <div class="error-banner-title">Report generation failed</div>
            <div class="error-banner-msg">${escapeHtml(err.message)}</div>
          </div>
        </div>`;
      errCard.style.display = 'block';

      genBtn.disabled = false;
      genBtn.innerHTML = '📄 Retry PDF Generation';
    }
  };
}
