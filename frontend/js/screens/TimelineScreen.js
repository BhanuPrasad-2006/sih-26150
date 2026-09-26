/**
 * TimelineScreen.js — Shared timeline for every recovered segment in a case.
 *
 * The API provides timestamp-sorted camera lanes and per-lane uncovered gaps.
 * This screen only presents that data; it never changes recovered segments.
 */

function timelineFormatUtc(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Unknown time';
  return date.toISOString().replace('T', ' ').replace('.000Z', '');
}

function timelineDuration(seconds) {
  const wholeSeconds = Math.max(0, Math.round(seconds || 0));
  const hours = Math.floor(wholeSeconds / 3600);
  const minutes = Math.floor((wholeSeconds % 3600) / 60);
  const remainder = wholeSeconds % 60;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${remainder}s`;
  return `${remainder}s`;
}

function timelineEscapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[character]));
}

function timelineStatusClass(status) {
  switch ((status || '').toUpperCase()) {
    case 'COMPLETE': return 'timeline-segment--complete';
    case 'PARTIAL': return 'timeline-segment--partial';
    case 'UNCERTAIN': return 'timeline-segment--uncertain';
    default: return 'timeline-segment--unknown';
  }
}

function timelinePercent(value, rangeStart, rangeMs) {
  const point = new Date(value).getTime();
  if (rangeMs <= 0 || Number.isNaN(point)) return 0;
  return Math.max(0, Math.min(100, ((point - rangeStart) / rangeMs) * 100));
}

function timelineTicks(startTime, endTime) {
  return timelineTicksForRange(startTime, endTime, 'all');
}

function timelineTicksForRange(startTime, endTime, zoomPreset = 'all') {
  const start = new Date(startTime).getTime();
  const end = new Date(endTime).getTime();
  const range = Math.max(0, end - start);
  if (range <= 0) return [];

  let intervalMs = 0;
  if (zoomPreset === '1h') intervalMs = 15 * 60 * 1000;       // 15 minutes
  else if (zoomPreset === '6h') intervalMs = 60 * 60 * 1000;   // 1 hour
  else if (zoomPreset === '24h') intervalMs = 4 * 3600 * 1000; // 4 hours

  // If 'all' or if the range is too small for the interval
  if (!intervalMs || range < intervalMs * 1.5) {
    return Array.from({ length: 5 }, (_, index) => {
      const offset = range * (index / 4);
      return {
        left: index * 25,
        label: timelineFormatUtc(new Date(start + offset).toISOString())
      };
    });
  }

  const ticks = [];
  let current = Math.ceil(start / intervalMs) * intervalMs;
  if (((current - start) / range) * 100 > 10) {
    ticks.push({
      left: 0,
      label: timelineFormatUtc(new Date(start).toISOString())
    });
  }

  while (current <= end) {
    const leftPct = ((current - start) / range) * 100;
    ticks.push({
      left: leftPct,
      label: timelineFormatUtc(new Date(current).toISOString())
    });
    current += intervalMs;
  }

  return ticks;
}

function renderTimelineSegment(segment, rangeStart, rangeMs, caseId, defaultEvidenceId) {
  const left = timelinePercent(segment.start_time, rangeStart, rangeMs);
  const end = timelinePercent(segment.end_time, rangeStart, rangeMs);
  const width = Math.min(100 - left, Math.max(1.25, end - left));
  const status = (segment.status || 'UNCERTAIN').toUpperCase();
  const evId = segment.evidence_id || defaultEvidenceId || '';

  return `
    <div class="timeline-segment ${timelineStatusClass(status)}"
      data-segment-id="${escapeHtml(segment.segment_id)}"
      data-evidence-id="${escapeHtml(evId)}"
      data-camera="${escapeHtml(String(segment.camera ?? ''))}"
      data-start="${escapeHtml(segment.start_time || '')}"
      data-end="${escapeHtml(segment.end_time || '')}"
      data-frames="${escapeHtml(String(segment.frame_count || 0))}"
      data-status="${escapeHtml(status)}"
      data-sha256="${escapeHtml(segment.sha256 || '')}"
      data-notes="${escapeHtml(segment.notes || '')}"
      ${navAttrs('recordings', { caseId, evidenceId: evId, highlightSegmentId: segment.segment_id })}
      style="left:${left}%; width:${width}%;"
      aria-label="Camera ${escapeHtml(String(segment.camera))}: ${escapeHtml(timelineFormatUtc(segment.start_time))} to ${escapeHtml(timelineFormatUtc(segment.end_time))}, ${escapeHtml(status)}">
      <span class="timeline-segment-label">${status}</span>
    </div>`;
}

function renderTimelineGap(gap, rangeStart, rangeMs) {
  const left = timelinePercent(gap.start_time, rangeStart, rangeMs);
  const end = timelinePercent(gap.end_time, rangeStart, rangeMs);
  const width = Math.min(100 - left, Math.max(0.6, end - left));
  const title = `Gap: ${timelineFormatUtc(gap.start_time)} — ${timelineFormatUtc(gap.end_time)} (${timelineDuration(gap.duration_seconds)})`;
  const label = gap.duration_seconds >= 60 ? timelineDuration(gap.duration_seconds) : '';

  return `
    <div class="timeline-gap" style="left:${left}%; width:${width}%;" title="${timelineEscapeHtml(title)}">
      ${label ? `<span class="timeline-gap-label">Gap ${label}</span>` : ''}
    </div>`;
}

function renderTimelineLane(lane, rangeStart, rangeMs, caseId, defaultEvidenceId) {
  return `
    <section class="timeline-lane" aria-label="Camera ${lane.camera} timeline">
      <div class="timeline-lane-label">
        <strong>Camera ${lane.camera}</strong>
        <span>${lane.segments.length} segment${lane.segments.length === 1 ? '' : 's'}</span>
      </div>
      <div class="timeline-lane-track">
        ${lane.gaps.map(gap => renderTimelineGap(gap, rangeStart, rangeMs)).join('')}
        ${lane.segments.map(segment => renderTimelineSegment(segment, rangeStart, rangeMs, caseId, defaultEvidenceId)).join('')}
      </div>
    </section>`;
}

function renderCorrelationCard(correlation) {
  if (!correlation) return '';
  const events = correlation.events || [];

  return `
    <div class="card">
      <div class="card-title">
        <span>Cross-Camera Correlated Events</span>
      </div>
      <p style="font-size:12px; color:var(--text-dim); margin:0 0 12px; line-height:1.6;">
        Segments whose time windows overlap across 2 or more cameras, clustered purely by time proximity —
        this is not content analysis and does not claim the events are related; independently confirm relevance.
        ${correlation.any_evidence_normalized
          ? 'Timestamps from evidence with a confirmed device clock offset were normalized to UTC before correlating.'
          : 'No evidence in this case has a confirmed device clock offset, so raw device-reported timestamps were used as-is — correlation across different devices may be unreliable if their clocks differ.'}
      </p>
      ${events.length === 0
        ? `<div class="empty-state" style="padding:24px 0;">
             <div class="empty-state-subtitle">No overlapping activity was found across different cameras.</div>
           </div>`
        : `<div class="table-container">
             <table>
               <thead>
                 <tr><th>Start</th><th>End</th><th>Duration</th><th>Cameras</th><th>Segments</th></tr>
               </thead>
               <tbody>
                 ${events.map(ev => `
                   <tr>
                     <td>${timelineFormatUtc(ev.start_time)}</td>
                     <td>${timelineFormatUtc(ev.end_time)}</td>
                     <td>${timelineDuration(ev.duration_seconds)}</td>
                     <td>${ev.cameras.map(c => `<span class="badge badge-verified" style="margin-right:4px;">Cam ${c}</span>`).join('')}</td>
                     <td style="color:var(--text-dim); font-size:12px;">${ev.segment_ids.length} segment${ev.segment_ids.length === 1 ? '' : 's'}</td>
                   </tr>`).join('')}
               </tbody>
             </table>
           </div>`}
    </div>`;
}

async function renderTimelineScreen(params) {
  const { caseId } = params;
  const root = document.getElementById('content-root');

  root.innerHTML = `
    <div class="loading-state">
      <div class="spinner"></div>
      <p>Building cross-camera timeline…</p>
    </div>`;

  let timeline;
  let correlation = null;
  try {
    timeline = await API.getTimeline(caseId);
    // Correlation is a supplementary panel — don't fail the whole screen if it errors.
    correlation = await API.getCorrelation(caseId).catch(() => null);
  } catch (err) {
    root.innerHTML = `
      <div class="page-header"><div class="page-title">Cross-Camera Timeline</div></div>
      <div class="error-banner">
        <div class="error-banner-icon">${icon('alert')}</div>
        <div class="error-banner-body">
          <div class="error-banner-title">Failed to load timeline</div>
          <div class="error-banner-msg">${escapeHtml(err.message)}</div>
        </div>
      </div>`;
    return;
  }

  const lanes = timeline.lanes || [];
  const segmentCount = lanes.reduce((count, lane) => count + lane.segments.length, 0);
  const gapCount = lanes.reduce((count, lane) => count + lane.gaps.length, 0);

  if (!timeline.start_time || !timeline.end_time || segmentCount === 0) {
    // Distinguish "nothing recovered yet" from "recovered, but no timestamps":
    // some recorders (e.g. Hikvision, generic stream carving) yield footage whose
    // timestamps cannot be read, so it cannot be placed on a time axis.
    const allSegments = await API.getSegments(caseId).catch(() => []);
    const hasUntimed = allSegments.length > 0;
    const title = hasUntimed
      ? 'Recovered segments have no readable timestamps'
      : 'No segments recovered yet';
    const subtitle = hasUntimed
      ? `${allSegments.length} segment(s) were recovered, but this recorder's timestamps could not be read, so they cannot be placed on a shared time axis. Open the recordings list to review and export them.`
      : 'Run a scan to recover segments, then return here to compare cameras on one timeline.';
    root.innerHTML = `
      <div class="page-header">
        <div class="page-title">Cross-Camera Timeline</div>
        <div class="page-subtitle">A shared view of recovered footage across every camera and evidence image in this case.</div>
      </div>
      <div class="card empty-state">
        ${emptyArt()}
        <div class="empty-state-title">${title}</div>
        <div class="empty-state-subtitle">${subtitle}</div>
        <button class="btn btn-primary" ${navAttrs('case-detail', { caseId: caseId })}>Return to Case Overview</button>
      </div>`;
    return;
  }

  const rangeStart = new Date(timeline.start_time).getTime();
  const rangeMs = Math.max(0, new Date(timeline.end_time).getTime() - rangeStart);
  const ticks = timelineTicks(timeline.start_time, timeline.end_time);

  root.innerHTML = `
    <div class="page-header">
      <div class="page-title">Cross-Camera Timeline</div>
      <div class="page-subtitle">All recovered, timestamped segments are placed on one axis using each recorder's own clock. Striped intervals indicate periods without recovered footage on that camera.</div>
    </div>

    <div class="timeline-summary-grid">
      <div class="timeline-summary-card"><span>Time Range</span><strong>${timelineFormatUtc(timeline.start_time)} — ${timelineFormatUtc(timeline.end_time)}</strong></div>
      <div class="timeline-summary-card"><span>Recovered Segments</span><strong>${segmentCount} across ${lanes.length} camera${lanes.length === 1 ? '' : 's'}</strong></div>
      <div class="timeline-summary-card"><span>Detected Gaps</span><strong>${gapCount} interval${gapCount === 1 ? '' : 's'} · ${timelineDuration(timeline.duration_seconds)}</strong></div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>Shared Timeline</span>
        <div class="timeline-zoom-controls" role="toolbar" aria-label="Timeline zoom presets">
          <span class="timeline-zoom-label">Zoom:</span>
          <button type="button" class="btn btn-secondary timeline-zoom-btn" data-zoom="1h">1h</button>
          <button type="button" class="btn btn-secondary timeline-zoom-btn" data-zoom="6h">6h</button>
          <button type="button" class="btn btn-secondary timeline-zoom-btn" data-zoom="24h">24h</button>
          <button type="button" class="btn btn-secondary timeline-zoom-btn active" data-zoom="all">All</button>
        </div>
        <div class="status-legend" aria-label="Segment status legend">
          <span class="status-legend-item">Segments:</span>
          <span class="badge badge-complete">COMPLETE</span>
          <span class="badge badge-partial">PARTIAL</span>
          <span class="badge badge-uncertain">UNCERTAIN</span>
          <span class="timeline-gap-key"><i></i> Gap</span>
        </div>
      </div>
      <div class="timeline-scroll">
        <div class="timeline-content">
          <div class="timeline-axis">
            <div class="timeline-axis-label">Recorder time</div>
            <div class="timeline-axis-track">
              ${ticks.map(tick => `<span class="timeline-tick" style="left:${tick.left}%">${tick.label}</span>`).join('')}
            </div>
          </div>
          ${lanes.map(lane => renderTimelineLane(lane, rangeStart, rangeMs, caseId, params.evidenceId)).join('')}
        </div>
      </div>
    </div>

    <div id="timeline-hover-card" class="timeline-hover-card" style="display:none;" role="tooltip" aria-hidden="true"></div>

    ${renderCorrelationCard(correlation)}

    ${timeline.unplaced_segments?.length ? `
      <div class="notice-card">
        <h3>${icon('alert')} ${timeline.unplaced_segments.length} segment${timeline.unplaced_segments.length === 1 ? '' : 's'} not positioned</h3>
        <p>These recovered segments lack a valid start/end timestamp and are therefore excluded from the visual timeline. Review them in Recordings before relying on their chronology.</p>
      </div>` : ''}
  `;

  // ── Hover card interaction ────────────────────────────────────────────────
  const hoverCard = document.getElementById('timeline-hover-card');
  const scrollArea = root.querySelector('.timeline-scroll');

  if (hoverCard && scrollArea) {
    let activeSegment = null;

    const updatePosition = (segmentEl) => {
      const rect = segmentEl.getBoundingClientRect();
      const cardWidth = 260;
      const cardHeight = 110;

      let left = rect.left + rect.width / 2;
      let top = rect.top - 10;

      if (top - cardHeight < 10) {
        top = rect.bottom + cardHeight + 10;
      }

      const halfWidth = cardWidth / 2;
      const minLeft = halfWidth + 10;
      const maxLeft = window.innerWidth - halfWidth - 10;
      if (left < minLeft) left = minLeft;
      if (left > maxLeft) left = maxLeft;

      hoverCard.style.left = `${Math.round(left)}px`;
      hoverCard.style.top = `${Math.round(top)}px`;
    };

    scrollArea.addEventListener('mouseover', (e) => {
      const seg = e.target.closest('.timeline-segment');
      if (!seg) return;
      activeSegment = seg;

      const d = seg.dataset;
      const status = (d.status || 'UNCERTAIN').toUpperCase();
      const badgeClass = timelineStatusClass(status).replace('timeline-segment--', 'badge-');
      const shaShort = d.sha256 ? `${escapeHtml(d.sha256.substring(0, 12))}…` : '—';
      const notesHtml = d.notes ? `<div class="hover-card-notes">${escapeHtml(d.notes)}</div>` : '';

      hoverCard.innerHTML = `
        <div class="hover-card-header">
          <strong>Camera ${escapeHtml(d.camera || '?')}</strong>
          <span class="badge ${escapeHtml(badgeClass)}">${escapeHtml(status)}</span>
        </div>
        <div class="hover-card-time">${escapeHtml(timelineFormatUtc(d.start))} — ${escapeHtml(timelineFormatUtc(d.end))}</div>
        <div class="hover-card-meta">Recorder time · ${escapeHtml(d.frames || '0')} frames</div>
        <div class="hover-card-hash">SHA-256: ${shaShort}</div>
        ${notesHtml}
      `;
      hoverCard.style.display = 'flex';
      hoverCard.setAttribute('aria-hidden', 'false');
      updatePosition(seg);
    });

    scrollArea.addEventListener('mouseout', (e) => {
      const seg = e.target.closest('.timeline-segment');
      if (!seg) return;
      if (seg.contains(e.relatedTarget)) return;

      activeSegment = null;
      hoverCard.style.display = 'none';
      hoverCard.setAttribute('aria-hidden', 'true');
    });

    scrollArea.addEventListener('scroll', () => {
      if (activeSegment) {
        hoverCard.style.display = 'none';
        hoverCard.setAttribute('aria-hidden', 'true');
        activeSegment = null;
      }
    }, { passive: true });
  }

  // ── Zoom presets toolbar ──────────────────────────────────────────────────
  const zoomControls = root.querySelector('.timeline-zoom-controls');
  const timelineContent = root.querySelector('.timeline-content');
  const axisTrack = root.querySelector('.timeline-axis-track');

  if (zoomControls && timelineContent && axisTrack) {
    zoomControls.addEventListener('click', (e) => {
      const btn = e.target.closest('.timeline-zoom-btn');
      if (!btn) return;
      const zoom = btn.dataset.zoom;

      zoomControls.querySelectorAll('.timeline-zoom-btn').forEach(b => {
        b.classList.toggle('active', b === btn);
      });

      let minWidth = '100%';
      if (zoom === '1h') {
        const windowMs = 3600 * 1000;
        const pct = Math.min(5000, Math.max(100, Math.round((rangeMs / windowMs) * 100)));
        minWidth = `${pct}%`;
      } else if (zoom === '6h') {
        const windowMs = 6 * 3600 * 1000;
        const pct = Math.min(5000, Math.max(100, Math.round((rangeMs / windowMs) * 100)));
        minWidth = `${pct}%`;
      } else if (zoom === '24h') {
        const windowMs = 24 * 3600 * 1000;
        const pct = Math.min(5000, Math.max(100, Math.round((rangeMs / windowMs) * 100)));
        minWidth = `${pct}%`;
      } else {
        minWidth = '100%';
      }

      timelineContent.style.minWidth = minWidth;

      const newTicks = timelineTicksForRange(timeline.start_time, timeline.end_time, zoom);
      axisTrack.innerHTML = newTicks.map(tick => `<span class="timeline-tick" style="left:${tick.left}%">${tick.label}</span>`).join('');
    });
  }
}
