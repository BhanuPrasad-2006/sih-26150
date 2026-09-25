/**
 * DashboardScreen.js — Main cases overview list.
 */
async function renderDashboardScreen() {
  const root = document.getElementById('content-root');

  root.innerHTML = `
    <div class="page-header">
      <div class="page-header-row">
        <div>
          <div class="page-title">Forensic Cases</div>
          <div class="page-subtitle">Select an active case or register a new investigation.</div>
        </div>
        <button id="btn-new-case" class="btn btn-primary">➕ Register New Case</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Active Cases</div>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Case Number</th>
              <th>Investigator</th>
              <th>Notes / Agency</th>
              <th>Registered</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="cases-table-body">
            <!-- loading state -->
            <tr class="skeleton-row">
              <td><div class="skeleton-cell" style="width:110px;"></div></td>
              <td><div class="skeleton-cell" style="width:140px;"></div></td>
              <td><div class="skeleton-cell" style="width:180px;"></div></td>
              <td><div class="skeleton-cell" style="width:130px;"></div></td>
              <td><div class="skeleton-cell" style="width:90px;"></div></td>
            </tr>
            <tr class="skeleton-row">
              <td><div class="skeleton-cell" style="width:90px;"></div></td>
              <td><div class="skeleton-cell" style="width:120px;"></div></td>
              <td><div class="skeleton-cell" style="width:160px;"></div></td>
              <td><div class="skeleton-cell" style="width:130px;"></div></td>
              <td><div class="skeleton-cell" style="width:90px;"></div></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  document.getElementById('btn-new-case').onclick = () => navigateTo('new-case');

  try {
    const cases = await API.listCases();
    const tbody = document.getElementById('cases-table-body');

    if (cases.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="5" style="padding: 0; border: none;">
            <div class="empty-state">
              <div class="empty-state-icon">📂</div>
              <div class="empty-state-title">No cases yet</div>
              <div class="empty-state-subtitle">Create your first forensic case to get started — each case tracks a chain of custody for one investigation.</div>
              <button class="btn btn-primary" onclick="navigateTo('new-case')">➕ Register First Case</button>
            </div>
          </td>
        </tr>`;
      return;
    }

    tbody.innerHTML = cases.map(c => `
      <tr>
        <td><strong style="color: var(--accent-cyan); font-family: var(--font-mono); font-size:13px;">${escapeHtml(c.case_number)}</strong></td>
        <td>${escapeHtml(c.examiner)}</td>
        <td style="color:var(--text-muted); font-size:12px;">${c.notes ? escapeHtml(c.notes) : '—'}</td>
        <td style="color:var(--text-dim); font-size:12px;">${new Date(c.created_at).toLocaleString()}</td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="navigateTo('case-detail', { caseId: '${c.case_id}' })">Open ➔</button>
        </td>
      </tr>
    `).join('');

  } catch (err) {
    const tbody = document.getElementById('cases-table-body');
    tbody.innerHTML = `
      <tr>
        <td colspan="5" style="padding: 12px; border: none;">
          <div class="error-banner">
            <div class="error-banner-icon">⚠️</div>
            <div class="error-banner-body">
              <div class="error-banner-title">Failed to load cases</div>
              <div class="error-banner-msg">${escapeHtml(err.message)}</div>
            </div>
          </div>
        </td>
      </tr>`;
  }
}
