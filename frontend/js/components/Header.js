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

  root.innerHTML = `
    <div class="logo-area">
      <div class="logo-icon">SIH</div>
      <div class="logo-text">
        <h1>DVR/NVR Forensic Analysis Tool</h1>
        <p>SIH26150 — Standardised Acquisition &amp; Carving</p>
      </div>
    </div>
    <div class="header-meta">
      <div style="font-size: 12px; color: var(--text-muted); display: flex; align-items: center; gap: 6px;">
        <span style="width: 7px; height: 7px; border-radius: 50%; background: var(--status-complete); display: inline-block; box-shadow: 0 0 6px var(--status-complete);"></span>
        ${hostLabel}
      </div>
    </div>
  `;

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
    { label: '🏠 Dashboard', screen: 'dashboard', params: {} },
    ...breadcrumbs
  ];

  strip.innerHTML = allCrumbs.map((crumb, idx) => {
    const isLast = idx === allCrumbs.length - 1;
    const sep = idx > 0 ? '<span class="crumb-sep"> / </span>' : '';
    if (isLast) {
      return `${sep}<span class="crumb-current">${crumb.label}</span>`;
    }
    return `${sep}<span class="crumb-link" data-screen="${crumb.screen}" data-params='${JSON.stringify(crumb.params || {})}'>${crumb.label}</span>`;
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
