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

function renderSetupScreen() {
  const root = document.getElementById('content-root');
  // Hide sidebar and header nav (not needed before auth)
  const sidebar = document.getElementById('sidebar-root');
  const breadcrumb = document.getElementById('breadcrumb-strip');
  if (sidebar) sidebar.style.display = 'none';
  if (breadcrumb) breadcrumb.style.display = 'none';

  document.getElementById('header-root').innerHTML = `
    <div class="logo-area" style="padding:0 24px;">
      <span style="font-size:22px;">🔬</span>
      <span style="font-weight:700; font-size:16px; margin-left:10px; color:var(--accent-cyan);">DVR/NVR Forensic Analysis Tool</span>
      <span style="font-size:11px; color:var(--text-dim); margin-left:10px;">SIH26150 — NTRO</span>
    </div>`;

  root.innerHTML = `
    <div class="auth-screen-wrapper">
      <div class="auth-card">
        <div class="auth-icon">🔐</div>
        <div class="auth-title">First-Run Setup</div>
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
            <span>⚠️</span>
            <span id="setup-error-msg"></span>
          </div>

          <button type="submit" id="btn-setup" class="btn btn-primary" style="width:100%; margin-top:8px;">
            Set Password &amp; Open Tool ➔
          </button>
        </form>
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
      // Restore layout
      if (sidebar) sidebar.style.display = '';
      if (breadcrumb) breadcrumb.style.display = '';
      navigateTo('dashboard');
    } catch (err) {
      const isAlreadySet = err.message && err.message.toLowerCase().includes('already set');
      if (isAlreadySet) {
        errMsg.innerHTML = 'Password is already set. <a href="javascript:void(0)" onclick="navigateTo(\'login\')" style="color:var(--accent-cyan); text-decoration:underline; font-weight:600; margin-left:6px;">Click here to Login ➔</a>';
      } else {
        errMsg.textContent = err.message || 'Setup failed. Please try again.';
      }
      errEl.style.display = 'flex';
      btnSetup.disabled = false;
      btnSetup.innerHTML = 'Set Password &amp; Open Tool ➔';
    }
  };
}


function renderLoginScreen() {
  const root = document.getElementById('content-root');
  // Hide sidebar and header nav
  const sidebar = document.getElementById('sidebar-root');
  const breadcrumb = document.getElementById('breadcrumb-strip');
  if (sidebar) sidebar.style.display = 'none';
  if (breadcrumb) breadcrumb.style.display = 'none';

  document.getElementById('header-root').innerHTML = `
    <div class="logo-area" style="padding:0 24px;">
      <span style="font-size:22px;">🔬</span>
      <span style="font-weight:700; font-size:16px; margin-left:10px; color:var(--accent-cyan);">DVR/NVR Forensic Analysis Tool</span>
      <span style="font-size:11px; color:var(--text-dim); margin-left:10px;">SIH26150 — NTRO</span>
    </div>`;

  root.innerHTML = `
    <div class="auth-screen-wrapper">
      <div class="auth-card">
        <div class="auth-icon">🔒</div>
        <div class="auth-title">Forensic Tool — Login</div>
        <div class="auth-subtitle">Enter your access password to continue.</div>

        <div id="lockout-banner" style="display:none;" class="error-banner" style="margin-bottom:16px;">
          <div class="error-banner-icon">🚫</div>
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

          <div id="login-error" style="display:none;" class="error-inline">
            <span>⚠️</span>
            <span id="login-error-msg"></span>
          </div>

          <button type="submit" id="btn-login" class="btn btn-primary" style="width:100%; margin-top:8px;">
            Login ➔
          </button>
        </form>
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

  form.onsubmit = async (e) => {
    e.preventDefault();
    errEl.style.display = 'none';

    const pw = document.getElementById('login-password').value;
    if (!pw) {
      errMsg.textContent = 'Password is required.';
      errEl.style.display = 'flex';
      return;
    }

    btnLogin.disabled = true;
    btnLogin.innerHTML = '<span class="btn-spinner"></span> Verifying…';

    try {
      const result = await API.login(pw);

      if (result.locked) {
        _startLockoutCountdown(result.retry_after || 60);
        btnLogin.innerHTML = 'Login ➔';
        return;
      }

      // Restore layout
      if (sidebar) sidebar.style.display = '';
      if (breadcrumb) breadcrumb.style.display = '';
      navigateTo('dashboard');

    } catch (err) {
      // Check if the error is a lockout (429)
      const msg = err.message || '';
      if (msg.includes('locked') || msg.includes('429')) {
        const seconds = parseInt(msg.match(/(\d+) second/)?.[1] || '60', 10);
        _startLockoutCountdown(seconds);
        btnLogin.innerHTML = 'Login ➔';
      } else {
        // Always show the same message regardless of failure reason
        errMsg.textContent = 'Incorrect password.';
        errEl.style.display = 'flex';
        btnLogin.disabled = false;
        btnLogin.innerHTML = 'Login ➔';
      }
      // Clear password field on failure
      document.getElementById('login-password').value = '';
    }
  };
}
