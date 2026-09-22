/**
 * Sidebar component.
 */
function renderSidebar(activeScreen = 'dashboard', currentCaseId = null, currentEvidenceId = null) {
  const root = document.getElementById('sidebar-root');

  const globalItems = [
    { id: 'dashboard', label: '📊 Cases Dashboard', action: () => navigateTo('dashboard') },
    { id: 'new-case', label: '➕ New Case', action: () => navigateTo('new-case') }
  ];

  let caseItems = [];
  if (currentCaseId) {
    caseItems.push({ id: 'case-detail', label: '📁 Case Overview', action: () => navigateTo('case-detail', { caseId: currentCaseId }) });

    if (currentEvidenceId) {
      caseItems.push({ id: 'evidence-scan', label: '🔍 Acquisition & Scan', action: () => navigateTo('evidence-scan', { caseId: currentCaseId, evidenceId: currentEvidenceId }) });
      caseItems.push({ id: 'recordings', label: '🎥 Recordings', action: () => navigateTo('recordings', { caseId: currentCaseId, evidenceId: currentEvidenceId }) });
      caseItems.push({ id: 'export-report', label: '📄 Report & Certificate', action: () => navigateTo('export-report', { caseId: currentCaseId, evidenceId: currentEvidenceId }) });
    }

    caseItems.push({ id: 'audit-log', label: '🔒 Hash Audit Log', action: () => navigateTo('audit-log', { caseId: currentCaseId }) });
  }

  const renderItems = (items) => items.map(item => `
    <div class="nav-item ${activeScreen === item.id ? 'active' : ''}" data-screen="${item.id}">
      ${item.label}
    </div>
  `).join('');

  root.innerHTML = `
    <div class="nav-section-label">Navigation</div>
    ${renderItems(globalItems)}
    ${caseItems.length > 0 ? `
      <div class="nav-section-label" style="margin-top:12px;">Current Case</div>
      ${renderItems(caseItems)}
    ` : ''}
  `;

  const allItems = [...globalItems, ...caseItems];
  root.querySelectorAll('.nav-item').forEach((el) => {
    const screenId = el.dataset.screen;
    const item = allItems.find(i => i.id === screenId);
    if (item) el.addEventListener('click', item.action);
  });
}
