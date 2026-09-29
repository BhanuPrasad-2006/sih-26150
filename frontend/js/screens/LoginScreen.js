/**
 * LoginScreen.js — Multi-examiner authentication gate.
 *
 * Handles two flows:
 *   1. First-run setup  — called when no examiner account exists yet. Creates the first account.
 *   2. Normal login     — called on every subsequent launch or session expiry. Any existing
 *                         examiner signs in with their own username and password.
 *
 * Security UX rules enforced here:
 *   • Error message never distinguishes an unknown username from a wrong password.
 *   • Lockout: 5 failures for a given username → 60-second countdown banner (per-account, not
 *     shared — a lockout on one examiner's account never blocks another's).
 *   • Credentials are submitted via fetch (never as a URL query parameter).
 *   • Two-factor is per-examiner: the code field only appears after a correct password reveals
 *     that this particular account needs one (see API.login's totp_required response).
 *   • Forgotten password: there is no in-app recovery (no email/SMS on an offline tool) — an
 *     examiner locked out of their own account needs someone with terminal access to the machine
 *     to run tools/reset_user_password.py.
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
const _ICON_WARN = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon-block-alert"><path d="M10.3 3.9 1.8 18a1 1 0 0 0 .9 1.5h18.6a1 1 0 0 0 .9-1.5L13.7 3.9a1 1 0 0 0-1.4 0Z"/><path d="M12 9v4M12 17h.01"/></svg>`;
const _ICON_BLOCK = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon-block-circle"><circle cx="12" cy="12" r="9"/><path d="m5.5 5.5 13 13"/></svg>`;
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
          <li>${_ICON_CHECK}<span><b>Every action is logged</b> in a hash-chained, tamper-evident audit trail, attributed to the examiner who did it.</span></li>
          <li>${_ICON_CHECK}<span><b>Locked down by default:</b> named examiner accounts, hashed credentials, per-account lockout after repeated failures.</span></li>
        </ul>
      </div>
    </div>`;
}

// A password rule string shown on both the first-run and "add examiner" forms — kept as one
// constant so the two can never describe different rules.
const _PASSWORD_RULE_TEXT = 'At least 8 characters, with an uppercase letter, a lowercase letter, a digit, and a special character.';

function renderSetupScreen() {
  const root = document.getElementById('content-root');
  _hideChromeForAuth();

  root.innerHTML = `
    <div class="auth-screen-wrapper">
      ${_brandPanelHtml()}
      <div class="auth-form-panel">
      <div class="auth-card">
        <div class="auth-icon">${_ICON_LOCK_PLUS}</div>
        <div class="auth-title">Create Local Profile</div>
        <div class="auth-subtitle">
          First-run setup for this installation. Your account and evidence remain strictly offline on this computer.
        </div>

        <form id="setup-form" novalidate autocomplete="off">
          <div class="form-group">
            <label for="setup-username">Username</label>
            <input
              type="text"
              id="setup-username"
              class="form-control"
              placeholder="e.g. examiner1"
              autocomplete="username"
              required
            />
          </div>
          <div class="form-group">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <label for="setup-password">Password</label>
              <button type="button" id="btn-toggle-setup-pw" style="background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 12px; padding: 0;">Show Password</button>
            </div>
            <input
              type="password"
              id="setup-password"
              class="form-control"
              placeholder="Minimum 8 characters"
              autocomplete="new-password"
              required
            />
            <div class="pw-rules-box" id="setup-pw-rules" style="margin-top: 8px; font-size: 11.5px; display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px; padding: 8px 10px; background: rgba(255,255,255,0.03); border-radius: 6px; border: 1px solid rgba(255,255,255,0.06);">
              <div id="pw-rule-len" style="color: #94a3b8; transition: color 0.15s;">○ 8+ characters</div>
              <div id="pw-rule-upper" style="color: #94a3b8; transition: color 0.15s;">○ 1 uppercase (A-Z)</div>
              <div id="pw-rule-lower" style="color: #94a3b8; transition: color 0.15s;">○ 1 lowercase (a-z)</div>
              <div id="pw-rule-num" style="color: #94a3b8; transition: color 0.15s;">○ 1 number (0-9)</div>
              <div id="pw-rule-sym" style="color: #94a3b8; transition: color 0.15s; grid-column: span 2;">○ 1 special symbol (!@#$%^&*)</div>
            </div>
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

          <div id="setup-error" class="error-inline" style="display: none; margin-bottom: 12px;">
            ${_ICON_WARN}
            <span id="setup-error-msg"></span>
          </div>

          <button type="submit" id="btn-setup" class="btn btn-primary btn-lg w-full mt-sm">
            Create Profile &amp; Open Tool ${icon('arrow-right')}
          </button>
        </form>
      </div>
      </div>
    </div>`;

  const form     = document.getElementById('setup-form');
  const errEl    = document.getElementById('setup-error');
  const errMsg   = document.getElementById('setup-error-msg');
  const btnSetup = document.getElementById('btn-setup');
  const pwInput  = document.getElementById('setup-password');
  const pw2Input = document.getElementById('setup-confirm');
  const userInput = document.getElementById('setup-username');
  const btnTogglePw = document.getElementById('btn-toggle-setup-pw');

  const ruleLen   = document.getElementById('pw-rule-len');
  const ruleUpper = document.getElementById('pw-rule-upper');
  const ruleLower = document.getElementById('pw-rule-lower');
  const ruleNum   = document.getElementById('pw-rule-num');
  const ruleSym   = document.getElementById('pw-rule-sym');

  function updateRule(el, ok, label) {
    if (ok) {
      el.style.color = '#10b981';
      el.textContent = '✔ ' + label;
    } else {
      el.style.color = '#94a3b8';
      el.textContent = '○ ' + label;
    }
  }

  pwInput.addEventListener('input', () => {
    const val = pwInput.value;
    updateRule(ruleLen, val.length >= 8, '8+ characters');
    updateRule(ruleUpper, /[A-Z]/.test(val), '1 uppercase (A-Z)');
    updateRule(ruleLower, /[a-z]/.test(val), '1 lowercase (a-z)');
    updateRule(ruleNum, /\d/.test(val), '1 number (0-9)');
    updateRule(ruleSym, /[^A-Za-z0-9]/.test(val), '1 special symbol (!@#$%^&*)');
  });

  if (btnTogglePw) {
    btnTogglePw.addEventListener('click', () => {
      const isPw = pwInput.type === 'password';
      pwInput.type = isPw ? 'text' : 'password';
      pw2Input.type = isPw ? 'text' : 'password';
      btnTogglePw.textContent = isPw ? 'Hide Password' : 'Show Password';
    });
  }

  function showError(msg) {
    errMsg.textContent = msg;
    errEl.style.display = 'flex';
    if (typeof Toast !== 'undefined' && Toast.error) {
      Toast.error(msg);
    }
  }

  function hideError() {
    errMsg.textContent = '';
    errEl.style.display = 'none';
  }

  form.onsubmit = async (e) => {
    e.preventDefault();
    hideError();

    const username = userInput.value.trim();
    const pw  = pwInput.value;
    const pw2 = pw2Input.value;

    if (!username) {
      showError('Please choose a username.');
      userInput.focus();
      return;
    }
    if (username.length < 3 || username.length > 32) {
      showError('Username must be 3-32 characters long.');
      userInput.focus();
      return;
    }
    if (pw.length < 8) {
      showError('Password must be at least 8 characters long.');
      pwInput.focus();
      return;
    }
    if (!/[A-Z]/.test(pw)) {
      showError('Password must include at least one uppercase letter (A-Z).');
      pwInput.focus();
      return;
    }
    if (!/[a-z]/.test(pw)) {
      showError('Password must include at least one lowercase letter (a-z).');
      pwInput.focus();
      return;
    }
    if (!/\d/.test(pw)) {
      showError('Password must include at least one number (0-9).');
      pwInput.focus();
      return;
    }
    if (!/[^A-Za-z0-9]/.test(pw)) {
      showError('Password must include at least one special character (e.g. ! @ # $ %).');
      pwInput.focus();
      return;
    }
    if (pw !== pw2) {
      showError('Passwords do not match. Please re-enter both fields.');
      pw2Input.focus();
      return;
    }

    btnSetup.disabled = true;
    btnSetup.innerHTML = '<span class="btn-spinner"></span> Setting up…';

    try {
      await API.setupAccount(username, pw);
      if (typeof Toast !== 'undefined' && Toast.success) {
        Toast.success('Profile created successfully! Welcome, ' + username);
      }
      _restoreChromeAfterAuth();
      navigateTo('dashboard');
      initUpdateBanner();
    } catch (err) {
      const isAlreadySet = err.message && err.message.toLowerCase().includes('already exists');
      if (isAlreadySet) {
        errMsg.innerHTML = 'An account already exists. <a href="#" data-nav="login" class="link-cyan">Go to sign in</a>';
        errEl.style.display = 'flex';
        if (typeof Toast !== 'undefined' && Toast.error) {
          Toast.error('An account already exists. Please sign in.');
        }
      } else {
        showError(err.message || 'Setup failed. Please try again.');
      }
      btnSetup.disabled = false;
      btnSetup.innerHTML = 'Create Profile &amp; Open Tool ' + icon('arrow-right');
    }
  };
}


async function renderLoginScreen() {
  const root = document.getElementById('content-root');
  _hideChromeForAuth();

  let rememberedUser = '';
  let requirePwEveryTime = false;
  try {
    const status = await API.authStatus();
    rememberedUser = status.remembered_username || '';
    requirePwEveryTime = !!status.require_password_every_time;
  } catch (_) {}

  function _esc(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  root.innerHTML = `
    <div class="auth-screen-wrapper">
      ${_brandPanelHtml()}
      <div class="auth-form-panel">
      <div class="auth-card">
        <div class="auth-icon">${_ICON_LOCK}</div>
        <div class="auth-title">Welcome back</div>
        <div class="auth-subtitle">Sign in to open your cases. Everything you do here is recorded in the audit log.</div>

        <div id="lockout-banner" class="error-banner hidden mb-lg">
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
            <label for="login-username">Username</label>
            <input
              type="text"
              id="login-username"
              class="form-control"
              placeholder="Enter your username"
              autocomplete="username"
              value="${_esc(rememberedUser)}"
              required
            />
          </div>
          <div class="form-group">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <label for="login-password">Password</label>
              <button type="button" id="btn-toggle-login-pw" style="background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 12px; padding: 0;">Show Password</button>
            </div>
            <input
              type="password"
              id="login-password"
              class="form-control"
              placeholder="Enter your password"
              autocomplete="current-password"
              required
            />
          </div>

          <div class="form-group checkbox-group" id="remember-me-group" style="${requirePwEveryTime ? 'display:none;' : 'margin: 6px 0 14px 0;'}">
            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 0.88rem; color: var(--text-secondary); user-select: none;">
              <input type="checkbox" id="login-remember-me" checked style="cursor: pointer; width: 16px; height: 16px;" />
              <span>Stay signed in for 7 days on this computer</span>
            </label>
          </div>

          <div class="form-group hidden" id="totp-group">
            <label for="login-totp">Authentication code (or a one-time recovery code)</label>
            <input type="text" id="login-totp" class="form-control" maxlength="16"
                   placeholder="6-digit code, or XXXXX-XXXXX recovery code" autocomplete="one-time-code" />
          </div>

          <div id="login-error" class="error-inline" style="display: none; margin-bottom: 12px;">
            ${_ICON_WARN}
            <span id="login-error-msg"></span>
          </div>

          <button type="submit" id="btn-login" class="btn btn-primary btn-lg w-full mt-sm">
            Sign in ${icon('arrow-right')}
          </button>
        </form>

        <div class="auth-forgot-note">
          Forgotten your password? An examiner cannot reset it from this screen — an offline tool
          has nowhere to send a reset email. Whoever has terminal access to this machine can run
          <code>tools/reset_user_password.py</code> to set a new one.
        </div>
      </div>
      </div>
    </div>`;

  const form      = document.getElementById('login-form');
  const errEl     = document.getElementById('login-error');
  const errMsg    = document.getElementById('login-error-msg');
  const btnLogin  = document.getElementById('btn-login');
  const lockoutEl = document.getElementById('lockout-banner');
  const countdownEl = document.getElementById('lockout-countdown');
  const totpGroup = document.getElementById('totp-group');
  let _lockoutTimer = null;
  let totpRequired = false;   // only known AFTER a correct password reveals it (2FA is per-account)

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

    const username = document.getElementById('login-username').value.trim();
    const pw = document.getElementById('login-password').value;
    if (!username || !pw) {
      errMsg.textContent = 'Username and password are required.';
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
      const rememberBox = document.getElementById('login-remember-me');
      const rememberMe = rememberBox ? rememberBox.checked : true;
      const result = await API.login(username, pw, totpCode, rememberMe);

      if (result.locked) {
        _startLockoutCountdown(result.retry_after || 60);
        btnLogin.innerHTML = 'Sign in ' + icon('arrow-right');
        return;
      }

      if (result.totp_required) {
        // Correct username/password; this account has 2FA — reveal the code field and ask
        // again without treating this as a failure or clearing what was typed.
        totpRequired = true;
        totpGroup.style.display = 'block';
        errMsg.textContent = 'Enter your two-factor authentication code to finish signing in.';
        errEl.style.display = 'flex';
        btnLogin.disabled = false;
        btnLogin.innerHTML = 'Sign in ' + icon('arrow-right');
        document.getElementById('login-totp').focus();
        return;
      }

      _restoreChromeAfterAuth();
      navigateTo('dashboard');
      initUpdateBanner();

    } catch (err) {
      // Check if the error is a lockout (429)
      const msg = err.message || '';
      if (msg.includes('locked') || msg.includes('429')) {
        const seconds = parseInt(msg.match(/(\d+) second/)?.[1] || '60', 10);
        _startLockoutCountdown(seconds);
        btnLogin.innerHTML = 'Sign in ' + icon('arrow-right');
      } else {
        // Always show the same message regardless of failure reason
        const failMsg = totpRequired
          ? 'Incorrect username, password, or authentication code.'
          : (err.message || 'Incorrect username or password.');
        errMsg.textContent = failMsg;
        errEl.style.display = 'flex';
        if (typeof Toast !== 'undefined' && Toast.error) {
          Toast.error(failMsg);
        }
        btnLogin.disabled = false;
        btnLogin.innerHTML = 'Sign in ' + icon('arrow-right');
      }
      // Clear password field on failure
      document.getElementById('login-password').value = '';
    }
  };

  const btnToggleLoginPw = document.getElementById('btn-toggle-login-pw');
  if (btnToggleLoginPw) {
    btnToggleLoginPw.addEventListener('click', () => {
      const pwInput = document.getElementById('login-password');
      if (!pwInput) return;
      const isPw = pwInput.type === 'password';
      pwInput.type = isPw ? 'text' : 'password';
      btnToggleLoginPw.textContent = isPw ? 'Hide Password' : 'Show Password';
    });
  }

  if (rememberedUser) {
    const pwInput = document.getElementById('login-password');
    if (pwInput) pwInput.focus();
  } else {
    const userInput = document.getElementById('login-username');
    if (userInput) userInput.focus();
  }
}
