/**
 * Sidebar.js — VisionOS Floating Dock
 * Sleek, glass-elevated navigation pill with tactile feedback and forensic status seals.
 */
let _sidebarAppVersion = null;

function renderSidebar(activeScreen = 'dashboard', currentCaseId = null, currentEvidenceId = null) {
  const root = document.getElementById('sidebar-root');

  if (_sidebarAppVersion === null) {
    _sidebarAppVersion = '';
    fetch('/api/version').then((r) => r.json()).then((body) => {
      _sidebarAppVersion = body.version || '';
      const el = document.getElementById('sidebar-version');
      if (el && _sidebarAppVersion) el.textContent = `A.E.G.I.S v${_sidebarAppVersion}`;
    }).catch(() => {});
  }

  const globalItems = [
    { id: 'dashboard', icon: 'dashboard', label: 'Cases Station', kbd: '⌘1', action: () => navigateTo('dashboard') },
    { id: 'new-case', icon: 'plus-circle', label: 'Register Case', kbd: '⌘N', action: () => navigateTo('new-case') }
  ];

  let caseItems = [];
  if (currentCaseId) {
    caseItems.push({ id: 'case-detail', icon: 'folder-open', label: 'Case Dossier', action: () => navigateTo('case-detail', { caseId: currentCaseId }) });
    caseItems.push({ id: 'timeline', icon: 'clock', label: 'Timeline Matrix', action: () => navigateTo('timeline', { caseId: currentCaseId }) });

    if (currentEvidenceId) {
      caseItems.push({ id: 'evidence-scan', icon: 'search', label: 'Carve & Scan', action: () => navigateTo('evidence-scan', { caseId: currentCaseId, evidenceId: currentEvidenceId }) });
      caseItems.push({ id: 'recordings', icon: 'film', label: 'Recovered Video', action: () => navigateTo('recordings', { caseId: currentCaseId, evidenceId: currentEvidenceId }) });
      caseItems.push({ id: 'export-report', icon: 'file-text', label: 'Signed Certificate', action: () => navigateTo('export-report', { caseId: currentCaseId, evidenceId: currentEvidenceId }) });
    }

    caseItems.push({ id: 'audit-log', icon: 'lock', label: 'Cryptographic Audit', action: () => navigateTo('audit-log', { caseId: currentCaseId }) });
  }

  const renderItems = (items) => items.map(item => `
    <div class="nav-item ${activeScreen === item.id ? 'active' : ''}" data-screen="${item.id}" title="${item.label}">
      <span class="nav-icon-wrap">${icon(item.icon)}</span>
      <span class="nav-label-text">${item.label}</span>
      ${item.kbd ? `<kbd class="nav-kbd">${item.kbd}</kbd>` : ''}
    </div>
  `).join('');

  root.innerHTML = `
    <div class="dock-section">
      <div class="nav-section-label">WORKSTATION</div>
      ${renderItems(globalItems)}
    </div>

    ${caseItems.length > 0 ? `
      <div class="dock-section">
        <div class="nav-section-label">ACTIVE DOSSIER</div>
        ${renderItems(caseItems)}
      </div>
    ` : ''}

    <div class="sidebar-foot">
      <div class="airgap-badge">
        <span class="airgap-dot"></span> AIR-GAPPED SECURE
      </div>
      <div class="foot-desc">Hardware-enforced Read-Only MMAP. Every operation is cryptographically signed.</div>
      <button type="button" class="sidebar-version" id="sidebar-version">${_sidebarAppVersion ? `A.E.G.I.S v${_sidebarAppVersion}` : 'A.E.G.I.S v3.0.0'}</button>
    </div>
  `;

  const allItems = [...globalItems, ...caseItems];
  root.querySelectorAll('.nav-item').forEach((el) => {
    const screenId = el.dataset.screen;
    const item = allItems.find(i => i.id === screenId);
    if (item) el.addEventListener('click', item.action);
  });
}
