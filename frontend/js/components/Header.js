/**
 * Header component.
 * Renders the top bar (branding + meta) and the breadcrumb strip below it.
 * Call renderHeader(breadcrumbs) where breadcrumbs is an array of:
 *   { label: string, screen?: string, params?: object }
 * The last item is always the current page (rendered as plain text).
 */
function renderHeader(breadcrumbs = []) {
  const root = document.getElementById('header-root');
  const host = window.location.hostname || '127.0.0.1';
  const isLocal = host === '127.0.0.1' || host === 'localhost';
  const hostLabel = isLocal ? '127.0.0.1' : `${host}`;

  const themeIcon = currentTheme() === 'dark' ? 'sun' : 'moon';
  root.innerHTML = `
    <div class="logo-area">
      ${logoMark()}
      <div class="logo-text">
        <h1>AEGIS <span class="logo-h1-sub">DVR/NVR Forensic Analysis Tool</span></h1>
        <p>SIH26150 · Recover, verify and report CCTV evidence</p>
      </div>
    </div>
    <div class="header-meta">
      <div id="case-context-pill" class="case-context-pill hidden" role="region" aria-label="Case context"></div>
      <button type="button" id="btn-restart-update" class="restart-update-btn" title="Click to restart and apply updates">
        Restart to Update &rarr;
      </button>
      <button type="button" id="btn-user-profile" class="btn btn-secondary btn-sm btn-profile" title="Examiner profile and security preferences">
        ${icon('user')} <span id="header-user-label">Profile</span> <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>
      </button>
      <button type="button" id="theme-toggle" class="icon-btn" aria-label="Switch light or dark theme" title="Switch light / dark theme">${icon(themeIcon)}</button>
    </div>
  `;
  document.getElementById('theme-toggle').addEventListener('click', () => {
    const next = toggleTheme();
    document.getElementById('theme-toggle').innerHTML = icon(next === 'dark' ? 'sun' : 'moon');
  });

  const updateBtn = document.getElementById('btn-restart-update');
  if (updateBtn) updateBtn.addEventListener('click', openUpdateModal);

  const profBtn = document.getElementById('btn-user-profile');
  if (profBtn) profBtn.addEventListener('click', openUserProfileModal);

  API.authStatus().then(st => {
    const lbl = document.getElementById('header-user-label');
    if (lbl && (st.username || st.remembered_username)) {
      lbl.textContent = st.username || st.remembered_username;
    }
  }).catch(() => {});

  // ── Breadcrumb strip ──────────────────────────────────────────────────────
  // Ensure the strip element exists (created once in index.html is ideal,
  // but we manage it here for resilience).
  let strip = document.getElementById('breadcrumb-strip');
  if (!strip) {
    // Insert after header, before main-layout
    strip = document.createElement('nav');
    strip.id = 'breadcrumb-strip';
    strip.className = 'breadcrumb-strip';
    const appContainer = document.getElementById('app-container');
    const mainLayout = document.querySelector('.main-layout');
    appContainer.insertBefore(strip, mainLayout);
  }

  // Always start with a "Dashboard" home crumb
  const allCrumbs = [
    { label: 'Dashboard', screen: 'dashboard', params: {}, icon: 'home' },
    ...breadcrumbs
  ];

  strip.innerHTML = allCrumbs.map((crumb, idx) => {
    const isLast = idx === allCrumbs.length - 1;
    const sep = idx > 0 ? `<span class="crumb-sep">${icon('chevron-right')}</span>` : '';
    const ico = crumb.icon ? icon(crumb.icon) : '';
    if (isLast) {
      return `${sep}<span class="crumb-current">${ico}${escapeHtml(crumb.label)}</span>`;
    }
    return `${sep}<span class="crumb-link" data-screen="${escapeHtml(crumb.screen)}" data-params="${escapeHtml(JSON.stringify(crumb.params || {}))}">${ico}${escapeHtml(crumb.label)}</span>`;
  }).join('');

  // Wire up clicks on crumb links
  strip.querySelectorAll('.crumb-link').forEach(el => {
    el.addEventListener('click', () => {
      const screen = el.dataset.screen;
      const params = JSON.parse(el.dataset.params || '{}');
      navigateTo(screen, params);
    });
  });
}

let activeHeaderCaseId = null;
let activeHeaderEvidenceId = null;

async function updateHeaderContext(caseId, evidenceId = null) {
  const pill = document.getElementById('case-context-pill');
  if (!pill) return;

  if (!caseId) {
    pill.classList.add('hidden');
    activeHeaderCaseId = null;
    activeHeaderEvidenceId = null;
    return;
  }

  activeHeaderCaseId = caseId;
  activeHeaderEvidenceId = evidenceId;

  try {
    const caseData = await API.getCase(caseId);
    if (activeHeaderCaseId !== caseId) return;

    // Breadcrumbs are drawn before the case loads, with the internal id: swap in the case number.
    document.querySelectorAll('#breadcrumb-strip .crumb-link, #breadcrumb-strip .crumb-current').forEach((el) => {
      if (el.textContent.trim() === `Case #${caseId}` && caseData.case_number) {
        el.lastChild.textContent = `Case ${caseData.case_number}`;
      }
    });

    const evidenceList = caseData.evidence || [];
    let currentEvidence = null;
    if (evidenceId) {
      currentEvidence = evidenceList.find(e => e.evidence_id === evidenceId);
    }
    if (!currentEvidence && evidenceList.length > 0) {
      currentEvidence = evidenceList[0];
    }

    const caseNum = caseData.case_number || (caseData.case_id ? caseData.case_id.substring(0, 8) : caseId);
    let evidenceLabel = 'None';
    let integrityState = 'none';

    if (currentEvidence) {
      evidenceLabel = currentEvidence.label
        || (currentEvidence.path ? currentEvidence.path.split(/[\\/]/).pop() : (currentEvidence.evidence_id.substring(0, 8) + '…'));

      if (currentEvidence.sha256_after === 'MISMATCH') {
        integrityState = 'mismatch';
      } else if (currentEvidence.sha256_after && currentEvidence.sha256_after === currentEvidence.sha256_before) {
        integrityState = 'verified';
      } else if (currentEvidence.sha256_after) {
        integrityState = 'verified';
      } else {
        integrityState = 'unverified';
      }
    }

    let integrityClass = 'badge-pending';
    let integrityIcon = 'shield';
    let integrityText = 'Not verified yet';
    let integrityTitle = 'Disk image not verified yet. Click to verify integrity.';

    if (integrityState === 'verified') {
      integrityClass = 'badge-verified';
      integrityIcon = 'check-circle';
      integrityText = 'Verified';
      integrityTitle = 'Integrity verified: matches baseline. Click to re-verify.';
    } else if (integrityState === 'mismatch') {
      integrityClass = 'badge-error';
      integrityIcon = 'alert';
      integrityText = 'Mismatch';
      integrityTitle = 'MISMATCH DETECTED: disk image has been modified! Click to re-verify.';
    } else if (integrityState === 'none') {
      integrityClass = 'badge-pending';
      integrityIcon = 'info';
      integrityText = 'No evidence';
      integrityTitle = 'No evidence image loaded for this case yet.';
    }

    pill.innerHTML = `
      <div class="case-pill-info" ${navAttrs('case-detail', { caseId: caseId })} title="Return to Case Overview">
        <span class="case-pill-id">${icon('folder')} Case #${escapeHtml(caseNum)}</span>
        <span class="case-pill-sep">·</span>
        <span class="case-pill-evidence">Evidence: <strong>${escapeHtml(evidenceLabel)}</strong></span>
      </div>
      <span class="case-pill-sep">·</span>
      <button type="button" class="case-pill-integrity badge ${integrityClass}" id="btn-pill-verify" title="${integrityTitle}">
        ${icon(integrityIcon)} ${escapeHtml(integrityText)}
      </button>
    `;
    pill.classList.remove('hidden');

    const verifyBtn = document.getElementById('btn-pill-verify');
    if (verifyBtn && currentEvidence) {
      verifyBtn.onclick = async (e) => {
        e.stopPropagation();
        e.preventDefault();
        verifyBtn.disabled = true;
        verifyBtn.innerHTML = '<span class="btn-spinner"></span> Verifying…';
        try {
          const res = await API.verifyEvidenceIntegrity(caseId, currentEvidence.evidence_id);
          if (res.match) {
            const shaShort = res.current_sha256 ? res.current_sha256.substring(0, 12) + '…' : '';
            showToast(`Integrity MATCH: Disk image verified against baseline (${shaShort})`, 'success');
          } else {
            showToast('MISMATCH DETECTED: Disk image has been modified since acquisition!', 'error', { duration: 8000 });
          }
          await updateHeaderContext(caseId, currentEvidence.evidence_id);
        } catch (err) {
          showToast('Verification failed: ' + err.message, 'error');
          await updateHeaderContext(caseId, currentEvidence.evidence_id);
        }
      };
    }
  } catch (_) {
    pill.classList.add('hidden');
  }
}

async function openUserProfileModal() {
  let username = 'Examiner';
  let requirePw = false;
  try {
    const st = await API.authStatus();
    username = st.username || st.remembered_username || 'Examiner';
    const prefs = await API.getSecurityPrefs();
    requirePw = !!prefs.require_password_every_time;
  } catch (_) {}

  let hasKey = null;
  try { hasKey = (await API.recoveryKeyStatus()).has_recovery_key; } catch (_) {}

  const bodyHtml = `
    <div class="profile-head">
      <div class="profile-avatar">${escapeHtml((username || 'E')[0].toUpperCase())}</div>
      <div>
        <div class="profile-name">${escapeHtml(username)}</div>
        <div class="profile-sub">Local Installation Profile &middot; Offline Security</div>
      </div>
    </div>

    <div class="profile-section">
      <div class="profile-section-title">${icon('lock')} Security &amp; Login Preferences</div>
      <label class="profile-check">
        <input type="checkbox" id="prof-require-pw" ${requirePw ? 'checked' : ''} />
        <div>
          <div class="profile-check-title">Require password every time I open the application</div>
          <div class="profile-check-sub">
            When disabled (default), your login session is securely remembered on this computer for up to 7 days. When enabled, you must enter your password every time the application starts.
          </div>
        </div>
      </label>
      <div id="prof-pref-status" class="profile-saved hidden">Preference saved.</div>
    </div>

    <div class="profile-section">
      <div class="profile-section-title">${icon('key')} Password recovery key</div>
      <div class="profile-check-sub">
        ${hasKey === false
          ? '<b>You have no recovery key yet.</b> Create one now so a forgotten password can be reset from the sign-in screen.'
          : 'Used on the sign-in screen (<b>Forgot password?</b>) if you forget your password. Creating a new key makes the old one stop working.'}
      </div>
      <div class="profile-key-row">
        <div class="pw-field profile-key-pw">
          <input type="password" id="prof-key-pw" class="form-control" placeholder="Your current password" autocomplete="current-password" />
          <button type="button" class="pw-eye" data-pw-for="prof-key-pw" aria-label="Show password" title="Show password">${icon('eye')}</button>
        </div>
        <button type="button" id="prof-key-btn" class="btn btn-secondary btn-sm">${icon('key')} Create new key</button>
      </div>
      <div id="prof-key-msg" class="profile-check-sub"></div>
      <div id="prof-key-out" class="hidden">
        <div class="recovery-key-box" id="prof-key-value"></div>
        <div class="profile-check-sub">Shown only once. Copy it or write it down and keep it offline.</div>
      </div>
    </div>
  `;

  showModal('Examiner Profile & Security', bodyHtml, [
    {
      label: 'Log Out',
      class: 'btn-danger',
      autoClose: true,
      onClick: async () => {
        try {
          await API.logout();
        } catch (_) {}
        navigateTo('login');
      },
    },
    {
      label: 'Close',
      class: 'btn-secondary',
      autoClose: true,
    },
  ]);

  const chk = document.getElementById('prof-require-pw');
  if (chk) {
    chk.onchange = async (e) => {
      try {
        await API.setSecurityPrefs(e.target.checked);
        const st = document.getElementById('prof-pref-status');
        if (st) {
          st.classList.remove('hidden');
          setTimeout(() => { if (st) st.classList.add('hidden'); }, 2000);
        }
      } catch (err) {
        showToast('Could not update setting: ' + err.message, 'error');
      }
    };
  }

  const modalRoot = document.getElementById('modal-root');
  if (typeof _wireEyes === 'function') _wireEyes(modalRoot);
  const keyBtn = document.getElementById('prof-key-btn');
  if (keyBtn) {
    keyBtn.onclick = async () => {
      const msg = document.getElementById('prof-key-msg');
      const pw = document.getElementById('prof-key-pw');
      if (!pw.value) { msg.textContent = 'Enter your current password first.'; pw.focus(); return; }
      keyBtn.disabled = true;
      msg.textContent = 'Creating…';
      try {
        const r = await API.regenerateRecoveryKey(pw.value);
        pw.value = '';
        document.getElementById('prof-key-value').textContent = r.recovery_key;
        document.getElementById('prof-key-out').classList.remove('hidden');
        msg.textContent = 'New recovery key created. Your previous key no longer works.';
        showToast('New recovery key created', 'success');
      } catch (err) {
        msg.textContent = err.message;
      } finally {
        keyBtn.disabled = false;
      }
    };
  }
}

/**
 * Open Update & Restart Modal
 * Allows examiner to inspect versions and trigger a live in-app update & restart.
 */
async function openUpdateModal() {
  let currentVer = '3.0.0';
  let updateAvail = false;
  let latestVer = '3.0.0';

  try {
    const vRes = await fetch('/api/version');
    if (vRes.ok) {
      const vData = await vRes.json();
      if (vData.version) currentVer = vData.version;
    }
  } catch (_) {}

  try {
    const uRes = await fetch('/api/update/check');
    if (uRes.ok) {
      const uData = await uRes.json();
      updateAvail = !!uData.update_available;
      if (uData.latest) latestVer = uData.latest;
    }
  } catch (_) {}

  const bodyHtml = `
    <div style="display:flex; flex-direction:column; gap:16px;">
      <div style="display:flex; align-items:center; justify-content:space-between; padding:14px 18px; border-radius:12px; background:var(--bg-surface-2); border:1px solid var(--border-color);">
        <div>
          <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.7px; color:var(--text-dim); font-weight:700;">Installed Version</div>
          <div style="font-size:17px; font-weight:800; font-family:var(--font-mono); color:var(--accent-cyan); margin-top:2px;">v${escapeHtml(currentVer)}</div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.7px; color:var(--text-dim); font-weight:700;">Release Status</div>
          <span class="badge ${updateAvail ? 'badge-partial' : 'badge-complete'}" style="margin-top:4px;">
            ${updateAvail ? `Update Available (v${escapeHtml(latestVer)})` : 'Active Build · Ready to Apply'}
          </span>
        </div>
      </div>

      <div style="font-size:13px; color:var(--text-muted); line-height:1.65;">
        <strong style="color:var(--text-main); display:block; margin-bottom:6px;">Latest Engine Highlights (v${escapeHtml(latestVer)}):</strong>
        <ul style="padding-left:18px; margin:0;">
          <li>Multi-vendor H.265 / HEVC stream carving &amp; <code>0x03</code> emulation prevention byte stripping.</li>
          <li>Proprietary storage plugins for Dahua, Hikvision, Hanwha Vision (Samsung), and WFS (Xiongmai).</li>
          <li>Synchronized multi-channel forensic timeline with gap identification &amp; CSV export.</li>
          <li>iPhone frosted liquid glassmorphism UI/UX design (zero blue palette).</li>
        </ul>
      </div>

      <div id="update-action-status" class="hidden" style="padding:12px 14px; border-radius:10px; background:var(--status-complete-soft); border:1px solid var(--border-glow); font-size:13px; color:var(--text-main);">
        <div style="display:flex; align-items:center; gap:10px;">
          <span class="btn-spinner"></span>
          <span id="update-status-msg" style="font-weight:600;">Applying update to latest code...</span>
        </div>
      </div>
    </div>
  `;

  showModal('Update &amp; Restart AEGIS', bodyHtml, [
    {
      label: 'Close',
      class: 'btn-secondary',
      autoClose: true,
    },
    {
      label: 'Restart to Update &rarr;',
      class: 'btn-primary',
      autoClose: false,
      onClick: async () => {
        const statusBox = document.getElementById('update-action-status');
        const statusMsg = document.getElementById('update-status-msg');
        const btn = document.getElementById('modal-btn-1');
        if (btn) btn.disabled = true;
        if (statusBox) statusBox.classList.remove('hidden');

        try {
          await fetch('/api/update/apply', { method: 'POST' }).catch(() => {});
        } catch (_) {}

        if (statusMsg) statusMsg.textContent = 'Restarting AEGIS forensic suite... Reloading app in 2 seconds...';
        setTimeout(() => {
          window.location.reload();
        }, 2200);
      }
    }
  ]);
}

