/**
 * Icon set + illustrations.
 *
 * Everything here is inline SVG built from constant strings, so it satisfies the strict
 * Content-Security-Policy (no images, fonts or scripts from anywhere else) and inherits the colour of
 * the surrounding text (stroke="currentColor"). The strings are fixed in this file, never built from
 * user data, so they are safe to drop straight into an innerHTML template.
 *
 * Usage:  ${icon('shield')}   ${icon('alert', 'icon-lg')}
 */
const ICON_PATHS = {
  dashboard: '<rect x="3" y="3" width="7.5" height="9" rx="2"/><rect x="13.5" y="3" width="7.5" height="5.5" rx="2"/><rect x="13.5" y="12" width="7.5" height="9" rx="2"/><rect x="3" y="15.5" width="7.5" height="5.5" rx="2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  'plus-circle': '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
  folder: '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2.2h7.5A2.5 2.5 0 0 1 21 9.7v7.8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/>',
  'folder-open': '<path d="M3 8.5V7a2 2 0 0 1 2-2h3.6l2 2.2H17a2 2 0 0 1 2 2v1.3"/><path d="M3.4 19.2 5.6 11a2 2 0 0 1 1.9-1.5h12.6a1.5 1.5 0 0 1 1.4 1.9l-1.9 6.9a2 2 0 0 1-1.9 1.5H4.9a1.5 1.5 0 0 1-1.5-1.6z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  video: '<rect x="3" y="6" width="12.5" height="12" rx="2.5"/><path d="m15.5 10.5 5-3v9l-5-3"/>',
  file: '<path d="M14 3H7.5A2.5 2.5 0 0 0 5 5.5v13A2.5 2.5 0 0 0 7.5 21h9a2.5 2.5 0 0 0 2.5-2.5V8z"/><path d="M14 3v5h5"/>',
  'file-text': '<path d="M14 3H7.5A2.5 2.5 0 0 0 5 5.5v13A2.5 2.5 0 0 0 7.5 21h9a2.5 2.5 0 0 0 2.5-2.5V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
  lock: '<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5M12 14.5v2.5"/>',
  unlock: '<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V8a4 4 0 0 1 7.6-1.7"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m10.8 12.2 8.2-8.2M15.5 7.5l2.5 2.5M13 10l2 2"/>',
  shield: '<path d="M12 3 4.5 6v5.5c0 4.6 3.1 8.1 7.5 9.5 4.4-1.4 7.5-4.9 7.5-9.5V6z"/>',
  'shield-check': '<path d="M12 3 4.5 6v5.5c0 4.6 3.1 8.1 7.5 9.5 4.4-1.4 7.5-4.9 7.5-9.5V6z"/><path d="m8.8 12 2.3 2.3 4.2-4.6"/>',
  home: '<path d="m3.5 11 8.5-7 8.5 7"/><path d="M5.5 9.7V19a1.5 1.5 0 0 0 1.5 1.5h10a1.5 1.5 0 0 0 1.5-1.5V9.7"/><path d="M10 20.5v-5.5h4v5.5"/>',
  'chevron-right': '<path d="m9.5 6 6 6-6 6"/>',
  'arrow-right': '<path d="M5 12h14M13 6l6 6-6 6"/>',
  'arrow-left': '<path d="M19 12H5M11 6l-6 6 6 6"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  'check-circle': '<circle cx="12" cy="12" r="9"/><path d="m8 12.2 2.8 2.8 5.2-5.6"/>',
  'x-circle': '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>',
  alert: '<path d="M10.3 4.3 2.7 17.5A2 2 0 0 0 4.4 20.5h15.2a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0z"/><path d="M12 9.5v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4.5 15v2.5A2.5 2.5 0 0 0 7 20h10a2.5 2.5 0 0 0 2.5-2.5V15"/>',
  'upload-cloud': '<path d="M7.5 18.5a4.5 4.5 0 0 1-.6-8.96A5.5 5.5 0 0 1 17.6 8.9 3.8 3.8 0 0 1 17 18.5"/><path d="m12 12.5 0 7M9 15.2l3-3 3 3"/>',
  download: '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4.5 15v2.5A2.5 2.5 0 0 0 7 20h10a2.5 2.5 0 0 0 2.5-2.5V15"/>',
  'hard-drive': '<rect x="3" y="12" width="18" height="8" rx="2.5"/><path d="M5 12l2.2-6.2A2 2 0 0 1 9.1 4.5h5.8a2 2 0 0 1 1.9 1.3L19 12"/><path d="M7 16h.01M11 16h6"/>',
  server: '<rect x="3.5" y="4" width="17" height="7" rx="2.2"/><rect x="3.5" y="13" width="17" height="7" rx="2.2"/><path d="M7 7.5h.01M7 16.5h.01M11 7.5h6M11 16.5h6"/>',
  database: '<ellipse cx="12" cy="6" rx="7.5" ry="3"/><path d="M4.5 6v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6M4.5 12v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2.2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>',
  camera: '<path d="M4.5 8h2.6l1.4-2h7l1.4 2h2.6A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5v-8A1.5 1.5 0 0 1 4.5 8z"/><circle cx="12" cy="13.2" r="3.4"/>',
  user: '<circle cx="12" cy="8.5" r="3.8"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0"/>',
  'scan-face': '<path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2"/><path d="M9 10v1M15 10v1M12 10v3.2h-1M9.2 15.5a4 4 0 0 0 5.6 0"/>',
  box: '<path d="m12 3 8 4.2v9.6L12 21l-8-4.2V7.2z"/><path d="m4 7.2 8 4.3 8-4.3M12 11.5V21"/>',
  activity: '<path d="M3 12h4l2.5-6 4 12 2.5-6H21"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
  refresh: '<path d="M20 11.5A8 8 0 0 0 5.6 7.2L4 9M4 4.5V9h4.5M4 12.5a8 8 0 0 0 14.4 4.3L20 15M20 19.5V15h-4.5"/>',
  play: '<path d="M7.5 5.2v13.6a.8.8 0 0 0 1.2.7l11-6.8a.8.8 0 0 0 0-1.4l-11-6.8a.8.8 0 0 0-1.2.7z"/>',
  rocket: '<path d="M14.5 4.5c2.5-.8 4.6-.6 5 .5.4 1.1-.2 3.2-2 5.5l-4.7 4.7-3.5-3.5z"/><path d="m8.9 11.7-3.4.6-1.6 3.2 3.3-.4M12.3 15.1l-.6 3.4-3.2 1.6.4-3.3"/><circle cx="15.5" cy="8.5" r="1.2"/>',
  package: '<path d="m12 3 8.2 4.3v9.4L12 21l-8.2-4.3V7.3z"/><path d="m3.8 7.3 8.2 4.3 8.2-4.3M12 11.6V21M7.9 5.2l8.2 4.3"/>',
  ruler: '<path d="m3.5 16.5 13-13a1.4 1.4 0 0 1 2 0l2 2a1.4 1.4 0 0 1 0 2l-13 13a1.4 1.4 0 0 1-2 0l-2-2a1.4 1.4 0 0 1 0-2z"/><path d="m7 13 2 2M10 10l1.6 1.6M13 7l2 2"/>',
  fingerprint: '<path d="M6.5 6.8A8 8 0 0 1 12 4.5a8 8 0 0 1 8 8v1.2M4.5 12.5a7.5 7.5 0 0 1 .5-2.6"/><path d="M8.5 20c.7-1.6 1-3.4 1-5.2a2.5 2.5 0 0 1 5 0c0 2-.3 3.6-1.1 5.2M12 12.8v2.2M17 17.5c.6-1.4.9-2.9.9-4.4M4.5 15c0 1.5-.2 3-.7 4.2"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/>',
  logout: '<path d="M14 4.5h3.5A2.5 2.5 0 0 1 20 7v10a2.5 2.5 0 0 1-2.5 2.5H14M10 8l-4 4 4 4M6 12h10"/>',
  layers: '<path d="m12 3.5 9 4.7-9 4.7-9-4.7z"/><path d="m3 12.2 9 4.7 9-4.7M3 16.4l9 4.6 9-4.6"/>',
  target: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1"/>',
  sparkles: '<path d="M12 3.5 13.9 9l5.6 1.9-5.6 1.9L12 18.5l-1.9-5.7L4.5 10.9 10.1 9z"/><path d="M19 3v3M17.5 4.5h3"/>',
};

function icon(name, cls) {
  const body = ICON_PATHS[name];
  if (!body) return '';
  return `<svg class="icon${cls ? ' ' + cls : ''}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${body}</svg>`;
}

/** Rounded tile that holds an icon (used in cards and stat tiles). */
function iconChip(name, tone) {
  return `<span class="icon-chip${tone ? ' ' + tone : ''}">${icon(name)}</span>`;
}

/** Brand mark: a shield with a lens/play glyph, on a blue gradient tile. */
function logoMark() {
  return `<svg class="logo-icon" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
    <defs><linearGradient id="lm-g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#2563eb"/></linearGradient></defs>
    <rect width="48" height="48" rx="13" fill="url(#lm-g)"/>
    <path d="M24 9.5 12.5 14v9.2c0 7 4.6 12.2 11.5 14.8 6.9-2.6 11.5-7.8 11.5-14.8V14z" fill="rgba(255,255,255,0.18)" stroke="#fff" stroke-width="2" stroke-linejoin="round"/>
    <circle cx="24" cy="24" r="6" fill="none" stroke="#fff" stroke-width="2"/>
    <path d="M22.6 21.8v4.4l3.9-2.2z" fill="#fff"/>
  </svg>`;
}

/** Dashboard hero illustration: a recorder, a disk and a magnifier. */
function heroArt() {
  return `<svg viewBox="0 0 340 250" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id="ha-a" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7dd3fc"/><stop offset="1" stop-color="#3b82f6"/></linearGradient>
      <linearGradient id="ha-b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff" stop-opacity="0.22"/><stop offset="1" stop-color="#ffffff" stop-opacity="0.06"/></linearGradient>
    </defs>
    <ellipse cx="170" cy="222" rx="130" ry="14" fill="#000" opacity="0.18"/>
    <rect x="34" y="70" width="200" height="106" rx="16" fill="url(#ha-b)" stroke="#bfdbfe" stroke-opacity="0.6" stroke-width="1.6"/>
    <rect x="50" y="86" width="168" height="18" rx="6" fill="#0b1b33" opacity="0.55"/>
    <circle cx="62" cy="95" r="3.5" fill="#34d399"/><circle cx="76" cy="95" r="3.5" fill="#fbbf24"/>
    <rect x="130" y="91" width="76" height="8" rx="4" fill="#93c5fd" opacity="0.7"/>
    <rect x="50" y="116" width="168" height="10" rx="5" fill="#fff" opacity="0.16"/>
    <rect x="50" y="134" width="168" height="10" rx="5" fill="#fff" opacity="0.16"/>
    <rect x="50" y="152" width="110" height="10" rx="5" fill="#fff" opacity="0.16"/>
    <path d="M236 124h26" stroke="#93c5fd" stroke-width="2.4" stroke-dasharray="4 5" stroke-linecap="round"/>
    <g transform="translate(262 82)">
      <rect width="56" height="88" rx="12" fill="#0f2c5c" stroke="#7dd3fc" stroke-width="1.6"/>
      <circle cx="28" cy="34" r="17" fill="none" stroke="url(#ha-a)" stroke-width="3"/>
      <circle cx="28" cy="34" r="6" fill="url(#ha-a)"/>
      <rect x="12" y="62" width="32" height="6" rx="3" fill="#7dd3fc" opacity="0.7"/>
      <rect x="12" y="73" width="20" height="4" rx="2" fill="#7dd3fc" opacity="0.4"/>
    </g>
    <g transform="translate(92 138)">
      <circle cx="44" cy="44" r="34" fill="#0b1b33" opacity="0.72" stroke="url(#ha-a)" stroke-width="5"/>
      <path d="M32 44a12 12 0 0 1 24 0" fill="none" stroke="#7dd3fc" stroke-width="3" stroke-linecap="round"/>
      <path d="M38 47l5 5 10-11" fill="none" stroke="#34d399" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="m70 70 22 22" stroke="url(#ha-a)" stroke-width="9" stroke-linecap="round"/>
    </g>
    <circle cx="40" cy="38" r="4" fill="#7dd3fc" opacity="0.7"/><circle cx="300" cy="44" r="3" fill="#fff" opacity="0.5"/><circle cx="286" cy="200" r="5" fill="#93c5fd" opacity="0.5"/>
  </svg>`;
}

/** Login panel illustration: shield + chain of custody blocks. */
function authArt() {
  return `<svg viewBox="0 0 300 190" aria-hidden="true" focusable="false">
    <defs><linearGradient id="aa-a" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7dd3fc"/><stop offset="1" stop-color="#3b82f6"/></linearGradient></defs>
    <g stroke="#7dd3fc" stroke-opacity="0.55" stroke-width="2" stroke-dasharray="3 5" fill="none"><path d="M60 150h60M180 150h60"/></g>
    <rect x="16" y="128" width="50" height="44" rx="10" fill="#fff" fill-opacity="0.1" stroke="#93c5fd" stroke-opacity="0.7" stroke-width="1.6"/>
    <rect x="234" y="128" width="50" height="44" rx="10" fill="#fff" fill-opacity="0.1" stroke="#93c5fd" stroke-opacity="0.7" stroke-width="1.6"/>
    <rect x="125" y="128" width="50" height="44" rx="10" fill="#fff" fill-opacity="0.1" stroke="#93c5fd" stroke-opacity="0.7" stroke-width="1.6"/>
    <path d="M28 150h26M28 158h16M246 150h26M246 158h16M137 150h26M137 158h16" stroke="#bfdbfe" stroke-width="2.4" stroke-linecap="round" opacity="0.8"/>
    <path d="M150 12 96 34v40c0 32 22 56 54 66 32-10 54-34 54-66V34z" fill="url(#aa-a)" fill-opacity="0.25" stroke="url(#aa-a)" stroke-width="3.5" stroke-linejoin="round"/>
    <path d="M150 30 112 45v28c0 22 15 39 38 47 23-8 38-25 38-47V45z" fill="#0b1b33" fill-opacity="0.55" stroke="#bfdbfe" stroke-opacity="0.6" stroke-width="1.5"/>
    <rect x="133" y="66" width="34" height="26" rx="6" fill="none" stroke="#e0f2fe" stroke-width="3"/>
    <path d="M139 66v-6a11 11 0 0 1 22 0v6" fill="none" stroke="#e0f2fe" stroke-width="3" stroke-linecap="round"/>
    <circle cx="150" cy="79" r="3.4" fill="#e0f2fe"/>
  </svg>`;
}

/** Empty-state illustration (a soft folder with a spark), tinted by the theme. */
function emptyArt() {
  return `<svg class="empty-state-art" viewBox="0 0 150 120" aria-hidden="true" focusable="false">
    <ellipse cx="75" cy="104" rx="52" ry="7" fill="currentColor" opacity="0.08"/>
    <path d="M18 34a8 8 0 0 1 8-8h27l9 10h42a8 8 0 0 1 8 8v46a8 8 0 0 1-8 8H26a8 8 0 0 1-8-8z" fill="var(--primary-soft)" stroke="var(--accent-cyan)" stroke-width="2.4" stroke-linejoin="round"/>
    <rect x="30" y="54" width="90" height="34" rx="6" fill="var(--bg-elevated)" stroke="var(--accent-cyan)" stroke-opacity="0.45" stroke-width="1.6"/>
    <path d="M40 66h44M40 76h28" stroke="var(--accent-cyan)" stroke-opacity="0.5" stroke-width="3" stroke-linecap="round"/>
    <path d="m118 24 2.6 6.4 6.4 2.6-6.4 2.6-2.6 6.4-2.6-6.4-6.4-2.6 6.4-2.6z" fill="var(--accent-cyan)" opacity="0.85"/>
    <circle cx="26" cy="20" r="3" fill="var(--accent-cyan)" opacity="0.35"/>
  </svg>`;
}

/** Dropzone illustration (cloud + arrow). */
function dropArt() {
  return `<svg class="dropzone-art" viewBox="0 0 92 70" aria-hidden="true" focusable="false">
    <path d="M24 56a15 15 0 0 1-2-29.8A20 20 0 0 1 60.5 22 15.5 15.5 0 0 1 64 56z" fill="var(--primary-soft)" stroke="var(--accent-cyan)" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M44 50V30M36 37l8-8 8 8" fill="none" stroke="var(--accent-cyan)" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}

/** Theme toggle: light/dark. Choice is kept only in this browser (localStorage, guarded). */
function currentTheme() {
  const attr = document.documentElement.getAttribute('data-theme');
  if (attr === 'light' || attr === 'dark') return attr;
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
function applySavedTheme() {
  try {
    const t = localStorage.getItem('sih-theme');
    if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
  } catch (e) { /* storage blocked: follow the system setting */ }
}
function toggleTheme() {
  const next = currentTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('sih-theme', next); } catch (e) { /* ignore */ }
  return next;
}
applySavedTheme();
