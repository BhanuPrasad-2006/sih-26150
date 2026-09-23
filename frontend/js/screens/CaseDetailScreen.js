/**
 * CaseDetailScreen.js — View case details and manage attached evidence files.
 *
 * The API always returns `evidence` as an array (never undefined), but we
 * also guard with `?? []` at every access point as belt-and-suspenders.
 */
async function renderCaseDetailScreen(params) {
  const caseId = params.caseId;
  const root = document.getElementById('content-root');

  // ── Loading state ─────────────────────────────────────────────────────────
  root.innerHTML = `
    <div class="loading-state">
      <div class="spinner"></div>
      <p>Loading case details…</p>
    </div>`;

  let caseObj;
  try {
    caseObj = await API.getCase(caseId);
  } catch (err) {
    root.innerHTML = `
      <div class="page-header">
        <div class="page-title">Case Details</div>
      </div>
      <div class="error-banner">
        <div class="error-banner-icon">⚠️</div>
        <div class="error-banner-body">
          <div class="error-banner-title">Failed to load case — GET /api/cases/${caseId}</div>
          <div class="error-banner-msg">${err.message}</div>
        </div>
      </div>`;
    return;
  }

  // Belt-and-suspenders: guarantee arrays even if a stale server omits the fields.
  const evidence = caseObj.evidence ?? [];

  // Update breadcrumb with real case number now that we have it
  renderHeader([{ label: `Case: ${caseObj.case_number}` }]);

  root.innerHTML = `
    <div class="page-header">
      <div class="page-header-row">
        <div>
          <div class="page-title">Case: <span style="color:var(--accent-cyan);">${escapeHtml(caseObj.case_number)}</span></div>
          <div class="page-subtitle">Investigator: ${escapeHtml(caseObj.examiner)}</div>
        </div>
        <button id="btn-add-evidence" class="btn btn-primary">➕ Load Disk Image (.dd/.img)</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Case Metadata</div>
      <div class="meta-grid">
        <div>
          <div class="meta-label">Registered</div>
          <div class="meta-value">${new Date(caseObj.created_at).toLocaleString()}</div>
        </div>
        <div>
          <div class="meta-label">Examiner</div>
          <div class="meta-value">${escapeHtml(caseObj.examiner)}</div>
        </div>
        <div>
          <div class="meta-label">Notes</div>
          <div class="meta-value" style="color:var(--text-muted);">${caseObj.notes ? escapeHtml(caseObj.notes) : '—'}</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>Attached Evidence Images</span>
        <span style="font-size:12px; color:var(--text-dim); font-weight:400;">${evidence.length} image${evidence.length !== 1 ? 's' : ''} loaded</span>
      </div>
      <div id="evidence-area">
        ${renderEvidenceTable(evidence, caseId)}
      </div>
    </div>
  `;

  // ── Load evidence modal ────────────────────────────────────────────────────
  document.getElementById('btn-add-evidence').onclick = () => {
    showModal(
      'Load Raw Disk Image (.dd / .img)',
      `
        <p style="font-size:13px; color:var(--text-muted); margin-bottom:14px; line-height:1.6;">
          Enter the absolute path to a raw disk image on localhost.<br>
          <em style="color:var(--text-dim);">Physical drives (\\.\PhysicalDriveN) are rejected to protect live data.</em>
        </p>
        <div class="form-group">
          <label>Evidence Label</label>
          <input type="text" id="modal-ev-label" class="form-control" value="EVID-00${evidence.length + 1}">
        </div>
        <div class="form-group">
          <label>Image File Path (.dd / .img / .raw)</label>
          <input type="text" id="modal-ev-path" class="form-control" placeholder="C:\\path\\to\\synthetic_dahua.dd">
        </div>
        <div class="form-group">
          <label>Device Clock Offset from UTC (optional)</label>
          <input type="number" id="modal-ev-tz-offset" class="form-control" placeholder="e.g. 330 for IST (UTC+5:30)" step="1" min="-720" max="840">
          <p style="font-size:12px; color:var(--text-dim); margin-top:4px; line-height:1.5;">
            Minutes, e.g. <code>330</code> for IST. Only set this if you have independently confirmed the
            recorder's configured timezone — carved timestamps are otherwise shown as raw device-reported
            values and are <strong>not</strong> assumed to be UTC. Used to normalize timestamps for
            cross-camera/cross-device correlation and reporting.
          </p>
        </div>
        <div id="modal-ev-error" style="display:none;" class="error-inline">
          <span>⚠️</span><span id="modal-ev-error-msg"></span>
        </div>
      `,
      [
        { label: 'Cancel', class: 'btn-secondary', onClick: () => {} },
        {
          label: 'Load & Calculate Hashes',
          class: 'btn-primary',
          onClick: async () => {
            const label = document.getElementById('modal-ev-label').value.trim();
            const path = document.getElementById('modal-ev-path').value.trim();
            const tzOffsetRaw = document.getElementById('modal-ev-tz-offset').value.trim();
            const tzOffset = tzOffsetRaw === '' ? null : parseInt(tzOffsetRaw, 10);
            const errDiv = document.getElementById('modal-ev-error');
            const errMsgEl = document.getElementById('modal-ev-error-msg');

            if (!path) {
              errMsgEl.textContent = 'A file path is required.';
              errDiv.style.display = 'flex';
              return;
            }
            if (tzOffsetRaw !== '' && (Number.isNaN(tzOffset) || tzOffset < -720 || tzOffset > 840)) {
              errMsgEl.textContent = 'Device clock offset must be a number of minutes between -720 and 840.';
              errDiv.style.display = 'flex';
              return;
            }

            try {
              const ev = await API.addEvidence(caseId, path, label, tzOffset);
              navigateTo('evidence-scan', { caseId, evidenceId: ev.evidence_id || ev.id });
            } catch (err) {
              // Show error inside modal, not a second modal
              errMsgEl.textContent = err.message;
              errDiv.style.display = 'flex';
            }
          }
        }
      ]
    );
  };
}

/** Helper — render the evidence table or empty state */
function renderEvidenceTable(evidence, caseId) {
  if (evidence.length === 0) {
    return `
      <div class="empty-state">
        <div class="empty-state-icon">📂</div>
        <div class="empty-state-title">No evidence loaded yet</div>
        <div class="empty-state-subtitle">Click "Load Disk Image" to attach a raw disk image (.dd / .img) to this case and begin forensic acquisition.</div>
      </div>`;
  }

  return `
    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th>Evidence ID</th>
            <th>File Path</th>
            <th>Brand Detected</th>
            <th>SHA-256 (prefix)</th>
            <th>Scan Status</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          ${evidence.map(ev => {
            const brand = ev.brand || ev.detected_brand || 'Unknown';
            const confidence = ev.confidence != null ? ` (${(ev.confidence * 100).toFixed(0)}%)` : '';
            const brandBadge = brand.toLowerCase().includes('unverified') ? 'badge-uncertain' : 'badge-verified';
            const scanStatus = ev.scan_status || 'PENDING';
            const badgeClass = scanStatus === 'COMPLETED' ? 'badge-complete'
                             : scanStatus === 'SCANNING'  ? 'badge-scanning'
                             : 'badge-pending';
            const scanLabel = scanStatus === 'COMPLETED' ? 'View Scan Results ➔' : 'Scan Disk Image ➔';
            const scanTitle = scanStatus === 'COMPLETED'
              ? 'Scan complete — click to view carved segments'
              : scanStatus === 'SCANNING'
              ? 'Scan currently in progress'
              : 'No scan run yet — click to start acquisition scan';

            return `
              <tr>
                <td><strong>${escapeHtml(ev.evidence_label || ev.evidence_id)}</strong></td>
                <td style="font-family:var(--font-mono); font-size:11px; color:var(--text-muted); max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(ev.path || ev.file_path || '')}</td>
                <td><span class="badge ${brandBadge}">${escapeHtml(brand)}${confidence}</span></td>
                <td class="hash-font">${ev.sha256_before ? ev.sha256_before.substring(0, 16) + '…' : '—'}</td>
                <td><span class="badge ${badgeClass}">${scanStatus}</span></td>
                <td>
                  <button class="btn btn-secondary btn-sm" title="${scanTitle}"
                    onclick="navigateTo('evidence-scan', { caseId: '${caseId}', evidenceId: '${ev.evidence_id}' })">
                    ${scanLabel}
                  </button>
                </td>
              </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>`;
}
