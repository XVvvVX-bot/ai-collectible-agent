"""Shared collector UI shell: CSS, navigation, a11y, dev-link gating."""

from __future__ import annotations

import html
import os
from urllib.parse import quote


def show_app_dev_ui() -> bool:
    return os.getenv("APP_SHOW_DEV_UI", "").strip().lower() in {"1", "true", "yes", "on"}


def html_lang_attr(user_language: str | None) -> str:
    """Map profile language to HTML lang (BCP 47)."""
    if not user_language:
        return "en"
    u = user_language.strip().lower().replace("_", "-")
    if u.startswith("zh"):
        return "zh-Hans" if ("cn" in u or "hans" in u or u in {"zh", "zh-cn"} or u == "zhcn") else "zh-Hant"
    if len(u) == 2:
        return u
    return u.split("-")[0] if "-" in u else "en"


def user_q(user_id: str) -> str:
    """Query string suffix such as '?user_id=...'"""
    return f"?user_id={quote(user_id, safe='')}"


SHARED_APP_CSS = """
    :root {
      --bg: #f8f5ef;
      --panel: rgba(255, 255, 255, 0.92);
      --panel-strong: #ffffff;
      --panel-soft: #fcf8f1;
      --border: #e8dbc7;
      --ink: #1f2430;
      --muted: #686258;
      --accent: #a34a1e;
      --accent-soft: #f4e6d5;
      --accent-deep: #6d2f13;
      --shadow: 0 18px 44px rgba(81, 60, 31, 0.08);
    }
    *, *::before, *::after { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Avenir Next", "Segoe UI Variable", "Segoe UI", "Trebuchet MS", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(194, 141, 74, 0.12), transparent 18%),
        radial-gradient(circle at 88% 0%, rgba(133, 96, 57, 0.08), transparent 18%),
        linear-gradient(180deg, #fbf8f3 0%, var(--bg) 100%);
      line-height: 1.5;
    }
    .site-skip {
      position: absolute;
      left: -9999px;
      top: auto;
      width: 1px;
      height: 1px;
      overflow: hidden;
      z-index: -1;
    }
    .site-skip:focus {
      position: fixed;
      left: 12px;
      top: 12px;
      width: auto;
      height: auto;
      z-index: 10000;
      padding: 10px 16px;
      background: var(--accent);
      color: #fffdf8;
      border-radius: 10px;
      font-weight: 700;
      text-decoration: none;
      outline: none;
      box-shadow: var(--shadow);
    }
    a:focus-visible,
    button:focus-visible,
    select:focus-visible,
    input:focus-visible,
    textarea:focus-visible,
    summary:focus-visible {
      outline: 3px solid var(--accent);
      outline-offset: 3px;
    }
    header.site-header {
      max-width: 1160px;
      margin: 0 auto;
      padding: 16px 20px 8px;
    }
    .site-nav-wrap {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 12px;
    }
    nav.site-nav {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    nav.site-nav a {
      padding: 8px 14px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.78);
      color: var(--muted);
      font-size: 0.92rem;
      text-decoration: none;
    }
    nav.site-nav a[aria-current="page"] {
      background: var(--accent-soft);
      color: var(--accent-deep);
      border-color: var(--accent);
      font-weight: 600;
    }
    nav.dashboard-toc {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 0 20px 12px;
      max-width: 1160px;
      margin: 0 auto;
    }
    nav.dashboard-toc a {
      padding: 6px 12px;
      font-size: 0.88rem;
      color: var(--muted);
      text-decoration: none;
      border-bottom: 2px solid transparent;
    }
    nav.dashboard-toc a:hover {
      border-bottom-color: var(--accent);
      color: var(--accent-deep);
    }
    main#main-content {
      max-width: 1160px;
      margin: 0 auto;
      padding: 8px 20px 56px;
    }
    main#main-content.page-wide {
      max-width: 1120px;
    }
    footer.site-help {
      max-width: 1160px;
      margin: 0 auto;
      padding: 0 20px 40px;
    }
    footer.site-help details.glossary-help {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 12px 18px;
    }
    footer.site-help summary {
      cursor: pointer;
      font-weight: 600;
      color: var(--muted);
    }
    footer.site-help p {
      color: var(--muted);
      font-size: 0.93rem;
      margin: 8px 0 0;
    }
    details.dev-advanced {
      margin-top: 8px;
      border: 1px dashed var(--border);
      border-radius: 12px;
      padding: 8px 12px;
      background: rgba(255,255,255,0.5);
      font-size: 0.9rem;
      color: var(--muted);
    }
    details.dev-advanced summary { cursor: pointer; font-weight: 600; }
    .developer-links {
      display: grid;
      gap: 8px;
      margin-top: 8px;
    }
    main#main-content .detail-body {
      max-width: 980px;
      margin-left: auto;
      margin-right: auto;
      padding-bottom: 40px;
    }
    main#main-content.detail-narrow .detail-body { max-width: 900px; }
    main#main-content.detail-narrow-wide .detail-body { max-width: 980px; }
    main#main-content.detail-matches-wide .detail-body { max-width: 1120px; }
"""


COLLECTOR_COMPONENT_CSS = """
    h1, h2, h3 { margin: 0 0 10px; }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    code {
      font-family: "JetBrains Mono", "Cascadia Code", ui-monospace, monospace;
      background: #efe4d4;
      padding: 2px 6px;
      border-radius: 6px;
      font-size: 0.9em;
    }
    .eyebrow {
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.78rem;
      color: var(--muted);
    }
    .hero {
      background: linear-gradient(135deg, rgba(255, 251, 245, 0.98), rgba(246, 236, 219, 0.9));
      border: 1px solid var(--border);
      border-radius: 26px;
      padding: 24px;
      box-shadow: var(--shadow);
      margin-bottom: 18px;
    }
    .hero h1 {
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2.2rem, 4vw, 3.5rem);
      letter-spacing: -0.04em;
    }
    .hero p {
      color: var(--muted);
      max-width: 660px;
      font-size: 1.04rem;
      line-height: 1.55;
      margin: 0;
    }
    .hero-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(260px, 0.8fr);
      gap: 18px;
      align-items: start;
    }
    .hero-side {
      background: rgba(255, 255, 255, 0.72);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 18px;
    }
    .hero-side h3 {
      font-family: Georgia, "Times New Roman", serif;
      margin-bottom: 6px;
    }
    details.identity-advanced {
      margin-top: 12px;
      font-size: 0.92rem;
      color: var(--muted);
      border-top: 1px solid var(--border);
      padding-top: 10px;
    }
    details.identity-advanced summary { cursor: pointer; font-weight: 600; color: var(--accent-deep); }
    .chip-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 999px;
      padding: 8px 12px;
      background: rgba(255, 255, 255, 0.82);
      border: 1px solid var(--border);
      color: var(--muted);
      font-size: 0.94rem;
    }
    .subtle-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin: 0 0 18px;
    }
    .summary-card {
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 18px;
      box-shadow: var(--shadow);
    }
    .summary-card strong {
      display: block;
      font-size: 1.9rem;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--accent-deep);
      margin-top: 8px;
    }
    .section {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 20px;
      margin-bottom: 18px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }
    .section-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 16px;
    }
    .section-header p { margin: 0; color: var(--muted); }
    .spotlight-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.95fr);
      gap: 18px;
      margin-bottom: 18px;
    }
    .quick-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .quick-card {
      background: var(--panel-soft);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 16px;
      display: grid;
      gap: 8px;
      box-shadow: var(--shadow);
      text-decoration: none;
      color: inherit;
    }
    .quick-card:hover { border-color: var(--accent); }
    .quick-card h3 {
      font-size: 1rem;
      margin-bottom: 0;
    }
    .quick-card p {
      margin: 0;
      color: var(--muted);
      line-height: 1.45;
      font-size: 0.96rem;
    }
    .digest-card {
      background: linear-gradient(180deg, rgba(255, 253, 248, 0.98), rgba(250, 243, 232, 0.92));
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 20px;
      box-shadow: var(--shadow);
      display: grid;
      gap: 12px;
    }
    .digest-meta { display: flex; flex-wrap: wrap; gap: 10px; }
    .digest-preview-read { display: grid; gap: 10px; }
    .digest-preview-heading {
      margin: 0;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--muted);
      font-weight: 700;
    }
    .digest-preview-list {
      margin: 0;
      padding-left: 1.35rem;
      color: var(--ink);
      line-height: 1.55;
    }
    .digest-preview-list li { margin: 0.42em 0; }
    .digest-preview-list li:first-child { margin-top: 0; }
    .digest-preview-para { margin: 0.35em 0 0; line-height: 1.55; }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 6px 10px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 0.82rem;
      font-weight: 600;
    }
    .signal-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px; }
    .signal-card {
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 18px;
      box-shadow: var(--shadow);
      display: grid;
      gap: 10px;
    }
    .signal-card h3 { margin: 0; font-size: 1.08rem; line-height: 1.35; }
    .signal-card p { margin: 0; color: var(--muted); line-height: 1.55; }
    .signal-meta { display: flex; flex-wrap: wrap; gap: 8px; }
    .signal-note { font-size: 0.94rem; color: var(--muted); }
    .signal-links { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 4px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 0; }
    .latest-card {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 16px;
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: var(--shadow);
      min-height: 132px;
      text-decoration: none;
      color: inherit;
    }
    .latest-card strong { font-size: 1.1rem; line-height: 1.3; }
    .latest-card .meta { margin-top: auto; color: var(--muted); font-size: 0.92rem; }
    .opportunity-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
    }
    details.digest-advanced { margin-top: 10px; font-size: 0.9rem; color: var(--muted); }
    details.digest-advanced summary { cursor: pointer; font-weight: 600; }
    .empty-state { color: var(--muted); margin: 0; }
    .empty-cta { margin-top: 12px; }
    .empty-cta a { font-weight: 600; }
    .action-button, .danger-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      border-radius: 999px;
      padding: 9px 14px;
      border: 1px solid var(--border);
      text-decoration: none;
      font-size: 0.92rem;
      cursor: pointer;
      font: inherit;
    }
    .action-button {
      background: var(--accent);
      color: #fff9f0;
      font-weight: 700;
    }
    .danger-button {
      background: #fff3ef;
      color: #8b2d17;
      font-weight: 600;
    }
    .action-card, .hero.page-hero .section-intro { box-sizing: border-box; }
    .actions-grid, .report-list { display: grid; gap: 14px; }
    .action-card {
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 18px;
      box-shadow: var(--shadow);
    }
    .action-card h3 { margin: 0 0 8px; font-size: 1.12rem; }
    .action-card form { display: grid; gap: 12px; margin-top: 14px; }
    .action-card label { display: grid; gap: 6px; color: var(--muted); font-size: 0.94rem; }
    .action-card input, .action-card select, .action-card button, .radio-line input {
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 10px 12px;
      font: inherit;
      background: #fffdf8;
      color: var(--ink);
    }
    .action-card button[type="submit"] {
      background: var(--accent);
      color: #fff9f0;
      font-weight: 700;
      cursor: pointer;
    }
    .radio-stack { display: grid; gap: 8px; margin-top: 4px; }
    .radio-line { display: flex; gap: 10px; align-items: flex-start; }
    .radio-line label { flex: 1; display: grid; gap: 4px; color: var(--muted); font-size: 0.92rem; }
    .radio-line input[type="radio"] { margin-top: 4px; }
    .report-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      align-items: center;
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 16px 18px;
    }
    .report-row h3 { margin: 0 0 6px; font-size: 1.05rem; }
    .report-row p { margin: 0; color: var(--muted); line-height: 1.5; }
    .meta-stack { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; color: var(--muted); font-size: 0.92rem; }
    .hero.page-hero {
      background: var(--panel);
      border-radius: 28px;
      padding: 24px;
      margin-bottom: 22px;
    }
    .interest-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 14px;
    }
    .interest-detail-card {
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 18px;
      box-shadow: var(--shadow);
    }
    .interest-detail-card h3 { margin: 0; font-size: 1.18rem; line-height: 1.3; }
    .detail-row, .hero-actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 16px; align-items: center; }
    .subpanel {
      background: rgba(255, 250, 244, 0.76);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 14px;
    }
    .subpanel h4 {
      margin: 0 0 8px;
      font-size: 0.98rem;
      color: var(--accent-deep);
      cursor: pointer;
    }
    .subpanel-collapsible summary { user-select: none; }
    .subpanel-collapsible summary::-webkit-details-marker { display: none; }
    .stack { display: grid; gap: 10px; margin-top: 14px; }
    .meta-row, .chip-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 28px;
      padding: 24px;
      box-shadow: var(--shadow);
      margin-bottom: 20px;
    }
    .interest-detail-card.form-panel label { display: grid; gap: 6px; color: var(--muted); font-size: 0.94rem; }
    .interest-detail-card.form-panel input, .interest-detail-card.form-panel select, .interest-detail-card.form-panel textarea, .interest-detail-card.form-panel button {
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 10px 12px;
      font: inherit;
      background: #fffdf8;
    }
    .interest-detail-card.form-panel button[type="submit"] {
      background: var(--accent);
      color: #fff9f0;
      font-weight: 700;
      cursor: pointer;
    }
    .form-fieldset-title {
      margin: 12px 0 8px;
      font-weight: 700;
      color: var(--accent-deep);
      font-size: 1.05rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 6px;
    }
    .card-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
    }
    .match-card, .opportunity-card {
      background: var(--panel-strong);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 18px;
      box-shadow: var(--shadow);
    }
    .match-card h3, .opportunity-card h3 { margin: 0; font-size: 1.08rem; line-height: 1.35; }
    .match-card p, .opportunity-card p { margin: 8px 0 0; color: var(--muted); line-height: 1.55; }
    label { display: grid; gap: 6px; }
    .field-help {
      font-size: 0.84rem;
      color: var(--muted);
      line-height: 1.45;
      font-weight: 400;
    }
    .inline-form { margin: 0; display: inline; }
    .digest-mini-card-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
      margin-top: 10px;
    }
    .digest-mini-card {
      background: var(--panel-soft);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      box-shadow: 0 6px 18px rgba(81, 60, 31, 0.05);
    }
    .digest-mini-card .badge-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .digest-mini-card .digest-mini-title {
      margin: 0;
      font-size: 1rem;
      line-height: 1.35;
      color: var(--ink);
      font-weight: 600;
    }
    .digest-mini-card .digest-mini-headline {
      font-size: 1.04rem;
      line-height: 1.3;
      color: var(--ink);
      font-weight: 700;
      letter-spacing: -0.005em;
    }
    .digest-mini-card .digest-mini-subtitle {
      font-size: 0.84rem;
      line-height: 1.35;
      color: var(--muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      font-family: "JetBrains Mono", "Cascadia Code", ui-monospace, monospace;
    }
    .digest-facet-row {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin-top: -2px;
    }
    .digest-facet {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 0.74rem;
      font-weight: 500;
      letter-spacing: 0.01em;
      background: rgba(255, 255, 255, 0.78);
      border: 1px solid var(--border);
      color: var(--muted);
    }
    .digest-facet--variant { background: #f3ead8; color: #6b4a1d; border-color: #d9c39b; }
    .digest-facet--cond { background: var(--accent-soft); color: var(--accent-deep); border-color: var(--accent); }
    .digest-facet--qty { background: #e9efe2; color: #4a5a3a; border-color: #b9c9a4; }
    .digest-facet--finish { background: #ece2d3; color: #5a4a32; border-color: #c8b793; }
    .digest-facet--weight { background: #e2e8ee; color: #3a4a5a; border-color: #a4b7c9; }
    .digest-facet--denom { background: #f0e2ee; color: #5a3a55; border-color: #c9a4c1; }
    .signal-consolidation-note {
      margin: 6px 0 0;
      font-size: 0.86rem;
      color: var(--muted);
      font-style: italic;
    }
    .digest-mini-card .meta-row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      color: var(--muted);
      font-size: 0.9rem;
    }
    .digest-mini-card .meta-row .price {
      color: var(--accent-deep);
      font-weight: 600;
    }
    .digest-mini-card .meta-row .condition {
      color: var(--muted);
    }
    .digest-mini-card .digest-listing-link {
      align-self: flex-start;
      font-size: 0.88rem;
      font-weight: 600;
      color: var(--accent);
    }
    .digest-mini-card .digest-listing-link:hover { text-decoration: underline; }
    .digest-mini-card .source-id {
      font-family: "JetBrains Mono", "Cascadia Code", ui-monospace, monospace;
      font-size: 0.78rem;
      color: var(--muted);
    }
    .digest-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      border-radius: 999px;
      padding: 3px 9px;
      font-size: 0.76rem;
      font-weight: 600;
      letter-spacing: 0.02em;
      background: rgba(255, 255, 255, 0.78);
      border: 1px solid var(--border);
      color: var(--muted);
    }
    .digest-badge--exact { background: var(--accent-soft); color: var(--accent-deep); border-color: var(--accent); }
    .digest-badge--variant { background: #f3ead8; color: #6b4a1d; border-color: #d9c39b; }
    .digest-badge--series { background: #ece2d3; color: #5a4a32; border-color: #c8b793; }
    .digest-badge--live { background: var(--accent); color: #fffdf8; border-color: var(--accent-deep); }
    .digest-badge--preview { background: #fff3e3; color: #8b5a1f; border-color: #e3c79a; }
    .digest-badge--ended { background: #ece6dc; color: #5a544a; border-color: #c9bfae; }
    .digest-badge--neutral { background: rgba(255,255,255,0.78); color: var(--muted); }
    time.digest-time { font-size: 0.86rem; color: var(--muted); }
    @media (max-width: 720px) {
      .hero-grid, .spotlight-grid, .quick-grid { grid-template-columns: 1fr; }
      .report-row { grid-template-columns: 1fr; }
      .meta-stack { align-items: flex-start; }
      .digest-mini-card-grid { grid-template-columns: 1fr; }
    }
"""


def full_collector_styles() -> str:
    return f"{SHARED_APP_CSS}\n{COLLECTOR_COMPONENT_CSS}"


def render_skip_link(target_id: str = "main-content") -> str:
    tid = html.escape(target_id, quote=True)
    return (
        f'<a class="site-skip" href="#{tid}">Skip to main content</a>'
    )


def render_primary_nav(user_id: str, *, active: str) -> str:
    """Unified top-level nav for every page.

    active: dashboard | matches | interests | settings | report
    """
    q = user_q(user_id)
    dash = f"/{q}"
    specs = (
        ("dashboard", dash, "Home"),
        ("matches", f"/matches{q}", "Matches"),
        ("interests", f"/interests{q}", "Interests"),
        ("settings", f"/actions{q}", "Actions"),
    )
    pieces: list[str] = []
    for key, href, label in specs:
        current = ' aria-current="page"' if key == active else ""
        pieces.append(
            f'<a href="{html.escape(href)}"{current}>{html.escape(label)}</a>'
        )
    return f'<nav class="site-nav" aria-label="Primary">{"".join(pieces)}</nav>'


def render_advanced_dev_links(user_id: str) -> str:
    """Collapsible developer links; gated by APP_SHOW_DEV_UI."""
    if not show_app_dev_ui():
        return ""
    uid = quote(user_id)
    body = f"""
    <div class="developer-links">
      <span>
        <a href="/healthz">Health check</a>
        · <a href="/api/users/{uid}/profile">Profile JSON</a>
        · <a href="/api/users/{uid}/signals">Signals JSON</a>
        · <a href="/api/users/{uid}/matches">Matches JSON</a>
        · <a href="/api/users/{uid}/interests">Interests JSON</a>
        · <a href="/api/users/{uid}/digest/latest">Digest JSON</a>
      </span>
    </div>
    """
    return f'<details class="dev-advanced"><summary>Advanced & API</summary>{body}</details>'


def render_glossary_footer() -> str:
    return """
    <footer class="site-help" role="contentinfo">
      <details class="glossary-help">
        <summary>What do these numbers mean?</summary>
        <p>
          <strong>Saved interests</strong> are themes or items you want us to watch.
          <strong>Matches</strong> are marketplace listings aligned with those interests (see the Matches page).
          <strong>Alerts</strong> are timely notices derived from matches and pricing context.
          Use <strong>Settings & refresh</strong> when you want to update matches or alerts manually.
        </p>
      </details>
    </footer>
    """


def render_site_header(user_id: str, *, nav_active: str) -> str:
    nav = render_primary_nav(user_id, active=nav_active)
    advanced = render_advanced_dev_links(user_id)
    return f"""
    <header class="site-header" role="banner">
      <div class="site-nav-wrap">
        {nav}
      </div>
      {advanced}
    </header>
    """


def render_document(
    *,
    title: str,
    html_lang: str,
    user_id: str,
    nav_active: str,
    main_inner_html: str,
    extra_css: str = "",
    main_classes: str = "",
    omit_glossary_footer: bool = False,
    body_suffix_html: str = "",
) -> str:
    """Wrap main content with shared header, skip link, and optional glossary footer."""
    skip = render_skip_link("main-content")
    header = render_site_header(user_id, nav_active=nav_active)
    footer = "" if omit_glossary_footer else render_glossary_footer()
    main_cls = f"main-content {main_classes}".strip()
    xc = extra_css.strip()
    extra_css_block = f"\n{xc}\n" if xc else ""
    suffix = body_suffix_html.strip()
    suffix_block = f"\n{suffix}\n" if suffix else ""
    return f"""<!DOCTYPE html>
<html lang="{html.escape(html_lang)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
{full_collector_styles()}
{extra_css_block}
  </style>
</head>
<body>
  {skip}
  {header}
  <main id="main-content" role="main" class="{html.escape(main_cls)}">
    {main_inner_html}
  </main>
  {footer}
{suffix_block}
</body>
</html>"""


def render_optional_signal_json_link(user_id: str) -> str:
    if not show_app_dev_ui():
        return ""
    uid = quote(user_id)
    return f' · <a href="/api/users/{uid}/signals">Signals JSON</a>'


def render_optional_matches_json_link(user_id: str) -> str:
    if not show_app_dev_ui():
        return ""
    uid = quote(user_id)
    return f' · <a href="/api/users/{uid}/matches">Matches JSON</a>'


def render_dashboard_anchor_nav(user_id: str) -> str:
    """In-page jump links for the dashboard's own sections."""
    items = (
        ("#signals", "Alerts"),
        ("#matches-preview", "Matches"),
        ("#digest-region", "Digest"),
        ("#reports-region", "Reports"),
    )
    parts = []
    for frag, label in items:
        parts.append(f'<a href="{html.escape(frag)}">{html.escape(label)}</a>')
    return f'<nav class="dashboard-toc" aria-label="On this page">{"".join(parts)}</nav>'
