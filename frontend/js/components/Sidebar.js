/**
 * Sidebar component.
 */
function renderSidebar(activeScreen = 'dashboard', currentCaseId = null, currentEvidenceId = null) {
  const root = document.getElementById('sidebar-root');

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
  `;

  const allItems = [...globalItems, ...caseItems];
  root.querySelectorAll('.nav-item').forEach((el) => {
    const screenId = el.dataset.screen;
    const item = allItems.find(i => i.id === screenId);
    if (item) el.addEventListener('click', item.action);
  });
}
