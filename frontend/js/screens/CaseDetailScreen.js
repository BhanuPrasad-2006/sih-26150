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
        <div class="error-banner-icon">${icon('alert')}</div>
        <div class="error-banner-body">
          <div class="error-banner-title">Failed to load case — GET /api/cases/${caseId}</div>
          <div class="error-banner-msg">${escapeHtml(err.message)}</div>
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
          <div class="page-title">
            Case: <span class="text-primary">${escapeHtml(caseObj.case_number)}</span>
            ${caseObj.priority ? `<span class="badge badge-priority-${escapeHtml(caseObj.priority.toLowerCase())}">${escapeHtml(caseObj.priority)}</span>` : ''}
            ${caseObj.status ? `<span class="badge badge-status-${escapeHtml(caseObj.status.toLowerCase())}">${escapeHtml(caseObj.status)}</span>` : ''}
          </div>
          <div class="page-subtitle">
            ${caseObj.case_title ? `<strong class="text-main">${escapeHtml(caseObj.case_title)}</strong> • ` : ''}
            Investigator: <strong>${escapeHtml(caseObj.examiner)}</strong>
            ${caseObj.created_by && caseObj.created_by !== caseObj.examiner ? ` <span class="text-dim">(registered by ${escapeHtml(caseObj.created_by)})</span>` : ''}
          </div>
        </div>
        <button id="btn-add-evidence" class="btn btn-primary btn-lg">${icon('upload-cloud')} Add disk image</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Case &amp; Custody Details</div>
      <div class="meta-grid">
        <div>
          <div class="meta-label">FIR / Crime Reference</div>
          <div class="meta-value font-mono">${caseObj.fir_number ? escapeHtml(caseObj.fir_number) : '—'}</div>
        </div>
        <div>
          <div class="meta-label">Police Unit / Agency</div>
          <div class="meta-value">${caseObj.agency ? escapeHtml(caseObj.agency) : '—'}</div>
        </div>
        <div>
          <div class="meta-label">Seizure Officer &amp; Scene</div>
          <div class="meta-value">
            ${caseObj.seizure_officer ? escapeHtml(caseObj.seizure_officer) : '—'}
            ${caseObj.seizure_location ? `<div class="text-xs text-muted">${escapeHtml(caseObj.seizure_location)}</div>` : ''}
          </div>
        </div>
        <div>
          <div class="meta-label">Target Hardware / DVR</div>
          <div class="meta-value font-mono text-sm">${caseObj.target_device ? escapeHtml(caseObj.target_device) : '—'}</div>
        </div>
        <div>
          <div class="meta-label">Registered (IST)</div>
          <div class="meta-value">${escapeHtml(formatIST(caseObj.created_at))}</div>
        </div>
        <div>
          <div class="meta-label">Incident / Seizure Date</div>
          <div class="meta-value">${caseObj.incident_date ? escapeHtml(caseObj.incident_date) : '—'}</div>
        </div>
        <div style="grid-column: 1 / -1;">
          <div class="meta-label">Notes &amp; Scope</div>
          <div class="meta-value text-muted">${caseObj.notes ? escapeHtml(caseObj.notes) : '—'}</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>Attached Evidence Images</span>
        <span class="text-sm text-dim font-normal">${evidence.length} image${evidence.length !== 1 ? 's' : ''} loaded</span>
      </div>
      <div id="evidence-area">
        ${renderEvidenceTable(evidence, caseId)}
      </div>
    </div>
  `;

  // ── Load evidence modal ────────────────────────────────────────────────────
  document.getElementById('btn-add-evidence').onclick = () => {
    let selectedFile = null;

    showModal(
      `${icon('hard-drive')} Add disk image`,
      `
        <p class="card-lead mt-0">
          Add the recorder's disk image to this case. It is hashed on load and only ever read, never changed. Pick <b>one</b> of the three ways below.
        </p>

        <div class="form-group">
          <label>Evidence Label</label>
          <input type="text" id="modal-ev-label" class="form-control" value="EVID-00${evidence.length + 1}">
        </div>

        <div class="option-stack">
          <!-- Option 1: Choose File -->
          <div class="option-card">
            <h4>${iconChip('upload-cloud')} Option 1 · Select or Drop File</h4>
            <input type="file" id="modal-ev-file-input" accept=".dd,.img,.raw,.bin,.001,.iso,.vmdk,.vhd,.vhdx,.e01,.ex01,.aff,.aff4,*" class="hidden">
            <div id="modal-ev-browse-btn" class="dropzone" role="button" tabindex="0" aria-label="Choose a disk image file">
              ${dropArt()}
              <div class="dropzone-title">Drop your disk image here</div>
              <div class="dropzone-sub">or <b>browse your computer</b> to pick a file</div>
              <div class="dropzone-types">.dd · .img · .raw · .bin · .001 · .iso · .vmdk · .e01</div>
            </div>
            <div id="modal-ev-file-chip" class="file-chip">
              ${iconChip('hard-drive', 'ok')}
              <div class="grow">
                <div class="file-chip-name" id="modal-ev-file-name">No file chosen</div>
                <div class="file-chip-meta">Ready to load into case</div>
              </div>
              <button type="button" id="modal-ev-file-clear" class="modal-close hidden" title="Remove selected file" aria-label="Remove selected file">${icon('x')}</button>
            </div>
          </div>

          <div class="option-or">or</div>

          <!-- Option 2: File Path -->
          <div class="option-card">
            <h4>${iconChip('server')} Option 2 · Disk Image Path on this Machine</h4>
            <div style="display: flex; gap: 8px;">
              <input type="text" id="modal-ev-path" class="form-control" placeholder="C:\\path\\to\\evidence_image.dd" style="flex: 1;">
              <button type="button" id="modal-ev-browse-path-btn" class="btn btn-secondary" style="white-space: nowrap;">${icon('folder-open')} Browse…</button>
            </div>
            <p class="form-hint">Fastest for large (multi-GB or TB) images: read in-place via read-only memory mapping, no copying needed.</p>
          </div>

          <div class="option-or">or</div>

          <!-- Option 3: Image a drive -->
          <div class="option-card">
            <h4>${iconChip('hard-drive', 'warn')} Option 3 · Create an image from a connected drive</h4>
            <div id="modal-acq-area" class="text-dim-125">Checking whether drive imaging is available…</div>
          </div>
        </div>

        <div class="form-group">
          <label>Device Clock Offset from UTC (optional)</label>
          <input type="number" id="modal-ev-tz-offset" class="form-control" placeholder="e.g. 330 for IST (UTC+5:30)" step="1" min="-720" max="840">
          <p class="text-sm text-dim mt-xs lh-base">
            Minutes, e.g. <code>330</code> for IST. Only set this if you have independently confirmed the
            recorder's configured timezone — carved timestamps are otherwise shown as raw device-reported
            values and are <strong>not</strong> assumed to be UTC. Used to normalize timestamps for
            cross-camera/cross-device correlation and reporting.
          </p>
        </div>

        <div id="modal-ev-progress-box" class="upload-progress hidden">
          <div class="d-flex justify-between text-muted-125">
            <span id="modal-ev-progress-status">Processing evidence file...</span>
            <span id="modal-ev-progress-pct" class="font-bold text-primary">0%</span>
          </div>
          <div class="progress-bar-container mt-sm mb-0">
            <div id="modal-ev-progress-bar" class="progress-bar-fill"></div>
          </div>
        </div>

        <div id="modal-ev-error" class="error-inline" style="display: none; margin-top: 12px;">
          <span>${icon('alert')}</span><span id="modal-ev-error-msg"></span>
        </div>
      `,
      [
        { label: 'Cancel', class: 'btn-secondary', onClick: () => {} },
        {
          label: 'Load & Calculate Hashes',
          class: 'btn-primary',
          autoClose: false,
          onClick: async () => {
            const label = document.getElementById('modal-ev-label').value.trim();
            let path = document.getElementById('modal-ev-path').value.trim();
            path = path.replace(/^["']|["']$/g, ''); // strip any Windows quotes
            const tzOffsetRaw = document.getElementById('modal-ev-tz-offset').value.trim();
            const tzOffset = tzOffsetRaw === '' ? null : parseInt(tzOffsetRaw, 10);
            const errDiv = document.getElementById('modal-ev-error');
            const errMsgEl = document.getElementById('modal-ev-error-msg');
            const submitBtn = document.getElementById('modal-btn-1');

            function showModalError(msg) {
              errMsgEl.textContent = msg;
              errDiv.style.display = 'flex';
              if (typeof Toast !== 'undefined' && Toast.error) {
                Toast.error(msg);
              }
            }
            function hideModalError() {
              errMsgEl.textContent = '';
              errDiv.style.display = 'none';
            }

            hideModalError();

            if (!selectedFile && !path) {
              showModalError('Please choose a file or enter an image file path.');
              return;
            }
            if (tzOffsetRaw !== '' && (Number.isNaN(tzOffset) || tzOffset < -720 || tzOffset > 840)) {
              showModalError('Device clock offset must be a number of minutes between -720 and 840.');
              return;
            }

            try {
              let ev;
              // If path is specified or derived from selectedFile.path, use addEvidence (in-place)
              if (path) {
                if (submitBtn) {
                  submitBtn.disabled = true;
                  submitBtn.innerHTML = '<span class="btn-spinner"></span> Loading…';
                }
                ev = await API.addEvidence(caseId, path, label, tzOffset);
              } else if (selectedFile && selectedFile.path) {
                if (submitBtn) {
                  submitBtn.disabled = true;
                  submitBtn.innerHTML = '<span class="btn-spinner"></span> Loading…';
                }
                ev = await API.addEvidence(caseId, selectedFile.path, label, tzOffset);
              } else if (selectedFile) {
                const progressBox = document.getElementById('modal-ev-progress-box');
                const progressStatus = document.getElementById('modal-ev-progress-status');
                const progressPct = document.getElementById('modal-ev-progress-pct');
                const progressBar = document.getElementById('modal-ev-progress-bar');

                progressBox.classList.remove('hidden');
                if (submitBtn) {
                  submitBtn.disabled = true;
                  submitBtn.innerHTML = '<span class="btn-spinner"></span> Uploading…';
                }

                ev = await API.uploadEvidence(caseId, selectedFile, tzOffset, (pct, loaded, total) => {
                  progressBar.style.width = pct + '%';
                  progressPct.textContent = pct + '%';
                  const mbLoaded = (loaded / (1024 * 1024)).toFixed(1);
                  const mbTotal = (total / (1024 * 1024)).toFixed(1);
                  progressStatus.textContent = `Uploading: ${mbLoaded} MB / ${mbTotal} MB...`;
                  if (pct >= 100) {
                    progressStatus.textContent = 'Upload complete. Calculating hashes...';
                  }
                });
              }

              if (typeof Toast !== 'undefined' && Toast.success) {
                Toast.success('Evidence loaded successfully');
              }
              closeModal();
              navigateTo('evidence-scan', { caseId, evidenceId: ev.evidence_id || ev.id });
            } catch (err) {
              showModalError(err.message || 'Failed to load evidence image');
              const progressBox = document.getElementById('modal-ev-progress-box');
              if (progressBox) progressBox.classList.add('hidden');
              if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Load & Calculate Hashes';
              }
            }
          }
        }
      ]
    );

    initAcquisitionPanel(caseId);

    // Wire up file picker controls
    const fileInput = document.getElementById('modal-ev-file-input');
    const browseBtn = document.getElementById('modal-ev-browse-btn');
    const browsePathBtn = document.getElementById('modal-ev-browse-path-btn');
    const fileNameSpan = document.getElementById('modal-ev-file-name');
    const fileClearBtn = document.getElementById('modal-ev-file-clear');
    const fileChip = document.getElementById('modal-ev-file-chip');
    const pathInput = document.getElementById('modal-ev-path');

    async function handleNativeOrBrowserPick() {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_file) {
        try {
          const chosen = await window.pywebview.api.pick_file();
          if (chosen) {
            pathInput.value = chosen;
            fileNameSpan.textContent = chosen.split(/[\\/]/).pop();
            fileNameSpan.style.color = 'var(--text-bright, #fff)';
            fileNameSpan.style.fontWeight = '500';
            fileClearBtn.classList.remove('hidden');
            if (fileChip) fileChip.classList.add('show');
            return;
          }
        } catch (_) {}
      }
      fileInput.click();
    }

    if (browsePathBtn) {
      browsePathBtn.onclick = handleNativeOrBrowserPick;
    }

    if (browseBtn && fileInput) {
      browseBtn.onclick = handleNativeOrBrowserPick;
      browseBtn.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleNativeOrBrowserPick(); } };
      browseBtn.ondragover = (e) => { e.preventDefault(); browseBtn.classList.add('dragover'); };
      browseBtn.ondragleave = () => browseBtn.classList.remove('dragover');
      browseBtn.ondrop = (e) => {
        e.preventDefault();
        browseBtn.classList.remove('dragover');
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
          fileInput.files = e.dataTransfer.files;
          fileInput.onchange({ target: fileInput });
        }
      };
    }

    if (fileInput) {
      fileInput.onchange = (e) => {
        const file = e.target.files && e.target.files[0];
        if (file) {
          selectedFile = file;
          // In WebView2, file.path contains full local path
          if (file.path && pathInput) {
            pathInput.value = file.path;
          }
          const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
          fileNameSpan.textContent = `${file.name} (${sizeMb} MB)`;
          fileNameSpan.style.color = 'var(--text-bright, #fff)';
          fileNameSpan.style.fontWeight = '500';
          fileClearBtn.classList.remove('hidden');
          if (fileChip) fileChip.classList.add('show');
        }
      };
    }

    if (fileClearBtn) {
      fileClearBtn.onclick = () => {
        selectedFile = null;
        if (fileInput) fileInput.value = '';
        if (pathInput) pathInput.value = '';
        fileNameSpan.textContent = 'No file chosen';
        fileNameSpan.style.color = 'var(--text-muted)';
        fileNameSpan.style.fontWeight = 'normal';
        fileClearBtn.classList.add('hidden');
        if (fileChip) fileChip.classList.remove('show');
      };
    }

    if (pathInput) {
      pathInput.oninput = () => {
        const val = pathInput.value.trim().replace(/^["']|["']$/g, '');
        if (val && !selectedFile) {
          fileNameSpan.textContent = val.split(/[\\/]/).pop();
          fileNameSpan.style.color = 'var(--text-bright, #fff)';
          fileNameSpan.style.fontWeight = '500';
          fileClearBtn.classList.remove('hidden');
          if (fileChip) fileChip.classList.add('show');
        }
      };
    }
  };
}

/** Option 3 of the evidence modal: image a local drive or file into the case (read-only, hashed, verified). */
async function initAcquisitionPanel(caseId) {
  const area = document.getElementById('modal-acq-area');
  if (!area) return;
  let info;
  try {
    info = await API.getDrives();
  } catch (err) {
    area.textContent = 'Could not check drive imaging: ' + err.message;
    return;
  }
  if (!info.enabled) {
    area.innerHTML = escapeHtml(info.message || 'Drive imaging is disabled on this server.');
    return;
  }
  const options = (info.drives || []).map(d =>
    `<option value="${escapeHtml(d.path)}">${escapeHtml(d.path)} — ${escapeHtml(d.model || 'unknown model')}` +
    `${d.size_bytes ? ' — ' + (d.size_bytes / 1e9).toFixed(1) + ' GB' : ''}</option>`).join('');
  area.innerHTML = `
    <div class="flex-col gap-sm">
      <select id="acq-drive" class="form-control"><option value="">Pick a drive…</option>${options}</select>
      <input type="text" id="acq-path" class="form-control" placeholder="…or type a device / file path">
      <label class="d-flex gap-sm items-start lh-base text-muted">
        <input type="checkbox" id="acq-wb" class="mt-3">
        <span>I confirm this source is connected through a <strong>hardware write blocker</strong> (or a read-only mount).
        The software cannot enforce this; your confirmation is recorded in the audit log.</span>
      </label>
      <label class="d-flex gap-sm items-center text-muted">
        <input type="checkbox" id="acq-verify"> Also re-read the source afterwards to confirm it did not change (slower)
      </label>
      <div class="text-partial">Imaging a real drive reads the whole disk and can take hours. Raw devices usually need administrator/root rights.</div>
      <button type="button" id="acq-start" class="btn btn-secondary">Start imaging</button>
      <div id="acq-status" class="font-mono word-break-all"></div>
    </div>`;

  document.getElementById('acq-drive').onchange = (e) => {
    if (e.target.value) document.getElementById('acq-path').value = e.target.value;
  };
  document.getElementById('acq-start').onclick = async () => {
    const source = document.getElementById('acq-path').value.trim();
    const status = document.getElementById('acq-status');
    const btn = document.getElementById('acq-start');
    if (!source) { status.textContent = 'Choose a drive or enter a path.'; return; }
    if (!document.getElementById('acq-wb').checked) { status.textContent = 'Confirm the write blocker first.'; return; }
    btn.disabled = true;
    status.textContent = 'Starting…';
    try {
      await API.startAcquisition(caseId, {
        source_path: source,
        write_blocker_confirmed: true,
        verify_source: document.getElementById('acq-verify').checked,
      });
      const timer = setInterval(async () => {
        try {
          const st = await API.getAcquisitionStatus(caseId);
          const el = document.getElementById('acq-status');
          if (!el) { clearInterval(timer); return; }
          if (st.state === 'running') {
            const total = st.total_bytes ? ' / ' + (st.total_bytes / 1048576).toFixed(0) + ' MB' : '';
            el.textContent = `Imaging… ${(st.bytes_done / 1048576).toFixed(0)} MB${total}`;
          } else if (st.state === 'done') {
            clearInterval(timer);
            const r = st.report;
            el.innerHTML = `Done. SHA-256 ${escapeHtml(r.sha256)}<br>` +
              (r.is_bit_exact ? 'Image verified and bit-exact.'
                              : `<span class="text-partial">Not bit-exact: ${escapeHtml((r.notes || []).join(' '))}</span>`);
            setTimeout(() => { closeModal(); navigateTo('evidence-scan', { caseId, evidenceId: st.evidence_id }); }, 1500);
          } else if (st.state === 'failed') {
            clearInterval(timer);
            el.textContent = 'Failed: ' + st.error;
            btn.disabled = false;
          }
        } catch (e) { /* transient poll error; keep polling */ }
      }, 1000);
    } catch (err) {
      status.textContent = err.message;
      btn.disabled = false;
    }
  };
}

/** Helper — render the evidence table or empty state */
function renderEvidenceTable(evidence, caseId) {
  if (evidence.length === 0) {
    return `
      <div class="empty-state">
        ${emptyArt()}
        <div class="empty-state-title">No evidence loaded yet</div>
        <div class="empty-state-subtitle">Use “Add disk image” to attach a raw disk image (.dd / .img) to this case. It is hashed on load and never modified.</div>
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
            const scanLabel = scanStatus === 'COMPLETED' ? 'View Scan Results' : 'Scan Disk Image';
            const scanTitle = scanStatus === 'COMPLETED'
              ? 'Scan complete — click to view carved segments'
              : scanStatus === 'SCANNING'
              ? 'Scan currently in progress'
              : 'No scan run yet — click to start acquisition scan';

            return `
              <tr>
                <td><strong>${escapeHtml(ev.evidence_label || ev.evidence_id)}</strong></td>
                <td class="font-mono-xs text-muted max-w-200 text-truncate">${escapeHtml(ev.path || ev.file_path || '')}</td>
                <td><span class="badge ${brandBadge}">${escapeHtml(brand)}${confidence}</span></td>
                <td class="hash-font">${ev.sha256_before ? ev.sha256_before.substring(0, 16) + '…' : '—'}</td>
                <td><span class="badge ${badgeClass}">${scanStatus}</span></td>
                <td>
                  <button class="btn btn-secondary btn-sm" title="${scanTitle}"
                    ${navAttrs('evidence-scan', { caseId: caseId, evidenceId: ev.evidence_id })}>
                    ${scanLabel}
                  </button>
                </td>
              </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>`;
}
