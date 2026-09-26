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
        <div class="error-banner-icon">${icon('alert')}</div>
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
        <button id="btn-generate-pdf" class="btn btn-primary">${icon('file-text')} Generate PDF Report</button>
      </div>
    </div>

    <div class="notice-card">
      <h3>${icon('alert')} Draft Certificate Notice</h3>
      <p>The Section 63(4) legal certificate pages carry a <strong>"DRAFT — NOT LEGAL ADVICE"</strong> watermark until reviewed and signed by a qualified expert.</p>
    </div>

    <div class="grid-2col">
      <div class="card">
        <div class="card-title">Included Report Sections</div>
        <ul class="report-disc-list">
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
        <p class="lead-text">
          Under Bharatiya Sakshya Adhiniyam 2023 Section 63(4) (formerly Indian Evidence Act Section 65B):
        </p>
        <div class="report-notice-box">
          • <strong>Part A</strong> (Tool Automated): Hashes, software version, algorithm details.<br>
          • <strong>Part B</strong> (Investigator): Physical seizure, custody dates, signature line.
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Encrypted Case Package</div>
      <p class="report-subtitle-text">
        A single passphrase-encrypted file (AES-256-GCM) with this case's exports, signed reports, analyses and audit log,
        for archiving or hand-over. Evidence images are not included. Any change to the file is detected when it is opened
        (<code>python -m backend.case_package decrypt file.sihpkg out.zip</code>). Lose the passphrase and it cannot be opened.
      </p>
      <div class="d-flex gap-10 flex-wrap items-center">
        <input type="password" id="pkg-pass" class="form-control max-w-sm" placeholder="Passphrase (12+ characters)" autocomplete="new-password">
        <button id="btn-package" class="btn btn-secondary">${icon('lock')} Create encrypted package</button>
        <span id="pkg-msg" class="text-sm text-muted"></span>
      </div>
    </div>

    <!-- Result panel — hidden until generation completes -->
    <div id="report-result-card" class="hidden"></div>

    <!-- Generation error — hidden until an error occurs -->
    <div id="report-error-card" class="hidden"></div>
  `;

  document.getElementById('btn-package').onclick = async () => {
    const msg = document.getElementById('pkg-msg');
    const pass = document.getElementById('pkg-pass').value;
    if (pass.length < 12) { msg.textContent = 'Use a passphrase of at least 12 characters.'; return; }
    msg.textContent = 'Encrypting…';
    try {
      const r = await API.downloadCasePackage(caseId, pass);
      const sizeStr = `${(r.size_bytes / 1024).toFixed(0)} KB`;
      msg.textContent = `Downloaded (${sizeStr}). Keep the passphrase safe.`;
      document.getElementById('pkg-pass').value = '';
      showToast(`Forensic package downloaded (${sizeStr})`, 'success');
    } catch (e) {
      msg.textContent = e.message;
      showToast(`Package creation failed: ${escapeHtml(e.message)}`, 'error');
    }
  };

  // ── Generate PDF ───────────────────────────────────────────────────────────
  const genBtn = document.getElementById('btn-generate-pdf');
  genBtn.onclick = async () => {
    genBtn.disabled = true;
    genBtn.innerHTML = '<span class="btn-spinner"></span> Generating…';

    document.getElementById('report-result-card').classList.add('hidden');
    document.getElementById('report-error-card').classList.add('hidden');

    try {
      const res = await API.generateReport(caseId, evidenceId);
      showToast(`PDF report generated: ${escapeHtml(res.filename)}`, 'success');

      // Success — show inline result card
      const resultCard = document.getElementById('report-result-card');
      resultCard.innerHTML = `
        <div class="card border-complete">
          <div class="card-title text-complete">${icon('check-circle')} PDF Report Generated &amp; Downloaded</div>
          <div class="flex-col gap-10 text-base">
            <div class="success-inline report-pkg-complete">
              Your browser has been triggered to download the PDF report.
            </div>
            <div>
              <div class="meta-label">Filename</div>
              <div class="font-mono-sm text-main word-break-all mt-xs">${escapeHtml(res.filename)}</div>
            </div>
            <div>
              <div class="meta-label">File Size</div>
              <div class="meta-value">${(res.size_bytes / 1024).toFixed(1)} KB</div>
            </div>
          </div>
        </div>`;
      resultCard.classList.remove('hidden');

      genBtn.disabled = false;
      genBtn.innerHTML = icon('file-text') + ' Regenerate PDF Report';

    } catch (err) {
      showToast(`Report generation failed: ${escapeHtml(err.message)}`, 'error');
      const errCard = document.getElementById('report-error-card');
      errCard.innerHTML = `
        <div class="error-banner">
          <div class="error-banner-icon">${icon('alert')}</div>
          <div class="error-banner-body">
            <div class="error-banner-title">Report generation failed</div>
            <div class="error-banner-msg">${escapeHtml(err.message)}</div>
          </div>
        </div>`;
      errCard.classList.remove('hidden');

      genBtn.disabled = false;
      genBtn.innerHTML = icon('file-text') + ' Retry PDF Generation';
    }
  };
}
