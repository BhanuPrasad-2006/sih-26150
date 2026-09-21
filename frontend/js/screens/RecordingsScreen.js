/**
 * RecordingsScreen.js — List and export carved video segments with status breakdown.
 */
async function renderRecordingsScreen(params) {
  const { caseId, evidenceId } = params;
  const root = document.getElementById('content-root');

  root.innerHTML = `<p style="color:var(--text-dim);">Loading carved video segments...</p>`;

  try {
    const segments = await API.getSegments(caseId, evidenceId);

    root.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
        <div>
          <h2 style="font-size: 24px; font-weight: 700;">Carved Video Segments</h2>
          <p style="color: var(--text-muted); font-size: 14px;">Total Segments Reconstructed: ${segments.length}</p>
        </div>
        <div>
          <button class="btn btn-secondary" onclick="navigateTo('export-report', { caseId: ${caseId}, evidenceId: ${evidenceId} })">📄 Export PDF Forensic Report ➔</button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">
          <span>Reconstructed Timelines & Segments</span>
          <div style="font-size: 13px; font-weight: normal; color: var(--text-muted);">
            Statuses: 
            <span class="badge badge-complete">COMPLETE</span>
            <span class="badge badge-partial">PARTIAL</span>
            <span class="badge badge-uncertain">UNCERTAIN</span>
          </div>
        </div>

        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Camera</th>
                <th>Time Range (UTC)</th>
                <th>Frames</th>
                <th>Status</th>
                <th>Rationale / Gaps</th>
                <th>SHA-256 Hash</th>
                <th>Export Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              ${segments.length === 0
                ? `<tr><td colspan="8" style="text-align:center; color:var(--text-dim); padding:20px;">No segments carved yet. Run a disk scan first.</td></tr>`
                : segments.map(s => `
                    <tr>
                      <td><strong>Camera ${s.camera_id}</strong></td>
                      <td>${new Date(s.start_time * 1000).toISOString().replace('T', ' ').substring(0, 19)} —<br>${new Date(s.end_time * 1000).toISOString().replace('T', ' ').substring(0, 19)}</td>
                      <td>${s.frame_count}</td>
                      <td>
                        <span class="badge ${s.status === 'COMPLETE' ? 'badge-complete' : s.status === 'PARTIAL' ? 'badge-partial' : 'badge-uncertain'}">
                          ${s.status}
                        </span>
                      </td>
                      <td style="font-size:12px; max-width:200px; color:var(--text-muted);">${s.status_rationale || '-'}</td>
                      <td class="hash-font">${s.sha256_hash ? s.sha256_hash.substring(0, 12) + '...' : '-'}</td>
                      <td>
                        ${s.is_exported ? `<span style="color:var(--accent-emerald);">Exported MP4</span>` : `<span style="color:var(--text-dim);">Not Exported</span>`}
                      </td>
                      <td>
                        <button class="btn btn-secondary" style="font-size:12px; padding:4px 10px;" onclick="exportSegment(${caseId}, ${evidenceId}, ${s.id})">
                          ${s.is_exported ? 'Re-Export MP4' : 'Export MP4 (-c copy)'}
                        </button>
                      </td>
                    </tr>
                  `).join('')
              }
            </tbody>
          </table>
        </div>
      </div>
    `;

  } catch (err) {
    root.innerHTML = `<p style="color:var(--accent-rose);">Failed to load segments: ${err.message}</p>`;
  }
}

async function exportSegment(caseId, evidenceId, segmentId) {
  showModal('Exporting Video', '<p>Exporting raw stream with FFmpeg (-c copy) and hashing MP4 container...</p>');
  try {
    const res = await API.exportSegment(caseId, evidenceId, segmentId);
    showModal(
      'Export Successful',
      `
        <p style="color:var(--accent-emerald);">✅ Segment successfully exported!</p>
        <p style="font-size:13px; margin-top:8px;"><strong>File Path:</strong><br><span style="font-family:var(--font-mono);">${res.file_path}</span></p>
        <p style="font-size:13px; margin-top:8px;"><strong>SHA-256:</strong><br><span class="hash-font">${res.sha256_hash}</span></p>
        <p style="font-size:13px; margin-top:8px;"><strong>ffprobe Validation:</strong> ${res.ffprobe_valid ? 'Valid MP4 Container' : 'Warning: Stream structure invalid'}</p>
      `,
      [{ label: 'OK', class: 'btn-primary', onClick: () => renderRecordingsScreen({ caseId, evidenceId }) }]
    );
  } catch (err) {
    showModal('Export Error', `<p style="color:var(--accent-rose);">${err.message}</p>`);
  }
}
