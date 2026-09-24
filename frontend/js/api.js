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
  async login(password) {
    const url = '/api/auth/login';
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });

    if (res.status === 429) {
      // Lockout — return the lockout payload instead of throwing
      const data = await res.json();
      return { locked: true, retry_after: data.retry_after || 60 };
    }

    if (res.status === 401) {
      throw new Error('Incorrect password.');
    }

    if (!res.ok) {
      let msg = 'Login failed.';
      try { const b = await res.json(); msg = b.detail || msg; } catch (_) {}
      throw new Error(msg);
    }

    return res.json();
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

  async startScan(caseId) {
    const url = `/api/cases/${caseId}/scan`;
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

  async verifyEvidenceIntegrity(caseId) {
    const url = `/api/cases/${caseId}/verify`;
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
  async generateReport(caseId) {
    const url = `/api/cases/${caseId}/report`;
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
