/**
 * Sidebar component.
 */
function renderSidebar(activeScreen = 'dashboard', currentCaseId = null, currentEvidenceId = null) {
  const root = document.getElementById('sidebar-root');
  
  const navItems = [
    { id: 'dashboard', label: '📊 Cases Dashboard', action: () => navigateTo('dashboard') },
    { id: 'new-case', label: '➕ New Case', action: () => navigateTo('new-case') }
  ];

  if (currentCaseId) {
    navItems.push({ id: 'case-detail', label: '📁 Case Overview', action: () => navigateTo('case-detail', { caseId: currentCaseId }) });
    
    if (currentEvidenceId) {
      navItems.push({ id: 'evidence-scan', label: '🔍 Acquisition & Scan', action: () => navigateTo('evidence-scan', { caseId: currentCaseId, evidenceId: currentEvidenceId }) });
      navItems.push({ id: 'recordings', label: '🎥 Recordings', action: () => navigateTo('recordings', { caseId: currentCaseId, evidenceId: currentEvidenceId }) });
      navItems.push({ id: 'export-report', label: '📄 Report & Certificate', action: () => navigateTo('export-report', { caseId: currentCaseId, evidenceId: currentEvidenceId }) });
    }
    
    navItems.push({ id: 'audit-log', label: '🔒 Hash Audit Log', action: () => navigateTo('audit-log', { caseId: currentCaseId }) });
  }

  root.innerHTML = navItems.map(item => `
    <div class="nav-item ${activeScreen === item.id ? 'active' : ''}" data-screen="${item.id}">
      ${item.label}
    </div>
  `).join('');

  root.querySelectorAll('.nav-item').forEach((el, index) => {
    el.addEventListener('click', navItems[index].action);
  });
}
