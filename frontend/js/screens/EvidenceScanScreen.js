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

/** Label and badge style for an evidence item's scan state (PENDING really means "never scanned"). */
function scanStatusMeta(status) {
  switch (status) {
    case 'COMPLETED': return { label: 'Completed', cls: 'badge-complete' };
    case 'SCANNING':  return { label: 'Scanning', cls: 'badge-scanning' };
    case 'NO_VIDEO':  return { label: 'No video found', cls: 'badge-uncertain' };
    case 'FAILED':    return { label: 'Scan failed', cls: 'badge-error' };
    default:          return { label: 'Not scanned yet', cls: 'badge-pending' };
  }
}

/** The line next to the status badge. */
function scanStatusNote(status) {
  if (status === 'COMPLETED') return 'Scan complete. Open Recordings to review the recovered segments.';
  if (status === 'NO_VIDEO') return 'The scan ran but recovered no video. See the explanation above.';
  if (status === 'FAILED') return 'The scan could not finish. See the explanation above.';
  if (status === 'SCANNING') return 'A scan is running.';
  return 'Click "Start Carving Scan" to begin.';
}

/** Turn the progress card into a clear "nothing recovered / scan failed" panel (no spinner, no 0%). */
function showScanFailure(state, message) {
  const card = document.getElementById('scan-progress-card');
  if (!card) return;
  card.classList.remove('hidden');
  const noVideo = state !== 'FAILED';
  document.getElementById('scan-title-spinner').innerHTML = icon(noVideo ? 'info' : 'x-circle');
  document.getElementById('scan-title-spinner').className = noVideo ? 'scan-title-icon' : 'scan-title-icon text-error';
  document.getElementById('scan-title-text').textContent = noVideo ? 'No video was recovered' : 'The scan could not finish';
  document.getElementById('scan-percentage').classList.add('hidden');
  card.querySelector('.progress-bar-container').classList.add('hidden');
  const box = document.getElementById('scan-status-text');
  box.innerHTML = `
    <div class="notice-card ${noVideo ? '' : 'notice-error'}">
      <div>
        <h3>${noVideo ? 'What happened' : 'What went wrong'}</h3>
        <p>${escapeHtml(message || 'The scan produced no result.')}</p>
        <p class="mt-sm">You can try again, or load a different disk image. Nothing on the evidence file was changed.</p>
      </div>
    </div>`;
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

  const statusMeta = scanStatusMeta(scanStatus);
  const lastScanFailed = scanStatus === 'NO_VIDEO' || scanStatus === 'FAILED';

  root.innerHTML = `
    <div class="page-header">
      <div class="page-header-row">
        <div>
          <div class="page-title">Acquisition &amp; Scan: <span class="text-primary">${escapeHtml(evLabel)}</span></div>
          <div class="page-subtitle font-mono-sm">${escapeHtml(evPath)}</div>
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
            <div class="hash-font mt-xs word-break-all" id="acq-sha256">${sha256}</div>
          </div>
          <div>
            <div class="meta-label">MD5</div>
            <div class="hash-font mt-xs word-break-all" id="acq-md5">${md5}</div>
          </div>
          <div class="d-flex gap-32 mt-xs">
            <div>
              <div class="meta-label">File Size</div>
              <div class="meta-value" id="acq-size">${sizeMB} MB</div>
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
    <div id="scan-progress-card" class="card mt-xl ${isScanning || lastScanFailed ? '' : 'hidden'}">
      <div class="card-title">
        <span class="d-flex items-center gap-10">
          <span id="scan-title-spinner" class="spinner spinner-sm"></span>
          <span id="scan-title-text">Scanning &amp; Frame Carving</span>
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
        <span id="scan-status-badge" class="badge ${statusMeta.cls}">${statusMeta.label}</span>
        <span id="scan-status-note" class="text-base text-muted">— ${scanStatusNote(scanStatus)}</span>
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
        showToast('Verification failed: ' + err.message, 'error');   // toasts render text, not HTML
      } finally {
        btnVerify.disabled = false;
        btnVerify.innerHTML = `${icon('shield-check')} Verify Integrity`;
      }
    };
  }

  // ── Start scan ─────────────────────────────────────────────────────────────
  const btnScan = document.getElementById('btn-start-scan');
  if (lastScanFailed) showScanFailure(scanStatus, ev.scan_message);

  // Keep the badge and the note under "Scan Results" in step with the scan that just ran.
  const refreshScanStatus = async () => {
    try {
      const fresh = await API.getEvidence(caseId, evidenceId);
      const meta = scanStatusMeta(fresh.scan_status);
      const badge = document.getElementById('scan-status-badge');
      if (badge) { badge.className = `badge ${meta.cls}`; badge.textContent = meta.label; }
      const note = document.getElementById('scan-status-note');
      if (note) note.textContent = '— ' + scanStatusNote(fresh.scan_status);
      return fresh;
    } catch (_) {
      return null;
    }
  };

  // Fill in what the scan worked out: hashes, size and the detected brand.
  const applyFreshEvidence = (fresh) => {
    if (!fresh) return;
    const setText = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
    setText('acq-sha256', fresh.sha256_before || fresh.sha256_after || '—');
    setText('acq-md5', fresh.md5_before || '—');
    if (fresh.size_bytes != null) setText('acq-size', (fresh.size_bytes / (1024 * 1024)).toFixed(2) + ' MB');
    const card = document.getElementById('brand-card-body');
    if (card) {
      const pct = fresh.confidence != null ? (fresh.confidence * 100).toFixed(0) : '—';
      card.innerHTML = brandCardHtml(fresh.brand || 'Unknown', pct, fresh.scan_status || 'COMPLETED');
    }
  };

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
            // Show what the scan just worked out (hashes, size and brand were left at their pre-scan values).
            refreshScanStatus().then(applyFreshEvidence);
          },
          // onError
          (errMsg) => {
            showScanFailure('FAILED', errMsg);                 // immediately, from the message we already have
            btnScan.disabled = false;
            btnScan.innerHTML = icon('rocket') + ' Retry Carving Scan';
            refreshScanStatus().then((fresh) => {              // then use the saved verdict (no video vs error)
              if (!fresh) return;
              applyFreshEvidence(fresh);
              if (fresh.scan_status === 'NO_VIDEO' || fresh.scan_status === 'FAILED') {
                showScanFailure(fresh.scan_status, fresh.scan_message || errMsg);
              }
            });
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
