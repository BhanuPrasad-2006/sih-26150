/**
 * UpdateBanner.js — small corner banner shown once logged in, if a newer version is available.
 *
 * initUpdateBanner() is called once after a successful login (see app.js). It checks
 * /api/update/check immediately, then again every 15 minutes for the rest of the session — a
 * long-running desktop app should notice an update without needing a manual refresh.
 */

const UPDATE_CHECK_INTERVAL_MS = 15 * 60 * 1000;
let _updateBannerStarted = false;

function _getOrCreateUpdateBanner() {
  let el = document.getElementById('update-banner');
  if (!el) {
    el = document.createElement('div');
    el.id = 'update-banner';
    el.className = 'update-banner hidden';
    document.body.appendChild(el);
  }
  return el;
}

function _renderUpdateBanner(latestVersion) {
  const el = _getOrCreateUpdateBanner();
  el.className = 'update-banner';
  el.innerHTML = `
    ${icon('refresh')}
    <span>Update available (v${latestVersion}).</span>
    <button type="button" id="update-banner-restart" class="btn btn-primary btn-sm">Restart to update</button>
    <button type="button" id="update-banner-dismiss" class="update-banner-dismiss" aria-label="Dismiss">${icon('x')}</button>
  `;

  document.getElementById('update-banner-dismiss').onclick = () => {
    el.className = 'update-banner hidden';
  };

  document.getElementById('update-banner-restart').onclick = async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = 'Restarting…';
    try {
      const res = await fetch('/api/update/apply', { method: 'POST' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || 'Could not start the update.');
      }
      el.innerHTML = `${icon('refresh')}<span>Updating — this window will close and reopen shortly.</span>`;
    } catch (err) {
      showToast(err.message || 'Could not start the update.', 'error');
      btn.disabled = false;
      btn.textContent = 'Restart to update';
    }
  };
}

async function _checkOnce() {
  try {
    const res = await fetch('/api/update/check');
    if (!res.ok) return;
    const body = await res.json();
    const headerBtn = document.getElementById('btn-restart-update');
    if (headerBtn) {
      if (body.update_available && body.latest) {
        headerBtn.innerHTML = `Restart to Update (v${escapeHtml(body.latest)}) &rarr;`;
      }
    }
    if (body.update_available && body.latest) {
      _renderUpdateBanner(body.latest);
    }
  } catch (_) {
    // Offline, or the check failed — say nothing; this is a courtesy notice, not a critical path.
  }
}

function initUpdateBanner() {
  if (_updateBannerStarted) return;   // called once per authenticated session, not per navigation
  _updateBannerStarted = true;
  _checkOnce();
  setInterval(_checkOnce, UPDATE_CHECK_INTERVAL_MS);
}
