/**
 * app.js — Main frontend SPA controller and router.
 *
 * Auth flow on startup:
 *   1. Call GET /api/auth/status-with-session (always unauthenticated).
 *   2. If no password set → renderSetupScreen().
 *   3. If password set but not authenticated → renderLoginScreen().
 *   4. If authenticated → renderDashboardScreen().
 *
 * 401 handler: any fetch call that results in 401 fires the 'auth:expired'
 * event, which redirects to the login screen without needing to know which
 * route caused it.
 */

let currentRoute = { screen: 'dashboard', params: {} };

function navigateTo(screen, params = {}) {
  currentRoute = { screen, params };

  // Auth screens: hide sidebar/breadcrumb — handled inside each render function.
  // Other screens: restore them.
  const sidebar = document.getElementById('sidebar-root');
  const breadcrumb = document.getElementById('breadcrumb-strip');

  if (screen !== 'login' && screen !== 'setup') {
    if (sidebar) sidebar.style.display = '';
    if (breadcrumb) breadcrumb.style.display = '';
    renderSidebar(screen, params.caseId, params.evidenceId);
  }

  switch (screen) {
    case 'login':
      renderLoginScreen();
      break;

    case 'setup':
      renderSetupScreen();
      break;

    case 'dashboard':
      renderHeader([]);  // just the home crumb
      renderDashboardScreen();
      break;

    case 'new-case':
      renderHeader([{ label: 'New Case' }]);
      renderNewCaseScreen();
      break;

    case 'case-detail':
      renderHeader([
        { label: `Case #${params.caseId}` }
      ]);
      renderCaseDetailScreen(params);
      break;

    case 'evidence-scan':
      renderHeader([
        { label: `Case #${params.caseId}`, screen: 'case-detail', params: { caseId: params.caseId } },
        { label: 'Acquisition & Scan' }
      ]);
      renderEvidenceScanScreen(params);
      break;

    case 'recordings':
      renderHeader([
        { label: `Case #${params.caseId}`, screen: 'case-detail', params: { caseId: params.caseId } },
        { label: 'Recordings' }
      ]);
      renderRecordingsScreen(params);
      break;

    case 'audit-log':
      renderHeader([
        { label: `Case #${params.caseId}`, screen: 'case-detail', params: { caseId: params.caseId } },
        { label: 'Audit Log' }
      ]);
      renderAuditLogScreen(params);
      break;

    case 'export-report':
      renderHeader([
        { label: `Case #${params.caseId}`, screen: 'case-detail', params: { caseId: params.caseId } },
        { label: 'Export Report' }
      ]);
      renderExportReportScreen(params);
      break;

    default:
      renderHeader([]);
      renderDashboardScreen();
  }
}

// ── Global 401 handler ────────────────────────────────────────────────────────
// Any API call returning 401 dispatches this event.
// This catches session expiry mid-use and redirects to login automatically.
window.addEventListener('auth:expired', () => {
  navigateTo('login');
});

// ── App Initialization ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  try {
    const status = await API.authStatus();
    if (!status.password_set) {
      navigateTo('setup');
    } else if (!status.authenticated) {
      navigateTo('login');
    } else {
      navigateTo('dashboard');
    }
  } catch (_) {
    // If the status check itself fails (server down?), show login
    navigateTo('login');
  }
});
