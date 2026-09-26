/**
 * api.js — API client for communication with FastAPI backend.
 *
 * Every fetch call checks res.ok and throws a descriptive Error that includes
 * the HTTP status code, the URL, and the server's error message so the UI can
 * show exactly which request failed and why.
 *
 * 401 handling: any API call returning 401 fires a custom 'auth:expired' event
 * on window so app.js can redirect to login without api.js knowing about routing.
 *
 * Note: The backend does not expose a dedicated GET /evidence/{id} endpoint.
 * `getEvidence()` derives evidence from the parent case's evidence list.
 */

/**
 * Escape a string for safe interpolation into innerHTML template strings.
 * Every value that originates as free-text user input (examiner name, case
 * notes, evidence file paths, etc.) must be passed through this before being
 * placed inside a template literal that gets assigned to .innerHTML.
 */
/**
 * Attributes for a navigation control. Rendered pages must not use inline event handlers (the CSP forbids
 * inline script), so clicks on [data-nav] are handled by one delegated listener in app.js.
 */
/** URL that streams an exported segment's MP4 for the <video> player (session cookie authenticates it). */
function segmentVideoUrl(caseId, segmentId) {
  return `/api/cases/${encodeURIComponent(caseId)}/video/${encodeURIComponent(segmentId)}`;
}

function navAttrs(screen, params) {
  return `data-nav="${escapeHtml(screen)}" data-params="${escapeHtml(JSON.stringify(params || {}))}"`;
}

/**
 * Format a real UTC instant (audit-log entries, case creation) as Indian Standard Time.
 * Uses the Asia/Kolkata zone explicitly, so it does not depend on the viewer's computer settings.
 * Do NOT use it on carved recording times: those are the recorder's own clock and carry no time zone.
 */
function formatIST(value) {
  if (!value) return '—';
  // Timestamps without a zone suffix are stored UTC; without this JS would read them as local time.
  const text = String(value);
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(text) ? text : text + 'Z');
  if (Number.isNaN(d.getTime())) return '—';
  const p = {};
  new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).formatToParts(d).forEach(x => { p[x.type] = x.value; });
  return `${p.year}-${p.month}-${p.day} ${p.hour === '24' ? '00' : p.hour}:${p.minute}:${p.second} IST`;
}

/** Attributes for a per-segment action button, handled by the same delegated listener. */
function actAttrs(action, caseId, evidenceId, segmentId) {
  return `data-act="${escapeHtml(action)}" data-case="${escapeHtml(caseId)}" data-evidence="${escapeHtml(evidenceId)}" data-segment="${escapeHtml(segmentId)}"`;
}

function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const API = {
  /** Throw a descriptive error when the server returns a non-2xx status. */
  async _checkOk(res, url) {
    if (res.ok) return res;

    // 401 → session expired or unauthenticated; fire event so app can redirect
    if (res.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:expired'));
      throw new Error('Session expired. Please log in again.');
    }

    let serverMsg = '';
    try {
      const body = await res.json();
      serverMsg = body.detail || body.message || JSON.stringify(body);
    } catch (_) {
      try { serverMsg = await res.text(); } catch (_) { serverMsg = '(no body)'; }
    }
    throw new Error(`HTTP ${res.status} from ${url} — ${serverMsg}`);
  },

  // ── Auth endpoints ─────────────────────────────────────────────────────────

  /**
   * Check server-side auth state.
   * Used on app init to decide which screen to show first.
   * This endpoint is exempt from the auth middleware.
   */
  async authStatus() {
    const url = '/api/auth/status-with-session';
    const res = await fetch(url);
    // This endpoint never returns 401 (it's exempt), so _checkOk is fine
    if (!res.ok) return { password_set: false, authenticated: false };
    return res.json();
  },

  /**
   * First-run: set the examiner password.
   * On success the backend also creates a session cookie automatically.
   */
  async setupPassword(password) {
    const url = '/api/auth/setup';
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    // Don't pass through _checkOk on 4xx because the caller handles the error
    if (!res.ok) {
      let msg = 'Setup failed.';
      try { const b = await res.json(); msg = b.detail || msg; } catch (_) {}
      throw new Error(msg);
    }
    return res.json();
  },

  /**
   * Login with password.
   * Returns {ok: true} on success, or {locked: true, retry_after: N} on lockout.
   * On wrong password the server returns 401; this method throws with "Incorrect password."
   */
  async login(password, totpCode) {
    const url = '/api/auth/login';
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password, totp_code: totpCode || null }),
    });

    if (res.status === 429) {
      // Lockout — return the lockout payload instead of throwing
      const data = await res.json();
      return { locked: true, retry_after: data.retry_after || 60 };
    }

    if (res.status === 401) {
      let m = 'Incorrect password.';
      try { m = (await res.json()).detail || m; } catch (_) {}
      throw new Error(m);
    }

    if (!res.ok) {
      let msg = 'Login failed.';
      try { const b = await res.json(); msg = b.detail || msg; } catch (_) {}
      throw new Error(msg);
    }

    return res.json();
  },

  // ── Two-factor authentication (TOTP) ───────────────────────────────────────
  async totpStatus() {
    const res = await fetch('/api/auth/totp');
    await this._checkOk(res, '/api/auth/totp');
    return res.json();
  },
  async totpEnroll() {
    const res = await fetch('/api/auth/totp/enroll', { method: 'POST' });
    await this._checkOk(res, '/api/auth/totp/enroll');
    return res.json();
  },
  async totpConfirm(code) {
    const res = await fetch('/api/auth/totp/confirm', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }),
    });
    await this._checkOk(res, '/api/auth/totp/confirm');
    return res.json();
  },
  async totpDisable(password, code) {
    const res = await fetch('/api/auth/totp/disable', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password, code }),
    });
    await this._checkOk(res, '/api/auth/totp/disable');
    return res.json();
  },

  async totpRecoveryCodes(password, code) {
    const res = await fetch('/api/auth/totp/recovery-codes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password, code }),
    });
    await this._checkOk(res, '/api/auth/totp/recovery-codes');
    return res.json();
  },

  async securityStatus() {
    const res = await fetch('/api/security/status');
    await this._checkOk(res, '/api/security/status');
    return res.json();
  },

  /** Passphrase-encrypted case archive (no evidence images). Triggers a browser download. */
  async downloadCasePackage(caseId, passphrase) {
    const url = `/api/cases/${caseId}/package`;
    const fd = new FormData();
    fd.append('passphrase', passphrase);
    const res = await fetch(url, { method: 'POST', body: fd });
    await this._checkOk(res, url);
    const blob = await res.blob();
    const disp = res.headers.get('Content-Disposition') || '';
    const m = disp.match(/filename="?([^";]+)"?/);
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = m ? m[1] : 'case.sihpkg';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    return { size_bytes: blob.size };
  },

  /** Logout — clears the session cookie on the server. */
  async logout() {
    const url = '/api/auth/logout';
    const res = await fetch(url, { method: 'POST' });
    // Best-effort — even if it fails, the client navigates to login
    return res.ok;
  },

  // ── Case endpoints ─────────────────────────────────────────────────────────

  async listCases() {
    const url = '/api/cases';
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  },

  async getCase(id) {
    const url = `/api/cases/${id}`;
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  },

  /**
   * Retrieve a single evidence record by deriving it from the case.
   * The backend embeds the evidence array in GET /api/cases/{id}.
   * If evidenceId is omitted, returns the most recently loaded evidence.
   */
  async getEvidence(caseId, evidenceId) {
    const caseObj = await this.getCase(caseId);
    const evidenceList = caseObj.evidence ?? [];
    if (evidenceList.length === 0) {
      throw new Error(`Case ${caseId} has no evidence loaded yet.`);
    }
    if (!evidenceId) {
      return evidenceList[evidenceList.length - 1];
    }
    const ev = evidenceList.find(e => String(e.evidence_id) === String(evidenceId));
    if (!ev) {
      throw new Error(`Evidence ${evidenceId} not found in case ${caseId}.`);
    }
    return ev;
  },

  async createCase(data) {
    const url = '/api/cases';
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        case_number: data.case_number,
        examiner: data.examiner || data.investigator_name,
        notes: data.notes
      })
    });
    await this._checkOk(res, url);
    return res.json();
  },

  async addEvidence(caseId, filePath, label, deviceUtcOffsetMinutes) {
    const url = `/api/cases/${caseId}/evidence`;
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: filePath,
        label,
        device_utc_offset_minutes: deviceUtcOffsetMinutes ?? null,
      })
    });
    await this._checkOk(res, url);
    return res.json();
  },

  async uploadEvidence(caseId, file, deviceUtcOffsetMinutes, onProgress) {
    const url = `/api/cases/${caseId}/evidence/upload`;
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', url);

      if (onProgress && xhr.upload) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            const percent = Math.round((e.loaded / e.total) * 100);
            onProgress(percent, e.loaded, e.total);
          }
        };
      }

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch (_) {
            reject(new Error('Invalid response from server'));
          }
        } else {
          try {
            const data = JSON.parse(xhr.responseText);
            reject(new Error(data.detail || data.message || `Upload failed (${xhr.status})`));
          } catch (_) {
            reject(new Error(`Upload failed (${xhr.status})`));
          }
        }
      };

      xhr.onerror = () => {
        reject(new Error('Network error during evidence upload'));
      };

      const formData = new FormData();
      formData.append('file', file);
      if (deviceUtcOffsetMinutes !== null && deviceUtcOffsetMinutes !== undefined && deviceUtcOffsetMinutes !== '') {
        formData.append('device_utc_offset_minutes', deviceUtcOffsetMinutes);
      }

      xhr.send(formData);
    });
  },

  async startScan(caseId, evidenceId) {
    const url = `/api/cases/${caseId}/scan` + (evidenceId ? `?evidence_id=${encodeURIComponent(evidenceId)}` : '');
    const res = await fetch(url, { method: 'POST' });
    await this._checkOk(res, url);
    return res.json();
  },

  listenScanProgress(caseId, evidenceId, onProgress, onComplete, onError) {
    const source = new EventSource(`/api/cases/${caseId}/status`);
    source.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'ping') return;
      if (data.type === 'done') {
        source.close();
        onComplete(data);
        return;
      }
      onProgress(data);
      if (data.phase === 'DONE') {
        source.close();
        onComplete(data);
      } else if (data.phase === 'ERROR') {
        source.close();
        onError(data.message);
      }
    };
    source.onerror = () => {
      source.close();
      onError('Connection to scan stream lost. The scan may still be running — refresh to check.');
    };
  },

  async getSegments(caseId, evidenceId) {
    const url = evidenceId
      ? `/api/cases/${caseId}/segments?evidence_id=${encodeURIComponent(evidenceId)}`
      : `/api/cases/${caseId}/segments`;
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  },

  /** Retrieve all recovered case segments pre-grouped for the timeline view. */
  async getTimeline(caseId) {
    const url = `/api/cases/${caseId}/timeline`;
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  },

  /**
   * Cross-camera event correlation: segments whose time windows overlap
   * across 2+ distinct cameras. Time-window clustering only, not content
   * analysis — see backend/correlation.py.
   */
  async getCorrelation(caseId) {
    const url = `/api/cases/${caseId}/correlation`;
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  },

  async exportSegment(caseId, evidenceId, segmentId) {
    const url = `/api/cases/${caseId}/export/${segmentId}`;
    const res = await fetch(url, { method: 'POST' });
    await this._checkOk(res, url);
    return res.json();
  },

  async detectMotion(caseId, segmentId) {
    const url = `/api/cases/${caseId}/motion/${segmentId}`;
    const res = await fetch(url, { method: 'POST' });
    await this._checkOk(res, url);
    return res.json();
  },

  /** Object detection (YOLOX if a model file is installed, otherwise the classical HOG person detector). */
  async detectObjects(caseId, segmentId) {
    const url = `/api/cases/${caseId}/object-detect/${segmentId}`;
    const res = await fetch(url, { method: 'POST' });
    await this._checkOk(res, url);
    return res.json();
  },

  async getObjectResults(caseId) {
    const url = `/api/cases/${caseId}/object-detect`;
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  },

  /**
   * Batch export segments with limited concurrency (max 2).
   * Continues past individual failures, supports cancellation,
   * reports progress via onProgress({ done, total, message }).
   */
  async batchExport(caseId, evidenceId, segments, { onProgress, shouldCancel } = {}) {
    const list = segments || [];
    const total = list.length;
    let completed = 0;
    let nextIndex = 0;
    const failures = [];
    let cancelled = false;

    if (total === 0) {
      return { total: 0, completed: 0, cancelled: false, failures: [] };
    }

    async function worker() {
      while (nextIndex < total) {
        if (shouldCancel && shouldCancel()) {
          cancelled = true;
          break;
        }
        const idx = nextIndex++;
        const seg = list[idx];
        if (onProgress) {
          onProgress({
            done: completed,
            total,
            message: `Exporting segment ${completed + 1} of ${total} (Camera ${seg.camera ?? '?'})`,
          });
        }
        try {
          const res = await API.exportSegment(caseId, evidenceId, seg.segment_id);
          const detail = (res && res.detail) || {};
          if (detail.error) {
            failures.push({
              segment_id: seg.segment_id,
              camera: seg.camera,
              error: detail.error,
            });
          }
        } catch (err) {
          failures.push({
            segment_id: seg.segment_id,
            camera: seg.camera,
            error: err.message || 'Export request failed',
          });
        }
        completed++;
        if (onProgress) {
          onProgress({
            done: completed,
            total,
            message: `${completed} of ${total} done`,
          });
        }
      }
    }

    const workers = [worker()];
    if (total > 1) {
      workers.push(worker());
    }
    await Promise.all(workers);

    return { total, completed, cancelled, failures };
  },

  /**
   * Run motion, face, and object detection for every exported segment with limited concurrency (max 2).
   * Continues past individual failures, supports cancellation,
   * reports progress via onProgress({ done, total, message }).
   */
  async batchAnalytics(caseId, exportedSegments, { onProgress, shouldCancel } = {}) {
    const list = exportedSegments || [];
    const total = list.length;
    let completed = 0;
    let nextIndex = 0;
    const failures = [];
    let cancelled = false;

    if (total === 0) {
      return { total: 0, completed: 0, cancelled: false, failures: [] };
    }

    async function worker() {
      while (nextIndex < total) {
        if (shouldCancel && shouldCancel()) {
          cancelled = true;
          break;
        }
        const idx = nextIndex++;
        const seg = list[idx];
        if (onProgress) {
          onProgress({
            done: completed,
            total,
            message: `Analyzing segment ${completed + 1} of ${total} (Camera ${seg.camera ?? '?'})`,
          });
        }

        // 1. Motion detection
        if (!shouldCancel || !shouldCancel()) {
          try {
            await API.detectMotion(caseId, seg.segment_id);
          } catch (err) {
            failures.push({
              segment_id: seg.segment_id,
              camera: seg.camera,
              type: 'Motion',
              error: err.message || 'Motion detection failed',
            });
          }
        }

        // 2. Face detection
        if (!shouldCancel || !shouldCancel()) {
          try {
            await API.detectFaces(caseId, seg.segment_id);
          } catch (err) {
            failures.push({
              segment_id: seg.segment_id,
              camera: seg.camera,
              type: 'Face',
              error: err.message || 'Face detection failed',
            });
          }
        }

        // 3. Object detection
        if (!shouldCancel || !shouldCancel()) {
          try {
            await API.detectObjects(caseId, seg.segment_id);
          } catch (err) {
            failures.push({
              segment_id: seg.segment_id,
              camera: seg.camera,
              type: 'Object',
              error: err.message || 'Object detection failed',
            });
          }
        }

        completed++;
        if (onProgress) {
          onProgress({
            done: completed,
            total,
            message: `${completed} of ${total} done`,
          });
        }
      }
    }

    const workers = [worker()];
    if (total > 1) {
      workers.push(worker());
    }
    await Promise.all(workers);

    return { total, completed, cancelled, failures };
  },


  /** Drive imaging (only enabled when the server runs locally with FORENSIC_ALLOW_LOCAL_ACQUISITION=1). */
  async getDrives() {
    const url = '/api/acquisition/drives';
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  },

  async startAcquisition(caseId, body) {
    const url = `/api/cases/${caseId}/acquire`;
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    await this._checkOk(res, url);
    return res.json();
  },

  async getAcquisitionStatus(caseId) {
    const url = `/api/cases/${caseId}/acquire/status`;
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  },

  /** AI-Based Face Detection (OpenCV YuNet) — detection only, no recognition/identification. */
  async detectFaces(caseId, segmentId) {
    const url = `/api/cases/${caseId}/face-detect/${segmentId}`;
    const res = await fetch(url, { method: 'POST' });
    await this._checkOk(res, url);
    return res.json();
  },

  /**
   * Face similarity search: upload a reference photo, search across every
   * segment already indexed (via detectFaces) for this case. Results are
   * similarity candidates for human review, NOT confirmed identity matches.
   */
  async searchFaces(caseId, imageFile) {
    const url = `/api/cases/${caseId}/face-search`;
    const formData = new FormData();
    formData.append('reference_image', imageFile);
    const res = await fetch(url, { method: 'POST', body: formData });
    await this._checkOk(res, url);
    return res.json();
  },

  /**
   * Measure a recovered segment against ground truth (a known-good video, a recording log,
   * and/or the original pre-deletion disk image). Anything not supplied comes back as "not measured".
   */
  async runAccuracy(caseId, formData) {
    const url = `/api/cases/${caseId}/accuracy`;
    const res = await fetch(url, { method: 'POST', body: formData });
    await this._checkOk(res, url);
    return res.json();
  },

  async getAccuracy(caseId) {
    const url = `/api/cases/${caseId}/accuracy`;
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  },

  async verifyEvidenceIntegrity(caseId, evidenceId) {
    const url = `/api/cases/${caseId}/verify` + (evidenceId ? `?evidence_id=${encodeURIComponent(evidenceId)}` : '');
    const res = await fetch(url);
    await this._checkOk(res, url);
    const data = await res.json();
    // Backend returns {unchanged, sha256} — normalise to {match, current_sha256}
    return { match: data.unchanged, current_sha256: data.sha256 };
  },

  /**
   * Generate a PDF forensic report.
   * The backend returns a FileResponse (binary PDF).
   * We trigger a browser download and return metadata for the UI.
   */
  async getCertificate(caseId) {
    const url = `/api/cases/${caseId}/certificate`;
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  },

  async saveCertificate(caseId, values) {
    const url = `/api/cases/${caseId}/certificate`;
    const res = await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    });
    await this._checkOk(res, url);
    return res.json();
  },

  async generateReport(caseId, evidenceId) {
    const url = `/api/cases/${caseId}/report` + (evidenceId ? `?evidence_id=${encodeURIComponent(evidenceId)}` : '');
    const res = await fetch(url);
    await this._checkOk(res, url);
    const blob = await res.blob();
    // Build a filename from Content-Disposition header if available
    const disp = res.headers.get('Content-Disposition') || '';
    const match = disp.match(/filename="?([^";]+)"?/);
    const filename = match ? match[1] : `report_case_${caseId}.pdf`;
    // Trigger browser download
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    return { filename, size_bytes: blob.size, file_path: filename };
  },

  async getAuditLog(caseId) {
    const url = `/api/cases/${caseId}/audit`;
    const res = await fetch(url);
    await this._checkOk(res, url);
    return res.json();
  }
};
