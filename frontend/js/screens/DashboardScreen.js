/**
 * DashboardScreen.js — Main cases overview list.
 */
async function renderDashboardScreen() {
  const root = document.getElementById('content-root');

  root.innerHTML = `
    <section class="hero">
      <div>
        <h2>Recover CCTV evidence, with every step on record.</h2>
        <p>Load a DVR/NVR disk image, carve the video that is still on it, prove nothing was altered, and export a signed forensic report. The evidence file is only ever read, never written.</p>
        <div class="hero-actions">
          <button id="btn-new-case" class="btn btn-primary btn-lg">${icon('plus-circle')} Register New Case</button>
          <button id="btn-2fa" class="btn btn-secondary btn-lg">${icon('key')} Two-factor</button>
          <button id="btn-add-examiner" class="btn btn-secondary btn-lg">${icon('plus-circle')} Add Examiner</button>
        </div>
      </div>
      <div class="hero-art">${heroArt()}</div>
    </section>

    <div class="card">
      <div class="card-title"><span>${icon('folder-open')} Your cases</span><span class="badge badge-pending" id="stat-cases">–</span></div>
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
              <td><div class="skeleton-cell skeleton-w-110"></div></td>
              <td><div class="skeleton-cell skeleton-w-140"></div></td>
              <td><div class="skeleton-cell skeleton-w-180"></div></td>
              <td><div class="skeleton-cell skeleton-w-130"></div></td>
              <td><div class="skeleton-cell skeleton-w-90"></div></td>
            </tr>
            <tr class="skeleton-row">
              <td><div class="skeleton-cell skeleton-w-90"></div></td>
              <td><div class="skeleton-cell skeleton-w-120"></div></td>
              <td><div class="skeleton-cell skeleton-w-160"></div></td>
              <td><div class="skeleton-cell skeleton-w-130"></div></td>
              <td><div class="skeleton-cell skeleton-w-90"></div></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  document.getElementById('btn-new-case').onclick = () => navigateTo('new-case');
  document.getElementById('btn-2fa').onclick = openTwoFactorDialog;
  document.getElementById('btn-add-examiner').onclick = openAddExaminerDialog;

  try {
    const cases = await API.listCases();
    document.getElementById('stat-cases').textContent = cases.length + (cases.length === 1 ? ' case' : ' cases');
    const tbody = document.getElementById('cases-table-body');

    if (cases.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="5" class="p-0 border-none">
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
        <td><strong class="text-primary font-mono text-base">${escapeHtml(c.case_number)}</strong></td>
        <td>${escapeHtml(c.examiner)}</td>
        <td class="text-muted text-sm">${c.notes ? escapeHtml(c.notes) : '—'}</td>
        <td class="text-dim text-sm">${escapeHtml(formatIST(c.created_at))}</td>
        <td>
          <button class="btn btn-secondary btn-sm" ${navAttrs('case-detail', { caseId: c.case_id })}>Open ${icon('arrow-right')}</button>
        </td>
      </tr>
    `).join('');

  } catch (err) {
    const tbody = document.getElementById('cases-table-body');
    tbody.innerHTML = `
      <tr>
        <td colspan="5" class="p-12 border-none">
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
      `<p class="mb-10">Adds a 6-digit code from an authenticator app to every login. Keep a copy of the key in a safe place:
       if the phone is lost and no copy exists, an administrator has to clear the stored secret from the database.</p>
       <div id="tf-area"></div>`,
      [{ label: 'Set up', class: 'btn-primary', autoClose: false, onClick: async () => {
          const area = document.getElementById('tf-area');
          try {
            const r = await API.totpEnroll();
            area.innerHTML = `
              <div class="form-group"><label>Secret key (enter manually in the app)</label>
                <input class="form-control font-mono" readonly value="${escapeHtml(r.secret)}"></div>
              <div class="form-group"><label>Or the setup link</label>
                <input class="form-control text-xs" readonly value="${escapeHtml(r.otpauth_uri)}"></div>
              <div class="form-group"><label>Current 6-digit code</label>
                <input id="tf-code" class="form-control" inputmode="numeric" maxlength="6"></div>
              <button id="tf-confirm" class="btn btn-primary">Confirm and enable</button>
              <div id="tf-msg" class="mt-sm text-base"></div>`;
            document.getElementById('tf-confirm').onclick = async () => {
              const msg = document.getElementById('tf-msg');
              try {
                const done = await API.totpConfirm(document.getElementById('tf-code').value.trim());
                msg.innerHTML = 'Two-factor authentication is now <strong>ON</strong>. Save these one-time recovery codes offline (each works once; shown only now):' +
                  '<pre class="totp-secret-box">' +
                  escapeHtml((done.recovery_codes || []).join('\n')) + '</pre>';
              } catch (e2) { msg.textContent = e2.message; }
            };
          } catch (e1) { area.innerHTML = `<div class="error-inline">${escapeHtml(e1.message)}</div>`; }
      } },
       { label: 'Close', class: 'btn-secondary', onClick: () => {} }]);
  } else {
    showModal('Two-factor authentication',
      `<p class="mb-10">Two-factor authentication is <strong>ON</strong>. To turn it off, enter your password and a current code.</p>
       <div class="form-group"><label>Password</label><input id="tf-pw" type="password" class="form-control"></div>
       <div class="form-group"><label>Current 6-digit code (or a recovery code)</label><input id="tf-code" class="form-control" maxlength="16"></div>
       <div id="tf-msg" class="text-base"></div>`,
      [{ label: 'New recovery codes', class: 'btn-secondary', autoClose: false, onClick: async () => {
          const msg = document.getElementById('tf-msg');
          try {
            const r = await API.totpRecoveryCodes(document.getElementById('tf-pw').value, document.getElementById('tf-code').value.trim());
            msg.innerHTML = 'New recovery codes (the old ones no longer work). Save them offline:' +
              '<pre class="totp-secret-box">' +
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


/** Lists existing examiner accounts and offers to add a new one (each with their own password). */
async function openAddExaminerDialog() {
  let usernames = [];
  try { usernames = await API.listExaminers(); } catch (err) {
    showModal('Examiner accounts', `<div class="error-inline">${escapeHtml(err.message)}</div>`, [{ label: 'Close', class: 'btn-secondary', onClick: () => {} }]);
    return;
  }
  showModal('Examiner accounts',
    `<p class="mb-10"><b>Existing accounts:</b> ${usernames.map(escapeHtml).join(', ') || '—'}</p>
     <p class="mb-10">Every examiner signs in with their own username and password; everything they
     do is attributed to them in the audit log. There are no separate permission levels — any
     signed-in examiner can see every case.</p>
     <div class="form-group"><label>New username</label><input id="ae-username" class="form-control" autocomplete="off"></div>
     <div class="form-group"><label>Password</label><input id="ae-password" type="password" class="form-control" autocomplete="new-password"></div>
     <div class="form-group"><label>Confirm password</label><input id="ae-password2" type="password" class="form-control" autocomplete="new-password"></div>
     <p class="text-xs mb-10">${_PASSWORD_RULE_TEXT}</p>
     <div id="ae-msg" class="text-base"></div>`,
    [{ label: 'Add examiner', class: 'btn-primary', autoClose: false, onClick: async () => {
        const msg = document.getElementById('ae-msg');
        const username = document.getElementById('ae-username').value.trim();
        const pw = document.getElementById('ae-password').value;
        const pw2 = document.getElementById('ae-password2').value;
        if (!username) { msg.textContent = 'Choose a username.'; return; }
        if (pw !== pw2) { msg.textContent = 'Passwords do not match.'; return; }
        try {
          await API.addExaminer(username, pw);
          msg.innerHTML = `<strong>${escapeHtml(username)}</strong> can now sign in with the password you just set.`;
          document.getElementById('ae-username').value = '';
          document.getElementById('ae-password').value = '';
          document.getElementById('ae-password2').value = '';
        } catch (e) { msg.textContent = e.message; }
    } },
     { label: 'Close', class: 'btn-secondary', onClick: () => {} }]);
}
