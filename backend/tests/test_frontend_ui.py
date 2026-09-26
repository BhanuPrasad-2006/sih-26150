"""Static guards for the front-end design system: icons exist, CSS variables used by the pages are defined,
and the icon script loads before anything that calls it. (Visual checks are done in a browser; these catch
the typos a browser would only show as a missing icon or an unstyled element.)"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "frontend"
JS = sorted((ROOT / "js").rglob("*.js"))
CSS = (ROOT / "css" / "style.css").read_text(encoding="utf-8")
ICONS_JS = (ROOT / "js" / "icons.js").read_text(encoding="utf-8")
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")


def _defined_icons() -> set[str]:
    block = ICONS_JS[ICONS_JS.index("const ICON_PATHS"):ICONS_JS.index("function icon(")]
    return set(re.findall(r"^\s*'?([a-z][a-z0-9-]*)'?:\s*'", block, flags=re.M))


def test_every_icon_used_in_the_pages_exists():
    defined = _defined_icons()
    assert len(defined) > 30
    used = set()
    for f in JS:
        if f.name == "icons.js":
            continue
        text = f.read_text(encoding="utf-8")
        used |= set(re.findall(r"\bicon\('([a-z0-9-]+)'", text))
        used |= set(re.findall(r"\biconChip\('([a-z0-9-]+)'", text))
        used |= set(re.findall(r"\bicon: '([a-z0-9-]+)'", text))
    missing = sorted(used - defined)
    assert not missing, f"icons used but not defined: {missing}"


def test_icon_script_loads_before_the_scripts_that_use_it():
    order = re.findall(r'<script src="/js/([^"?]+)', INDEX)
    assert order[0] == "icons.js"
    assert order.index("icons.js") < order.index("api.js") < order.index("app.js")


def test_css_variables_used_by_the_pages_are_defined():
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", CSS))
    used = set()
    for f in JS:
        used |= set(re.findall(r"var\((--[a-z0-9-]+)", f.read_text(encoding="utf-8")))
    used |= set(re.findall(r"var\((--[a-z0-9-]+)", INDEX))
    missing = sorted(used - defined)
    assert not missing, f"CSS variables used in the pages but never defined: {missing}"


def test_dark_theme_redefines_the_surface_and_text_tokens():
    for token in ("--bg-primary", "--bg-card", "--text-main", "--text-muted", "--border-color", "--bg-input"):
        assert len(re.findall(re.escape(token) + r"\s*:", CSS)) >= 3, f"{token} needs light, system-dark and manual-dark values"


def test_no_hard_coded_light_on_dark_colours_left_in_page_templates():
    for f in JS:
        if f.name == "icons.js":
            continue
        text = f.read_text(encoding="utf-8")
        assert "rgba(255,255,255" not in text.replace(" ", ""), f"{f.name}: use theme tokens instead of white-on-dark rgba"


def test_no_emoji_left_in_the_interface_code():
    pat = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐✅❌]")
    for f in JS:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith(("//", "*", "/*")):
                continue
            assert not pat.search(line), f"{f.name}:{n} still uses an emoji instead of an icon"


def test_upload_zone_keeps_the_element_ids_the_upload_logic_depends_on():
    text = (ROOT / "js" / "screens" / "CaseDetailScreen.js").read_text(encoding="utf-8")
    for element_id in ("modal-ev-file-input", "modal-ev-browse-btn", "modal-ev-file-name", "modal-ev-file-clear",
                       "modal-ev-path", "modal-acq-area", "modal-ev-progress-box", "modal-ev-progress-bar",
                       "modal-ev-progress-pct", "modal-ev-progress-status", "modal-ev-error-msg"):
        assert f'id="{element_id}"' in text, element_id


def test_scan_screen_no_longer_auto_redirects_and_labels_the_real_format():
    text = (ROOT / "js" / "screens" / "EvidenceScanScreen.js").read_text(encoding="utf-8")
    assert "}, 1200)" not in text, "the scan must not navigate away on its own"
    assert "View recordings" in text
    assert "Raw Binary (.dd)" not in text, "format label must come from the file, not be hard-coded"
    assert "evidenceFormatLabel(ev.path)" in text


def test_unverified_brands_get_a_warning_badge_not_the_verified_one():
    text = (ROOT / "js" / "screens" / "EvidenceScanScreen.js").read_text(encoding="utf-8")
    body = text[text.index("function brandBadge"):text.index("async function renderEvidenceScanScreen")]
    assert "unverified" in body and "unvalidated" in body and "detection-only" in body
    assert "badge-partial" in body and "badge-verified" in body


def test_recordings_screen_has_batch_actions_and_progress_elements():
    rec_text = (ROOT / "js" / "screens" / "RecordingsScreen.js").read_text(encoding="utf-8")
    for el_id in ("btn-batch-export", "btn-batch-analytics", "btn-batch-cancel",
                  "batch-progress-box", "batch-progress-label", "batch-progress-bar", "batch-progress-pct"):
        assert f'id="{el_id}"' in rec_text, f"Missing element ID: {el_id}"
    assert "Export all segments" in rec_text
    assert "Run all analytics on exported" in rec_text
    assert "handleBatchResult" in rec_text


def test_api_has_batch_methods_with_concurrency_and_cancellation():
    api_text = (ROOT / "js" / "api.js").read_text(encoding="utf-8")
    assert "async batchExport(" in api_text
    assert "async batchAnalytics(" in api_text
    assert "shouldCancel" in api_text
    assert "workers.push(worker())" in api_text


def test_batch_bar_css_classes_defined():
    for cls_name in (".batch-bar", ".batch-bar-controls", ".batch-progress-box",
                     ".batch-progress-row", ".batch-progress-text", ".batch-progress-pct"):
        assert cls_name in CSS, f"Missing CSS class: {cls_name}"


def test_recordings_screen_has_compact_ai_detections_column():
    rec_text = (ROOT / "js" / "screens" / "RecordingsScreen.js").read_text(encoding="utf-8")
    assert "<th>AI Detections</th>" in rec_text
    assert "<th>Basic Motion Detection</th>" not in rec_text
    assert "<th>AI-Based Face Detection</th>" not in rec_text
    assert "<th>Object Detection</th>" not in rec_text
    assert "ai-pills" in rec_text
    assert "ai-pill" in rec_text
    assert "btn-compact" in rec_text


def test_ai_pills_css_classes_defined():
    for cls_name in (".ai-pills", ".ai-pill", ".ai-pill-active", ".ai-pill-muted",
                     ".ai-pill-disabled", ".btn-compact"):
        assert cls_name in CSS, f"Missing CSS class: {cls_name}"


def test_timeline_has_zoom_presets_and_hover_card():
    tl_text = (ROOT / "js" / "screens" / "TimelineScreen.js").read_text(encoding="utf-8")
    assert "timeline-zoom-controls" in tl_text
    assert "timeline-zoom-btn" in tl_text
    for preset in ("1h", "6h", "24h", "all"):
        assert f'data-zoom="{preset}"' in tl_text
    assert "timelineTicksForRange" in tl_text
    assert "timeline-hover-card" in tl_text
    assert "highlightSegmentId" in tl_text


def test_recordings_screen_has_highlight_handler():
    rec_text = (ROOT / "js" / "screens" / "RecordingsScreen.js").read_text(encoding="utf-8")
    assert "highlightSegmentId" in rec_text
    assert "row-highlight" in rec_text
    assert "segment-row-" in rec_text


def test_timeline_improvements_css_classes_defined():
    for cls_name in (".timeline-hover-card", ".timeline-zoom-controls",
                     ".timeline-zoom-btn", ".row-highlight"):
        assert cls_name in CSS, f"Missing CSS class: {cls_name}"


def test_toast_component_and_script_loaded():
    assert "Toast.js" in INDEX
    toast_file = ROOT / "js" / "components" / "Toast.js"
    assert toast_file.is_file()
    toast_text = toast_file.read_text(encoding="utf-8")
    assert "function showToast(" in toast_text
    assert "function dismissToast(" in toast_text
    assert "toast-container" in toast_text
    assert "TOAST_MAX_COUNT" in toast_text
    assert "aria-live" in toast_text


def test_toast_css_classes_defined():
    css = (ROOT / "css" / "style.css").read_text(encoding="utf-8")
    for cls_name in (".toast-container", ".toast", ".toast-success", ".toast-info",
                     ".toast-warn", ".toast-error", ".toast-close"):
        assert cls_name in css, f"Missing CSS class: {cls_name}"


def test_screens_use_toasts_for_transient_confirmations():
    rec_text = (ROOT / "js" / "screens" / "RecordingsScreen.js").read_text(encoding="utf-8")
    assert "showToast(" in rec_text
    assert "Export complete:" in rec_text

    scan_text = (ROOT / "js" / "screens" / "EvidenceScanScreen.js").read_text(encoding="utf-8")
    assert "showToast(" in scan_text
    assert "Integrity MATCH:" in scan_text

    rep_text = (ROOT / "js" / "screens" / "ExportReportScreen.js").read_text(encoding="utf-8")
    assert "showToast(" in rep_text
    assert "PDF report generated:" in rep_text


def test_header_has_case_context_pill():
    hdr_text = (ROOT / "js" / "components" / "Header.js").read_text(encoding="utf-8")
    assert "case-context-pill" in hdr_text
    assert "updateHeaderContext" in hdr_text
    assert "btn-pill-verify" in hdr_text

    app_text = (ROOT / "js" / "app.js").read_text(encoding="utf-8")
    assert "updateHeaderContext(" in app_text

    css = (ROOT / "css" / "style.css").read_text(encoding="utf-8")
    for cls_name in (".case-context-pill", ".case-pill-info", ".case-pill-id",
                     ".case-pill-evidence", ".case-pill-integrity"):
        assert cls_name in css, f"Missing CSS class: {cls_name}"







def test_recordings_screen_offers_playback_only_for_exported_segments():
    text = (ROOT / "js" / "screens" / "RecordingsScreen.js").read_text(encoding="utf-8")
    assert "function playSegment" in text and "segmentVideoUrl(" in text
    assert "${isExported ? playButtonHtml(" in text, "Play must only be shown once an MP4 exists"
    app = (ROOT / "js" / "app.js").read_text(encoding="utf-8")
    assert "play: playSegment" in app
    assert "/video/" in (ROOT / "js" / "api.js").read_text(encoding="utf-8")


def test_generic_carving_gets_an_explanation_instead_of_a_bare_zero_percent():
    text = (ROOT / "js" / "screens" / "EvidenceScanScreen.js").read_text(encoding="utf-8")
    assert "Generic stream carving active" in text and "What this means" in text
    assert "Confidence: <strong>" not in text


def test_export_screen_has_the_certificate_details_form_and_saves_before_generating():
    text = (ROOT / "js" / "screens" / "ExportReportScreen.js").read_text(encoding="utf-8")
    assert 'id="cert-form"' in text and 'id="btn-save-cert"' in text
    assert text.index("await saveCertForm()") < text.index("await API.generateReport(")
    assert "escapeHtml(f.label)" in text and "escapeHtml(cert.values[f.key]" in text
