/**
 * LoginScreen.js — Multi-examiner authentication gate.
 *
 * Handles four flows:
 *   1. First-run setup  — no examiner account exists yet. Creates the first account and shows its
 *                         password recovery key once.
 *   2. Normal login     — any existing examiner signs in with their own username and password.
 *   3. Forgot password  — username + recovery key + a new password (fully offline; the key was shown
 *                         once when the account was created and is replaced after every use).
 *   4. Recovery key     — the one-time screen that shows a new key with Copy / Save buttons.
 *
 * Security UX rules enforced here:
 *   • Error messages never distinguish an unknown username from a wrong password or key.
 *   • Lockout: 5 failures for a given username → 60-second countdown banner (per-account).
 *   • Credentials are submitted via fetch (never as a URL query parameter).
 *   • Two-factor is per-examiner: the code field only appears after a correct password reveals
 *     that this particular account needs one (see API.login's totp_required response).
 *   • No inline styles (the CSP is style-src 'self'): visibility is toggled with the .hidden class.
 */

function _hideChromeForAuth() {
  ['sidebar-root', 'breadcrumb-strip', 'header-root'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.classList.add('hidden');
  });
}

function _restoreChromeAfterAuth() {
  ['sidebar-root', 'breadcrumb-strip', 'header-root'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('hidden');
  });
}

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
        <div class="auth-brand-name">AEGIS</div>
        <div class="auth-brand-desc">DVR/NVR Forensic Analysis Tool</div>
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

const _PW_RULES = [
  ['len',   '8+ characters',              (v) => v.length >= 8],
  ['upper', '1 uppercase (A-Z)',          (v) => /[A-Z]/.test(v)],
  ['lower', '1 lowercase (a-z)',          (v) => /[a-z]/.test(v)],
  ['num',   '1 number (0-9)',             (v) => /\d/.test(v)],
  ['sym',   '1 special symbol (!@#$%^&*)', (v) => /[^A-Za-z0-9]/.test(v)],
];

/** A password input with an eye button inside it (show / hide). */
function _pwFieldHtml(id, placeholder, autocomplete) {
  return `
    <div class="pw-field">
      <input type="password" id="${id}" class="form-control" placeholder="${placeholder}" autocomplete="${autocomplete}" required />
      <button type="button" class="pw-eye" data-pw-for="${id}" aria-label="Show password" title="Show password">${icon('eye')}</button>
    </div>`;
}

function _pwRulesHtml(prefix) {
  return `<div class="pw-rules" id="${prefix}-pw-rules">
    ${_PW_RULES.map(([k, label]) => `<div class="pw-rule${k === 'sym' ? ' pw-rule-wide' : ''}" id="${prefix}-rule-${k}">${label}</div>`).join('')}
  </div>`;
}

function _errorBoxHtml(id) {
  return `<div id="${id}" class="error-inline auth-error hidden" role="alert">${_ICON_WARN}<span id="${id}-msg"></span></div>`;
}

/** Wire every eye button inside `scope`: toggles its input between hidden and visible text. */
function _wireEyes(scope) {
  scope.querySelectorAll('.pw-eye').forEach((btn) => {
    btn.addEventListener('click', () => {
      const input = document.getElementById(btn.dataset.pwFor);
      if (!input) return;
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.innerHTML = icon(show ? 'eye-off' : 'eye');
      btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      btn.title = show ? 'Hide password' : 'Show password';
    });
  });
}

function _wireRules(input, prefix) {
  input.addEventListener('input', () => {
    _PW_RULES.forEach(([k, , test]) => {
      const el = document.getElementById(`${prefix}-rule-${k}`);
      const ok = test(input.value);
      el.classList.toggle('ok', ok);   // the ring / tick marker is drawn by CSS (.pw-rule::before)
    });
  });
}

function _errorApi(id) {
  const box = document.getElementById(id);
  const msg = document.getElementById(`${id}-msg`);
  return {
    show(text, html = false) {
      if (html) msg.innerHTML = text; else msg.textContent = text;
      box.classList.remove('hidden');
    },
    hide() { msg.textContent = ''; box.classList.add('hidden'); },
  };
}

/** Same checks as the server, so the examiner gets the reason before a round trip. */
function _passwordProblem(pw, pw2) {
  if (pw.length < 8) return 'Password must be at least 8 characters long.';
  if (!/[A-Z]/.test(pw)) return 'Password must include at least one uppercase letter (A-Z).';
  if (!/[a-z]/.test(pw)) return 'Password must include at least one lowercase letter (a-z).';
  if (!/\d/.test(pw)) return 'Password must include at least one number (0-9).';
  if (!/[^A-Za-z0-9]/.test(pw)) return 'Password must include at least one special character (e.g. ! @ # $ %).';
  if (pw !== pw2) return 'Passwords do not match. Please re-enter both fields.';
  return '';
}

function _authShell(iconSvg, title, subtitle, inner) {
  return `
    <div class="auth-screen-wrapper">
      ${_brandPanelHtml()}
      <div class="auth-form-panel">
        <div class="auth-card">
          <div class="auth-icon">${iconSvg}</div>
          <div class="auth-title">${title}</div>
          <div class="auth-subtitle">${subtitle}</div>
          ${inner}
        </div>
      </div>
    </div>`;
}


// ── Recovery key (shown once) ────────────────────────────────────────────────

/**
 * Show a freshly issued recovery key once. The examiner must tick "I have saved it" before
 * continuing — there is no other way to see this key again (only its hash is stored).
 */
function renderRecoveryKeyScreen(username, key, { title, intro, continueLabel, onContinue }) {
  const root = document.getElementById('content-root');
  _hideChromeForAuth();
  root.innerHTML = _authShell(icon('key'), title, intro, `
    <div class="recovery-key-box" id="recovery-key-value">${escapeHtml(key)}</div>
    <div class="recovery-key-actions">
      <button type="button" class="btn btn-secondary btn-sm" id="btn-copy-key">${icon('file')} Copy</button>
      <button type="button" class="btn btn-secondary btn-sm" id="btn-save-key">${icon('download')} Save as text file</button>
    </div>
    <ul class="recovery-key-notes">
      <li>If you forget your password, choose <b>Forgot password?</b> on the sign-in screen and enter this key.</li>
      <li>Keep it offline and private, like a spare house key. Anyone with it and your username can reset your password.</li>
      <li>Each key works once. After a reset you will be given a new one.</li>
    </ul>
    <label class="check-row"><input type="checkbox" id="chk-saved-key"> <span>I have saved my recovery key somewhere safe</span></label>
    <button type="button" id="btn-key-continue" class="btn btn-primary btn-lg w-full mt-sm" disabled>${continueLabel} ${icon('arrow-right')}</button>
  `);

  document.getElementById('btn-copy-key').onclick = async () => {
    try {
      await navigator.clipboard.writeText(key);
      if (typeof showToast === 'function') showToast('Recovery key copied', 'success');
    } catch (_) {
      if (typeof showToast === 'function') showToast('Could not copy automatically. Please write the key down.', 'error');
    }
  };
  document.getElementById('btn-save-key').onclick = () => {
    const text = `AEGIS / SIH26150 Forensic Tool - password recovery key\n\nUsername:     ${username}\nRecovery key: ${key}\nIssued:       ${new Date().toLocaleString()}\n\nUse it on the sign-in screen (Forgot password?). Each key works once.\n`;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
    a.download = `recovery-key-${username}.txt`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  };
  const chk = document.getElementById('chk-saved-key');
  const btn = document.getElementById('btn-key-continue');
  chk.onchange = () => { btn.disabled = !chk.checked; };
  btn.onclick = onContinue;
}


// ── 1. First-run setup ───────────────────────────────────────────────────────

function renderSetupScreen() {
  const root = document.getElementById('content-root');
  _hideChromeForAuth();

  root.innerHTML = _authShell(_ICON_LOCK_PLUS, 'Create Local Profile',
    'First-run setup for this installation. Your account and evidence remain strictly offline on this computer.', `
    <form id="setup-form" novalidate autocomplete="off">
      <div class="form-group">
        <label for="setup-username">Username</label>
        <input type="text" id="setup-username" class="form-control" placeholder="e.g. examiner1" autocomplete="username" required />
      </div>
      <div class="form-group">
        <label for="setup-password">Password</label>
        ${_pwFieldHtml('setup-password', 'Minimum 8 characters', 'new-password')}
        ${_pwRulesHtml('setup')}
      </div>
      <div class="form-group">
        <label for="setup-confirm">Confirm Password</label>
        ${_pwFieldHtml('setup-confirm', 'Re-enter password', 'new-password')}
      </div>
      ${_errorBoxHtml('setup-error')}
      <button type="submit" id="btn-setup" class="btn btn-primary btn-lg w-full mt-sm">
        Create Profile &amp; Open Tool ${icon('arrow-right')}
      </button>
    </form>`);

  const form      = document.getElementById('setup-form');
  const err       = _errorApi('setup-error');
  const btnSetup  = document.getElementById('btn-setup');
  const pwInput   = document.getElementById('setup-password');
  const pw2Input  = document.getElementById('setup-confirm');
  const userInput = document.getElementById('setup-username');
  _wireEyes(root);
  _wireRules(pwInput, 'setup');

  form.onsubmit = async (e) => {
    e.preventDefault();
    err.hide();
    const username = userInput.value.trim();
    if (!username) { err.show('Please choose a username.'); userInput.focus(); return; }
    if (username.length < 3 || username.length > 32) { err.show('Username must be 3-32 characters long.'); userInput.focus(); return; }
    const problem = _passwordProblem(pwInput.value, pw2Input.value);
    if (problem) { err.show(problem); (problem.includes('match') ? pw2Input : pwInput).focus(); return; }

    btnSetup.disabled = true;
    btnSetup.innerHTML = '<span class="btn-spinner"></span> Setting up…';
    try {
      const res = await API.setupAccount(username, pwInput.value);
      const goIn = () => {
        _restoreChromeAfterAuth();
        navigateTo('dashboard');
        initUpdateBanner();
        if (typeof Toast !== 'undefined' && Toast.success) Toast.success('Profile created. Welcome, ' + username);
      };
      if (res.recovery_key) {
        renderRecoveryKeyScreen(username, res.recovery_key, {
          title: 'Save your recovery key',
          intro: 'This key lets you reset your password if you ever forget it. It is shown only once.',
          continueLabel: 'Open the tool',
          onContinue: goIn,
        });
      } else {
        goIn();
      }
    } catch (ex) {
      if (ex.message && ex.message.toLowerCase().includes('already exists')) {
        err.show('An account already exists. <a href="#" data-nav="login" class="link-cyan">Go to sign in</a>', true);
      } else {
        err.show(ex.message || 'Setup failed. Please try again.');
      }
      btnSetup.disabled = false;
      btnSetup.innerHTML = 'Create Profile &amp; Open Tool ' + icon('arrow-right');
    }
  };
}


// ── 2. Sign in ───────────────────────────────────────────────────────────────

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

  root.innerHTML = _authShell(_ICON_LOCK, 'Welcome back',
    'Sign in to open your cases. Everything you do here is recorded in the audit log.', `
    <div id="lockout-banner" class="error-banner hidden mb-lg">
      <div class="error-banner-icon">${_ICON_BLOCK}</div>
      <div class="error-banner-body">
        <div class="error-banner-title">Login temporarily locked</div>
        <div class="error-banner-msg">Too many failed attempts. Try again in <span id="lockout-countdown">60</span> seconds.</div>
      </div>
    </div>

    <form id="login-form" novalidate autocomplete="off">
      <div class="form-group">
        <label for="login-username">Username</label>
        <input type="text" id="login-username" class="form-control" placeholder="Enter your username"
               autocomplete="username" value="${escapeHtml(rememberedUser)}" required />
      </div>
      <div class="form-group">
        <div class="label-row">
          <label for="login-password">Password</label>
          <a href="#" id="link-forgot" class="auth-link">Forgot password?</a>
        </div>
        ${_pwFieldHtml('login-password', 'Enter your password', 'current-password')}
      </div>

      <label class="check-row${requirePwEveryTime ? ' hidden' : ''}" id="remember-me-group">
        <input type="checkbox" id="login-remember-me" checked />
        <span>Stay signed in for 7 days on this computer</span>
      </label>

      <div class="form-group hidden" id="totp-group">
        <label for="login-totp">Authentication code (or a one-time 2FA recovery code)</label>
        <input type="text" id="login-totp" class="form-control" maxlength="16"
               placeholder="6-digit code, or XXXXX-XXXXX code" autocomplete="one-time-code" />
      </div>

      ${_errorBoxHtml('login-error')}

      <button type="submit" id="btn-login" class="btn btn-primary btn-lg w-full mt-sm">Sign in ${icon('arrow-right')}</button>
    </form>`);

  const form        = document.getElementById('login-form');
  const err         = _errorApi('login-error');
  const btnLogin    = document.getElementById('btn-login');
  const lockoutEl   = document.getElementById('lockout-banner');
  const countdownEl = document.getElementById('lockout-countdown');
  const totpGroup   = document.getElementById('totp-group');
  let lockoutTimer  = null;
  let totpRequired  = false;   // only known AFTER a correct password reveals it (2FA is per-account)
  _wireEyes(root);

  document.getElementById('link-forgot').onclick = (e) => {
    e.preventDefault();
    if (lockoutTimer) clearInterval(lockoutTimer);
    renderRecoverScreen(document.getElementById('login-username').value.trim());
  };

  function startLockoutCountdown(seconds) {
    lockoutEl.classList.remove('hidden');
    err.hide();
    btnLogin.disabled = true;
    let remaining = seconds;
    countdownEl.textContent = remaining;
    if (lockoutTimer) clearInterval(lockoutTimer);
    lockoutTimer = setInterval(() => {
      remaining -= 1;
      countdownEl.textContent = Math.max(0, remaining);
      if (remaining <= 0) {
        clearInterval(lockoutTimer);
        lockoutEl.classList.add('hidden');
        btnLogin.disabled = false;
      }
    }, 1000);
  }

  form.onsubmit = async (e) => {
    e.preventDefault();
    err.hide();
    const username = document.getElementById('login-username').value.trim();
    const pw = document.getElementById('login-password').value;
    if (!username || !pw) { err.show('Username and password are required.'); return; }
    const totpCode = document.getElementById('login-totp').value.trim();
    if (totpRequired && !(/^\d{3}\s?\d{3}$/.test(totpCode) || /^[A-Za-z0-9]{5}-?[A-Za-z0-9]{5}$/.test(totpCode))) {
      err.show('Enter the 6-digit code, or a 2FA recovery code (XXXXX-XXXXX).');
      return;
    }

    btnLogin.disabled = true;
    btnLogin.innerHTML = '<span class="btn-spinner"></span> Verifying…';
    try {
      const rememberMe = document.getElementById('login-remember-me').checked;
      const result = await API.login(username, pw, totpCode, rememberMe);

      if (result.locked) {
        startLockoutCountdown(result.retry_after || 60);
        btnLogin.innerHTML = 'Sign in ' + icon('arrow-right');
        return;
      }
      if (result.totp_required) {
        // Correct username/password; this account has 2FA — reveal the code field and ask again
        // without treating this as a failure or clearing what was typed.
        totpRequired = true;
        totpGroup.classList.remove('hidden');
        err.show('Enter your two-factor authentication code to finish signing in.');
        btnLogin.disabled = false;
        btnLogin.innerHTML = 'Sign in ' + icon('arrow-right');
        document.getElementById('login-totp').focus();
        return;
      }
      _restoreChromeAfterAuth();
      navigateTo('dashboard');
      initUpdateBanner();
    } catch (ex) {
      const msg = ex.message || '';
      if (msg.includes('locked') || msg.includes('429')) {
        startLockoutCountdown(parseInt(msg.match(/(\d+) second/)?.[1] || '60', 10));
        btnLogin.innerHTML = 'Sign in ' + icon('arrow-right');
      } else {
        // Always the same message regardless of which part was wrong
        const failMsg = totpRequired ? 'Incorrect username, password, or authentication code.'
                                     : (msg || 'Incorrect username or password.');
        err.show(failMsg);
        btnLogin.disabled = false;
        btnLogin.innerHTML = 'Sign in ' + icon('arrow-right');
      }
      document.getElementById('login-password').value = '';
    }
  };

  document.getElementById(rememberedUser ? 'login-password' : 'login-username').focus();
}


// ── 3. Forgot password ───────────────────────────────────────────────────────

function renderRecoverScreen(prefillUser = '') {
  const root = document.getElementById('content-root');
  _hideChromeForAuth();

  root.innerHTML = _authShell(icon('key'), 'Reset your password',
    'Enter your username and the recovery key you saved when your account was created, then choose a new password.', `
    <form id="recover-form" novalidate autocomplete="off">
      <div class="form-group">
        <label for="recover-username">Username</label>
        <input type="text" id="recover-username" class="form-control" placeholder="Your username" autocomplete="username"
               value="${escapeHtml(prefillUser)}" required />
      </div>
      <div class="form-group">
        <label for="recover-key">Recovery key</label>
        <input type="text" id="recover-key" class="form-control font-mono" placeholder="XXXXX-XXXXX-XXXXX-XXXXX"
               maxlength="29" autocomplete="off" spellcheck="false" required />
      </div>
      <div class="form-group">
        <label for="recover-password">New password</label>
        ${_pwFieldHtml('recover-password', 'Minimum 8 characters', 'new-password')}
        ${_pwRulesHtml('recover')}
      </div>
      <div class="form-group">
        <label for="recover-confirm">Confirm new password</label>
        ${_pwFieldHtml('recover-confirm', 'Re-enter new password', 'new-password')}
      </div>
      ${_errorBoxHtml('recover-error')}
      <button type="submit" id="btn-recover" class="btn btn-primary btn-lg w-full mt-sm">Reset password ${icon('arrow-right')}</button>
    </form>
    <div class="auth-forgot-note">
      <a href="#" id="link-back-login" class="auth-link">${icon('arrow-left')} Back to sign in</a>
      <p>No recovery key? An administrator of this computer can still set a new password with
      <code>tools/reset_user_password.py</code>. Every reset is recorded in the audit log.</p>
    </div>`);

  const err = _errorApi('recover-error');
  const btn = document.getElementById('btn-recover');
  const pw  = document.getElementById('recover-password');
  const pw2 = document.getElementById('recover-confirm');
  _wireEyes(root);
  _wireRules(pw, 'recover');
  document.getElementById('link-back-login').onclick = (e) => { e.preventDefault(); renderLoginScreen(); };
  document.getElementById(prefillUser ? 'recover-key' : 'recover-username').focus();

  document.getElementById('recover-form').onsubmit = async (e) => {
    e.preventDefault();
    err.hide();
    const username = document.getElementById('recover-username').value.trim();
    const key = document.getElementById('recover-key').value.trim();
    if (!username || !key) { err.show('Enter your username and recovery key.'); return; }
    const problem = _passwordProblem(pw.value, pw2.value);
    if (problem) { err.show(problem); return; }

    btn.disabled = true;
    btn.innerHTML = '<span class="btn-spinner"></span> Checking…';
    try {
      const res = await API.recoverPassword(username, key, pw.value);
      renderRecoveryKeyScreen(username, res.recovery_key, {
        title: 'Password changed',
        intro: 'Your old recovery key no longer works. Save this new one: it is shown only once.',
        continueLabel: 'Go to sign in',
        onContinue: () => renderLoginScreen(),
      });
    } catch (ex) {
      err.show(ex.message || 'Could not reset the password.');
      btn.disabled = false;
      btn.innerHTML = 'Reset password ' + icon('arrow-right');
    }
  };
}
