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
  let objectResults = {};
  try {
    segments = await API.getSegments(caseId, evidenceId);
    try {
      const o = await API.getObjectResults(caseId);
      (o.results || []).forEach(r => { objectResults[r.segment_id] = r; });
    } catch (_) { /* object results are optional */ }
  } catch (err) {
    root.innerHTML = `
      <div class="page-header">
        <div class="page-title">Carved Video Segments</div>
      </div>
      <div class="error-banner">
        <div class="error-banner-icon">⚠️</div>
        <div class="error-banner-body">
          <div class="error-banner-title">Failed to load segments</div>
          <div class="error-banner-msg">${escapeHtml(err.message)}</div>
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
                   <th>Basic Motion Detection</th>
                   <th>AI-Based Face Detection</th>
                   <th>Object Detection</th>
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

                   let objectCell = `<span style="font-size:11px; color:var(--text-dim);">Export required</span>`;
                   if (isExported) {
                     const o = objectResults[s.segment_id];
                     if (o) {
                       const names = Object.keys(o.classes || {});
                       objectCell = names.length
                         ? `<span class="badge badge-partial" data-tooltip="${escapeHtml(o.summary || '')}">${escapeHtml(names.slice(0, 3).join(', '))}${names.length > 3 ? '…' : ''}</span>`
                         : `<span class="badge badge-pending" data-tooltip="${escapeHtml(o.summary || '')}">None found</span>`;
                     } else {
                       objectCell = `<button id="obj-btn-${s.segment_id}" class="btn btn-secondary btn-sm" style="font-size:11px; padding:3px 8px;"
                         onclick="runObjectDetection('${caseId}', '${evidenceId}', '${s.segment_id}', this)">
                         Check Objects
                       </button>`;
                     }
                   }

                   return `
                     <tr>
                       <td><strong>Camera ${s.camera ?? s.camera_id ?? '?'}</strong></td>
                       <td style="font-size:12px; font-family:var(--font-mono); color:var(--text-muted);">${startStr}<br>${endStr}</td>
                       <td>${s.frame_count}</td>
                       <td>
                         <span class="badge ${badgeClass}" data-tooltip="${escapeHtml(tooltip)}">${escapeHtml(s.status)}</span>
                       </td>
                       <td style="font-size:12px; max-width:180px; color:var(--text-muted); line-height:1.5;">${escapeHtml(s.notes || s.status_rationale || '—')}</td>
                       <td class="hash-font">${hashDisplay}</td>
                       <td>
                         ${isExported
                           ? `<span class="badge badge-complete" style="font-size:10px;">Exported MP4</span>`
                           : `<span style="font-size:12px; color:var(--text-dim);">Not exported</span>`}
                       </td>
                       <td>${motionCell}</td>
                       <td>${faceCell}</td>
                       <td>${objectCell}</td>
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

    ${segments.length > 0 ? `
    <div class="card">
      <div class="card-title"><span>Search for a Person Across Recordings</span></div>
      <p style="font-size:12px; color:var(--text-dim); margin:0 0 12px; line-height:1.6;">
        Optional: upload a reference photo to search for similar faces across every segment above that has
        already been checked with "Check Faces". <strong>Results are similarity candidates for human review,
        not confirmed identity matches</strong> — different people can score above the reference threshold
        shown in results. Always corroborate independently.
      </p>
      <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
        <input type="file" id="face-search-input" accept="image/*" class="form-control" style="max-width:320px;">
        <button id="face-search-btn" class="btn btn-primary btn-sm">🔎 Search</button>
      </div>
      <div id="face-search-results" style="margin-top:14px;"></div>
    </div>

    <div class="card">
      <div class="card-title"><span>Accuracy Against Ground Truth</span></div>
      <p style="font-size:12px; color:var(--text-dim); margin:0 0 12px; line-height:1.6;">
        The tool cannot know how much footage there should have been, so it never states a recovery percentage on its
        own. To measure one, supply ground truth for a segment: a known-good video (e.g. exported by the recorder's own
        player), a recording log, and/or the <strong>original disk image from before the deletion</strong>.
        Anything you leave out is shown as <em>not measured</em>. Export the segment first for the video checks.
      </p>
      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:12px;">
        <div class="form-group">
          <label>Segment</label>
          <select id="acc-segment" class="form-control">
            ${segments.map((s, i) => `<option value="${escapeHtml(s.segment_id)}">#${i + 1} · camera ${s.camera} · ${escapeHtml(s.segment_id.substring(0, 8))}${s.export_path ? '' : ' (not exported)'}</option>`).join('')}
          </select>
        </div>
        <div class="form-group">
          <label>Ground-truth video</label>
          <input type="file" id="acc-video" accept="video/*,.mp4,.avi,.dav,.h264,.mkv" class="form-control">
        </div>
        <div class="form-group">
          <label>Recording log (JSON)</label>
          <input type="file" id="acc-log" accept=".json,application/json" class="form-control">
        </div>
        <div class="form-group">
          <label>Original (pre-deletion) disk image path</label>
          <input type="text" id="acc-original" class="form-control" placeholder="C:\\path\\to\\original_before_delete.dd">
        </div>
        <div class="form-group">
          <label>Frame comparison</label>
          <select id="acc-mode" class="form-control">
            <option value="exact">Exact (same stream, only re-wrapped)</option>
            <option value="perceptual">Perceptual (vendor player re-encoded)</option>
          </select>
        </div>
        <div class="form-group">
          <label>Log times are in</label>
          <select id="acc-clock" class="form-control">
            <option value="device">the recorder's own clock</option>
            <option value="utc">UTC (needs the evidence's clock offset)</option>
          </select>
        </div>
      </div>
      <p style="font-size:11px; color:var(--text-dim); margin:0 0 12px;">
        Log format: <code>{"recordings":[{"name":"front door","camera":1,"start":"2026-03-01T10:00:00Z","end":"2026-03-01T11:00:00Z"}]}</code>
      </p>
      <button id="acc-run" class="btn btn-primary btn-sm">📏 Measure</button>
      <div id="acc-results" style="margin-top:14px;"></div>
      <div id="acc-history" style="margin-top:14px;"></div>
    </div>` : ''}
  `;

  if (segments.length > 0) {
    document.getElementById('face-search-btn').onclick = () => runFaceSearch(caseId);
    document.getElementById('acc-run').onclick = () => runAccuracyCheck(caseId);
    loadAccuracyHistory(caseId);
  }
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

async function runObjectDetection(caseId, evidenceId, segmentId, btnEl) {
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.innerHTML = '<span class="btn-spinner"></span> Analyzing…';
  }
  try {
    const res = await API.detectObjects(caseId, segmentId);
    const rows = Object.entries(res.classes || {}).map(([name, st]) => `
      <tr>
        <td>${escapeHtml(name)}</td>
        <td>${st.frames_with} / ${res.frames_sampled}</td>
        <td>${st.max_in_frame}</td>
        <td>${st.first_time_s == null ? '—' : st.first_time_s + ' s'}</td>
        <td>${st.best_score}</td>
      </tr>`).join('');
    showModal(
      'Object Detection Results',
      `
        <div class="${res.objects_detected ? 'notice-card' : 'success-inline'}" style="margin-bottom:12px;">
          <strong>${escapeHtml(res.label)}</strong><br>${escapeHtml(res.summary)}
        </div>
        ${rows ? `<div class="table-container"><table>
          <thead><tr><th>Object</th><th>Sampled frames</th><th>Max at once</th><th>First seen</th><th>Best score</th></tr></thead>
          <tbody>${rows}</tbody></table></div>` : ''}
        <div style="font-size:11px; color:var(--text-dim); margin-top:10px; line-height:1.5;">
          Automated detections for human review — not identification. Frames are sampled, so an object visible only in
          skipped frames is missed. Evidence hash and video container remain unaltered.
        </div>
      `,
      [{ label: 'OK', class: 'btn-primary', onClick: () => renderRecordingsScreen({ caseId, evidenceId }) }]
    );
  } catch (err) {
    showModal(
      'Object Detection Error',
      `<div class="error-banner" style="margin-top:0;">
         <div class="error-banner-icon">⚠️</div>
         <div class="error-banner-body">
           <div class="error-banner-title">Object detection failed</div>
           <div class="error-banner-msg">${escapeHtml(err.message)}</div>
         </div>
       </div>`,
      [{ label: 'OK', class: 'btn-secondary', onClick: () => {} }]
    );
    if (btnEl) {
      btnEl.disabled = false;
      btnEl.innerHTML = 'Check Objects';
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


// ── Accuracy against ground truth ────────────────────────────────────────────

function accTile(label, value, hint, tone) {
  const color = tone === 'good' ? 'var(--status-complete)' : tone === 'bad' ? 'var(--status-error)'
              : tone === 'warn' ? 'var(--status-partial)' : 'var(--text-main)';
  return `<div class="acc-tile" title="${escapeHtml(hint || '')}">
      <div class="acc-tile-value" style="color:${color};">${value}</div>
      <div class="acc-tile-label">${escapeHtml(label)}</div>
    </div>`;
}

function accPctTone(p) {
  if (p === null || p === undefined) return '';
  return p >= 95 ? 'good' : p >= 60 ? 'warn' : 'bad';
}

function accFmt(p) {
  return (p === null || p === undefined) ? '—' : `${p}%`;
}

function renderAccuracyResult(r) {
  const tiles = [];
  const f = r.frames, b = r.bytes, pl = r.placement;
  if (f) {
    tiles.push(accTile('Frames recovered', accFmt(f.frame_recall_pct),
      `${f.matched_frames} of ${f.truth_frames} ground-truth frames were found in the recovered video.`, accPctTone(f.frame_recall_pct)));
    tiles.push(accTile('Frames that are right', accFmt(f.frame_precision_pct),
      `${f.extra_or_wrong_frames} recovered frame(s) are not in the ground truth.`, accPctTone(f.frame_precision_pct)));
    tiles.push(accTile('In correct order', accFmt(f.in_order_pct),
      'Share of matched frames that appear in the same order as the ground truth.', accPctTone(f.in_order_pct)));
  }
  if (b) {
    tiles.push(accTile('Byte-identical file', b.identical ? 'YES' : 'NO', b.meaning, b.identical ? 'good' : ''));
  }
  if (pl) {
    tiles.push(accTile('Original bytes recovered', accFmt(pl.byte_recall_pct),
      'Share of the original recordings\u2019 bytes covered by recovered segments (by disk offset).', accPctTone(pl.byte_recall_pct)));
    tiles.push(accTile('Bytes from the right place', accFmt(pl.placement_precision_pct),
      'Share of recovered bytes that lie inside an original recording\u2019s location.', accPctTone(pl.placement_precision_pct)));
  }
  const parts = [];
  if (tiles.length) parts.push(`<div class="acc-tiles">${tiles.join('')}</div>`);

  if (f) {
    parts.push(`<p class="acc-note">${escapeHtml(f.meaning)}</p>`);
    if (f.missing_ranges && f.missing_ranges.length) {
      const txt = f.missing_ranges.map(([a, z]) => a === z ? `${a}` : `${a}–${z}`).join(', ');
      parts.push(`<p class="acc-note"><strong>Missing ground-truth frames (0-based):</strong> ${escapeHtml(txt)}${f.missing_ranges_truncated ? ' …' : ''}</p>`);
    }
  }
  if (b && !b.identical) {
    parts.push(`<p class="acc-note">First differing byte: ${b.first_mismatch_offset === null ? '—' : b.first_mismatch_offset}. Sizes: recovered ${b.recovered_size}, ground truth ${b.truth_size}.</p>`);
  }
  if (pl) {
    parts.push(`<p class="acc-note">${escapeHtml(pl.meaning)}</p>`);
    const mixed = (pl.per_segment || []).filter(s => s.mixes_several_originals).length;
    if (mixed) parts.push(`<p class="acc-note"><strong>${mixed} recovered segment(s) contain bytes from more than one original recording.</strong></p>`);
    parts.push(`<div class="table-container"><table><thead><tr><th>Original recording</th><th>Bytes</th><th>Recovered</th><th>Recall</th></tr></thead><tbody>
      ${(pl.per_original || []).map(o => `<tr><td>${escapeHtml(o.original)}</td><td>${o.bytes}</td><td>${o.recovered_bytes}</td><td><strong>${accFmt(o.byte_recall_pct)}</strong></td></tr>`).join('')}
    </tbody></table></div>`);
  }
  if (r.log) {
    parts.push(`<div class="table-container"><table><thead><tr><th>Logged recording</th><th>Camera</th><th>Time covered</th><th>Start Δ (s)</th><th>End Δ (s)</th></tr></thead><tbody>
      ${r.log.entries.map(e => `<tr><td>${escapeHtml(e.name || '')}</td><td>${e.camera ?? 'any'}</td><td><strong>${accFmt(e.time_coverage_pct)}</strong></td><td>${e.start_delta_seconds ?? '—'}</td><td>${e.end_delta_seconds ?? '—'}</td></tr>`).join('')}
    </tbody></table></div><p class="acc-note">${escapeHtml(r.log.meaning)}</p>`);
  }
  if (r.not_measured && r.not_measured.length) {
    parts.push(`<div class="notice-card" style="margin-top:10px;"><p style="margin:0; font-size:12px;"><strong>Not measured:</strong> ${r.not_measured.map(escapeHtml).join(' · ')}</p></div>`);
  }
  if (r.measured_meaning) parts.push(`<p class="acc-note">${escapeHtml(r.measured_meaning)}</p>`);
  return parts.join('');
}

async function runAccuracyCheck(caseId) {
  const resultsEl = document.getElementById('acc-results');
  const btn = document.getElementById('acc-run');
  const video = document.getElementById('acc-video').files[0];
  const log = document.getElementById('acc-log').files[0];
  const original = document.getElementById('acc-original').value.trim();

  if (!video && !log && !original) {
    resultsEl.innerHTML = `<div class="error-inline"><span>⚠️</span><span>Supply at least one ground truth: a video, a recording log, or the original disk image path.</span></div>`;
    return;
  }
  const fd = new FormData();
  fd.append('segment_id', document.getElementById('acc-segment').value);
  fd.append('mode', document.getElementById('acc-mode').value);
  fd.append('log_clock', document.getElementById('acc-clock').value);
  if (video) fd.append('ground_truth', video);
  if (log) fd.append('truth_log', log);
  if (original) fd.append('original_image_path', original);

  btn.disabled = true;
  btn.innerHTML = '<span class="btn-spinner"></span> Measuring…';
  resultsEl.innerHTML = '';
  try {
    const res = await API.runAccuracy(caseId, fd);
    resultsEl.innerHTML = renderAccuracyResult(res);
    loadAccuracyHistory(caseId);
  } catch (err) {
    resultsEl.innerHTML = `<div class="error-banner" style="margin-top:0;"><div class="error-banner-icon">⚠️</div><div class="error-banner-body">
      <div class="error-banner-title">Measurement failed</div><div class="error-banner-msg">${escapeHtml(err.message)}</div></div></div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '📏 Measure';
  }
}

async function loadAccuracyHistory(caseId) {
  const el = document.getElementById('acc-history');
  if (!el) return;
  try {
    const items = await API.getAccuracy(caseId);
    if (!items.length) { el.innerHTML = ''; return; }
    el.innerHTML = `<div class="card-title" style="font-size:13px;"><span>Earlier measurements (${items.length}) — included in the PDF report</span></div>
      <div class="table-container"><table><thead><tr><th>When</th><th>Segment</th><th>Frames recovered</th><th>In order</th><th>Byte-identical</th><th>Original bytes recovered</th></tr></thead><tbody>
      ${items.map(r => `<tr>
        <td>${escapeHtml((r.created_at || '').substring(0, 19).replace('T', ' '))}</td>
        <td class="hash-font" style="font-size:11px;">${escapeHtml((r.segment_id || '').substring(0, 8))}…</td>
        <td>${r.frames ? accFmt(r.frames.frame_recall_pct) : '—'}</td>
        <td>${r.frames ? accFmt(r.frames.in_order_pct) : '—'}</td>
        <td>${r.bytes ? (r.bytes.identical ? 'yes' : 'no') : '—'}</td>
        <td>${r.placement ? accFmt(r.placement.byte_recall_pct) : '—'}</td></tr>`).join('')}
      </tbody></table></div>`;
  } catch (_) { el.innerHTML = ''; }
}
