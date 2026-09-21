/**
 * AuditLogScreen.js — View cryptographic hash-chained audit log and chain integrity status.
 */
async function renderAuditLogScreen(params) {
  const caseId = params.caseId;
  const root = document.getElementById('content-root');

  root.innerHTML = `<p style="color:var(--text-dim);">Loading audit log...</p>`;

  try {
    const auditData = await API.getAuditLog(caseId);

    root.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
        <div>
          <h2 style="font-size: 24px; font-weight: 700;">Hash-Chained Audit Log</h2>
          <p style="color: var(--text-muted); font-size: 14px;">Formula: Hash_n = SHA-256( Time | Action | Params | Hash_(n-1) )</p>
        </div>
        <div style="text-align: right;">
          <span class="badge ${auditData.valid ? 'badge-complete' : 'badge-uncertain'}" style="font-size:14px; padding:6px 14px;">
            ${auditData.valid ? '🔒 CHAIN INTEGRITY VERIFIED (VALID)' : '❌ TAMPERING DETECTED'}
          </span>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Audit Chain Entries (${auditData.entries.length})</div>
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Seq #</th>
                <th>Timestamp (UTC)</th>
                <th>Action</th>
                <th>Parameters</th>
                <th>Calculated Entry Hash (SHA-256)</th>
              </tr>
            </thead>
            <tbody>
              ${auditData.entries.length === 0
                ? `<tr><td colspan="5" style="text-align:center; color:var(--text-dim); padding:20px;">No audit entries logged yet.</td></tr>`
                : auditData.entries.map(e => `
                    <tr>
                      <td><strong>#${e.sequence_number}</strong></td>
                      <td style="font-size:12px; color:var(--text-muted);">${new Date(e.timestamp * 1000).toISOString()}</td>
                      <td><span style="color:var(--accent-cyan); font-weight:600;">${e.action}</span></td>
                      <td style="font-size:12px; max-width:250px; color:var(--text-muted); font-family:var(--font-mono);">${e.params}</td>
                      <td class="hash-font">${e.entry_hash}</td>
                    </tr>
                  `).join('')
              }
            </tbody>
          </table>
        </div>
      </div>
    `;

  } catch (err) {
    root.innerHTML = `<p style="color:var(--accent-rose);">Failed to load audit log: ${err.message}</p>`;
  }
}
