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
        <div class="error-banner-icon">${icon('alert')}</div>
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
        <button class="btn btn-secondary" ${navAttrs('export-report', { caseId: caseId, evidenceId: evidenceId })}>${icon('file-text')} Export PDF forensic report ${icon('arrow-right')}</button>
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
             ${emptyArt()}
             <div class="empty-state-title">No segments carved yet</div>
             <div class="empty-state-subtitle">Run a disk scan first on the Acquisition &amp; Scan screen to extract video segments from this image.</div>
             <button class="btn btn-primary" ${navAttrs('evidence-scan', { caseId: caseId, evidenceId: evidenceId })}>
               Go to Acquisition &amp; Scan ${icon('arrow-right')}
             </button>
           </div>`
        : `
            <div class="batch-bar">
              <div class="batch-bar-controls">
                <button id="btn-batch-export" class="btn btn-secondary btn-sm" type="button">
                  ${icon('download')} Export all segments
                </button>
                <button id="btn-batch-analytics" class="btn btn-secondary btn-sm" type="button">
                  ${icon('sparkles')} Run all analytics on exported
                </button>
              </div>
              <div id="batch-progress-box" class="batch-progress-box hidden">
                <div class="batch-progress-row">
                  <span id="batch-progress-label" class="batch-progress-text">
                    <span class="spinner spinner-sm"></span> Initialising batch...
                  </span>
                  <span id="batch-progress-pct" class="batch-progress-pct">0%</span>
                  <button id="btn-batch-cancel" class="btn btn-secondary btn-sm" type="button">
                    ${icon('x')} Cancel
                  </button>
                </div>
                <div class="progress-bar-container mt-xs mb-0">
                  <div id="batch-progress-bar" class="progress-bar-fill"></div>
                </div>
              </div>
            </div>
            <div class="table-container">

             <table>
               <thead>
                 <tr>
                   <th>Camera</th>
                   <th>Recorder time</th>
                   <th>Frames</th>
                   <th>Status</th>
                   <th>Rationale / Gaps</th>
                   <th>SHA-256 (prefix)</th>
                   <th>Export</th>
                   <th>AI Detections</th>
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
                    let aiDetectionsCell = '';
                    if (!isExported) {
                      aiDetectionsCell = `<div class="ai-pills"><span class="ai-pill ai-pill-disabled" data-tooltip="Export MP4 first to analyze video">${icon('film')} Export required</span></div>`;
                    } else {
                      // Motion Pill
                      let motionPill = '';
                      if (s.motion_detected === true) {
                        motionPill = `<button type="button" class="ai-pill ai-pill-active" ${actAttrs('motion', caseId, evidenceId, s.segment_id)} data-tooltip="${escapeHtml(s.motion_details || 'Basic Motion Detection: Motion detected')}">${icon('activity')} Motion</button>`;
                      } else if (s.motion_detected === false) {
                        motionPill = `<button type="button" class="ai-pill ai-pill-muted" ${actAttrs('motion', caseId, evidenceId, s.segment_id)} data-tooltip="${escapeHtml(s.motion_details || 'Basic Motion Detection: No significant motion detected')}">${icon('activity')} No motion</button>`;
                      } else {
                        motionPill = `<button type="button" class="ai-pill" ${actAttrs('motion', caseId, evidenceId, s.segment_id)} data-tooltip="Run Basic Motion Detection">${icon('play')} Motion</button>`;
                      }

                      // Face Pill
                      let facePill = '';
                      if (s.face_detected === true) {
                        facePill = `<button type="button" class="ai-pill ai-pill-active" ${actAttrs('face', caseId, evidenceId, s.segment_id)} data-tooltip="${escapeHtml(s.face_detection_details || 'AI-Based Face Detection: Face(s) detected')}">${icon('scan-face')} Faces</button>`;
                      } else if (s.face_detected === false) {
                        facePill = `<button type="button" class="ai-pill ai-pill-muted" ${actAttrs('face', caseId, evidenceId, s.segment_id)} data-tooltip="${escapeHtml(s.face_detection_details || 'AI-Based Face Detection: No faces detected')}">${icon('scan-face')} No faces</button>`;
                      } else {
                        facePill = `<button type="button" class="ai-pill" ${actAttrs('face', caseId, evidenceId, s.segment_id)} data-tooltip="Run AI-Based Face Detection">${icon('play')} Faces</button>`;
                      }

                      // Object Pill
                      let objectPill = '';
                      const o = objectResults[s.segment_id];
                      if (o) {
                        const names = Object.keys(o.classes || {});
                        if (names.length > 0) {
                          const objLabel = names.slice(0, 2).join(', ') + (names.length > 2 ? '…' : '');
                          objectPill = `<button type="button" class="ai-pill ai-pill-active" ${actAttrs('object', caseId, evidenceId, s.segment_id)} data-tooltip="${escapeHtml(o.summary || '')}">${icon('box')} ${escapeHtml(objLabel)}</button>`;
                        } else {
                          objectPill = `<button type="button" class="ai-pill ai-pill-muted" ${actAttrs('object', caseId, evidenceId, s.segment_id)} data-tooltip="${escapeHtml(o.summary || 'None found')}">${icon('box')} No objects</button>`;
                        }
                      } else {
                        objectPill = `<button type="button" class="ai-pill" ${actAttrs('object', caseId, evidenceId, s.segment_id)} data-tooltip="Run Object Detection">${icon('play')} Objects</button>`;
                      }

                      aiDetectionsCell = `<div class="ai-pills">${motionPill}${facePill}${objectPill}</div>`;
                    }

                    return `
                      <tr id="segment-row-${escapeHtml(s.segment_id)}" data-segment-id="${escapeHtml(s.segment_id)}">
                        <td><strong>Camera ${s.camera ?? s.camera_id ?? '?'}</strong></td>
                        <td class="font-mono-sm text-muted">${startStr}<br>${endStr}</td>
                        <td>${s.frame_count}</td>
                        <td>
                          <span class="badge ${badgeClass}" data-tooltip="${escapeHtml(tooltip)}">${escapeHtml(s.status)}</span>
                        </td>
                        <td class="text-sm max-w-180 text-muted lh-base">${escapeHtml(s.notes || s.status_rationale || '—')}</td>
                        <td class="hash-font">${hashDisplay}</td>
                        <td>
                          ${isExported
                            ? `<span class="badge badge-complete text-xxs">Exported</span>`
                            : `<span class="text-sm text-dim">Not exported</span>`}
                        </td>
                        <td>${aiDetectionsCell}</td>
                        <td class="action-cell">
                          ${isExported ? playButtonHtml(caseId, evidenceId, s.segment_id) : ''}
                          <button id="export-btn-${s.segment_id}" class="btn btn-secondary btn-sm btn-compact"
                            ${actAttrs('export', caseId, evidenceId, s.segment_id)}
                            title="${isExported ? 'Re-Export MP4 container' : 'Export video to MP4 container'}">
                            ${icon('download')} ${isExported ? 'Re-Export' : 'Export'}
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
      <p class="lead-text-sm">
        Optional: upload a reference photo to search for similar faces across every segment above that has
        already been checked with "Check Faces". <strong>Results are similarity candidates for human review,
        not confirmed identity matches</strong> — different people can score above the reference threshold
        shown in results. Always corroborate independently.
      </p>
      <div class="d-flex gap-10 items-center flex-wrap">
        <input type="file" id="face-search-input" accept="image/*" class="form-control max-w-sm">
        <button id="face-search-btn" class="btn btn-primary btn-sm">${icon('search')} Search</button>
      </div>
      <div id="face-search-results" class="mt-14"></div>
    </div>

    <div class="card">
      <div class="card-title"><span>Accuracy Against Ground Truth</span></div>
      <p class="lead-text-sm">
        The tool cannot know how much footage there should have been, so it never states a recovery percentage on its
        own. To measure one, supply ground truth for a segment: a known-good video (e.g. exported by the recorder's own
        player), a recording log, and/or the <strong>original disk image from before the deletion</strong>.
        Anything you leave out is shown as <em>not measured</em>. Export the segment first for the video checks.
      </p>
      <div class="grid-fit-240">
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
      <p class="text-xs text-dim mb-md">
        Log format: <code>{"recordings":[{"name":"front door","camera":1,"start":"2026-03-01T10:00:00Z","end":"2026-03-01T11:00:00Z"}]}</code>
      </p>
      <button id="acc-run" class="btn btn-primary btn-sm">${icon('ruler')} Measure</button>
      <div id="acc-results" class="mt-14"></div>
      <div id="acc-history" class="mt-14"></div>
    </div>` : ''}
  `;

  if (segments.length > 0) {
    document.getElementById('face-search-btn').onclick = () => runFaceSearch(caseId);
    document.getElementById('acc-run').onclick = () => runAccuracyCheck(caseId);
    loadAccuracyHistory(caseId);

    const btnBatchExport = document.getElementById('btn-batch-export');
    const btnBatchAnalytics = document.getElementById('btn-batch-analytics');
    const btnBatchCancel = document.getElementById('btn-batch-cancel');
    const progressBox = document.getElementById('batch-progress-box');
    const progressLabel = document.getElementById('batch-progress-label');
    const progressBar = document.getElementById('batch-progress-bar');
    const progressPct = document.getElementById('batch-progress-pct');

    let cancelRequested = false;

    if (btnBatchCancel) {
      btnBatchCancel.onclick = () => {
        cancelRequested = true;
        btnBatchCancel.disabled = true;
        btnBatchCancel.innerHTML = '<span class="btn-spinner"></span> Cancelling…';
      };
    }

    if (btnBatchExport) {
      btnBatchExport.onclick = async () => {
        cancelRequested = false;
        btnBatchExport.disabled = true;
        btnBatchAnalytics.disabled = true;
        if (btnBatchCancel) {
          btnBatchCancel.disabled = false;
          btnBatchCancel.innerHTML = `${icon('x')} Cancel`;
        }
        if (progressBox) progressBox.classList.remove('hidden');
        if (progressBar) progressBar.style.width = '0%';
        if (progressPct) progressPct.textContent = '0%';
        if (progressLabel) progressLabel.innerHTML = '<span class="spinner spinner-sm"></span> Initialising export…';

        const shouldCancel = () => cancelRequested || !document.getElementById('batch-progress-box');
        const onProgress = ({ done, total, message }) => {
          const pct = total > 0 ? Math.round((done / total) * 100) : 0;
          if (progressBar) progressBar.style.width = `${pct}%`;
          if (progressPct) progressPct.textContent = `${pct}%`;
          if (progressLabel) progressLabel.innerHTML = `<span class="spinner spinner-sm"></span> ${escapeHtml(message || `${done} of ${total} done`)}`;
        };

        try {
          const res = await API.batchExport(caseId, evidenceId, segments, { onProgress, shouldCancel });
          handleBatchResult('Batch Export', res, caseId, evidenceId);
        } catch (err) {
          showModal(
            'Batch Export Error',
            `<div class="error-banner">
               <div class="error-banner-icon">${icon('alert')}</div>
               <div class="error-banner-body">
                 <div class="error-banner-title">Batch export encountered an error</div>
                 <div class="error-banner-msg">${escapeHtml(err.message)}</div>
               </div>
             </div>`,
            [{ label: 'OK', class: 'btn-secondary', onClick: () => renderRecordingsScreen({ caseId, evidenceId }) }]
          );
        }
      };
    }

    if (btnBatchAnalytics) {
      btnBatchAnalytics.onclick = async () => {
        const exported = segments.filter(s => !!s.export_path);
        if (exported.length === 0) {
          showModal(
            'Export Required',
            `<div class="notice-card info">
               <div>
                 <h3>${icon('info')} No exported segments found</h3>
                 <p>Video analytics (motion, face, and object detection) require an exported MP4 container. Click <strong>Export all segments</strong> first, or export individual segments.</p>
               </div>
             </div>`,
            [{ label: 'OK', class: 'btn-primary', onClick: () => {} }]
          );
          return;
        }

        cancelRequested = false;
        btnBatchExport.disabled = true;
        btnBatchAnalytics.disabled = true;
        if (btnBatchCancel) {
          btnBatchCancel.disabled = false;
          btnBatchCancel.innerHTML = `${icon('x')} Cancel`;
        }
        if (progressBox) progressBox.classList.remove('hidden');
        if (progressBar) progressBar.style.width = '0%';
        if (progressPct) progressPct.textContent = '0%';
        if (progressLabel) progressLabel.innerHTML = '<span class="spinner spinner-sm"></span> Initialising analytics…';

        const shouldCancel = () => cancelRequested || !document.getElementById('batch-progress-box');
        const onProgress = ({ done, total, message }) => {
          const pct = total > 0 ? Math.round((done / total) * 100) : 0;
          if (progressBar) progressBar.style.width = `${pct}%`;
          if (progressPct) progressPct.textContent = `${pct}%`;
          if (progressLabel) progressLabel.innerHTML = `<span class="spinner spinner-sm"></span> ${escapeHtml(message || `${done} of ${total} done`)}`;
        };

        try {
          const res = await API.batchAnalytics(caseId, exported, { onProgress, shouldCancel });
          handleBatchResult('Batch Analytics', res, caseId, evidenceId);
        } catch (err) {
          showModal(
            'Batch Analytics Error',
            `<div class="error-banner">
               <div class="error-banner-icon">${icon('alert')}</div>
               <div class="error-banner-body">
                 <div class="error-banner-title">Batch analytics encountered an error</div>
                 <div class="error-banner-msg">${escapeHtml(err.message)}</div>
               </div>
             </div>`,
            [{ label: 'OK', class: 'btn-secondary', onClick: () => renderRecordingsScreen({ caseId, evidenceId }) }]
          );
        }
      };
    }
  }

  if (params.highlightSegmentId) {
    setTimeout(() => {
      const targetRow = document.getElementById(`segment-row-${params.highlightSegmentId}`)
        || document.querySelector(`tr[data-segment-id="${params.highlightSegmentId}"]`);
      if (targetRow) {
        targetRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
        targetRow.classList.add('row-highlight');
        setTimeout(() => {
          targetRow.classList.remove('row-highlight');
        }, 3000);
      }
    }, 100);
  }
}

function handleBatchResult(actionName, res, caseId, evidenceId) {
  if (res.failures && res.failures.length > 0) {
    showModal(
      `${actionName} Complete — with warnings`,
      `<div class="notice-card warning">
         <div>
           <h3>${icon('alert')} Some items could not be processed</h3>
           <p>${res.completed - res.failures.length} of ${res.total} completed successfully. The following ${res.failures.length} item(s) failed:</p>
           <ul class="text-sm mt-sm lh-relaxed pl-18">
             ${res.failures.map(f => `<li>Camera ${escapeHtml(String(f.camera ?? '?'))}${f.type ? ' (' + escapeHtml(f.type) + ')' : ''}: ${escapeHtml(f.error)}</li>`).join('')}
           </ul>
         </div>
       </div>`,
      [{ label: 'OK', class: 'btn-primary', onClick: () => renderRecordingsScreen({ caseId, evidenceId }) }]
    );
  } else if (res.cancelled) {
    showModal(
      `${actionName} Cancelled`,
      `<p>${res.completed} of ${res.total} items processed before cancellation.</p>`,
      [{ label: 'OK', class: 'btn-secondary', onClick: () => renderRecordingsScreen({ caseId, evidenceId }) }]
    );
  } else {
    renderRecordingsScreen({ caseId, evidenceId });
  }
}


async function runFaceSearch(caseId) {
  const fileInput = document.getElementById('face-search-input');
  const resultsEl = document.getElementById('face-search-results');
  const btn = document.getElementById('face-search-btn');
  const file = fileInput.files && fileInput.files[0];

  if (!file) {
    resultsEl.innerHTML = `<div class="error-inline"><span>${icon('alert')}</span><span>Choose a reference photo first.</span></div>`;
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
        <div class="empty-state py-16">
          <div class="empty-state-subtitle">No candidate faces found. Either no segments have been indexed yet
          (run "Check Faces" on exported segments below first), or none were similar enough to appear.</div>
        </div>`;
    } else {
      resultsEl.innerHTML = `
        <div class="notice-card mb-10">
          <p class="m-0 text-sm">${escapeHtml(res.warning)}</p>
        </div>
        <div class="table-container">
          <table>
            <thead><tr><th>Segment</th><th>Time Offset</th><th>Similarity</th><th>vs. Reference Threshold (${res.reference_threshold})</th></tr></thead>
            <tbody>
              ${matches.map(m => `
                <tr>
                  <td class="hash-font text-xs">${escapeHtml(m.segment_id.substring(0, 8))}…</td>
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
      <div class="error-banner mt-0">
        <div class="error-banner-icon">${icon('alert')}</div>
        <div class="error-banner-body">
          <div class="error-banner-title">Face search failed</div>
          <div class="error-banner-msg">${escapeHtml(err.message)}</div>
        </div>
      </div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = icon('search') + ' Search';
  }
}

/** Play button for an exported segment (shown only once an MP4 exists). */
function playButtonHtml(caseId, evidenceId, segmentId) {
  return `<button type="button" id="play-btn-${escapeHtml(segmentId)}" class="btn btn-primary btn-sm btn-compact"
            ${actAttrs('play', caseId, evidenceId, segmentId)} title="Watch the exported video here">${icon('play')} Play</button>`;
}

/** Watch an exported segment inside the app (plays the exported MP4 copy; the evidence is never touched). */
function playSegment(caseId, evidenceId, segmentId) {
  const src = segmentVideoUrl(caseId, segmentId);
  showModal(
    `${icon('film')} Exported segment`,
    `<video id="segment-player" class="video-player" controls preload="metadata" playsinline src="${escapeHtml(src)}"></video>
     <div id="segment-player-error" class="error-inline hidden">
       <span>${icon('alert')}</span><span id="segment-player-error-msg"></span>
     </div>
     <p class="form-hint mt-md">This is the exported MP4 copy, played read-only. Use the video controls to pause, seek and change speed.
     Playing it does not change the file or the evidence image.</p>`,
    [{ label: 'Close', class: 'btn-secondary', onClick: () => {} }]
  );
  const modal = document.querySelector('#modal-root .modal-content');
  if (modal) modal.classList.add('modal-wide');
  const video = document.getElementById('segment-player');
  if (video) {
    video.addEventListener('error', () => {
      document.getElementById('segment-player-error-msg').textContent =
        'This video could not be played. It may be missing from disk or not decodable by your browser; export the segment again or open the exported file in an external player.';
      document.getElementById('segment-player-error').classList.remove('hidden');
    });
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
      // The backend genuinely could not export this segment — show as toast failure
      showToast(`Export unavailable: ${detail.error}`, 'error');
      if (btnEl) {
        btnEl.disabled = false;
        btnEl.innerHTML = `${icon('download')} Export`;
      }
      return;
    }

    const filename = detail.export_path ? detail.export_path.split(/[\\/]/).pop() : 'video.mp4';
    const shaShort = detail.sha256 ? detail.sha256.substring(0, 12) : '';
    const cam = res.camera ?? (detail.camera ?? '');
    const camLabel = cam ? `Camera ${cam} — ` : '';

    showToast(`Export complete: ${camLabel}${filename}${shaShort ? ` (SHA: ${shaShort}…)` : ''}`, 'success');

    // Update button and row without blocking modal
    const exportBtn = document.getElementById(`export-btn-${segmentId}`);
    if (exportBtn) {
      exportBtn.disabled = false;
      exportBtn.title = 'Re-Export MP4 container';
      exportBtn.innerHTML = `${icon('download')} Re-Export`;
      if (!document.getElementById(`play-btn-${segmentId}`)) {
        exportBtn.insertAdjacentHTML('beforebegin', playButtonHtml(caseId, evidenceId, segmentId));
      }
      const row = exportBtn.closest('tr');
      if (row && row.children.length >= 7) {
        row.children[6].innerHTML = `<span class="badge badge-complete text-xxs">Exported</span>`;
        if (detail.sha256 && row.children[5]) {
          row.children[5].innerHTML = `<span title="${escapeHtml(detail.sha256)}">${escapeHtml(detail.sha256.substring(0, 8))}…</span>`;
        }
      }
    }
  } catch (err) {
    showToast('Export failed: ' + err.message, 'error');
    if (btnEl) {
      btnEl.disabled = false;
      btnEl.innerHTML = `${icon('download')} Export`;
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
        <div class="${res.motion_detected ? 'notice-card' : 'success-inline'} mb-md">
          <strong>${escapeHtml(res.label || 'Basic Motion Detection')}:</strong> ${escapeHtml(res.details)}
        </div>
        <div class="flex-col gap-6 text-base text-muted">
          <div><strong>Motion Detected:</strong> ${res.motion_detected ? '<span class="text-partial font-bold">YES</span>' : '<span class="text-complete font-bold">NO</span>'}</div>
          <div><strong>Motion Frames:</strong> ${res.motion_frames} / ${res.total_frames} (${((res.motion_ratio || 0) * 100).toFixed(1)}%)</div>
          <div class="text-xs text-dim mt-xs">Decoupled post-export analysis via OpenCV frame differencing. Evidence hash and video container remain unaltered.</div>
        </div>
      `,
      [{ label: 'OK', class: 'btn-primary', onClick: () => renderRecordingsScreen({ caseId, evidenceId }) }]
    );
  } catch (err) {
    showModal(
      'Basic Motion Detection Error',
      `<div class="error-banner mt-0">
         <div class="error-banner-icon">${icon('alert')}</div>
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
        <div class="${res.objects_detected ? 'notice-card' : 'success-inline'} mb-md">
          <strong>${escapeHtml(res.label)}</strong><br>${escapeHtml(res.summary)}
        </div>
        ${rows ? `<div class="table-container"><table>
          <thead><tr><th>Object</th><th>Sampled frames</th><th>Max at once</th><th>First seen</th><th>Best score</th></tr></thead>
          <tbody>${rows}</tbody></table></div>` : ''}
        <div class="text-xs text-dim mt-10 lh-base">
          Automated detections for human review — not identification. Frames are sampled, so an object visible only in
          skipped frames is missed. Evidence hash and video container remain unaltered.
        </div>
      `,
      [{ label: 'OK', class: 'btn-primary', onClick: () => renderRecordingsScreen({ caseId, evidenceId }) }]
    );
  } catch (err) {
    showModal(
      'Object Detection Error',
      `<div class="error-banner mt-0">
         <div class="error-banner-icon">${icon('alert')}</div>
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
        <div class="${res.faces_detected ? 'notice-card' : 'success-inline'} mb-md">
          <strong>${escapeHtml(res.label || 'AI-Based Face Detection')}:</strong> ${escapeHtml(res.details)}
        </div>
        <div class="flex-col gap-6 text-base text-muted">
          <div><strong>Face(s) Detected:</strong> ${res.faces_detected ? '<span class="text-partial font-bold">YES</span>' : '<span class="text-complete font-bold">NO</span>'}</div>
          <div><strong>Frames with faces:</strong> ${res.frames_with_faces} / ${res.frames_sampled} sampled (of ${res.total_frames} total)</div>
          <div><strong>Max faces in one frame:</strong> ${res.max_faces_in_single_frame}</div>
          <div class="text-xs text-dim mt-xs">
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
      `<div class="error-banner mt-0">
         <div class="error-banner-icon">${icon('alert')}</div>
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
  const toneClass = tone === 'good' ? 'text-complete' : tone === 'bad' ? 'text-error'
                  : tone === 'warn' ? 'text-partial' : 'text-main';
  return `<div class="acc-tile" title="${escapeHtml(hint || '')}">
      <div class="acc-tile-value ${toneClass}">${value}</div>
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
    parts.push(`<div class="notice-card mt-10"><p class="m-0 text-sm"><strong>Not measured:</strong> ${r.not_measured.map(escapeHtml).join(' · ')}</p></div>`);
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
    resultsEl.innerHTML = `<div class="error-inline"><span>${icon('alert')}</span><span>Supply at least one ground truth: a video, a recording log, or the original disk image path.</span></div>`;
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
    resultsEl.innerHTML = `<div class="error-banner mt-0"><div class="error-banner-icon">${icon('alert')}</div><div class="error-banner-body">
      <div class="error-banner-title">Measurement failed</div><div class="error-banner-msg">${escapeHtml(err.message)}</div></div></div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = icon('ruler') + ' Measure';
  }
}

async function loadAccuracyHistory(caseId) {
  const el = document.getElementById('acc-history');
  if (!el) return;
  try {
    const items = await API.getAccuracy(caseId);
    if (!items.length) { el.innerHTML = ''; return; }
    el.innerHTML = `<div class="card-title text-base"><span>Earlier measurements (${items.length}) — included in the PDF report</span></div>
      <div class="table-container"><table><thead><tr><th>When</th><th>Segment</th><th>Frames recovered</th><th>In order</th><th>Byte-identical</th><th>Original bytes recovered</th></tr></thead><tbody>
      ${items.map(r => `<tr>
        <td>${escapeHtml(formatIST(r.created_at))}</td>
        <td class="hash-font text-xs">${escapeHtml((r.segment_id || '').substring(0, 8))}…</td>
        <td>${r.frames ? accFmt(r.frames.frame_recall_pct) : '—'}</td>
        <td>${r.frames ? accFmt(r.frames.in_order_pct) : '—'}</td>
        <td>${r.bytes ? (r.bytes.identical ? 'yes' : 'no') : '—'}</td>
        <td>${r.placement ? accFmt(r.placement.byte_recall_pct) : '—'}</td></tr>`).join('')}
      </tbody></table></div>`;
  } catch (_) { el.innerHTML = ''; }
}
