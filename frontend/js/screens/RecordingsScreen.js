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
      <div class="card-title"><span>Search for a Person Across Recordings</span></div>
      <p style="font-size:12px; color:var(--text-dim); margin:0 0 12px; line-height:1.6;">
        Upload a reference photo to search for similar faces across every segment in this case that has already
        been checked with "Check Faces" below. <strong>Results are similarity candidates for human review, not
        confirmed identity matches</strong> — this project's own testing found two different synthetic faces
        scoring above the reference threshold shown in results. Always corroborate independently.
      </p>
      <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
        <input type="file" id="face-search-input" accept="image/*" class="form-control" style="max-width:320px;">
        <button id="face-search-btn" class="btn btn-primary btn-sm">🔎 Search</button>
      </div>
      <div id="face-search-results" style="margin-top:14px;"></div>
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
                   <th>Basic Motion Detection</th>
                   <th>AI-Based Face Detection</th>
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

                   let motionCell = `<span style="font-size:11px; color:var(--text-dim);">Export required</span>`;
                   if (isExported) {
                     if (s.motion_detected === true) {
                       motionCell = `<span class="badge badge-partial" data-tooltip="${escapeHtml(s.motion_details || 'Basic Motion Detection: Motion detected')}">Motion Detected</span>`;
                     } else if (s.motion_detected === false) {
                       motionCell = `<span class="badge badge-pending" data-tooltip="${escapeHtml(s.motion_details || 'Basic Motion Detection: No significant motion detected')}">No Motion</span>`;
                     } else {
                       motionCell = `<button id="motion-btn-${s.segment_id}" class="btn btn-secondary btn-sm" style="font-size:11px; padding:3px 8px;"
                         onclick="runMotionDetection('${caseId}', '${evidenceId}', '${s.segment_id}', this)">
                         Check Motion
                       </button>`;
                     }
                   }

                   let faceCell = `<span style="font-size:11px; color:var(--text-dim);">Export required</span>`;
                   if (isExported) {
                     if (s.face_detected === true) {
                       faceCell = `<span class="badge badge-partial" data-tooltip="${escapeHtml(s.face_detection_details || 'AI-Based Face Detection: Face(s) detected')}">Face(s) Detected</span>`;
                     } else if (s.face_detected === false) {
                       faceCell = `<span class="badge badge-pending" data-tooltip="${escapeHtml(s.face_detection_details || 'AI-Based Face Detection: No faces detected')}">No Faces</span>`;
                     } else {
                       faceCell = `<button id="face-btn-${s.segment_id}" class="btn btn-secondary btn-sm" style="font-size:11px; padding:3px 8px;"
                         onclick="runFaceDetection('${caseId}', '${evidenceId}', '${s.segment_id}', this)">
                         Check Faces
                       </button>`;
                     }
                   }

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
                       <td>${motionCell}</td>
                       <td>${faceCell}</td>
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

  document.getElementById('face-search-btn').onclick = () => runFaceSearch(caseId);
}

async function runFaceSearch(caseId) {
  const fileInput = document.getElementById('face-search-input');
  const resultsEl = document.getElementById('face-search-results');
  const btn = document.getElementById('face-search-btn');
  const file = fileInput.files && fileInput.files[0];

  if (!file) {
    resultsEl.innerHTML = `<div class="error-inline"><span>⚠️</span><span>Choose a reference photo first.</span></div>`;
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="btn-spinner"></span> Searching…';
  resultsEl.innerHTML = '';

  try {
    const res = await API.searchFaces(caseId, file);
    const matches = res.matches || [];

    if (matches.length === 0) {
      resultsEl.innerHTML = `
        <div class="empty-state" style="padding:16px 0;">
          <div class="empty-state-subtitle">No candidate faces found. Either no segments have been indexed yet
          (run "Check Faces" on exported segments below first), or none were similar enough to appear.</div>
        </div>`;
    } else {
      resultsEl.innerHTML = `
        <div class="notice-card" style="margin-bottom:10px;">
          <p style="margin:0; font-size:12px;">${escapeHtml(res.warning)}</p>
        </div>
        <div class="table-container">
          <table>
            <thead><tr><th>Segment</th><th>Time Offset</th><th>Similarity</th><th>vs. Reference Threshold (${res.reference_threshold})</th></tr></thead>
            <tbody>
              ${matches.map(m => `
                <tr>
                  <td class="hash-font" style="font-size:11px;">${escapeHtml(m.segment_id.substring(0, 8))}…</td>
                  <td>${m.frame_offset_seconds.toFixed(1)}s</td>
                  <td><strong>${(m.similarity * 100).toFixed(1)}%</strong></td>
                  <td>${m.above_reference_threshold
                    ? '<span class="badge badge-partial">Above — review</span>'
                    : '<span class="badge badge-pending">Below</span>'}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    }
  } catch (err) {
    resultsEl.innerHTML = `
      <div class="error-banner" style="margin-top:0;">
        <div class="error-banner-icon">⚠️</div>
        <div class="error-banner-body">
          <div class="error-banner-title">Face search failed</div>
          <div class="error-banner-msg">${escapeHtml(err.message)}</div>
        </div>
      </div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🔎 Search';
  }
}

async function exportSegment(caseId, evidenceId, segmentId, btnEl) {
  // Disable the export button and show spinner
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.innerHTML = '<span class="btn-spinner"></span> Exporting…';
  }

  try {
    const res = await API.exportSegment(caseId, evidenceId, segmentId);
    const detail = res.detail || {};

    if (detail.error) {
      // The backend genuinely could not export this segment (e.g. no
      // verified frame boundaries for experimental Hikvision carving) —
      // show this as a failure, never as a false "Export Successful".
      showModal(
        'Export Unavailable',
        `<div class="error-banner" style="margin-top:0;">
           <div class="error-banner-icon">⚠️</div>
           <div class="error-banner-body">
             <div class="error-banner-title">This segment could not be exported</div>
             <div class="error-banner-msg">${escapeHtml(detail.error)}</div>
           </div>
         </div>`,
        [{ label: 'OK', class: 'btn-secondary', onClick: () => renderRecordingsScreen({ caseId, evidenceId }) }]
      );
      return;
    }

    showModal(
      'Export Successful',
      `
        <div class="success-inline" style="border-radius:6px; border-left:none; border:1px solid rgba(16,185,129,0.4); margin-bottom:12px;">
          ✅ Segment exported successfully!
        </div>
        <div style="font-size:13px; display:flex; flex-direction:column; gap:10px;">
          <div>
            <div class="meta-label">File Path</div>
            <div style="font-family:var(--font-mono); font-size:12px; color:var(--text-main); word-break:break-all; margin-top:4px;">${escapeHtml(detail.export_path)}</div>
          </div>
          <div>
            <div class="meta-label">SHA-256</div>
            <div class="hash-font" style="margin-top:4px; word-break:break-all;">${escapeHtml(detail.sha256)}</div>
          </div>
          <div>
            <div class="meta-label">ffprobe Validation</div>
            <div class="meta-value" style="margin-top:4px; color:${detail.ffprobe_valid ? 'var(--status-complete)' : 'var(--status-error)'};">
              ${detail.ffprobe_valid ? '✅ Valid MP4 container' : '⚠️ Warning: stream structure invalid'}
            </div>
          </div>
          ${detail.ffmpeg_warning ? `
          <div>
            <div class="meta-label">FFmpeg Notice</div>
            <div class="meta-value" style="margin-top:4px; color:var(--status-partial);">⚠️ ${escapeHtml(detail.ffmpeg_warning)}</div>
          </div>` : ''}
        </div>`,
      [{ label: 'OK', class: 'btn-primary', onClick: () => renderRecordingsScreen({ caseId, evidenceId }) }]
    );
  } catch (err) {
    showModal('Export Failed',
      `<div class="error-banner" style="margin-top:0;">
         <div class="error-banner-icon">⚠️</div>
         <div class="error-banner-body">
           <div class="error-banner-title">Export failed</div>
           <div class="error-banner-msg">${escapeHtml(err.message)}</div>
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

async function runMotionDetection(caseId, evidenceId, segmentId, btnEl) {
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.innerHTML = '<span class="btn-spinner"></span> Analyzing…';
  }
  try {
    const res = await API.detectMotion(caseId, segmentId);
    showModal(
      'Basic Motion Detection Results',
      `
        <div class="${res.motion_detected ? 'notice-card' : 'success-inline'}" style="margin-bottom:12px;">
          <strong>${escapeHtml(res.label || 'Basic Motion Detection')}:</strong> ${escapeHtml(res.details)}
        </div>
        <div style="font-size:13px; display:flex; flex-direction:column; gap:6px; color:var(--text-muted);">
          <div><strong>Motion Detected:</strong> ${res.motion_detected ? '<span style="color:var(--status-partial); font-weight:700;">YES</span>' : '<span style="color:var(--status-complete); font-weight:700;">NO</span>'}</div>
          <div><strong>Motion Frames:</strong> ${res.motion_frames} / ${res.total_frames} (${((res.motion_ratio || 0) * 100).toFixed(1)}%)</div>
          <div style="font-size:11px; color:var(--text-dim); margin-top:4px;">Decoupled post-export analysis via OpenCV frame differencing. Evidence hash and video container remain unaltered.</div>
        </div>
      `,
      [{ label: 'OK', class: 'btn-primary', onClick: () => renderRecordingsScreen({ caseId, evidenceId }) }]
    );
  } catch (err) {
    showModal(
      'Basic Motion Detection Error',
      `<div class="error-banner" style="margin-top:0;">
         <div class="error-banner-icon">⚠️</div>
         <div class="error-banner-body">
           <div class="error-banner-title">Motion detection failed</div>
           <div class="error-banner-msg">${escapeHtml(err.message)}</div>
         </div>
       </div>`,
      [{ label: 'OK', class: 'btn-secondary', onClick: () => {} }]
    );
    if (btnEl) {
      btnEl.disabled = false;
      btnEl.innerHTML = 'Check Motion';
    }
  }
}

async function runFaceDetection(caseId, evidenceId, segmentId, btnEl) {
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.innerHTML = '<span class="btn-spinner"></span> Analyzing…';
  }
  try {
    const res = await API.detectFaces(caseId, segmentId);
    showModal(
      'AI-Based Face Detection Results',
      `
        <div class="${res.faces_detected ? 'notice-card' : 'success-inline'}" style="margin-bottom:12px;">
          <strong>${escapeHtml(res.label || 'AI-Based Face Detection')}:</strong> ${escapeHtml(res.details)}
        </div>
        <div style="font-size:13px; display:flex; flex-direction:column; gap:6px; color:var(--text-muted);">
          <div><strong>Face(s) Detected:</strong> ${res.faces_detected ? '<span style="color:var(--status-partial); font-weight:700;">YES</span>' : '<span style="color:var(--status-complete); font-weight:700;">NO</span>'}</div>
          <div><strong>Frames with faces:</strong> ${res.frames_with_faces} / ${res.frames_sampled} sampled (of ${res.total_frames} total)</div>
          <div><strong>Max faces in one frame:</strong> ${res.max_faces_in_single_frame}</div>
          <div style="font-size:11px; color:var(--text-dim); margin-top:4px;">
            Decoupled post-export analysis via OpenCV's YuNet CNN. Detects the presence/location of faces only —
            no identity or recognition is attempted. Evidence hash and video container remain unaltered.
          </div>
        </div>
      `,
      [{ label: 'OK', class: 'btn-primary', onClick: () => renderRecordingsScreen({ caseId, evidenceId }) }]
    );
  } catch (err) {
    showModal(
      'Face Detection Error',
      `<div class="error-banner" style="margin-top:0;">
         <div class="error-banner-icon">⚠️</div>
         <div class="error-banner-body">
           <div class="error-banner-title">Face detection failed</div>
           <div class="error-banner-msg">${escapeHtml(err.message)}</div>
         </div>
       </div>`,
      [{ label: 'OK', class: 'btn-secondary', onClick: () => {} }]
    );
    if (btnEl) {
      btnEl.disabled = false;
      btnEl.innerHTML = 'Check Faces';
    }
  }
}
