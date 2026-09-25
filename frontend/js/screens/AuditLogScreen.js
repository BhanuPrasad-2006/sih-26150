/**
 * AuditLogScreen.js — View cryptographic hash-chained audit log and chain integrity status.
 */
async function renderAuditLogScreen(params) {
  const caseId = params.caseId;
  const root = document.getElementById('content-root');

  // ── Loading state ─────────────────────────────────────────────────────────
  root.innerHTML = `
    <div class="loading-state">
      <div class="spinner"></div>
      <p>Loading audit log…</p>
    </div>`;

  let auditData;
  try {
    auditData = await API.getAuditLog(caseId);
  } catch (err) {
    root.innerHTML = `
      <div class="page-header">
        <div class="page-title">Hash-Chained Audit Log</div>
      </div>
      <div class="error-banner">
        <div class="error-banner-icon">⚠️</div>
        <div class="error-banner-body">
          <div class="error-banner-title">Failed to load audit log</div>
          <div class="error-banner-msg">${escapeHtml(err.message)}</div>
        </div>
      </div>`;
    return;
  }

  const isValid = auditData.chain_intact;
  const chainError = auditData.error || '';

  root.innerHTML = `
    <div class="page-header">
      <div class="page-header-row">
        <div>
          <div class="page-title">Hash-Chained Audit Log</div>
          <div class="page-subtitle" style="font-family:var(--font-mono); font-size:12px;">
            Hash<sub>n</sub> = SHA-256( Time | Action | Params | Hash<sub>n-1</sub> )
          </div>
        </div>
        <div style="text-align:right;">
          <span class="badge ${isValid ? 'badge-complete' : 'badge-error'}" style="font-size:12px; padding:6px 14px;">
            ${isValid ? '🔒 CHAIN VALID' : '❌ TAMPERING DETECTED'}
          </span>
          <div style="font-size:11px; color:var(--text-dim); margin-top:6px; max-width:220px; text-align:right; line-height:1.5;">
            ${isValid
              ? 'Every audit entry\'s hash matches the expected value — the chain has not been modified since creation.' + (auditData.seal ? '<br>Seal: ' + escapeHtml(auditData.seal.message) : '')
              : `One or more entries do not match their expected hash. ${chainError ? '<br><span style="font-family:var(--font-mono); font-size:10px;">' + escapeHtml(chainError) + '</span>' : 'The log may have been tampered with.'}`}
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Audit Chain Entries (${auditData.entries.length})</div>

      ${auditData.entries.length === 0
        ? `<div class="empty-state">
             <div class="empty-state-icon">🔒</div>
             <div class="empty-state-title">No audit entries yet</div>
             <div class="empty-state-subtitle">Actions performed on this case — evidence loading, scans, exports — will appear here as cryptographically chained entries.</div>
           </div>`
        : `<div class="table-container">
             <table>
               <thead>
                 <tr>
                   <th>Seq #</th>
                   <th>Timestamp (UTC)</th>
                   <th>Action</th>
                   <th>Parameters</th>
                   <th>Entry Hash (SHA-256)</th>
                 </tr>
               </thead>
               <tbody>
                 ${auditData.entries.map((e, idx) => `
                   <tr>
                     <td><strong style="color:var(--text-muted);">#${idx + 1}</strong></td>
                     <td style="font-size:12px; color:var(--text-muted); font-family:var(--font-mono);">${e.created_at}</td>
                     <td><span style="color:var(--accent-cyan); font-weight:600; font-size:13px;">${escapeHtml(e.action)}</span></td>
                     <td style="font-size:11px; max-width:220px; color:var(--text-muted); font-family:var(--font-mono); word-break:break-all;">${escapeHtml(e.details || '—')}</td>
                     <td class="hash-font">${escapeHtml(e.entry_hash)}</td>
                   </tr>`).join('')}
               </tbody>
             </table>
           </div>`
      }
    </div>
  `;
}
