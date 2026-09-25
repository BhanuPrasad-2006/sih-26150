/**
 * EvidenceScanScreen.js — Acquisition overview, brand detection, and live carving scan.
 */
async function renderEvidenceScanScreen(params) {
  const { caseId, evidenceId } = params;
  const root = document.getElementById('content-root');

  // ── Loading state ─────────────────────────────────────────────────────────
  root.innerHTML = `
    <div class="loading-state">
      <div class="spinner"></div>
      <p>Loading evidence details…</p>
    </div>`;

  let ev;
  try {
    ev = await API.getEvidence(caseId, evidenceId);
  } catch (err) {
    root.innerHTML = `
      <div class="page-header">
        <div class="page-title">Acquisition &amp; Scan</div>
      </div>
      <div class="error-banner">
        <div class="error-banner-icon">⚠️</div>
        <div class="error-banner-body">
          <div class="error-banner-title">Failed to load evidence</div>
          <div class="error-banner-msg">${escapeHtml(err.message)}</div>
        </div>
      </div>`;
    return;
  }

  // Map backend field names to display values
  const evLabel     = ev.evidence_label || ev.path?.split(/[\\/]/).pop() || ev.evidence_id;
  const evPath      = ev.path || '—';
  const sha256      = ev.sha256_before || ev.sha256_after || '—';
  const md5         = ev.md5_before || '—';
  const detBrand    = ev.brand || 'Unknown';
  const brandConf   = ev.confidence != null ? (ev.confidence * 100).toFixed(0) : '—';
  const sizeMB      = ev.size_bytes != null ? (ev.size_bytes / (1024 * 1024)).toFixed(2) : '—';
  const scanStatus  = ev.scan_status || 'PENDING';
  const isScanning  = scanStatus === 'SCANNING';
  const isCompleted = scanStatus === 'COMPLETED';
  const scanBtnLabel = isCompleted ? '🔁 Re-Run Forensic Scan' : '🚀 Start Carving Scan';

  const statusBadgeClass = isCompleted ? 'badge-complete'
                         : isScanning  ? 'badge-scanning'
                         : 'badge-pending';

  root.innerHTML = `
    <div class="page-header">
      <div class="page-header-row">
        <div>
          <div class="page-title">Acquisition &amp; Scan: <span style="color:var(--accent-cyan);">${evLabel}</span></div>
          <div class="page-subtitle" style="font-family:var(--font-mono); font-size:12px;">${evPath}</div>
        </div>
        <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
          <button id="btn-verify-integrity" class="btn btn-secondary">🔍 Verify Image Hashes</button>
          <button id="btn-start-scan" class="btn btn-primary"
            ${isScanning ? 'disabled title="A scan is already running on this image"' : ''}>
            ${isScanning ? '<span class="btn-spinner"></span> Scan Running…' : scanBtnLabel}
          </button>
        </div>
      </div>
    </div>

    <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-bottom: 0;">
      <!-- Hashes card -->
      <div class="card" style="margin-bottom:0;">
        <div class="card-title">Acquisition Hashes</div>
        <div style="display: flex; flex-direction: column; gap: 14px; font-size: 13px;">
          <div>
            <div class="meta-label">SHA-256</div>
            <div class="hash-font" style="margin-top:4px; word-break:break-all;">${sha256}</div>
          </div>
          <div>
            <div class="meta-label">MD5</div>
            <div class="hash-font" style="margin-top:4px; word-break:break-all;">${md5}</div>
          </div>
          <div style="display:flex; gap:32px; margin-top:4px;">
            <div>
              <div class="meta-label">File Size</div>
              <div class="meta-value">${sizeMB} MB</div>
            </div>
            <div>
              <div class="meta-label">Format</div>
              <div class="meta-value">Raw Binary (.dd)</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Brand detection card -->
      <div class="card" style="margin-bottom:0;">
        <div class="card-title">Brand Detection</div>
        <div style="text-align:center; padding:12px 0;">
          <div style="font-size:26px; font-weight:700; color:var(--accent-cyan); margin-bottom:6px;">${detBrand}</div>
          <div style="font-size:13px; color:var(--text-muted);">Confidence: <strong>${brandConf}%</strong></div>
          <div style="margin-top:12px;">
            <span class="badge ${detBrand.toLowerCase().includes('unverified') ? 'badge-uncertain' : 'badge-verified'}">${detBrand}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Live scan progress -->
    <div id="scan-progress-card" class="card" style="margin-top:20px; display:${isScanning ? 'block' : 'none'};">
      <div class="card-title">
        <span style="display:flex; align-items:center; gap:10px;">
          <span id="scan-title-spinner" class="spinner spinner-sm"></span>
          Scanning &amp; Frame Carving
        </span>
        <span id="scan-percentage" style="color:var(--accent-cyan); font-size:18px; font-weight:700;">0%</span>
      </div>
      <div class="progress-bar-container">
        <div id="scan-progress-bar" class="progress-bar-fill"></div>
      </div>
      <p id="scan-status-text" style="font-size:13px; color:var(--text-muted); margin-top:6px;">Initialising scanner…</p>
    </div>

    <!-- Scan results summary -->
    <div class="card" style="margin-top:20px;">
      <div class="card-title">
        <span>Scan Results &amp; Segments</span>
        ${isCompleted ? `<button class="btn btn-secondary btn-sm" onclick="navigateTo('recordings', { caseId: '${caseId}', evidenceId: '${evidenceId}' })">View Recordings ➔</button>` : ''}
      </div>
      <div style="display:flex; align-items:center; gap:12px; font-size:14px;">
        <span style="color:var(--text-muted);">Current status:</span>
        <span class="badge ${statusBadgeClass}">${ev.scan_status || 'PENDING'}</span>
        ${isCompleted ? '<span style="font-size:13px; color:var(--text-muted);">— Scan complete. Navigate to Recordings to review carved segments.</span>' : ''}
        ${!isCompleted && !isScanning ? '<span style="font-size:13px; color:var(--text-muted);">— Click "Start Carving Scan" to begin forensic acquisition.</span>' : ''}
      </div>
    </div>
  `;

  // ── Verify integrity ───────────────────────────────────────────────────────
  document.getElementById('btn-verify-integrity').onclick = async () => {
    showModal('Integrity Verification', `
      <div class="loading-state" style="padding:24px;">
        <div class="spinner"></div>
        <p>Verifying SHA-256 hash against acquisition baseline…</p>
      </div>`);
    try {
      const res = await API.verifyEvidenceIntegrity(caseId, evidenceId);
      showModal(
        'Integrity Verification Result',
        res.match
          ? `<div class="success-inline" style="border-radius:6px; border-left:none; border:1px solid rgba(16,185,129,0.4);">
               ✅ MATCH — Disk image has not been altered or tampered with.
             </div>
             <p class="hash-font" style="margin-top:12px; word-break:break-all;">SHA-256: ${res.current_sha256}</p>`
          : `<div class="error-banner" style="margin-top:0;">
               <div class="error-banner-icon">❌</div>
               <div class="error-banner-body">
                 <div class="error-banner-title">MISMATCH DETECTED</div>
                 <div class="error-banner-msg">The disk image has been modified since acquisition. Do not use this evidence until the discrepancy is investigated.</div>
               </div>
             </div>`
      );
    } catch (err) {
      showModal('Verification Error', `
        <div class="error-banner" style="margin-top:0;">
          <div class="error-banner-icon">⚠️</div>
          <div class="error-banner-body">
            <div class="error-banner-title">Verification failed</div>
            <div class="error-banner-msg">${escapeHtml(err.message)}</div>
          </div>
        </div>`);
    }
  };

  // ── Start scan ─────────────────────────────────────────────────────────────
  const btnScan = document.getElementById('btn-start-scan');
  if (!isScanning) {
    btnScan.onclick = async () => {
      const progressCard = document.getElementById('scan-progress-card');
      const progressBar  = document.getElementById('scan-progress-bar');
      const progressPct  = document.getElementById('scan-percentage');
      const statusText   = document.getElementById('scan-status-text');

      // Disable button immediately
      btnScan.disabled = true;
      btnScan.innerHTML = '<span class="btn-spinner"></span> Starting…';
      progressCard.style.display = 'block';

      try {
        await API.startScan(caseId, evidenceId);
        btnScan.innerHTML = '<span class="btn-spinner"></span> Scan Running…';

        API.listenScanProgress(
          caseId,
          evidenceId,
          // onProgress — field names must match backend/models.py's ScanProgress
          // (percent, bytes_done), not the progress_pct/bytes_processed names
          // this previously (and always) referenced, which silently threw on
          // every single message and meant this callback never ran at all.
          (prog) => {
            const pct = prog.percent || 0;
            progressBar.style.width = `${pct}%`;
            progressPct.innerText   = `${pct.toFixed(0)}%`;
            statusText.innerText    = prog.message
              || `Processed ${prog.bytes_done} / ${prog.total_bytes} bytes — Frames carved: ${prog.frames_found}`;
          },
          // onComplete — ScanProgress has no frames_found/segments_reconstructed
          // counts at the DONE phase; the human-readable summary lives in .message.
          (comp) => {
            progressPct.innerText = '100%';
            progressBar.style.width = '100%';
            statusText.innerHTML = `<span style="color:var(--status-complete);">✅ ${escapeHtml(comp.message || 'Scan complete.')}</span>`;
            btnScan.disabled = false;
            btnScan.innerHTML = '🔁 Re-Run Forensic Scan';
            setTimeout(() => {
              navigateTo('recordings', { caseId, evidenceId });
            }, 1200);
          },
          // onError
          (errMsg) => {
            statusText.innerHTML = `
              <div class="error-inline" style="margin-top:8px;">
                <span>⚠️</span>
                <span>Scan failed: ${escapeHtml(errMsg)}</span>
              </div>`;
            btnScan.disabled = false;
            btnScan.innerHTML = '🚀 Retry Carving Scan';
          }
        );
      } catch (err) {
        // Could not even start the scan
        statusText.innerHTML = `
          <div class="error-inline" style="margin-top:8px;">
            <span>⚠️</span>
            <span>Failed to initiate scan: ${escapeHtml(err.message)}</span>
          </div>`;
        btnScan.disabled = false;
        btnScan.innerHTML = '🚀 Start Carving Scan';
      }
    };
  }
}
