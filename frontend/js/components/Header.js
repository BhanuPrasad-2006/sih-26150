/**
 * Header component.
 * No NTRO branding — this is the SIH-26150 team tool, not an official NTRO product.
 */
function renderHeader() {
  const root = document.getElementById('header-root');
  root.innerHTML = `
    <div class="logo-area">
      <div class="logo-icon">SIH</div>
      <div class="logo-text">
        <h1>Team [name] — DVR/NVR Forensic Tool</h1>
        <p>SIH26150 — Standardized Acquisition &amp; Carving</p>
      </div>
    </div>
    <div class="header-meta">
      <div class="synthetic-banner-header">⚠️ SYNTHETIC DATA MODE ACTIVE</div>
      <div style="font-size: 13px; color: var(--text-muted); display: flex; align-items: center; gap: 6px;">
        <span style="width: 8px; height: 8px; border-radius: 50%; background: var(--accent-emerald); display: inline-block;"></span>
        Local Server Bound (127.0.0.1)
      </div>
    </div>
  `;
}
