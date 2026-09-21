/**
 * CaseDetailScreen.js — View case details and manage attached evidence files.
 *
 * The API now always returns `evidence` as an array (never undefined), but we
 * also guard with `?? []` at every access point as a belt-and-suspenders defence.
 */
async function renderCaseDetailScreen(params) {
  const caseId = params.caseId;
  const root = document.getElementById('content-root');

  root.innerHTML = `<p style="color:var(--text-dim);">Loading case details…</p>`;

  let caseObj;
  try {
    caseObj = await API.getCase(caseId);
  } catch (err) {
    root.innerHTML = `
      <p style="color:var(--accent-rose);">
        Failed to load case — <strong>GET /api/cases/${caseId}</strong> returned:<br>
        ${err.message}
      </p>`;
    return;
  }

  // Belt-and-suspenders: guarantee arrays even if a stale server omits the fields.
  const evidence = caseObj.evidence ?? [];

  root.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
      <div>
        <h2 style="font-size: 24px; font-weight: 700;">Case: ${caseObj.case_number}</h2>
        <p style="color: var(--text-muted); font-size: 14px;">Investigator: ${caseObj.examiner} (${caseObj.agency || caseObj.examiner})</p>
      </div>
      <button id="btn-add-evidence" class="btn btn-primary">➕ Load Disk Image (.dd/.img)</button>
    </div>

    <div class="card">
      <div class="card-title">Case Metadata</div>
      <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; font-size: 14px;">
        <div><strong style="color:var(--text-muted);">Registered:</strong><br>${new Date(caseObj.created_at).toLocaleString()}</div>
        <div><strong style="color:var(--text-muted);">Examiner:</strong><br>${caseObj.examiner}</div>
        <div><strong style="color:var(--text-muted);">Notes:</strong><br>${caseObj.notes || 'None'}</div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Attached Evidence Images</div>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Evidence ID</th>
              <th>File Path</th>
              <th>Brand Detected</th>
              <th>SHA-256 Hash</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            ${evidence.length === 0
              ? `<tr><td colspan="6" style="text-align:center; color:var(--text-dim); padding:20px;">
                   📂 No evidence loaded yet. Click "Load Disk Image" to attach a disk image to this case.
                 </td></tr>`
              : evidence.map(ev => `
                  <tr>
                    <td><strong>${ev.evidence_label || ev.evidence_id}</strong></td>
                    <td style="font-family:var(--font-mono); font-size:12px;">${ev.path || ev.file_path || ''}</td>
                    <td>
                      <span class="badge ${ev.brand === 'Dahua' || ev.detected_brand === 'Dahua' ? 'badge-verified' : (ev.brand === 'Hikvision' || ev.detected_brand === 'Hikvision') ? 'badge-partial' : 'badge-uncertain'}">
                        ${ev.brand || ev.detected_brand || 'Unknown'}${ev.confidence != null ? ' (' + (ev.confidence * 100).toFixed(0) + '%)' : ''}
                      </span>
                    </td>
                    <td class="hash-font">${ev.sha256_before ? ev.sha256_before.substring(0, 16) + '…' : '—'}</td>
                    <td>${ev.scan_status || 'PENDING'}</td>
                    <td>
                      <button class="btn btn-secondary" onclick="navigateTo('evidence-scan', { caseId: ${caseId}, evidenceId: '${ev.evidence_id}' })">
                        ${ev.scan_status === 'COMPLETED' ? 'View Scan Results ➔' : 'Scan Disk Image ➔'}
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

  document.getElementById('btn-add-evidence').onclick = () => {
    showModal(
      'Load Raw Disk Image (.dd / .img)',
      `
        <p style="font-size:13px; color:var(--text-muted); margin-bottom:12px;">
          Enter absolute path to a raw disk image file on localhost.<br>
          <em>Note: Physical drives (\\\\.\\PhysicalDriveN) will be rejected to protect live data.</em>
        </p>
        <div class="form-group">
          <label>Evidence Label</label>
          <input type="text" id="modal-ev-label" class="form-control" value="EVID-00${evidence.length + 1}">
        </div>
        <div class="form-group">
          <label>Image File Path (.dd / .img / .raw)</label>
          <input type="text" id="modal-ev-path" class="form-control" placeholder="C:\\path\\to\\synthetic_dahua.dd">
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
            if (!path) return;
            try {
              const ev = await API.addEvidence(caseId, path, label);
              navigateTo('evidence-scan', { caseId, evidenceId: ev.evidence_id || ev.id });
            } catch (err) {
              showModal('Error', `<p style="color:var(--accent-rose);">Failed to load evidence:<br>${err.message}</p>`);
            }
          }
        }
      ]
    );
  };
}
