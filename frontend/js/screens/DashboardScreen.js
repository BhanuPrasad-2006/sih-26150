/**
 * DashboardScreen.js — Main cases overview list.
 */
async function renderDashboardScreen() {
  const root = document.getElementById('content-root');

  root.innerHTML = `
    <section class="hero">
      <div>
        <h2>Recover CCTV evidence you can defend in court.</h2>
        <p>Load a DVR/NVR disk image, carve the video that is still on it, prove nothing was altered, and export a signed forensic report. The evidence file is only ever read, never written.</p>
        <div class="hero-actions">
          <button id="btn-new-case" class="btn btn-primary btn-lg">${icon('plus-circle')} Register New Case</button>
          <button id="btn-security" class="btn btn-secondary btn-lg">${icon('shield-check')} Security status</button>
          <button id="btn-2fa" class="btn btn-secondary btn-lg">${icon('key')} Two-factor</button>
        </div>
      </div>
      <div class="hero-art">${heroArt()}</div>
    </section>

    <div class="stat-grid">
      <div class="stat-card">${iconChip('folder')}<div><div class="stat-value" id="stat-cases">–</div><div class="stat-label">Cases registered</div></div></div>
      <div class="stat-card">${iconChip('fingerprint', 'ok')}<div><div class="stat-value">SHA-256</div><div class="stat-label">Every image hashed on load</div></div></div>
      <div class="stat-card">${iconChip('lock', 'warn')}<div><div class="stat-value">Read-only</div><div class="stat-label">Evidence is never modified</div></div></div>
      <div class="stat-card">${iconChip('link')}<div><div class="stat-value">Chained</div><div class="stat-label">Tamper-evident audit log</div></div></div>
    </div>

    <div class="card">
      <div class="card-title"><span>${icon('layers')} How an investigation flows</span></div>
      <div class="step-list">
        <div class="step-card"><span class="n">1</span><h4>Register a case</h4><p>Case number and examiner start the chain of custody.</p></div>
        <div class="step-card"><span class="n">2</span><h4>Load the disk image</h4><p>Upload a .dd/.img file, point to one, or image a connected drive.</p></div>
        <div class="step-card"><span class="n">3</span><h4>Scan and recover</h4><p>The carver finds recordings, including deleted ones, and rates each result.</p></div>
        <div class="step-card"><span class="n">4</span><h4>Report</h4><p>Export a signed PDF, or an encrypted package for another examiner.</p></div>
      </div>
    </div>

    <div class="card">
      <div class="card-title"><span>${icon('folder-open')} Your cases</span></div>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Case Number</th>
              <th>Investigator</th>
              <th>Notes / Agency</th>
              <th>Registered</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="cases-table-body">
            <!-- loading state -->
            <tr class="skeleton-row">
              <td><div class="skeleton-cell" style="width:110px;"></div></td>
              <td><div class="skeleton-cell" style="width:140px;"></div></td>
              <td><div class="skeleton-cell" style="width:180px;"></div></td>
              <td><div class="skeleton-cell" style="width:130px;"></div></td>
              <td><div class="skeleton-cell" style="width:90px;"></div></td>
            </tr>
            <tr class="skeleton-row">
              <td><div class="skeleton-cell" style="width:90px;"></div></td>
              <td><div class="skeleton-cell" style="width:120px;"></div></td>
              <td><div class="skeleton-cell" style="width:160px;"></div></td>
              <td><div class="skeleton-cell" style="width:130px;"></div></td>
              <td><div class="skeleton-cell" style="width:90px;"></div></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  document.getElementById('btn-new-case').onclick = () => navigateTo('new-case');
  document.getElementById('btn-2fa').onclick = openTwoFactorDialog;
  document.getElementById('btn-security').onclick = openSecurityStatusDialog;

  try {
    const cases = await API.listCases();
    document.getElementById('stat-cases').textContent = String(cases.length);
    const tbody = document.getElementById('cases-table-body');

    if (cases.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="5" style="padding: 0; border: none;">
            <div class="empty-state">
              ${emptyArt()}
              <div class="empty-state-title">No cases yet</div>
              <div class="empty-state-subtitle">Create your first forensic case to get started — each case tracks a chain of custody for one investigation.</div>
              <button class="btn btn-primary" ${navAttrs('new-case')}>${icon('plus-circle')} Register First Case</button>
            </div>
          </td>
        </tr>`;
      return;
    }

    tbody.innerHTML = cases.map(c => `
      <tr>
        <td><strong style="color: var(--accent-cyan); font-family: var(--font-mono); font-size:13px;">${escapeHtml(c.case_number)}</strong></td>
        <td>${escapeHtml(c.examiner)}</td>
        <td style="color:var(--text-muted); font-size:12px;">${c.notes ? escapeHtml(c.notes) : '—'}</td>
        <td style="color:var(--text-dim); font-size:12px;">${new Date(c.created_at).toLocaleString()}</td>
        <td>
          <button class="btn btn-secondary btn-sm" ${navAttrs('case-detail', { caseId: c.case_id })}>Open ${icon('arrow-right')}</button>
        </td>
      </tr>
    `).join('');

  } catch (err) {
    const tbody = document.getElementById('cases-table-body');
    tbody.innerHTML = `
      <tr>
        <td colspan="5" style="padding: 12px; border: none;">
          <div class="error-banner">
            <div class="error-banner-icon">${icon('alert')}</div>
            <div class="error-banner-body">
              <div class="error-banner-title">Failed to load cases</div>
              <div class="error-banner-msg">${escapeHtml(err.message)}</div>
            </div>
          </div>
        </td>
      </tr>`;
  }
}


/** Two-factor authentication: enable (secret + confirmation code) or disable (password + code). */
async function openTwoFactorDialog() {
  let enabled = false;
  try { enabled = (await API.totpStatus()).enabled; } catch (err) {
    showModal('Two-factor authentication', `<div class="error-inline">${escapeHtml(err.message)}</div>`, [{ label: 'Close', class: 'btn-secondary', onClick: () => {} }]);
    return;
  }
  if (!enabled) {
    showModal('Two-factor authentication',
      `<p style="margin:0 0 10px;">Adds a 6-digit code from an authenticator app to every login. Keep a copy of the key in a safe place:
       if the phone is lost and no copy exists, an administrator has to clear the stored secret from the database.</p>
       <div id="tf-area"></div>`,
      [{ label: 'Set up', class: 'btn-primary', autoClose: false, onClick: async () => {
          const area = document.getElementById('tf-area');
          try {
            const r = await API.totpEnroll();
            area.innerHTML = `
              <div class="form-group"><label>Secret key (enter manually in the app)</label>
                <input class="form-control" readonly value="${escapeHtml(r.secret)}" style="font-family:var(--font-mono);"></div>
              <div class="form-group"><label>Or the setup link</label>
                <input class="form-control" readonly value="${escapeHtml(r.otpauth_uri)}" style="font-size:11px;"></div>
              <div class="form-group"><label>Current 6-digit code</label>
                <input id="tf-code" class="form-control" inputmode="numeric" maxlength="6"></div>
              <button id="tf-confirm" class="btn btn-primary">Confirm and enable</button>
              <div id="tf-msg" style="margin-top:8px; font-size:13px;"></div>`;
            document.getElementById('tf-confirm').onclick = async () => {
              const msg = document.getElementById('tf-msg');
              try {
                const done = await API.totpConfirm(document.getElementById('tf-code').value.trim());
                msg.innerHTML = 'Two-factor authentication is now <strong>ON</strong>. Save these one-time recovery codes offline (each works once; shown only now):' +
                  '<pre style="margin-top:8px; padding:10px; background:var(--bg-surface-3); border-radius:6px; font-family:var(--font-mono); user-select:all;">' +
                  escapeHtml((done.recovery_codes || []).join('\n')) + '</pre>';
              } catch (e2) { msg.textContent = e2.message; }
            };
          } catch (e1) { area.innerHTML = `<div class="error-inline">${escapeHtml(e1.message)}</div>`; }
      } },
       { label: 'Close', class: 'btn-secondary', onClick: () => {} }]);
  } else {
    showModal('Two-factor authentication',
      `<p style="margin:0 0 10px;">Two-factor authentication is <strong>ON</strong>. To turn it off, enter your password and a current code.</p>
       <div class="form-group"><label>Password</label><input id="tf-pw" type="password" class="form-control"></div>
       <div class="form-group"><label>Current 6-digit code (or a recovery code)</label><input id="tf-code" class="form-control" maxlength="16"></div>
       <div id="tf-msg" style="font-size:13px;"></div>`,
      [{ label: 'New recovery codes', class: 'btn-secondary', autoClose: false, onClick: async () => {
          const msg = document.getElementById('tf-msg');
          try {
            const r = await API.totpRecoveryCodes(document.getElementById('tf-pw').value, document.getElementById('tf-code').value.trim());
            msg.innerHTML = 'New recovery codes (the old ones no longer work). Save them offline:' +
              '<pre style="margin-top:8px; padding:10px; background:var(--bg-surface-3); border-radius:6px; font-family:var(--font-mono); user-select:all;">' +
              escapeHtml(r.recovery_codes.join('\n')) + '</pre>';
          } catch (e) { msg.textContent = e.message; }
      } },
       { label: 'Turn off', class: 'btn-primary', autoClose: false, onClick: async () => {
          const msg = document.getElementById('tf-msg');
          try { await API.totpDisable(document.getElementById('tf-pw').value, document.getElementById('tf-code').value.trim()); msg.textContent = 'Two-factor authentication is now OFF.'; }
          catch (e) { msg.textContent = e.message; }
      } },
       { label: 'Close', class: 'btn-secondary', onClick: () => {} }]);
  }
}


/** Live security self-check of this installation. */
async function openSecurityStatusDialog() {
  showModal('Security status', '<div id="sec-area">Checking…</div>', [{ label: 'Close', class: 'btn-primary', onClick: () => {} }]);
  const area = document.getElementById('sec-area');
  try {
    const r = await API.securityStatus();
    const dot = { ok: 'var(--status-complete)', warn: 'var(--status-partial)', info: 'var(--text-dim)' };
    area.innerHTML = `<p style="margin:0 0 10px;">${r.warnings ? r.warnings + ' item(s) need attention.' : 'All checks pass.'}</p>` +
      r.checks.map(c => `
        <div style="display:flex; gap:10px; align-items:flex-start; padding:6px 0; border-top:1px solid var(--border-color);">
          <span style="width:10px; height:10px; border-radius:50%; margin-top:6px; flex:none; background:${dot[c.status] || dot.info};"></span>
          <div><strong>${escapeHtml(c.title)}</strong><div style="font-size:12px; color:var(--text-muted);">${escapeHtml(c.detail)}</div></div>
        </div>`).join('');
  } catch (e) { area.textContent = e.message; }
}
