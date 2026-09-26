/**
 * Header component.
 * Renders the top bar (branding + meta) and the breadcrumb strip below it.
 * Call renderHeader(breadcrumbs) where breadcrumbs is an array of:
 *   { label: string, screen?: string, params?: object }
 * The last item is always the current page (rendered as plain text).
 */
function renderHeader(breadcrumbs = []) {
  const root = document.getElementById('header-root');
  const host = window.location.hostname || '127.0.0.1';
  const isLocal = host === '127.0.0.1' || host === 'localhost';
  const hostLabel = isLocal ? '127.0.0.1' : `${host}`;

  const themeIcon = currentTheme() === 'dark' ? 'sun' : 'moon';
  root.innerHTML = `
    <div class="logo-area">
      ${logoMark()}
      <div class="logo-text">
        <h1>DVR/NVR Forensic Analysis Tool</h1>
        <p>SIH26150 · Recover, verify and report CCTV evidence</p>
      </div>
    </div>
    <div class="header-meta">
      <div id="case-context-pill" class="case-context-pill" style="display:none;" role="region" aria-label="Case context"></div>
      <div class="host-pill" data-tooltip="This tool is served from this machine. Nothing leaves it unless you export."><span class="dot"></span><span class="label">${escapeHtml(hostLabel)}</span></div>
      <button type="button" id="theme-toggle" class="icon-btn" aria-label="Switch light or dark theme" title="Switch light / dark theme">${icon(themeIcon)}</button>
    </div>
  `;
  document.getElementById('theme-toggle').addEventListener('click', () => {
    const next = toggleTheme();
    document.getElementById('theme-toggle').innerHTML = icon(next === 'dark' ? 'sun' : 'moon');
  });

  // ── Breadcrumb strip ──────────────────────────────────────────────────────
  // Ensure the strip element exists (created once in index.html is ideal,
  // but we manage it here for resilience).
  let strip = document.getElementById('breadcrumb-strip');
  if (!strip) {
    // Insert after header, before main-layout
    strip = document.createElement('nav');
    strip.id = 'breadcrumb-strip';
    strip.className = 'breadcrumb-strip';
    const appContainer = document.getElementById('app-container');
    const mainLayout = document.querySelector('.main-layout');
    appContainer.insertBefore(strip, mainLayout);
  }

  // Always start with a "Dashboard" home crumb
  const allCrumbs = [
    { label: 'Dashboard', screen: 'dashboard', params: {}, icon: 'home' },
    ...breadcrumbs
  ];

  strip.innerHTML = allCrumbs.map((crumb, idx) => {
    const isLast = idx === allCrumbs.length - 1;
    const sep = idx > 0 ? `<span class="crumb-sep">${icon('chevron-right')}</span>` : '';
    const ico = crumb.icon ? icon(crumb.icon) : '';
    if (isLast) {
      return `${sep}<span class="crumb-current">${ico}${escapeHtml(crumb.label)}</span>`;
    }
    return `${sep}<span class="crumb-link" data-screen="${escapeHtml(crumb.screen)}" data-params="${escapeHtml(JSON.stringify(crumb.params || {}))}">${ico}${escapeHtml(crumb.label)}</span>`;
  }).join('');

  // Wire up clicks on crumb links
  strip.querySelectorAll('.crumb-link').forEach(el => {
    el.addEventListener('click', () => {
      const screen = el.dataset.screen;
      const params = JSON.parse(el.dataset.params || '{}');
      navigateTo(screen, params);
    });
  });
}

let activeHeaderCaseId = null;
let activeHeaderEvidenceId = null;

async function updateHeaderContext(caseId, evidenceId = null) {
  const pill = document.getElementById('case-context-pill');
  if (!pill) return;

  if (!caseId) {
    pill.style.display = 'none';
    activeHeaderCaseId = null;
    activeHeaderEvidenceId = null;
    return;
  }

  activeHeaderCaseId = caseId;
  activeHeaderEvidenceId = evidenceId;

  try {
    const caseData = await API.getCase(caseId);
    if (activeHeaderCaseId !== caseId) return;

    const evidenceList = caseData.evidence || [];
    let currentEvidence = null;
    if (evidenceId) {
      currentEvidence = evidenceList.find(e => e.evidence_id === evidenceId);
    }
    if (!currentEvidence && evidenceList.length > 0) {
      currentEvidence = evidenceList[0];
    }

    const caseNum = caseData.case_number || (caseData.case_id ? caseData.case_id.substring(0, 8) : caseId);
    let evidenceLabel = 'None';
    let integrityState = 'none';

    if (currentEvidence) {
      evidenceLabel = currentEvidence.label
        || (currentEvidence.path ? currentEvidence.path.split(/[\\/]/).pop() : (currentEvidence.evidence_id.substring(0, 8) + '…'));

      if (currentEvidence.sha256_after === 'MISMATCH') {
        integrityState = 'mismatch';
      } else if (currentEvidence.sha256_after && currentEvidence.sha256_after === currentEvidence.sha256_before) {
        integrityState = 'verified';
      } else if (currentEvidence.sha256_after) {
        integrityState = 'verified';
      } else {
        integrityState = 'unverified';
      }
    }

    let integrityClass = 'badge-pending';
    let integrityIcon = 'shield';
    let integrityText = 'Not verified yet';
    let integrityTitle = 'Disk image not verified yet. Click to verify integrity.';

    if (integrityState === 'verified') {
      integrityClass = 'badge-verified';
      integrityIcon = 'check-circle';
      integrityText = 'Verified';
      integrityTitle = 'Integrity verified: matches baseline. Click to re-verify.';
    } else if (integrityState === 'mismatch') {
      integrityClass = 'badge-error';
      integrityIcon = 'alert';
      integrityText = 'Mismatch';
      integrityTitle = 'MISMATCH DETECTED: disk image has been modified! Click to re-verify.';
    } else if (integrityState === 'none') {
      integrityClass = 'badge-pending';
      integrityIcon = 'info';
      integrityText = 'No evidence';
      integrityTitle = 'No evidence image loaded for this case yet.';
    }

    pill.innerHTML = `
      <div class="case-pill-info" ${navAttrs('case-detail', { caseId: caseId })} title="Return to Case Overview">
        <span class="case-pill-id">${icon('folder')} Case #${escapeHtml(caseNum)}</span>
        <span class="case-pill-sep">·</span>
        <span class="case-pill-evidence">Evidence: <strong>${escapeHtml(evidenceLabel)}</strong></span>
      </div>
      <span class="case-pill-sep">·</span>
      <button type="button" class="case-pill-integrity badge ${integrityClass}" id="btn-pill-verify" title="${integrityTitle}">
        ${icon(integrityIcon)} ${escapeHtml(integrityText)}
      </button>
    `;
    pill.style.display = 'inline-flex';

    const verifyBtn = document.getElementById('btn-pill-verify');
    if (verifyBtn && currentEvidence) {
      verifyBtn.onclick = async (e) => {
        e.stopPropagation();
        e.preventDefault();
        verifyBtn.disabled = true;
        verifyBtn.innerHTML = '<span class="btn-spinner"></span> Verifying…';
        try {
          const res = await API.verifyEvidenceIntegrity(caseId, currentEvidence.evidence_id);
          if (res.match) {
            const shaShort = res.current_sha256 ? res.current_sha256.substring(0, 12) + '…' : '';
            showToast(`Integrity MATCH: Disk image verified against baseline (${shaShort})`, 'success');
          } else {
            showToast('MISMATCH DETECTED: Disk image has been modified since acquisition!', 'error', { duration: 8000 });
          }
          await updateHeaderContext(caseId, currentEvidence.evidence_id);
        } catch (err) {
          showToast(`Verification failed: ${escapeHtml(err.message)}`, 'error');
          await updateHeaderContext(caseId, currentEvidence.evidence_id);
        }
      };
    }
  } catch (_) {
    pill.style.display = 'none';
  }
}
