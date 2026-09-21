/**
 * ExportReportScreen.js — Generate PDF Forensic Report and Section 63(4) Certificate.
 */
async function renderExportReportScreen(params) {
  const { caseId, evidenceId } = params;
  const root = document.getElementById('content-root');

  root.innerHTML = `<p style="color:var(--text-dim);">Loading reporting options...</p>`;

  try {
    const ev = await API.getEvidence(caseId, evidenceId);

    root.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
        <div>
          <h2 style="font-size: 24px; font-weight: 700;">Forensic Report & Legal Certificate</h2>
          <p style="color: var(--text-muted); font-size: 14px;">Generate verified PDF documentation for evidence ${ev.evidence_label}.</p>

        </div>
        <button id="btn-generate-pdf" class="btn btn-primary">📄 Generate PDF Forensic Report</button>
      </div>

      <div class="card" style="border-left: 4px solid var(--accent-amber); background: rgba(245, 158, 11, 0.05);">
        <h3 style="color: var(--accent-amber); font-size: 14px; margin-bottom: 4px;">⚠️ Draft Watermark Notice</h3>
        <p style="font-size: 13px; color: var(--text-muted);">
          All reports generated from synthetic disk images contain a prominent <strong>"DRAFT - SYNTHETIC DATA"</strong> watermark across every page as required by protocol.
        </p>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
        <div class="card">
          <div class="card-title">Included Report Sections</div>
          <ul style="font-size: 14px; color: var(--text-muted); padding-left: 20px; line-height: 1.8;">
            <li>Cover Page with Case Reference & Chain of Custody</li>
            <li>Evidence Integrity Hashes (Acquisition vs Pre-Scan)</li>
            <li>Brand Detection Results & Confidence Breakdown</li>
            <li>Channel & Timestamp Summary Table</li>
            <li>Identified Timeline Gaps & Rationale</li>
            <li>Exported File Hashes & Re-verification Log</li>
            <li>Section 63(4) BSA Certificate (Part A)</li>
            <li>Cryptographic Hash-Chained Audit Log</li>
          </ul>
        </div>

        <div class="card">
          <div class="card-title">Legal Certificate Details</div>
          <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">
            Under Bharatiya Sakshya Adhiniyam 2023 Section 63(4) (formerly Indian Evidence Act Section 65B):
          </p>
          <div style="background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px; font-size: 12px; font-family: var(--font-mono); color: var(--text-muted);">
            • Part A (Tool Automated): Hashes, software version, algorithm details.<br>
            • Part B (Investigator): Physical seizure, custody dates, signature line.
          </div>
        </div>
      </div>

      <div id="report-result-card" class="card" style="display:none;">
        <div class="card-title" style="color: var(--accent-emerald);">Generated PDF Document</div>
        <p id="report-path-text" style="font-family: var(--font-mono); font-size: 13px; color: var(--text-main);"></p>
      </div>
    `;

    document.getElementById('btn-generate-pdf').onclick = async () => {
      showModal('Generating Report', '<p>Building PDF report with ReportLab...</p>');
      try {
        const res = await API.generateReport(caseId, evidenceId);
        showModal(
          'Report Ready',
          `
            <p style="color:var(--accent-emerald);">✅ PDF report generated successfully!</p>
            <p style="font-size:13px; margin-top:8px;"><strong>File Path:</strong><br><span style="font-family:var(--font-mono);">${res.file_path}</span></p>
            <p style="font-size:13px; margin-top:8px;"><strong>File Size:</strong> ${(res.size_bytes / 1024).toFixed(1)} KB</p>
          `
        );
        document.getElementById('report-result-card').style.display = 'block';
        document.getElementById('report-path-text').innerText = `PDF Location: ${res.file_path}`;
      } catch (err) {
        showModal('Error', `<p style="color:var(--accent-rose);">${err.message}</p>`);
      }
    };

  } catch (err) {
    root.innerHTML = `<p style="color:var(--accent-rose);">Failed to load report screen: ${err.message}</p>`;
  }
}
