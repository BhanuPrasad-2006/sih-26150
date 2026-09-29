/**
 * DashboardScreen.js — Main cases overview list.
 * Clean, offline, single-examiner local installation UI.
 */
async function renderDashboardScreen() {
  const root = document.getElementById('content-root');

  root.innerHTML = `
    <section class="hero">
      <div>
        <h2>Recover CCTV evidence, with every step on record.</h2>
        <p>Load a DVR/NVR disk image, carve the video that is still on it, prove nothing was altered, and export a signed forensic report. The evidence file is only ever read, never written.</p>
        <div class="hero-actions">
          <button id="btn-new-case" class="btn btn-primary btn-lg">${icon('plus-circle')} Register New Case</button>
        </div>
      </div>
      <div class="hero-art">${heroArt()}</div>
    </section>

    <div class="card">
      <div class="case-tabs-container">
        <div style="font-weight: 600; font-size: 1rem; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
          ${icon('folder-open')} Forensic Cases <span class="tab-badge" id="count-cases">0</span>
        </div>
        <span class="badge badge-pending" id="stat-cases">–</span>
      </div>

      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Case / Title</th>
              <th>Investigator / Agency</th>
              <th>FIR / Crime Ref</th>
              <th>Priority</th>
              <th>Status</th>
              <th>Registered</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="cases-table-body">
            <!-- loading state -->
            <tr class="skeleton-row">
              <td><div class="skeleton-cell skeleton-w-110"></div></td>
              <td><div class="skeleton-cell skeleton-w-140"></div></td>
              <td><div class="skeleton-cell skeleton-w-100"></div></td>
              <td><div class="skeleton-cell skeleton-w-70"></div></td>
              <td><div class="skeleton-cell skeleton-w-70"></div></td>
              <td><div class="skeleton-cell skeleton-w-130"></div></td>
              <td><div class="skeleton-cell skeleton-w-90"></div></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;

  document.getElementById('btn-new-case').onclick = () => navigateTo('new-case');

  async function loadCases() {
    const tbody = document.getElementById('cases-table-body');
    try {
      const cases = await API.listCases(true);
      const statEl = document.getElementById('stat-cases');
      const countEl = document.getElementById('count-cases');

      if (statEl) {
        statEl.textContent = `${cases.length} total`;
        statEl.className = 'badge badge-active';
      }
      if (countEl) {
        countEl.textContent = cases.length;
      }

      if (cases.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="7" class="p-0 border-none">
              <div class="empty-state">
                ${emptyArt()}
                <div class="empty-state-title">No cases yet</div>
                <div class="empty-state-subtitle">Create your first forensic case to begin chain of custody.</div>
                <button class="btn btn-primary" ${navAttrs('new-case')}>${icon('plus-circle')} Register New Case</button>
              </div>
            </td>
          </tr>`;
        return;
      }

      tbody.innerHTML = cases.map(c => `
        <tr>
          <td>
            <strong class="text-primary font-mono text-base">${escapeHtml(c.case_number)}</strong>
            ${c.case_title ? `<div class="text-xs text-muted mt-2">${escapeHtml(c.case_title)}</div>` : ''}
          </td>
          <td>
            <div class="font-medium">${escapeHtml(c.examiner)}</div>
            ${c.agency ? `<div class="text-xs text-muted">${escapeHtml(c.agency)}</div>` : ''}
          </td>
          <td>${c.fir_number ? `<span class="badge font-mono text-xs">${escapeHtml(c.fir_number)}</span>` : '<span class="text-muted">–</span>'}</td>
          <td>${priorityBadge(c.priority || 'MEDIUM')}</td>
          <td>${caseStatusBadge(c.status)}</td>
          <td class="text-sm text-muted">${formatDate(c.created_at)}</td>
          <td>
            <button class="btn btn-secondary btn-sm" ${navAttrs('case-detail', { caseId: c.case_id })}>
              Open ${icon('arrow-right')}
            </button>
          </td>
        </tr>
      `).join('');

    } catch (err) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7">
            <div class="error-banner">
              <div class="error-banner-icon">${icon('alert-circle')}</div>
              <div class="error-banner-body">
                <div class="error-banner-title">Could not load forensic cases</div>
                <div class="error-banner-msg">${escapeHtml(err.message)}</div>
              </div>
            </div>
          </td>
        </tr>`;
    }
  }

  await loadCases();
}
