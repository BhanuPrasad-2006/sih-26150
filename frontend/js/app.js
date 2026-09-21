/**
 * app.js — Main frontend SPA controller and router.
 */

let currentRoute = { screen: 'dashboard', params: {} };

function navigateTo(screen, params = {}) {
  currentRoute = { screen, params };

  // Render header & sidebar
  renderHeader();
  renderSidebar(screen, params.caseId, params.evidenceId);

  // Router dispatch
  switch (screen) {
    case 'dashboard':
      renderDashboardScreen();
      break;
    case 'new-case':
      renderNewCaseScreen();
      break;
    case 'case-detail':
      renderCaseDetailScreen(params);
      break;
    case 'evidence-scan':
      renderEvidenceScanScreen(params);
      break;
    case 'recordings':
      renderRecordingsScreen(params);
      break;
    case 'audit-log':
      renderAuditLogScreen(params);
      break;
    case 'export-report':
      renderExportReportScreen(params);
      break;
    default:
      renderDashboardScreen();
  }
}

// App Initialization
document.addEventListener('DOMContentLoaded', () => {
  navigateTo('dashboard');
});
