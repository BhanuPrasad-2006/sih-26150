/**
 * RecordingsScreen.js — List and export carved video segments with status breakdown.
 *
 * Segment status semantic colors:
 *   COMPLETE  = green  — all frames recovered, high evidentiary confidence
 *   PARTIAL   = amber  — gaps detected, moderate confidence
 *   UNCERTAIN = orange — significant corruption, low confidence; corroborate independently
 */

/**
 * Returns the CSS badge class and tooltip text for a segment status value.
 */
function segmentStatusMeta(status) {
  switch ((status || '').toUpperCase()) {
    case 'COMPLETE':
      return {
        badgeClass: 'badge-complete',
        tooltip: 'All frames recovered with no gaps. High evidentiary confidence.'
      };
    case 'PARTIAL':
      return {
        badgeClass: 'badge-partial',
        tooltip: 'Some frames missing or gaps detected. Moderate confidence — note gaps in report.'
      };
    case 'UNCERTAIN':
      return {
        badgeClass: 'badge-uncertain',
        tooltip: 'Significant corruption or missing data. Low confidence — corroborate with independent evidence.'
      };
    default:
      return {
        badgeClass: 'badge-pending',
        tooltip: 'Status not yet determined.'
      };
  }
}

async function renderRecordingsScreen(params) {
  const { caseId, evidenceId } = params;
  const root = document.getElementById('content-root');

  // ── Loading state ─────────────────────────────────────────────────────────
  root.innerHTML = `
    <div class="loading-state">
      <div class="spinner"></div>
      <p>Loading carved video segments…</p>
    </div>`;

  let segments;
  try {
    segments = await API.getSegments(caseId, evidenceId);
  } catch (err) {
    root.innerHTML = `
      <div class="page-header">
        <div class="page-title">Carved Video Segments</div>
      </div>
      <div class="error-banner">
        <div class="error-banner-icon">⚠️</div>
        <div class="error-banner-body">
          <div class="error-banner-title">Failed to load segments</div>
          <div class="error-banner-msg">${err.message}</div>
        </div>
      </div>`;
    return;
  }

  root.innerHTML = `
    <div class="page-header">
      <div class="page-header-row">
        <div>
          <div class="page-title">Carved Video Segments</div>
          <div class="page-subtitle">${segments.length} segment${segments.length !== 1 ? 's' : ''} reconstructed from disk image</div>
        </div>
        <button class="btn btn-secondary" onclick="navigateTo('export-report', { caseId: '${caseId}', evidenceId: '${evidenceId}' })">📄 Export PDF Forensic Report ➔</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>Reconstructed Timelines &amp; Segments</span>
        <!-- Status legend with tooltips -->
        <div class="status-legend">
          <span class="status-legend-item">Legend:</span>
          <span class="badge badge-complete" data-tooltip="All frames recovered — high evidentiary confidence">COMPLETE</span>
          <span class="badge badge-partial"  data-tooltip="Gaps detected — moderate confidence, note in report">PARTIAL</span>
          <span class="badge badge-uncertain" data-tooltip="Significant corruption — low confidence, corroborate independently">UNCERTAIN</span>
        </div>
      </div>

      ${segments.length === 0
        ? `<div class="empty-state">
             <div class="empty-state-icon">🎞️</div>
             <div class="empty-state-title">No segments carved yet</div>
             <div class="empty-state-subtitle">Run a disk scan first on the Acquisition &amp; Scan screen to extract video segments from this image.</div>
             <button class="btn btn-primary" onclick="navigateTo('evidence-scan', { caseId: '${caseId}', evidenceId: '${evidenceId}' })">
               Go to Acquisition &amp; Scan ➔
             </button>
           </div>`
        : `<div class="table-container">
             <table>
               <thead>
                 <tr>
                   <th>Camera</th>
                   <th>Time Range (UTC)</th>
                   <th>Frames</th>
                   <th>Status</th>
                   <th>Rationale / Gaps</th>
                   <th>SHA-256 (prefix)</th>
                   <th>Export</th>
                   <th>Action</th>
                 </tr>
               </thead>
               <tbody>
                 ${segments.map(s => {
                   const { badgeClass, tooltip } = segmentStatusMeta(s.status);
                   const startStr = s.start_time ? new Date(s.start_time).toISOString().replace('T', ' ').substring(0, 19) : '—';
                   const endStr   = s.end_time   ? new Date(s.end_time).toISOString().replace('T', ' ').substring(0, 19) : '—';
                   const isExported = !!s.export_path;
                   const hashDisplay = s.sha256 ? s.sha256.substring(0, 12) + '…' : '—';
                   return `
                     <tr>
                       <td><strong>Camera ${s.camera ?? s.camera_id ?? '?'}</strong></td>
                       <td style="font-size:12px; font-family:var(--font-mono); color:var(--text-muted);">${startStr}<br>${endStr}</td>
                       <td>${s.frame_count}</td>
                       <td>
                         <span class="badge ${badgeClass}" data-tooltip="${tooltip}">${s.status}</span>
                       </td>
                       <td style="font-size:12px; max-width:180px; color:var(--text-muted); line-height:1.5;">${s.notes || s.status_rationale || '—'}</td>
                       <td class="hash-font">${hashDisplay}</td>
                       <td>
                         ${isExported
                           ? `<span class="badge badge-complete" style="font-size:10px;">Exported MP4</span>`
                           : `<span style="font-size:12px; color:var(--text-dim);">Not exported</span>`}
                       </td>
                       <td>
                         <button id="export-btn-${s.segment_id}" class="btn btn-secondary btn-sm"
                           onclick="exportSegment('${caseId}', '${evidenceId}', '${s.segment_id}', this)">
                           ${isExported ? 'Re-Export MP4' : 'Export MP4'}
                         </button>
                       </td>
                     </tr>`;
                 }).join('')}
               </tbody>
             </table>
           </div>`
      }
    </div>
  `;
}

async function exportSegment(caseId, evidenceId, segmentId, btnEl) {
  // Disable the export button and show spinner
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.innerHTML = '<span class="btn-spinner"></span> Exporting…';
  }

  try {
    const res = await API.exportSegment(caseId, evidenceId, segmentId);
    showModal(
      'Export Successful',
      `
        <div class="success-inline" style="border-radius:6px; border-left:none; border:1px solid rgba(16,185,129,0.4); margin-bottom:12px;">
          ✅ Segment exported successfully!
        </div>
        <div style="font-size:13px; display:flex; flex-direction:column; gap:10px;">
          <div>
            <div class="meta-label">File Path</div>
            <div style="font-family:var(--font-mono); font-size:12px; color:var(--text-main); word-break:break-all; margin-top:4px;">${res.file_path}</div>
          </div>
          <div>
            <div class="meta-label">SHA-256</div>
            <div class="hash-font" style="margin-top:4px; word-break:break-all;">${res.sha256_hash}</div>
          </div>
          <div>
            <div class="meta-label">ffprobe Validation</div>
            <div class="meta-value" style="margin-top:4px; color:${res.ffprobe_valid ? 'var(--status-complete)' : 'var(--status-error)'};">
              ${res.ffprobe_valid ? '✅ Valid MP4 container' : '⚠️ Warning: stream structure invalid'}
            </div>
          </div>
        </div>`,
      [{ label: 'OK', class: 'btn-primary', onClick: () => renderRecordingsScreen({ caseId, evidenceId }) }]
    );
  } catch (err) {
    showModal('Export Failed',
      `<div class="error-banner" style="margin-top:0;">
         <div class="error-banner-icon">⚠️</div>
         <div class="error-banner-body">
           <div class="error-banner-title">Export failed</div>
           <div class="error-banner-msg">${err.message}</div>
         </div>
       </div>`,
      [{ label: 'OK', class: 'btn-secondary', onClick: () => {} }]
    );
    // Re-enable button
    if (btnEl) {
      btnEl.disabled = false;
      btnEl.innerHTML = 'Export MP4';
    }
  }
}
