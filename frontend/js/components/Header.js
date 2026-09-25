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
        <h1>DVR/NVR Forensic Analysis Tool</h1>
        <p>SIH26150 · Recover, verify and report CCTV evidence</p>
      </div>
    </div>
    <div class="header-meta">
      <div class="host-pill" data-tooltip="This tool is served from this machine. Nothing leaves it unless you export."><span class="dot"></span><span class="label">${escapeHtml(hostLabel)}</span></div>
      <button type="button" id="theme-toggle" class="icon-btn" aria-label="Switch light or dark theme" title="Switch light / dark theme">${icon(themeIcon)}</button>
    </div>
  `;
  document.getElementById('theme-toggle').addEventListener('click', () => {
    const next = toggleTheme();
    document.getElementById('theme-toggle').innerHTML = icon(next === 'dark' ? 'sun' : 'moon');
  });

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
