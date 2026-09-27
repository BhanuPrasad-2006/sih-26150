/**
 * FirstRunScreen.js — one-time wizard shown before the password-setup screen:
 *   Step 1: Terms & Conditions (must accept to continue)
 *   Step 2: where to keep case data (a folder on this machine)
 *
 * Runs entirely unauthenticated (no password exists yet at this point). Uses the same
 * auth-screen visual shell as LoginScreen.js. When running as a desktop window (pywebview),
 * "Browse..." opens a real native folder picker via window.pywebview.api.pick_folder(); in a
 * plain browser tab that bridge does not exist, so the field is just a text input instead.
 */

const _FIRST_RUN_TERMS_TEXT = `
This tool (the "SIH26150 DVR/NVR Forensic Analysis Tool") reads a CCTV recorder's disk image or
drive, recovers video from it, and analyses that recovered video, entirely on this computer.

1. Local by design. Evidence images, recovered video and reports are stored in the folder you
   choose on the next step. Nothing is uploaded anywhere by this tool. If you configure it to use
   a remote database (an optional setting, not required), case records are stored there instead
   of the local default — that is your choice to make, not something this tool does on its own.

2. No warranty of forensic or legal outcome. This is a prototype built for the Smart India
   Hackathon. It does not guarantee that recovered evidence is complete, that any report meets a
   particular legal standard, or that it will be accepted by any court or authority. Results
   marked PARTIAL or UNCERTAIN mean exactly that — always corroborate independently and have a
   qualified examiner review the output before relying on it for any real investigation.

3. You are responsible for how you use it. Only use this tool on evidence you are authorised to
   examine. You are responsible for complying with the law that applies to you, including rules
   about handling seized evidence and personal data.

4. No liability. This software is provided "as is", without warranty of any kind. The authors are
   not liable for any loss or damage arising from its use.

5. This is a summary for a hackathon prototype, not a substitute for your organisation's own
   legal review before using this tool on a real case.
`.trim();

function _firstRunTermsStepHtml() {
  return `
    <div class="auth-card">
      <div class="auth-icon">${icon('shield')}</div>
      <div class="auth-title">Before you start</div>
      <div class="auth-subtitle">Please read and accept the terms below.</div>

      <div id="fr-terms-box" class="fr-terms-box">${_FIRST_RUN_TERMS_TEXT}</div>

      <label class="fr-accept-row">
        <input type="checkbox" id="fr-accept-checkbox">
        <span>I have read and accept these terms.</span>
      </label>

      <button type="button" id="fr-continue-btn" class="btn btn-primary btn-lg w-full" disabled>
        Continue ${icon('arrow-right')}
      </button>
    </div>`;
}

function _firstRunFolderStepHtml(defaultDir, hasNativePicker) {
  const browseBtn = hasNativePicker
    ? `<button type="button" id="fr-browse-btn" class="btn btn-secondary fr-browse-btn">Browse&hellip;</button>`
    : '';
  const hint = hasNativePicker
    ? 'Choose any folder on this computer with enough free space for recovered video.'
    : 'Type or paste a folder path on this computer. (The native folder picker is only available when running as the desktop app.)';

  return `
    <div class="auth-card">
      <div class="auth-icon">${icon('folder')}</div>
      <div class="auth-title">Where should case data live?</div>
      <div class="auth-subtitle">${hint}</div>

      <div class="form-group fr-folder-group">
        <label for="fr-case-dir">Data folder</label>
        <div class="fr-folder-row">
          <input type="text" id="fr-case-dir" class="form-control" value="${defaultDir.replace(/"/g, '&quot;')}" autocomplete="off">
          ${browseBtn}
        </div>
      </div>

      <div id="fr-folder-error" class="error-inline hidden">
        ${icon('alert')}
        <span id="fr-folder-error-msg"></span>
      </div>

      <button type="button" id="fr-finish-btn" class="btn btn-primary btn-lg w-full mt-sm">
        Finish Setup ${icon('arrow-right')}
      </button>
    </div>`;
}

async function renderFirstRunScreen(status) {
  const root = document.getElementById('content-root');
  _hideChromeForAuth();

  let step = 'terms';

  function paint() {
    const inner = step === 'terms'
      ? _firstRunTermsStepHtml()
      : _firstRunFolderStepHtml(status.default_case_dir, !!(window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder));

    root.innerHTML = `
      <div class="auth-screen-wrapper">
        ${_brandPanelHtml()}
        <div class="auth-form-panel">${inner}</div>
      </div>`;

    if (step === 'terms') {
      const checkbox = document.getElementById('fr-accept-checkbox');
      const continueBtn = document.getElementById('fr-continue-btn');
      checkbox.onchange = () => { continueBtn.disabled = !checkbox.checked; };
      continueBtn.onclick = () => { step = 'folder'; paint(); };
    } else {
      const browseBtn = document.getElementById('fr-browse-btn');
      const dirInput = document.getElementById('fr-case-dir');
      const finishBtn = document.getElementById('fr-finish-btn');
      const errEl = document.getElementById('fr-folder-error');
      const errMsg = document.getElementById('fr-folder-error-msg');

      if (browseBtn) {
        browseBtn.onclick = async () => {
          try {
            const chosen = await window.pywebview.api.pick_folder();
            if (chosen) dirInput.value = chosen;
          } catch (_) { /* user cancelled, or the bridge isn't available — keep the typed value */ }
        };
      }

      finishBtn.onclick = async () => {
        errEl.style.display = 'none';
        finishBtn.disabled = true;
        try {
          const res = await fetch('/api/setup/first-run-complete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ case_dir: dirInput.value.trim(), accept_terms: true }),
          });
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(body.detail || 'Could not use that folder.');
          }
          // First run is done — hand off to the normal auth flow (setup/login/dashboard).
          const authStatus = await API.authStatus();
          if (!authStatus.password_set) navigateTo('setup');
          else if (!authStatus.authenticated) navigateTo('login');
          else navigateTo('dashboard');
        } catch (err) {
          errMsg.textContent = err.message || 'Could not use that folder.';
          errEl.style.display = 'flex';
          finishBtn.disabled = false;
        }
      };
    }
  }

  paint();
}
