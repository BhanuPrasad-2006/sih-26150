/**
 * LoginScreen.js — Single-examiner authentication gate.
 *
 * Handles two flows:
 *   1. First-run setup  — called when no password has been set yet.
 *   2. Normal login     — called on every subsequent launch or session expiry.
 *
 * Security UX rules enforced here:
 *   • Error message is always "Incorrect password." — no hint about account existence.
 *   • Lockout: 5 failures → 60-second countdown banner.  No retry until lockout expires.
 *   • Password is submitted via fetch (never as a URL query parameter).
 *   • The UI intentionally provides no "username" field — single examiner tool.
 */

function _hideChromeForAuth() {
  const sidebar = document.getElementById('sidebar-root');
  const breadcrumb = document.getElementById('breadcrumb-strip');
  const header = document.getElementById('header-root');
  if (sidebar) sidebar.style.display = 'none';
  if (breadcrumb) breadcrumb.style.display = 'none';
  if (header) header.style.display = 'none';
}

function _restoreChromeAfterAuth() {
  const sidebar = document.getElementById('sidebar-root');
  const breadcrumb = document.getElementById('breadcrumb-strip');
  const header = document.getElementById('header-root');
  if (sidebar) sidebar.style.display = '';
  if (breadcrumb) breadcrumb.style.display = '';
  if (header) header.style.display = '';
}

const _ICON_SHIELD = `<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 4 5v6c0 5 3.4 9 8 11 4.6-2 8-6 8-11V5l-8-3z"/><path d="m9 12 2 2 4-4"/></svg>`;
const _ICON_LOCK = `<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>`;
const _ICON_LOCK_PLUS = `<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/><path d="M12 14v4M10 16h4"/></svg>`;
const _ICON_WARN = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px;flex:none;"><path d="M10.3 3.9 1.8 18a1 1 0 0 0 .9 1.5h18.6a1 1 0 0 0 .9-1.5L13.7 3.9a1 1 0 0 0-1.4 0Z"/><path d="M12 9v4M12 17h.01"/></svg>`;
const _ICON_BLOCK = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px;flex:none;"><circle cx="12" cy="12" r="9"/><path d="m5.5 5.5 13 13"/></svg>`;
const _ICON_CHECK = `<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m20 6-11 11-5-5"/></svg>`;

function _brandPanelHtml() {
  return `
    <div class="auth-brand-panel">
      <div class="auth-brand-mesh"></div>
      <div class="auth-brand-content">
        <div class="auth-brand-badge">${logoMark()}</div>
        <div class="auth-brand-name">DVR/NVR Forensic<br>Analysis Tool</div>
        <div class="auth-brand-tag">SIH26150 &middot; NTRO</div>
        <div class="auth-brand-art">${authArt()}</div>
        <ul class="auth-feature-list">
          <li>${_ICON_CHECK}<span><b>Evidence is only ever read.</b> The source disk image is never modified.</span></li>
          <li>${_ICON_CHECK}<span><b>Every action is logged</b> in a hash-chained, tamper-evident audit trail.</span></li>
          <li>${_ICON_CHECK}<span><b>Locked down by default:</b> single-examiner access, hashed credentials, lockout after repeated failures.</span></li>
        </ul>
      </div>
    </div>`;
}

function renderSetupScreen() {
  const root = document.getElementById('content-root');
  _hideChromeForAuth();

  root.innerHTML = `
    <div class="auth-screen-wrapper">
      ${_brandPanelHtml()}
      <div class="auth-form-panel">
      <div class="auth-card">
        <div class="auth-icon">${_ICON_LOCK_PLUS}</div>
        <div class="auth-title">Set up your workspace</div>
        <div class="auth-subtitle">
          Create a password to protect access to this forensic tool.<br>
          <strong>Minimum 12 characters.</strong> The password will be stored only as a bcrypt hash.
        </div>

        <form id="setup-form" novalidate autocomplete="off">
          <div class="form-group">
            <label for="setup-password">Access Password</label>
            <input
              type="password"
              id="setup-password"
              class="form-control"
              placeholder="Minimum 12 characters"
              autocomplete="new-password"
              required
            />
          </div>
          <div class="form-group">
            <label for="setup-confirm">Confirm Password</label>
            <input
              type="password"
              id="setup-confirm"
              class="form-control"
              placeholder="Re-enter password"
              autocomplete="new-password"
              required
            />
          </div>

          <div id="setup-error" style="display:none;" class="error-inline">
            ${_ICON_WARN}
            <span id="setup-error-msg"></span>
          </div>

          <button type="submit" id="btn-setup" class="btn btn-primary btn-lg" style="width:100%; margin-top:8px;">
            Set Password &amp; Open Tool ${icon('arrow-right')}
          </button>
        </form>
      </div>
      </div>
    </div>`;

  const form    = document.getElementById('setup-form');
  const errEl   = document.getElementById('setup-error');
  const errMsg  = document.getElementById('setup-error-msg');
  const btnSetup = document.getElementById('btn-setup');

  form.onsubmit = async (e) => {
    e.preventDefault();
    errEl.style.display = 'none';

    const pw  = document.getElementById('setup-password').value;
    const pw2 = document.getElementById('setup-confirm').value;

    if (pw.length < 12) {
      errMsg.textContent = 'Password must be at least 12 characters long.';
      errEl.style.display = 'flex';
      return;
    }
    if (pw !== pw2) {
      errMsg.textContent = 'Passwords do not match. Please re-enter both fields.';
      errEl.style.display = 'flex';
      return;
    }

    btnSetup.disabled = true;
    btnSetup.innerHTML = '<span class="btn-spinner"></span> Setting up…';

    try {
      await API.setupPassword(pw);
      _restoreChromeAfterAuth();
      navigateTo('dashboard');
    } catch (err) {
      const isAlreadySet = err.message && err.message.toLowerCase().includes('already set');
      if (isAlreadySet) {
        errMsg.innerHTML = 'Password is already set. <a href="#" data-nav="login" style="color:var(--accent-cyan); text-decoration:underline; font-weight:600; margin-left:6px;">Go to sign in</a>';
      } else {
        errMsg.textContent = err.message || 'Setup failed. Please try again.';
      }
      errEl.style.display = 'flex';
      btnSetup.disabled = false;
      btnSetup.innerHTML = 'Set Password &amp; Open Tool ' + icon('arrow-right');
    }
  };
}


function renderLoginScreen() {
  const root = document.getElementById('content-root');
  _hideChromeForAuth();

  root.innerHTML = `
    <div class="auth-screen-wrapper">
      ${_brandPanelHtml()}
      <div class="auth-form-panel">
      <div class="auth-card">
        <div class="auth-icon">${_ICON_LOCK}</div>
        <div class="auth-title">Welcome back</div>
        <div class="auth-subtitle">Sign in to open your cases. Everything you do here is recorded in the audit log.</div>

        <div id="lockout-banner" style="display:none; margin-bottom:16px;" class="error-banner">
          <div class="error-banner-icon">${_ICON_BLOCK}</div>
          <div class="error-banner-body">
            <div class="error-banner-title">Login temporarily locked</div>
            <div class="error-banner-msg">
              Too many failed attempts. Try again in <span id="lockout-countdown">60</span> seconds.
            </div>
          </div>
        </div>

        <form id="login-form" novalidate autocomplete="off">
          <div class="form-group">
            <label for="login-password">Access Password</label>
            <input
              type="password"
              id="login-password"
              class="form-control"
              placeholder="Enter your password"
              autocomplete="current-password"
              required
            />
          </div>

          <div class="form-group" id="totp-group" style="display:none;">
            <label for="login-totp">Authentication code (or a one-time recovery code)</label>
            <input type="text" id="login-totp" class="form-control" maxlength="16"
                   placeholder="6-digit code, or XXXXX-XXXXX recovery code" autocomplete="one-time-code" />
          </div>

          <div id="login-error" style="display:none;" class="error-inline">
            ${_ICON_WARN}
            <span id="login-error-msg"></span>
          </div>

          <button type="submit" id="btn-login" class="btn btn-primary btn-lg" style="width:100%; margin-top:8px;">
            Sign in ${icon('arrow-right')}
          </button>
        </form>
      </div>
      </div>
    </div>`;

  const form      = document.getElementById('login-form');
  const errEl     = document.getElementById('login-error');
  const errMsg    = document.getElementById('login-error-msg');
  const btnLogin  = document.getElementById('btn-login');
  const lockoutEl = document.getElementById('lockout-banner');
  const countdownEl = document.getElementById('lockout-countdown');
  let _lockoutTimer = null;

  function _startLockoutCountdown(seconds) {
    lockoutEl.style.display = 'flex';
    errEl.style.display = 'none';
    btnLogin.disabled = true;
    let remaining = seconds;
    countdownEl.textContent = remaining;

    if (_lockoutTimer) clearInterval(_lockoutTimer);
    _lockoutTimer = setInterval(() => {
      remaining -= 1;
      countdownEl.textContent = Math.max(0, remaining);
      if (remaining <= 0) {
        clearInterval(_lockoutTimer);
        lockoutEl.style.display = 'none';
        btnLogin.disabled = false;
      }
    }, 1000);
  }

  // Show the code field only when two-factor authentication is switched on.
  let totpRequired = false;
  API.authStatus().then((st) => {
    totpRequired = !!st.totp_enabled;
    if (totpRequired) document.getElementById('totp-group').style.display = 'block';
  }).catch(() => {});

  form.onsubmit = async (e) => {
    e.preventDefault();
    errEl.style.display = 'none';

    const pw = document.getElementById('login-password').value;
    if (!pw) {
      errMsg.textContent = 'Password is required.';
      errEl.style.display = 'flex';
      return;
    }
    const totpCode = document.getElementById('login-totp').value.trim();
    if (totpRequired && !(/^\d{3}\s?\d{3}$/.test(totpCode) || /^[A-Za-z0-9]{5}-?[A-Za-z0-9]{5}$/.test(totpCode))) {
      errMsg.textContent = 'Enter the 6-digit code, or a recovery code (XXXXX-XXXXX).';
      errEl.style.display = 'flex';
      return;
    }

    btnLogin.disabled = true;
    btnLogin.innerHTML = '<span class="btn-spinner"></span> Verifying…';

    try {
      const result = await API.login(pw, totpCode);

      if (result.locked) {
        _startLockoutCountdown(result.retry_after || 60);
        btnLogin.innerHTML = 'Sign in ' + icon('arrow-right');
        return;
      }

      _restoreChromeAfterAuth();
      navigateTo('dashboard');

    } catch (err) {
      // Check if the error is a lockout (429)
      const msg = err.message || '';
      if (msg.includes('locked') || msg.includes('429')) {
        const seconds = parseInt(msg.match(/(\d+) second/)?.[1] || '60', 10);
        _startLockoutCountdown(seconds);
        btnLogin.innerHTML = 'Sign in ' + icon('arrow-right');
      } else {
        // Always show the same message regardless of failure reason
        errMsg.textContent = totpRequired ? 'Incorrect password or authentication code.' : 'Incorrect password.';
        errEl.style.display = 'flex';
        btnLogin.disabled = false;
        btnLogin.innerHTML = 'Sign in ' + icon('arrow-right');
      }
      // Clear password field on failure
      document.getElementById('login-password').value = '';
    }
  };
}
