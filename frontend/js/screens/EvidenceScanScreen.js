/**
 * EvidenceScanScreen.js — Acquisition overview, brand detection, and live carving scan.
 */
/** What kind of file this is, from its extension. The tool reads every image as raw bytes. */
function evidenceFormatLabel(path) {
  const name = String(path || '').split(/[\\/]/).pop();
  const m = /\.([A-Za-z0-9]{1,6})$/.exec(name);
  const ext = m ? m[1].toLowerCase() : '';
  if (!ext) return 'Raw image (no file extension)';
  if (['e01', 'ex01', 'aff', 'aff4', 'vmdk', 'vhd', 'vhdx', 'qcow2'].includes(ext)) {
    return `Container image (.${ext}) — read as raw bytes; convert to raw first`;
  }
  if (ext === '001') return 'Raw image, first split part (.001)';
  if (['dd', 'img', 'raw', 'bin', 'iso'].includes(ext)) return `Raw disk image (.${ext})`;
  return `Raw image (.${ext})`;
}

/** True when the scan fell back to standards-based stream carving instead of a vendor parser. */
function isGenericCarving(brand) {
  const b = String(brand || '').toLowerCase();
  return b.includes('generic') || b.includes('unidentified');
}

/** The Brand Detection card body: a mode indicator instead of a bare "0%" when no vendor matched. */
function brandCardHtml(brand, confidencePct, scanStatus) {
  const b = String(brand || '');
  const notScanned = (!b || b.toLowerCase() === 'unknown') && scanStatus === 'PENDING';
  if (notScanned) {
    return `
      <div class="brand-mode">
        <div class="brand-mode-name">Not scanned yet</div>
        <div class="brand-mode-sub">The recorder brand is worked out when you start the scan.</div>
      </div>`;
  }
  if (isGenericCarving(b)) {
    const hint = b.includes(' \u2014 ') ? b.split(' \u2014 ')[0] : '';
    return `
      <div class="brand-mode">
        <span class="badge badge-verified">${icon('layers')} Generic stream carving active</span>
        <div class="brand-mode-sub">No vendor signature matched, so no brand is claimed.</div>
        <div class="notice-card info">
          <div>
            <h3>What this means</h3>
            <p>No proprietary file-system header was recognised (Dahua, Hikvision, Honeywell). The tool falls back to
            signature-based carving of standard MPEG-PS and H.264 streams. Results stay UNCERTAIN until the exported video
            decodes, and camera numbers and times are only available if the stream itself carries them.</p>
            ${hint ? `<p class="mt-sm">A weak hint of <strong>${escapeHtml(hint)}</strong> was seen but not enough to trust.</p>` : ''}
          </div>
        </div>
      </div>`;
  }
  const bb = brandBadge(b);
  return `
    <div class="brand-mode">
      <div class="brand-mode-name">${escapeHtml(b)}</div>
      <div class="brand-mode-sub">Signature match confidence: <strong>${escapeHtml(String(confidencePct))}%</strong></div>
      <div class="mt-md">
        <span class="badge ${bb.cls}" data-tooltip="${escapeHtml(bb.tip)}">${escapeHtml(b)}</span>
      </div>
    </div>`;
}

/** Badge style for the detected brand: only recognised, described layouts look "verified". */
function brandBadge(brand) {
  const b = String(brand || '').toLowerCase();
  if (!b || b.includes('unknown') || b.includes('unidentified') || b.includes('generic')) {
    return { cls: 'badge-pending', tip: 'No recorder brand was identified.' };
  }
  if (b.includes('unverified') || b.includes('unvalidated') || b.includes('detection-only')) {
    return { cls: 'badge-partial', tip: 'Detection only. This layout has not been verified on a real recorder disk, so treat results with caution.' };
  }
  return { cls: 'badge-verified', tip: 'Recognised recorder layout.' };
}

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
        <div class="error-banner-icon">${icon('alert')}</div>
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
  const scanBtnLabel = isCompleted ? icon('refresh') + ' Re-Run Forensic Scan' : icon('rocket') + ' Start Carving Scan';

  const statusBadgeClass = isCompleted ? 'badge-complete'
                         : isScanning  ? 'badge-scanning'
                         : 'badge-pending';

  root.innerHTML = `
    <div class="page-header">
      <div class="page-header-row">
        <div>
          <div class="page-title">Acquisition &amp; Scan: <span class="text-primary">${evLabel}</span></div>
          <div class="page-subtitle font-mono-sm">${evPath}</div>
        </div>
        <div class="d-flex gap-10 flex-wrap items-center">
          <button id="btn-verify-integrity" class="btn btn-secondary">${icon('fingerprint')} Verify Image Hashes</button>
          <button id="btn-start-scan" class="btn btn-primary"
            ${isScanning ? 'disabled title="A scan is already running on this image"' : ''}>
            ${isScanning ? '<span class="btn-spinner"></span> Scan Running…' : scanBtnLabel}
          </button>
        </div>
      </div>
    </div>

    <div class="scan-grid">
      <!-- Hashes card -->
      <div class="card mb-0">
        <div class="card-title">Acquisition Hashes</div>
        <div class="flex-col gap-14 text-base">
          <div>
            <div class="meta-label">SHA-256</div>
            <div class="hash-font mt-xs word-break-all">${sha256}</div>
          </div>
          <div>
            <div class="meta-label">MD5</div>
            <div class="hash-font mt-xs word-break-all">${md5}</div>
          </div>
          <div class="d-flex gap-32 mt-xs">
            <div>
              <div class="meta-label">File Size</div>
              <div class="meta-value">${sizeMB} MB</div>
            </div>
            <div>
              <div class="meta-label">Format</div>
              <div class="meta-value">${escapeHtml(evidenceFormatLabel(ev.path))}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Brand detection card -->
      <div class="card mb-0">
        <div class="card-title">Brand Detection</div>
        <div id="brand-card-body">${brandCardHtml(detBrand, brandConf, scanStatus)}</div>
      </div>
    </div>

    <!-- Live scan progress -->
    <div id="scan-progress-card" class="card mt-xl ${isScanning ? '' : 'hidden'}">
      <div class="card-title">
        <span class="d-flex items-center gap-10">
          <span id="scan-title-spinner" class="spinner spinner-sm"></span>
          Scanning &amp; Frame Carving
        </span>
        <span id="scan-percentage" class="stat-medium">0%</span>
      </div>
      <div class="progress-bar-container">
        <div id="scan-progress-bar" class="progress-bar-fill"></div>
      </div>
      <p id="scan-status-text" class="text-base text-muted mt-6">Initialising scanner…</p>
    </div>

    <!-- Scan results summary -->
    <div class="card mt-xl">
      <div class="card-title">
        <span>Scan Results &amp; Segments</span>
        ${isCompleted ? `<button class="btn btn-secondary btn-sm" ${navAttrs('recordings', { caseId: caseId, evidenceId: evidenceId })}>View Recordings ${icon('arrow-right')}</button>` : ''}
      </div>
      <div class="d-flex items-center gap-md text-lg">
        <span class="text-muted">Current status:</span>
        <span class="badge ${statusBadgeClass}">${ev.scan_status || 'PENDING'}</span>
        ${isCompleted ? '<span class="text-base text-muted">— Scan complete. Navigate to Recordings to review carved segments.</span>' : ''}
        ${!isCompleted && !isScanning ? '<span class="text-base text-muted">— Click "Start Carving Scan" to begin forensic acquisition.</span>' : ''}
      </div>
    </div>
  `;

  // ── Verify integrity ───────────────────────────────────────────────────────
  const btnVerify = document.getElementById('btn-verify-integrity');
  if (btnVerify) {
    btnVerify.onclick = async () => {
      btnVerify.disabled = true;
      btnVerify.innerHTML = '<span class="btn-spinner"></span> Verifying…';
      try {
        const res = await API.verifyEvidenceIntegrity(caseId, evidenceId);
        if (res.match) {
          const shaShort = res.current_sha256 ? res.current_sha256.substring(0, 12) + '…' : '';
          showToast(`Integrity MATCH: Disk image verified against baseline (${shaShort})`, 'success');
        } else {
          showToast('MISMATCH DETECTED: Disk image has been modified since acquisition!', 'error', { duration: 8000 });
        }
      } catch (err) {
        showToast(`Verification failed: ${escapeHtml(err.message)}`, 'error');
      } finally {
        btnVerify.disabled = false;
        btnVerify.innerHTML = `${icon('shield-check')} Verify Integrity`;
      }
    };
  }

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
      progressCard.classList.remove('hidden');

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
            statusText.innerHTML = `
              <div class="d-flex items-center gap-14 flex-wrap">
                <span class="text-complete">${icon('check-circle')} ${escapeHtml(comp.message || 'Scan complete.')}</span>
                <button class="btn btn-primary btn-sm" ${navAttrs('recordings', { caseId: caseId, evidenceId: evidenceId })}>View recordings ${icon('arrow-right')}</button>
              </div>`;
            btnScan.disabled = false;
            btnScan.innerHTML = icon('refresh') + ' Re-Run Forensic Scan';
            // Show the brand the scan just decided on (was left at the pre-scan value).
            API.getEvidence(caseId, evidenceId).then((fresh) => {
              const card = document.getElementById('brand-card-body');
              if (card) {
                const pct = fresh.confidence != null ? (fresh.confidence * 100).toFixed(0) : '—';
                card.innerHTML = brandCardHtml(fresh.brand || 'Unknown', pct, fresh.scan_status || 'COMPLETED');
              }
            }).catch(() => { /* the card keeps its previous content */ });
          },
          // onError
          (errMsg) => {
            statusText.innerHTML = `
              <div class="error-inline mt-sm">
                <span>${icon('alert')}</span>
                <span>Scan failed: ${escapeHtml(errMsg)}</span>
              </div>`;
            btnScan.disabled = false;
            btnScan.innerHTML = icon('rocket') + ' Retry Carving Scan';
          }
        );
      } catch (err) {
        // Could not even start the scan
        statusText.innerHTML = `
          <div class="error-inline mt-sm">
            <span>${icon('alert')}</span>
            <span>Failed to initiate scan: ${escapeHtml(err.message)}</span>
          </div>`;
        btnScan.disabled = false;
        btnScan.innerHTML = icon('rocket') + ' Start Carving Scan';
      }
    };
  }
}
