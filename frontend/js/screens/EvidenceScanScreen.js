/**
 * EvidenceScanScreen.js — Acquisition overview, brand detection, and live carving scan execution.
 */
async function renderEvidenceScanScreen(params) {
  const { caseId, evidenceId } = params;
  const root = document.getElementById('content-root');

  root.innerHTML = `<p style="color:var(--text-dim);">Loading evidence details...</p>`;

  try {
    const ev = await API.getEvidence(caseId, evidenceId);

    root.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
        <div>
          <h2 style="font-size: 24px; font-weight: 700;">Acquisition & Scan: ${ev.evidence_label}</h2>
          <p style="color: var(--text-muted); font-size: 14px;">Path: ${ev.file_path}</p>
        </div>
        <div>
          <button id="btn-verify-integrity" class="btn btn-secondary">🔍 Verify Image Hashes</button>
          <button id="btn-start-scan" class="btn btn-primary" ${ev.scan_status === 'COMPLETED' ? '' : ''}>
            ${ev.scan_status === 'COMPLETED' ? '🔁 Re-Run Forensic Scan' : '🚀 Start Carving Scan'}
          </button>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 20px;">
        <div class="card">
          <div class="card-title">Acquisition Hashes (Read-Only Memory Map)</div>
          <div style="display: flex; flex-direction: column; gap: 12px; font-size: 13px;">
            <div>
              <span style="color:var(--text-muted);">SHA-256 Hash:</span><br>
              <span class="hash-font">${ev.sha256_hash}</span>
            </div>
            <div>
              <span style="color:var(--text-muted);">MD5 Hash:</span><br>
              <span class="hash-font">${ev.md5_hash}</span>
            </div>
            <div style="display: flex; gap: 24px; margin-top: 8px;">
              <div><span style="color:var(--text-muted);">Size:</span> ${(ev.size_bytes / (1024*1024)).toFixed(2)} MB</div>
              <div><span style="color:var(--text-muted);">Format:</span> Raw Binary (.dd)</div>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-title">Brand Detection</div>
          <div style="text-align: center; padding: 10px 0;">
            <div style="font-size: 28px; font-weight: 700; color: var(--accent-cyan); margin-bottom: 4px;">
              ${ev.detected_brand}
            </div>
            <div style="font-size: 13px; color: var(--text-muted);">
              Confidence: ${(ev.brand_confidence * 100).toFixed(0)}%
            </div>
          </div>
        </div>
      </div>

      <!-- Live Scan Progress Section -->
      <div id="scan-progress-card" class="card" style="display: ${ev.scan_status === 'SCANNING' ? 'block' : 'none'};">
        <div class="card-title">
          <span>Scanning & Frame Carving Progress</span>
          <span id="scan-percentage" style="color: var(--accent-cyan);">0%</span>
        </div>
        <div class="progress-bar-container">
          <div id="scan-progress-bar" class="progress-bar-fill"></div>
        </div>
        <p id="scan-status-text" style="font-size: 13px; color: var(--text-muted);">Initializing scanner...</p>
      </div>

      <!-- Scan Summary Results -->
      <div class="card">
        <div class="card-title">
          <span>Scan Results & Segments</span>
          ${ev.scan_status === 'COMPLETED' ? `<button class="btn btn-secondary" onclick="navigateTo('recordings', { caseId: ${caseId}, evidenceId: ${evidenceId} })">View Recordings List ➔</button>` : ''}
        </div>
        <p style="font-size: 14px; color: var(--text-muted);">
          Status: <strong style="color: ${ev.scan_status === 'COMPLETED' ? 'var(--accent-emerald)' : 'var(--accent-amber)'};">${ev.scan_status}</strong>
        </p>
      </div>
    `;

    // Verify Integrity handler
    document.getElementById('btn-verify-integrity').onclick = async () => {
      showModal('Integrity Verification', '<p>Verifying SHA-256 hash against initial acquisition hash...</p>');
      try {
        const res = await API.verifyEvidenceIntegrity(caseId, evidenceId);
        showModal(
          'Integrity Verification Result',
          res.match
            ? `<p style="color:var(--accent-emerald);">✅ MATCH: Disk image has not been altered or tampered with.</p>
               <p class="hash-font" style="margin-top:10px;">SHA-256: ${res.current_sha256}</p>`
            : `<p style="color:var(--accent-rose);">❌ MISMATCH DETECTED! Disk image has been modified!</p>`
        );
      } catch (err) {
        showModal('Error', `<p style="color:var(--accent-rose);">${err.message}</p>`);
      }
    };

    // Start Scan handler
    document.getElementById('btn-start-scan').onclick = async () => {
      const progressCard = document.getElementById('scan-progress-card');
      const progressBar = document.getElementById('scan-progress-bar');
      const progressPct = document.getElementById('scan-percentage');
      const statusText = document.getElementById('scan-status-text');

      progressCard.style.display = 'block';

      try {
        await API.startScan(caseId, evidenceId);

        API.listenScanProgress(
          caseId,
          evidenceId,
          (prog) => {
            progressBar.style.width = `${prog.progress_pct}%`;
            progressPct.innerText = `${prog.progress_pct.toFixed(0)}%`;
            statusText.innerText = `Processed ${prog.bytes_processed} / ${prog.total_bytes} bytes — Frames carved: ${prog.frames_found}`;
          },
          (comp) => {
            statusText.innerText = `Scan complete! Carved ${comp.frames_found} frames into ${comp.segments_reconstructed} segments.`;
            setTimeout(() => {
              navigateTo('recordings', { caseId, evidenceId });
            }, 1000);
          },
          (err) => {
            statusText.innerHTML = `<span style="color:var(--accent-rose);">Scan failed: ${err}</span>`;
          }
        );
      } catch (err) {
        showModal('Error', `<p style="color:var(--accent-rose);">Failed to initiate scan: ${err.message}</p>`);
      }
    };

  } catch (err) {
    root.innerHTML = `<p style="color:var(--accent-rose);">Failed to load evidence: ${err.message}</p>`;
  }
}
