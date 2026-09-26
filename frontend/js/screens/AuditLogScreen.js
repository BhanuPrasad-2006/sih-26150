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
        <div class="error-banner-icon">${icon('alert')}</div>
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
          <div class="page-subtitle font-mono-sm">
            Hash<sub>n</sub> = SHA-256( Time | Action | Params | Hash<sub>n-1</sub> )
          </div>
        </div>
        <div class="text-right">
          <span class="badge badge-lg ${isValid ? 'badge-complete' : 'badge-error'}">
            ${isValid ? `${icon('shield-check')} CHAIN VALID` : `${icon('x-circle')} TAMPERING DETECTED`}
          </span>
          <div class="text-xs text-dim mt-6 max-w-220 text-right lh-base">
            ${isValid
              ? 'Every audit entry\'s hash matches the expected value — the chain has not been modified since creation.' + (auditData.seal ? '<br>Seal: ' + escapeHtml(auditData.seal.message) : '')
              : `One or more entries do not match their expected hash. ${chainError ? '<br><span class="font-mono-xxs">' + escapeHtml(chainError) + '</span>' : 'The log may have been tampered with.'}`}
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Audit Chain Entries (${auditData.entries.length})</div>

      ${auditData.entries.length === 0
        ? `<div class="empty-state">
             ${emptyArt()}
             <div class="empty-state-title">No audit entries yet</div>
             <div class="empty-state-subtitle">Actions performed on this case — evidence loading, scans, exports — will appear here as cryptographically chained entries.</div>
           </div>`
        : `<div class="table-container">
             <table>
               <thead>
                 <tr>
                   <th>Seq #</th>
                   <th>Timestamp (IST)</th>
                   <th>Action</th>
                   <th>Parameters</th>
                   <th>Entry Hash (SHA-256)</th>
                 </tr>
               </thead>
               <tbody>
                 ${auditData.entries.map((e, idx) => `
                   <tr>
                     <td><strong class="text-muted">#${idx + 1}</strong></td>
                     <td class="font-mono-sm text-muted">${escapeHtml(formatIST(e.created_at))}</td>
                     <td><span class="text-primary font-semibold text-base">${escapeHtml(e.action)}</span></td>
                     <td class="font-mono-xs max-w-220 text-muted word-break-all">${escapeHtml(e.details || '—')}</td>
                     <td class="hash-font">${escapeHtml(e.entry_hash)}</td>
                   </tr>`).join('')}
               </tbody>
             </table>
           </div>`
      }
    </div>
  `;
}
