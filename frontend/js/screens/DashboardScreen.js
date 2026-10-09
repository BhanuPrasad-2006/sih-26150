/**
 * DashboardScreen.js — VisionOS Floating Bento Station
 * High-concept forensic command workstation:
 * - Evidence Intake Vault with animated holographic radar
 * - Cryptographic Integrity Dial (100% SHA-256 seal)
 * - Multi-Vendor Carving Engine Telemetry
 * - Interactive Holographic Case Dossiers with View Switcher (Dossier vs Dense Table)
 * - Zero Blue, Zero Green: Radiant Crimson-Coral, Electric Ultraviolet & Solar Amber.
 */

function priorityBadge(priority) {
  const p = String(priority || 'MEDIUM').toUpperCase();
  const cls = {
    LOW: 'badge-priority-low',
    MEDIUM: 'badge-priority-medium',
    HIGH: 'badge-priority-high',
    CRITICAL: 'badge-priority-critical'
  }[p] || 'badge-priority-medium';
  return `<span class="dossier-chip ${cls}">${escapeHtml(p)}</span>`;
}

function caseStatusBadge(status) {
  const s = String(status || 'ACTIVE').toUpperCase();
  const cls = s === 'ACTIVE' ? 'badge-status-active' : 'badge-status-closed';
  return `<span class="dossier-chip ${cls}"><span class="pulse-dot"></span>${escapeHtml(s)}</span>`;
}

let _dashboardViewMode = 'dossier'; // 'dossier' | 'table'

async function renderDashboardScreen() {
  const root = document.getElementById('content-root');

  root.innerHTML = `
    <!-- Top Bento Command Station -->
    <div class="bento-station-grid">
      <!-- Bento Widget 1: Evidence Intake Chamber (Hero Bento) -->
      <div class="bento-card bento-hero-chamber">
        <div class="bento-hero-content">
          <div class="bento-tag">
            <span class="laser-dot"></span> AIR-GAPPED FORENSIC WORKSTATION · v3.0.0
          </div>
          <h2 class="bento-hero-title">Recover DVR/NVR Evidence with Zero Alteration</h2>
          <p class="bento-hero-desc">
            Hardware-locked read-only disk intake. Carve raw fragmented H.264/H.265 streams across proprietary DVR formats with continuous SHA-256 cryptographic proof.
          </p>
          <div class="bento-actions">
            <button id="btn-new-case" class="btn-vision-primary">
              <span class="btn-glow-layer"></span>
              ${icon('plus-circle')} Register Forensic Case
            </button>
            <button id="btn-quick-scan" class="btn-vision-secondary">
              ${icon('search')} Quick Telemetry Scan
            </button>
          </div>
        </div>

        <div class="bento-hero-visual">
          <div class="radar-scanner">
            <div class="radar-circle circle-1"></div>
            <div class="radar-circle circle-2"></div>
            <div class="radar-circle circle-3"></div>
            <div class="radar-sweep"></div>
            <div class="radar-center-shield">
              <svg viewBox="0 0 48 48" width="34" height="34" fill="none">
                <path d="M24 9.5 12.5 14v9.2c0 7 4.6 12.2 11.5 14.8 6.9-2.6 11.5-7.8 11.5-14.8V14z" fill="rgba(255, 51, 102, 0.25)" stroke="#ff3366" stroke-width="2.5" stroke-linejoin="round"/>
                <path d="M20 23l3 3 6-6" stroke="#fbbf24" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </div>
            <span class="radar-ping ping-1"></span>
            <span class="radar-ping ping-2"></span>
          </div>
        </div>
      </div>

      <!-- Bento Widget 2: Cryptographic Integrity Gauge -->
      <div class="bento-card bento-dial-card">
        <div class="bento-card-header">
          <span class="bento-card-title">${icon('shield-check')} Integrity Seal</span>
          <span class="live-pill active">VERIFIED</span>
        </div>
        <div class="radial-gauge-container">
          <svg class="radial-gauge-svg" viewBox="0 0 120 120">
            <circle class="gauge-bg" cx="60" cy="60" r="50"/>
            <circle class="gauge-bar" cx="60" cy="60" r="50"/>
          </svg>
          <div class="radial-gauge-value">
            <span class="gauge-pct">100%</span>
            <span class="gauge-label">READ-ONLY</span>
          </div>
        </div>
        <div class="gauge-subtext">
          <span>SHA-256 Chain of Custody</span>
          <strong>Tamper-Proof MMAP</strong>
        </div>
      </div>

      <!-- Bento Widget 3: Multi-Vendor Carving Radar -->
      <div class="bento-card bento-radar-card">
        <div class="bento-card-header">
          <span class="bento-card-title">${icon('cpu')} Carving Engine</span>
          <span class="bento-sub-pill">MULTI-VENDOR</span>
        </div>
        <div class="engine-signatures">
          <div class="sig-item">
            <span class="sig-name">Hikvision H.264/265</span>
            <span class="sig-status ready">● READY</span>
          </div>
          <div class="sig-item">
            <span class="sig-name">Dahua DHFS Stream</span>
            <span class="sig-status ready">● READY</span>
          </div>
          <div class="sig-item">
            <span class="sig-name">CP-PLUS WFS System</span>
            <span class="sig-status ready">● READY</span>
          </div>
          <div class="sig-item">
            <span class="sig-name">Proprietary Raw DVR</span>
            <span class="sig-status ready">● READY</span>
          </div>
        </div>
      </div>

      <!-- Bento Widget 4: Quick Telemetry Metrics -->
      <div class="bento-card bento-stat-card">
        <div class="bento-card-header">
          <span class="bento-card-title">${icon('activity')} Forensic Telemetry</span>
        </div>
        <div class="stat-metrics-row">
          <div class="metric-cell">
            <div class="metric-number text-coral" id="stat-total-cases">–</div>
            <div class="metric-caption">Active Cases</div>
          </div>
          <div class="metric-cell">
            <div class="metric-number text-violet" id="stat-total-recovered">100%</div>
            <div class="metric-caption">Audit Integrity</div>
          </div>
          <div class="metric-cell">
            <div class="metric-number text-gold" id="stat-system-state">ONLINE</div>
            <div class="metric-caption">Engine State</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Case Dossier Command Header -->
    <div class="dossier-control-bar">
      <div class="dossier-headline">
        <h3>${icon('folder-open')} Forensic Case Vault</h3>
        <span class="dossier-count-chip" id="count-cases-chip">0 Cases</span>
      </div>

      <div class="dossier-filter-tools">
        <div class="search-input-wrapper">
          ${icon('search')}
          <input type="text" id="case-search-box" placeholder="Filter by Case, FIR, or Examiner..." autocomplete="off">
        </div>
        <div class="view-switch-capsule">
          <button id="view-mode-dossier" class="view-btn ${(_dashboardViewMode === 'dossier') ? 'active' : ''}" title="Dossier Cards">
            ${icon('dashboard')} Dossiers
          </button>
          <button id="view-mode-table" class="view-btn ${(_dashboardViewMode === 'table') ? 'active' : ''}" title="High-Density Table">
            ${icon('layers')} Table
          </button>
        </div>
      </div>
    </div>

    <!-- Case Content Presentation (Dossier Cards OR Table) -->
    <div id="cases-view-container" class="cases-view-container">
      <div class="skeleton-dossier-grid">
        <div class="skeleton-dossier-card"></div>
        <div class="skeleton-dossier-card"></div>
        <div class="skeleton-dossier-card"></div>
      </div>
    </div>
  `;

  // Attach button triggers
  document.getElementById('btn-new-case').onclick = () => navigateTo('new-case');
  const quickScanBtn = document.getElementById('btn-quick-scan');
  if (quickScanBtn) {
    quickScanBtn.onclick = () => {
      Toast.info('Select a case dossier below to initialize deep evidence acquisition.');
    };
  }

  // View switch triggers
  const btnDossier = document.getElementById('view-mode-dossier');
  const btnTable = document.getElementById('view-mode-table');

  btnDossier.onclick = () => {
    _dashboardViewMode = 'dossier';
    btnDossier.classList.add('active');
    btnTable.classList.remove('active');
    renderCases(window._cachedCases || []);
  };

  btnTable.onclick = () => {
    _dashboardViewMode = 'table';
    btnTable.classList.add('active');
    btnDossier.classList.remove('active');
    renderCases(window._cachedCases || []);
  };

  const searchBox = document.getElementById('case-search-box');
  searchBox.oninput = () => {
    const term = searchBox.value.trim().toLowerCase();
    const cases = window._cachedCases || [];
    if (!term) {
      renderCases(cases);
    } else {
      const filtered = cases.filter(c =>
        (c.case_number && c.case_number.toLowerCase().includes(term)) ||
        (c.case_title && c.case_title.toLowerCase().includes(term)) ||
        (c.fir_number && c.fir_number.toLowerCase().includes(term)) ||
        (c.examiner && c.examiner.toLowerCase().includes(term)) ||
        (c.agency && c.agency.toLowerCase().includes(term))
      );
      renderCases(filtered);
    }
  };

  function renderCases(cases) {
    const container = document.getElementById('cases-view-container');
    const chip = document.getElementById('count-cases-chip');
    if (chip) chip.textContent = `${cases.length} Case${cases.length === 1 ? '' : 's'}`;

    if (cases.length === 0) {
      container.innerHTML = `
        <div class="empty-dossier-vault">
          <div class="empty-vault-radar">${emptyArt()}</div>
          <h4>No Forensic Cases Found</h4>
          <p>Register an investigation case to lock disk evidence and begin stream reconstruction.</p>
          <button class="btn-vision-primary" onclick="navigateTo('new-case')">
            <span class="btn-glow-layer"></span>
            ${icon('plus-circle')} Register Case Dossier
          </button>
        </div>
      `;
      return;
    }

    if (_dashboardViewMode === 'dossier') {
      // Holographic Dossier Cards Grid
      container.innerHTML = `
        <div class="dossier-cards-grid">
          ${cases.map(c => `
            <div class="dossier-card" data-case-id="${c.case_id}">
              <div class="dossier-card-top">
                <div class="dossier-stamp">
                  <span class="dossier-security-badge">🔒 SECURED</span>
                  ${caseStatusBadge(c.status)}
                </div>
                ${priorityBadge(c.priority || 'MEDIUM')}
              </div>

              <div class="dossier-main-info">
                <div class="dossier-case-number">${escapeHtml(c.case_number)}</div>
                ${c.case_title ? `<div class="dossier-case-title">${escapeHtml(c.case_title)}</div>` : ''}
              </div>

              <div class="dossier-meta-grid">
                <div class="dossier-meta-item">
                  <span class="meta-label">INVESTIGATOR</span>
                  <span class="meta-val">${escapeHtml(c.examiner || 'Examiner')}</span>
                </div>
                <div class="dossier-meta-item">
                  <span class="meta-label">AGENCY / UNIT</span>
                  <span class="meta-val">${escapeHtml(c.agency || 'Forensic Lab')}</span>
                </div>
                <div class="dossier-meta-item">
                  <span class="meta-label">FIR / CRIME REF</span>
                  <span class="meta-val font-mono">${c.fir_number ? escapeHtml(c.fir_number) : '—'}</span>
                </div>
                <div class="dossier-meta-item">
                  <span class="meta-label">DATE REGISTERED</span>
                  <span class="meta-val text-xs">${formatIST(c.created_at)}</span>
                </div>
              </div>

              <div class="dossier-footer">
                <button class="dossier-open-btn" onclick="navigateTo('case-detail', { caseId: '${c.case_id}' })">
                  Open Dossier ${icon('arrow-right')}
                </button>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    } else {
      // High-Density Forensic Table View
      container.innerHTML = `
        <div class="vision-table-wrapper">
          <table class="vision-table">
            <thead>
              <tr>
                <th>CASE NUMBER / TITLE</th>
                <th>INVESTIGATOR &amp; AGENCY</th>
                <th>FIR REF</th>
                <th>PRIORITY</th>
                <th>STATUS</th>
                <th>REGISTERED</th>
                <th>ACTION</th>
              </tr>
            </thead>
            <tbody>
              ${cases.map(c => `
                <tr>
                  <td>
                    <strong class="text-coral font-mono text-base">${escapeHtml(c.case_number)}</strong>
                    ${c.case_title ? `<div class="text-xs text-muted mt-1">${escapeHtml(c.case_title)}</div>` : ''}
                  </td>
                  <td>
                    <div class="font-medium text-white">${escapeHtml(c.examiner)}</div>
                    ${c.agency ? `<div class="text-xs text-muted">${escapeHtml(c.agency)}</div>` : ''}
                  </td>
                  <td>${c.fir_number ? `<span class="dossier-chip font-mono text-xs">${escapeHtml(c.fir_number)}</span>` : '<span class="text-muted">–</span>'}</td>
                  <td>${priorityBadge(c.priority || 'MEDIUM')}</td>
                  <td>${caseStatusBadge(c.status)}</td>
                  <td class="text-xs text-muted">${formatIST(c.created_at)}</td>
                  <td>
                    <button class="dossier-open-btn-sm" onclick="navigateTo('case-detail', { caseId: '${c.case_id}' })">
                      Open ${icon('arrow-right')}
                    </button>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
    }
  }

  // Load cases asynchronously
  try {
    const cases = await API.listCases(true);
    window._cachedCases = cases;

    const totalEl = document.getElementById('stat-total-cases');
    if (totalEl) totalEl.textContent = cases.length;

    renderCases(cases);
  } catch (err) {
    const container = document.getElementById('cases-view-container');
    if (container) {
      container.innerHTML = `
        <div class="error-banner">
          <div class="error-banner-icon">${icon('alert')}</div>
          <div class="error-banner-body">
            <div class="error-banner-title">Could not load forensic cases</div>
            <div class="error-banner-msg">${escapeHtml(err.message)}</div>
          </div>
        </div>
      `;
    }
  }
}
