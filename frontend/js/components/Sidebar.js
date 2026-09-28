/**
 * Sidebar component.
 */
let _sidebarAppVersion = null;   // fetched once, cached — renderSidebar() runs on every navigation

function renderSidebar(activeScreen = 'dashboard', currentCaseId = null, currentEvidenceId = null) {
  const root = document.getElementById('sidebar-root');

  if (_sidebarAppVersion === null) {
    _sidebarAppVersion = '';   // avoid firing a fetch per navigation while the first one is in flight
    fetch('/api/version').then((r) => r.json()).then((body) => {
      _sidebarAppVersion = body.version || '';
      const el = document.getElementById('sidebar-version');
      if (el && _sidebarAppVersion) el.textContent = `v${_sidebarAppVersion}`;
    }).catch(() => {});
  }

  const globalItems = [
    { id: 'dashboard', icon: 'dashboard', label: 'Cases Dashboard', action: () => navigateTo('dashboard') },
    { id: 'new-case', icon: 'plus-circle', label: 'New Case', action: () => navigateTo('new-case') }
  ];

  let caseItems = [];
  if (currentCaseId) {
    caseItems.push({ id: 'case-detail', icon: 'folder-open', label: 'Case Overview', action: () => navigateTo('case-detail', { caseId: currentCaseId }) });
    caseItems.push({ id: 'timeline', icon: 'clock', label: 'Cross-Camera Timeline', action: () => navigateTo('timeline', { caseId: currentCaseId }) });

    if (currentEvidenceId) {
      caseItems.push({ id: 'evidence-scan', icon: 'search', label: 'Acquisition & Scan', action: () => navigateTo('evidence-scan', { caseId: currentCaseId, evidenceId: currentEvidenceId }) });
      caseItems.push({ id: 'recordings', icon: 'film', label: 'Recordings', action: () => navigateTo('recordings', { caseId: currentCaseId, evidenceId: currentEvidenceId }) });
      caseItems.push({ id: 'export-report', icon: 'file-text', label: 'Report & Certificate', action: () => navigateTo('export-report', { caseId: currentCaseId, evidenceId: currentEvidenceId }) });
    }

    caseItems.push({ id: 'audit-log', icon: 'lock', label: 'Hash Audit Log', action: () => navigateTo('audit-log', { caseId: currentCaseId }) });
  }

  const renderItems = (items) => items.map(item => `
    <div class="nav-item ${activeScreen === item.id ? 'active' : ''}" data-screen="${item.id}">
      ${icon(item.icon)}<span>${item.label}</span>
    </div>
  `).join('');

  root.innerHTML = `
    <div class="nav-section-label">Navigation</div>
    ${renderItems(globalItems)}
    ${caseItems.length > 0 ? `
      <div class="nav-section-label">Current Case</div>
      ${renderItems(caseItems)}
    ` : ''}
    <div class="sidebar-foot"><b>Evidence stays read-only.</b><br>Every action is hashed into a tamper-evident audit log.</div>
    <button type="button" class="sidebar-version" id="sidebar-version">${_sidebarAppVersion ? `v${_sidebarAppVersion}` : ''}</button>
  `;

  const allItems = [...globalItems, ...caseItems];
  root.querySelectorAll('.nav-item').forEach((el) => {
    const screenId = el.dataset.screen;
    const item = allItems.find(i => i.id === screenId);
    if (item) el.addEventListener('click', item.action);
  });

  document.getElementById('sidebar-version').addEventListener('click', showAboutModal);
}

async function showAboutModal() {
  showModal('About this tool', '<p>Loading…</p>');
  try {
    const info = await (await fetch('/api/app-info')).json();
    showModal('About this tool', `
      <div class="about-rows">
        <div class="about-row"><span>Version</span><b>v${info.version}</b></div>
        <div class="about-row"><span>Database</span><b>${info.database_backend}</b></div>
        <div class="about-row"><span>Case data folder</span><b class="about-path">${info.case_dir}</b></div>
        <div class="about-row"><span>Terms accepted</span><b>v${info.terms_version_accepted || '—'}</b></div>
      </div>
      <p class="about-note">This tool runs entirely on this computer. Evidence images are opened
      read-only and never leave the folder above unless you configure a remote database yourself.
      Prototype built for Smart India Hackathon (SIH26150) — not certified for forensic use;
      always corroborate PARTIAL/UNCERTAIN results independently.</p>
    `, [{ label: 'Close', class: 'btn-primary' }]);
  } catch (_) {
    showModal('About this tool', '<p>Could not load version information.</p>', [{ label: 'Close', class: 'btn-primary' }]);
  }
}
