/**
 * DashboardScreen.js — Main cases overview list.
 */
async function renderDashboardScreen() {
  const root = document.getElementById('content-root');
  root.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
      <div>
        <h2 style="font-size: 24px; font-weight: 700;">Forensic Cases</h2>
        <p style="color: var(--text-muted); font-size: 14px;">Select an active case or register a new investigation.</p>
      </div>
      <button id="btn-new-case" class="btn btn-primary">➕ Register New Case</button>
    </div>

    <div class="card" style="border-left: 4px solid var(--accent-amber); background: rgba(245, 158, 11, 0.05);">
      <h3 style="color: var(--accent-amber); font-size: 14px; margin-bottom: 4px;">⚠️ Forensic Integrity Notice</h3>
      <p style="font-size: 13px; color: var(--text-muted);">
        All test datasets used in this environment are <strong>SYNTHETIC DATA</strong>. Never cite metrics from synthetic datasets as real-world accuracy claims.
      </p>
    </div>

    <div class="card">
      <div class="card-title">Active Cases</div>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Case Number</th>
              <th>Investigator</th>
              <th>Agency</th>
              <th>Created Date</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="cases-table-body">
            <tr><td colspan="5" style="text-align:center; color: var(--text-dim);">Loading cases...</td></tr>
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
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color: var(--text-dim); padding: 30px;">No forensic cases found. Click "Register New Case" to start.</td></tr>`;
      return;
    }
    tbody.innerHTML = cases.map(c => `
      <tr>
        <td><strong style="color: var(--accent-cyan);">${c.case_number}</strong></td>
        <td>${c.examiner}</td>
        <td>${c.notes || 'NTRO Forensic Unit'}</td>
        <td>${new Date(c.created_at).toLocaleString()}</td>
        <td>
          <button class="btn btn-secondary" onclick="navigateTo('case-detail', { caseId: '${c.case_id}' })">Open Case ➔</button>
        </td>
      </tr>
    `).join('');

  } catch (err) {
    document.getElementById('cases-table-body').innerHTML = `<tr><td colspan="5" style="color:var(--accent-rose); text-align:center;">Failed to load cases: ${err.message}</td></tr>`;
  }
}
