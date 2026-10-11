// custom_components/genesisenergy/www/powershout-card.js
// Genesis Energy — Power Shout & Account Custom Lovelace Card (v2.0.1)

const CARD_VERSION = "2.0.1";
const DOMAIN = "genesisenergy";


const DAILY_FETCH_PREV_MONTHS = 3;
const EV_START_YEAR = 2026;
const EV_START_MONTH = 8; 
const LIVE_DATA_CACHE_TTL_MS = 4 * 60 * 60 * 1000;

const TAB_SHOUT = "shout";
const TAB_USAGE = "usage";
const TAB_PAST = "past";
const TAB_FORECAST = "forecast";
const TAB_SUMMARY = "summary";

const LOGO_SVG_URL = new URL("./powershout.svg", import.meta.url).href;
const LOGO_PNG_URL = new URL("./powershout.png", import.meta.url).href;

function parseData(val) {
  if (!val) return null;
  if (typeof val === "object") return val;
  try {
    return JSON.parse(val);
  } catch {
    return null;
  }
}

function fmtHour(isoStr) {
  if (!isoStr) return "—";
  try {
    return new Date(isoStr)
      .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      .toLowerCase();
  } catch {
    return "—";
  }
}

function fmtNum(val, decimals = 2) {
  const n = parseFloat(val);
  return isNaN(n) ? null : n.toFixed(decimals);
}

function fmtDate(isoStr) {
  if (!isoStr) return null;
  const d = new Date(isoStr);
  return isNaN(d) ? null : d.toLocaleDateString([], { day: "numeric", month: "short" });
}

function fmtPastHour(isoStr) {
  if (!isoStr) return "Unknown hour";
  const parsed = new Date(isoStr);
  if (isNaN(parsed)) return isoStr.replace("T", " ");
  return parsed.toLocaleString([], {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

function fmtDisplayDate(dateStr) {
  if (!dateStr) return "";
  const [y, m, d] = dateStr.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return dt.toLocaleDateString([], {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function fmtTooltipDate(dateObj) {
  if (!dateObj) return "";
  return dateObj.toLocaleDateString([], {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function parseApiDateKey(dateStr) {
  if (!dateStr) return "";
  return dateStr.split("T")[0].split(" ")[0];
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function build24HourOptions() {
  return Array.from({ length: 24 }, (_, hour) => {
    const val = String(hour).padStart(2, "0");
    const d = new Date(2000, 0, 1, hour);
    const label = d
      .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      .toLowerCase();
    return `<option value="${val}">${label}</option>`;
  }).join("");
}

function calculateEndHour(dateStr, hourStr, duration) {
  if (!dateStr || hourStr === "") return "";
  const [y, m, d] = dateStr.split("-").map(Number);
  const start = new Date(y, m - 1, d, parseInt(hourStr, 10));
  const end = new Date(start.getTime() + (Number(duration) || 1) * 3600000);
  return end.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }).toLowerCase();
}

function endHourLabel(startDatetime, duration) {
  const parsed = new Date(startDatetime);
  if (isNaN(parsed)) return "";
  const end = new Date(parsed.getTime() + Math.max(1, Number(duration) || 1) * 3600000);
  return end.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }).toLowerCase();
}

const PS_PIN_SVG = `
  <svg width="13" height="16" viewBox="0 0 16 20" fill="none" style="vertical-align:-2px;flex-shrink:0;">
    <circle cx="8" cy="8" r="8" fill="var(--genesis-orange)"/>
    <path d="M 5 13 L 8 19 L 11 13 Z" fill="var(--genesis-orange)"/>
    <text x="8" y="11.2" text-anchor="middle" fill="#ffffff" font-size="9" font-weight="900" font-family="-apple-system, sans-serif">P</text>
  </svg>
`;

const CARD_CSS = `
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :host {
    --genesis-orange: #f15b29;
    --genesis-orange-hover: #d94e20;
    --genesis-plum: #56004e;
    --genesis-plum-light: #8e24aa;
    --genesis-teal: #00838f;
    --genesis-yellow: #e8a13c;
    --live-banner-bg: var(--genesis-orange);
    --offer-banner-border: var(--genesis-yellow);
    --expiring-banner-border: var(--genesis-yellow);
    --genesis-card-bg: var(--ha-card-background, var(--card-background-color, #1a1612));
    --genesis-text: var(--primary-text-color, #ffffff);
    --genesis-muted: var(--secondary-text-color, #9e948a);
    --genesis-surface: var(--secondary-background-color, rgba(127, 127, 127, 0.12));
    --genesis-border: var(--divider-color, rgba(127, 127, 127, 0.22));
    --genesis-track: rgba(86, 0, 78, 0.25);
    display: block;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  :host(.theme-dark) {
    --genesis-plum: #ba68c8;
    --genesis-track: rgba(186, 104, 200, 0.3);
  }
  [hidden] { display: none !important; }

  .card {
    border-radius: 20px;
    background: var(--genesis-card-bg);
    border: 1px solid var(--genesis-border);
    box-shadow: 0 1px 3px rgba(0,0,0,.08), 0 14px 44px rgba(0,0,0,.25);
    color: var(--genesis-text);
    overflow: visible;
    padding: 16px;
  }

  .hero {
    align-items: center;
    display: flex;
    justify-content: space-between;
    gap: 8px;
    min-height: 48px;
  }
  .hero-left {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
    flex: 1;
  }
  .hero-logo-ps {
    display: flex;
    align-items: center;
    flex-shrink: 0;
  }
  .hero-logo-ps img {
    height: clamp(38px, 9vw, 44px);
    width: auto;
    display: block;
    object-fit: contain;
  }
  .hero-logo-std {
    color: var(--genesis-orange);
    display: flex;
    align-items: center;
    flex-shrink: 0;
  }
  .balwrap {
    align-items: baseline;
    display: flex;
    gap: 4px;
    white-space: nowrap;
  }
  .balwrap .n {
    font-size: clamp(38px, 10vw, 52px);
    font-weight: 800;
    letter-spacing: -.045em;
    line-height: .9;
    color: var(--genesis-text);
  }
  .balwrap .u {
    color: var(--genesis-muted);
    font-size: 16px;
    font-weight: 700;
  }
  
  .account-hero-info { min-width: 0; flex: 1; }
  .account-hero-title {
    font-size: clamp(17px, 4.8vw, 22px);
    font-weight: 800;
    letter-spacing: -.02em;
    color: var(--genesis-text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .account-hero-sub {
    font-size: 12px;
    color: var(--genesis-muted);
    font-weight: 600;
    margin-top: 1px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .elig {
    border-radius: 999px;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: .04em;
    padding: 4px 10px;
    text-transform: uppercase;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .elig.ok {
    background: rgba(76, 175, 80, 0.18);
    border: 1px solid rgba(76, 175, 80, 0.45);
    color: #4caf50;
  }
  .elig.bad {
    background: rgba(244, 67, 54, 0.18);
    border: 1px solid rgba(244, 67, 54, 0.45);
    color: #ff5252;
  }
  .elig.warn {
    background: rgba(241, 91, 41, 0.18);
    border: 1px solid rgba(241, 91, 41, 0.45);
    color: var(--genesis-orange);
  }

  .sum-card {
    background: var(--genesis-surface);
    border: 1px solid var(--genesis-border);
    border-radius: 14px;
    padding: 13px 14px;
    margin-top: 14px;
    color: var(--genesis-text);
  }
  .sum-hero {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
  }
  .sum-hero-val {
    font-size: 30px;
    font-weight: 800;
    color: var(--genesis-orange);
    line-height: 1;
    margin-top: 2px;
  }
  .sum-hero-lbl {
    font-size: 11px;
    color: var(--genesis-muted);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .05em;
  }
  .sum-forecast-val {
    font-size: 24px;
    font-weight: 800;
    color: var(--genesis-text);
    line-height: 1.1;
    margin-top: 2px;
  }
  .sum-bar-wrap { margin-top: 11px; }
  .sum-bar-header {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: var(--genesis-muted);
    font-weight: 600;
    margin-bottom: 6px;
  }
  .sum-bar-header strong { color: var(--genesis-text); }
  .sum-bar-track {
    background: var(--genesis-border);
    border-radius: 6px;
    height: 7px;
    overflow: hidden;
  }
  .sum-bar-fill {
    background: var(--genesis-orange);
    height: 100%;
    border-radius: 6px;
    transition: width 0.4s ease;
  }

  .live {
    align-items: center;
    background: var(--live-banner-bg);
    border-radius: 12px;
    color: #fff;
    display: flex;
    font-size: 13px;
    font-weight: 700;
    justify-content: space-between;
    margin-top: 12px;
    padding: 11px 13px;
    box-shadow: 0 0 16px 2px var(--live-banner-bg);
    animation: pulse-glow-live 2s ease-in-out infinite;
  }
  .live .ll { align-items: center; display: flex; gap: 8px; }
  .live .dot {
    animation: pulse 1.4s ease-in-out infinite;
    background: #fff;
    border-radius: 50%;
    height: 9px;
    width: 9px;
  }
  @keyframes pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: .3; transform: scale(.8); } }
  @keyframes pulse-glow-live {
    0% { filter: brightness(1); }
    50% { filter: brightness(1.12); }
    100% { filter: brightness(1); }
  }

  .offer {
    align-items: center;
    background: rgba(232, 161, 60, 0.12);
    border: 1.8px dashed var(--offer-banner-border);
    border-radius: 14px;
    display: flex;
    gap: 10px;
    justify-content: space-between;
    margin-top: 12px;
    padding: 12px 14px;
    animation: pulse-glow-offer 2.2s ease-in-out infinite;
  }
  .offer .ot { color: var(--offer-banner-border); font-size: 13.5px; font-weight: 700; }
  .offer .ot b { color: var(--genesis-orange); font-size: 15px; }
  .offer .add-btn {
    appearance: none;
    background: var(--offer-banner-border);
    border: 0;
    border-radius: 11px;
    color: #1a1612;
    cursor: pointer;
    flex: none;
    font: inherit;
    font-size: 13px;
    font-weight: 800;
    padding: 8px 14px;
    white-space: nowrap;
    transition: filter .2s;
  }
  .offer .add-btn:hover { filter: brightness(1.1); }
  @keyframes pulse-glow-offer {
    0% { filter: brightness(1); }
    50% { filter: brightness(1.1); }
    100% { filter: brightness(1); }
  }

  .expiring-bar {
    align-items: center;
    background: rgba(232, 161, 60, 0.14);
    border: 1.5px solid var(--expiring-banner-border);
    border-radius: 12px;
    color: var(--genesis-text);
    display: flex;
    font-size: 13px;
    font-weight: 700;
    gap: 10px;
    margin-top: 12px;
    padding: 10px 14px;
    line-height: 1.4;
  }
  .expiring-bar .exp-icon {
    font-size: 18px;
    flex-shrink: 0;
  }
  .expiring-bar b {
    color: var(--genesis-orange);
    font-weight: 800;
  }

  .tabs {
    border-bottom: 1px solid var(--genesis-border);
    display: flex;
    align-items: center;
    gap: 2px;
    margin: 14px -16px 0;
    padding: 0 12px;
    overflow-x: auto;
    scrollbar-width: none;
  }
  .tabs::-webkit-scrollbar { display: none; }
  .tabs button {
    align-items: center;
    appearance: none;
    background: none;
    border: 0;
    border-bottom: 2.5px solid transparent;
    color: var(--genesis-muted);
    cursor: pointer;
    display: inline-flex;
    font: inherit;
    font-size: 13px;
    font-weight: 700;
    gap: 5px;
    margin-bottom: -1px;
    padding: 10px 8px;
    white-space: nowrap;
    flex-shrink: 0;
    transition: color .2s;
  }
  .tabs button:hover { color: var(--genesis-text); }
  .tabs button[aria-selected="true"] {
    border-bottom-color: var(--genesis-orange);
    color: var(--genesis-text);
  }
  .tabs .cnt {
    background: var(--genesis-orange);
    border-radius: 999px;
    color: #fff;
    font-size: 10px;
    font-weight: 800;
    line-height: 1;
    padding: 2px 6px;
  }

  /* Top Tabs Meter Status Pill (Far Right) */
  .main-sync-badge {
    margin-left: auto;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--genesis-muted);
    letter-spacing: .01em;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
    padding-left: 6px;
    flex-shrink: 0;
  }
  .main-sync-badge strong {
    color: var(--genesis-text);
    font-weight: 700;
  }
  .usage-sync-dot {
    height: 7px;
    width: 7px;
    border-radius: 50%;
    background: #4caf50;
    display: inline-block;
    flex-shrink: 0;
  }
  .usage-sync-dot.lagging {
    background: var(--genesis-yellow);
  }
  .usage-sync-dot.stalled {
    background: #ff5252;
  }
  @media (max-width: 440px) {
    .main-sync-badge .sync-text-prefix { display: none; }
  }

  .panel { padding-top: 4px; }

  .detailed-usage-card {
    background: var(--genesis-surface);
    border: 1px solid var(--genesis-border);
    border-radius: 16px;
    padding: 14px;
    margin-top: 10px;
    position: relative;
  }
  .service-subtabs-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1.5px solid var(--genesis-border);
    padding-bottom: 4px;
    margin-bottom: 12px;
    gap: 8px;
  }
  .service-subtabs {
    display: flex;
    gap: 6px;
    overflow-x: auto;
    scrollbar-width: none;
  }
  .service-subtabs::-webkit-scrollbar { display: none; }
  .service-subtabs button {
    appearance: none;
    background: none;
    border: 0;
    border-bottom: 3px solid transparent;
    color: var(--genesis-muted);
    cursor: pointer;
    font: inherit;
    font-size: 13.5px;
    font-weight: 700;
    padding: 6px 10px;
    margin-bottom: -5.5px;
    white-space: nowrap;
    transition: all .2s;
  }
  .service-subtabs button.sel {
    border-bottom-color: var(--genesis-orange);
    color: var(--genesis-text);
  }

  /* Submenu Targeted Sync Button */
  .sync-action-btn {
    appearance: none;
    background: var(--genesis-surface);
    border: 1px solid var(--genesis-border);
    border-radius: 8px;
    color: var(--genesis-muted);
    cursor: pointer;
    font: inherit;
    font-size: 11.5px;
    font-weight: 700;
    padding: 3px 8px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    transition: all .2s;
    flex-shrink: 0;
    margin-bottom: 2px;
  }
  .sync-action-btn:hover {
    color: var(--genesis-orange);
    border-color: var(--genesis-orange);
  }
  .sync-action-btn.syncing .sync-icon {
    animation: spin .7s linear infinite;
    color: var(--genesis-orange);
  }

  .usage-metrics-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin: 4px 2px 4px;
  }
  .usage-metric-box {
    display: flex;
    align-items: baseline;
    gap: 6px;
  }
  .usage-metric-lbl { font-size: 12.5px; color: var(--genesis-muted); font-weight: 600; }
  .usage-metric-val { font-size: 14.5px; font-weight: 800; color: var(--genesis-text); }
  .usage-period-center {
    text-align: center;
    font-size: 12px;
    font-weight: 700;
    color: var(--genesis-muted);
    letter-spacing: .02em;
    margin-bottom: 8px;
  }

  .analytics-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }
  .granularity-pill {
    background: var(--genesis-card-bg);
    border: 1px solid var(--genesis-border);
    border-radius: 20px;
    display: inline-flex;
    padding: 3px;
    gap: 2px;
  }
  .granularity-pill button {
    appearance: none;
    background: none;
    border: 0;
    border-radius: 16px;
    color: var(--genesis-muted);
    cursor: pointer;
    font: inherit;
    font-size: 12px;
    font-weight: 700;
    padding: 5px 13px;
    transition: all .2s;
  }
  .granularity-pill button.sel {
    background: rgba(86, 0, 78, 0.16);
    color: var(--genesis-plum);
  }
  :host(.theme-dark) .granularity-pill button.sel {
    background: rgba(186, 104, 200, 0.22);
    color: #e1bee7;
  }

  .unit-toggle-wrap {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-weight: 700;
    color: var(--genesis-muted);
  }
  .unit-switch {
    appearance: none;
    background: var(--genesis-plum);
    border-radius: 12px;
    border: 0;
    cursor: pointer;
    height: 22px;
    position: relative;
    width: 40px;
    transition: background .2s;
  }
  .unit-switch::after {
    background: #fff;
    border-radius: 50%;
    content: "";
    height: 16px;
    left: 3px;
    position: absolute;
    top: 3px;
    transition: transform .2s;
    width: 16px;
  }
  .unit-switch.active-dollar::after {
    transform: translateX(18px);
  }

  .date-navigator {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
    position: relative;
  }
  .date-nav-btn {
    appearance: none;
    background: var(--genesis-card-bg);
    border: 1px solid var(--genesis-border);
    border-radius: 8px;
    color: var(--genesis-text);
    cursor: pointer;
    font-weight: 800;
    height: 32px;
    width: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .date-nav-btn:hover:not(:disabled) { border-color: var(--genesis-orange); }
  .date-nav-btn:disabled { opacity: .3; cursor: not-allowed; }
  
  .date-nav-label {
    background: var(--genesis-card-bg);
    border: 1.5px solid var(--genesis-plum);
    border-radius: 18px;
    color: var(--genesis-text);
    font-size: 13.5px;
    font-weight: 800;
    padding: 6px 16px;
    display: flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    user-select: none;
  }
  .date-nav-label:hover { border-color: var(--genesis-orange); }
  :host(.theme-dark) .date-nav-label { border-color: #ba68c8; }

  .date-popover {
    position: absolute;
    top: 42px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--genesis-card-bg);
    border: 1px solid var(--genesis-border);
    border-radius: 16px;
    box-shadow: 0 12px 36px rgba(0,0,0,0.55);
    padding: 14px;
    z-index: 250;
    width: 256px;
  }
  .date-popover-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--genesis-border);
  }
  .date-popover-year {
    background: var(--genesis-surface);
    border: 1px solid var(--genesis-border);
    border-radius: 8px;
    color: var(--genesis-text);
    font: inherit;
    font-size: 14px;
    font-weight: 800;
    padding: 5px 10px;
    outline: none;
    cursor: pointer;
  }
  .date-popover-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 6px;
  }
  .date-popover-month-btn {
    appearance: none;
    background: var(--genesis-surface);
    border: 1px solid var(--genesis-border);
    border-radius: 9px;
    color: var(--genesis-text);
    cursor: pointer;
    font: inherit;
    font-size: 12.5px;
    font-weight: 700;
    padding: 8px 4px;
    text-align: center;
  }
  .date-popover-month-btn:hover:not(:disabled) {
    border-color: var(--genesis-orange);
    color: var(--genesis-orange);
  }
  .date-popover-month-btn.sel {
    background: var(--genesis-orange) !important;
    border-color: var(--genesis-orange) !important;
    color: #fff !important;
  }
  .date-popover-month-btn:disabled {
    opacity: .3;
    cursor: not-allowed;
  }

  .date-popover-footer {
    margin-top: 10px;
    padding-top: 8px;
    border-top: 1px solid var(--genesis-border);
    display: flex;
    justify-content: center;
  }
  .date-popover-clear-btn {
    appearance: none;
    background: none;
    border: 1px dashed var(--genesis-border);
    border-radius: 8px;
    color: var(--genesis-muted);
    cursor: pointer;
    font: inherit;
    font-size: 11px;
    font-weight: 700;
    padding: 5px 10px;
    width: 100%;
    transition: all .2s;
  }
  .date-popover-clear-btn:hover {
    border-color: var(--genesis-orange);
    color: var(--genesis-orange);
  }

  .chart-container {
    width: 100%;
    margin-top: 6px;
    position: relative;
    user-select: none;
  }
  .chart-svg {
    width: 100%;
    height: 195px;
    overflow: visible;
    transition: opacity 0.2s ease;
  }
  .chart-grid-line {
    stroke: var(--genesis-border);
    stroke-dasharray: 4, 4;
    stroke-width: 1;
  }
  .chart-axis-text {
    fill: var(--genesis-muted);
    font-size: 11px;
    font-weight: 600;
  }
  .chart-timeline-track {
    background: var(--genesis-border);
    border-radius: 4px;
    height: 6px;
    margin: 6px 0 10px 34px;
    overflow: hidden;
  }
  .chart-timeline-fill {
    background: var(--genesis-track);
    height: 100%;
    border-radius: 4px;
  }

  .chart-loading-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: rgba(18, 16, 14, 0.45);
    backdrop-filter: blur(2px);
    -webkit-backdrop-filter: blur(2px);
    border-radius: 12px;
    z-index: 100;
    gap: 8px;
  }
  :host(:not(.theme-dark)) .chart-loading-overlay {
    background: rgba(255, 255, 255, 0.55);
  }

  .chart-tooltip {
    position: absolute;
    background: rgba(226, 213, 236, 0.94);
    color: #4a0d46;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid rgba(74, 13, 70, 0.22);
    border-radius: 10px;
    padding: 8px 12px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.32);
    pointer-events: none;
    z-index: 150;
    min-width: 155px;
    max-width: 215px;
    opacity: 0;
    transform: translateY(4px);
    transition: opacity .15s ease, transform .15s ease;
  }
  .chart-tooltip.visible {
    opacity: 1;
    transform: translateY(0);
  }
  :host(.theme-dark) .chart-tooltip {
    background: rgba(38, 22, 42, 0.93);
    color: #f3e5f5;
    border-color: rgba(186, 104, 200, 0.38);
    box-shadow: 0 12px 34px rgba(0,0,0,0.65);
  }

  .tip-date-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    font-size: 12.5px;
    font-weight: 800;
    color: #4a0d46;
    margin-bottom: 5px;
    gap: 8px;
    white-space: nowrap;
  }
  :host(.theme-dark) .tip-date-row { color: #e1bee7; }

  .tip-kwh { font-size: 12px; font-weight: 800; color: #5d1757; }
  :host(.theme-dark) .tip-kwh { color: #ce93d8; }

  .tip-row {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    font-weight: 600;
    color: #4a0d46;
    margin: 2px 0;
  }
  :host(.theme-dark) .tip-row { color: #ede7f6; }

  .tip-divider {
    border-top: 1px solid rgba(74, 13, 70, 0.22);
    margin: 5px 0;
  }
  :host(.theme-dark) .tip-divider { border-top-color: rgba(186, 104, 200, 0.25); }

  .tip-row.total { font-weight: 800; font-size: 12.5px; }

  .tip-ps-badge {
    background: rgba(241, 91, 41, 0.16);
    border: 1px solid rgba(241, 91, 41, 0.4);
    border-radius: 6px;
    color: #c94013;
    font-size: 10.5px;
    font-weight: 800;
    margin-top: 5px;
    padding: 3px 5px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
  }
  :host(.theme-dark) .tip-ps-badge {
    background: rgba(241, 91, 41, 0.22);
    border-color: rgba(241, 91, 41, 0.55);
    color: #ff8a65;
  }

  .tip-drilldown {
    font-size: 10.5px;
    font-weight: 800;
    color: var(--genesis-plum);
    margin-top: 6px;
    text-align: center;
    border-top: 1px dashed rgba(74, 13, 70, 0.25);
    padding-top: 5px;
  }
  :host(.theme-dark) .tip-drilldown {
    color: #ba68c8;
    border-top-color: rgba(186, 104, 200, 0.3);
  }

  .chart-legend {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 16px;
    margin-top: 10px;
    font-size: 12px;
    color: var(--genesis-muted);
    font-weight: 600;
    flex-wrap: wrap;
  }
  .legend-item {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .legend-dot {
    border-radius: 50%;
    height: 9px;
    width: 9px;
    flex-shrink: 0;
  }

  .ctrl-label {
    color: var(--genesis-muted);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: .07em;
    margin: 14px 0 6px;
    text-transform: uppercase;
  }
  .picker-grid { display: grid; gap: 10px; grid-template-columns: 1.15fr 1fr; }
  .ctrl-input, .ctrl-select {
    background: var(--genesis-surface);
    border: 1px solid var(--genesis-border);
    border-radius: 12px;
    color: var(--genesis-text) !important;
    font: inherit;
    font-size: 14px;
    font-weight: 700;
    height: 44px;
    padding: 0 12px;
    width: 100%;
    outline: none;
    cursor: pointer;
    color-scheme: dark light;
    transition: border-color .2s;
  }
  .ctrl-input:focus, .ctrl-select:focus { border-color: var(--genesis-orange); }
  .seg { display: flex; gap: 6px; }
  .seg button {
    appearance: none;
    background: var(--genesis-surface);
    border: 1px solid var(--genesis-border);
    border-radius: 12px;
    color: var(--genesis-muted);
    cursor: pointer;
    flex: 1;
    font: inherit;
    font-size: 14.5px;
    font-weight: 700;
    height: 44px;
    padding: 0;
  }
  .seg button:hover { color: var(--genesis-text); }
  .seg button.sel {
    background: var(--genesis-orange);
    border-color: var(--genesis-orange);
    color: #fff;
  }

  .cta {
    align-items: center;
    background: var(--genesis-orange);
    border: 0;
    border-radius: 14px;
    color: #fff;
    cursor: pointer;
    display: flex;
    font: inherit;
    font-size: 15px;
    font-weight: 700;
    height: 48px;
    justify-content: center;
    margin-top: 14px;
    padding: 0 14px;
    width: 100%;
  }

  .bk {
    align-items: center;
    border-top: 1px solid var(--genesis-border);
    display: flex;
    gap: 10px;
    padding: 11px 0;
    justify-content: space-between;
  }
  .bk:first-of-type { border-top: 0; }
  .bk .w { flex: 1; font-size: 13.5px; font-weight: 600; color: var(--genesis-text); }
  .bk .w small { color: var(--genesis-muted); display: block; font-size: 11.5px; font-weight: 400; margin-top: 2px; }
  .bk button {
    appearance: none;
    background: none;
    border: 0;
    color: var(--genesis-muted);
    cursor: pointer;
    font: inherit;
    font-size: 12.5px;
    font-weight: 700;
    padding: 5px 8px;
    border-radius: 6px;
  }
  .bk button:hover { color: var(--genesis-orange); background: var(--genesis-surface); }
  .bk button:disabled { opacity: .5; cursor: not-allowed; }
  .empty { color: var(--genesis-muted); font-size: 13px; padding: 12px 0; }

  .cost {
    align-items: flex-end;
    border-top: 1px solid var(--genesis-border);
    display: flex;
    gap: 12px;
    justify-content: space-between;
    margin-top: 16px;
    padding-top: 16px;
  }
  .cost .big { font-size: 28px; font-weight: 800; letter-spacing: -.02em; color: var(--genesis-text); }
  .cost .sub { color: var(--genesis-muted); font-size: 12px; margin-top: 2px; }
  .toggle {
    background: var(--genesis-surface);
    border-radius: 10px;
    display: inline-flex;
    flex: none;
    overflow: hidden;
    border: 1px solid var(--genesis-border);
  }
  .toggle button {
    appearance: none;
    background: none;
    border: 0;
    color: var(--genesis-muted);
    cursor: pointer;
    font: inherit;
    font-size: 12px;
    font-weight: 700;
    padding: 7px 12px;
  }
  .toggle button.sel { background: var(--genesis-orange); color: #fff; }

  .ranked-scroll { max-height: 296px; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; }
  .row { align-items: center; border-top: 1px solid var(--genesis-border); display: flex; gap: 11px; padding: 11px 0; }
  .row:first-of-type { border-top: 0; }
  .row input { accent-color: var(--genesis-orange); flex: none; height: 18px; margin: 0; width: 18px; cursor: pointer; }
  .row label { cursor: pointer; flex: 1; }
  .row .when { display: block; font-size: 14px; font-weight: 600; color: var(--genesis-text); }
  .row small { color: var(--genesis-muted); display: block; font-size: 12px; margin-top: 1px; }
  .row small b { color: #4caf50; font-weight: 800; }
  .rank { border-radius: 6px; color: #fff; flex: none; font-size: 10px; font-weight: 800; letter-spacing: .05em; padding: 3px 6px; text-transform: uppercase; white-space: nowrap; }
  .rank.best { background: #005f60; }

  .selection-help { color: var(--genesis-muted); font-size: 12px; margin-top: 9px; line-height: 1.4; }
  .wide-btn {
    appearance: none;
    background: var(--genesis-orange);
    border: 0;
    border-radius: 12px;
    color: #fff;
    cursor: pointer;
    font: inherit;
    font-size: 15px;
    font-weight: 700;
    margin-top: 11px;
    padding: 13px;
    width: 100%;
  }

  .result { border-radius: 12px; font-size: 13px; line-height: 1.45; margin-top: 12px; padding: 11px 12px; }
  .result.ok { background: rgba(76, 175, 80, 0.15); border: 1px solid rgba(76, 175, 80, 0.3); color: #4caf50; }
  .result.bad { background: rgba(244, 67, 54, 0.15); border: 1px solid rgba(244, 67, 54, 0.3); color: #ff5252; }

  .sum-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 9px 0;
    border-top: 1px solid var(--genesis-border);
    font-size: 13.5px;
  }
  .sum-row:first-of-type { border-top: 0; }
  .sum-row b { font-weight: 700; color: var(--genesis-text); }
  .sum-row span { color: var(--genesis-muted); font-weight: 600; }

  .tariff-plan-box {
    background: var(--genesis-surface);
    border: 1px solid var(--genesis-border);
    border-radius: 12px;
    padding: 12px 14px;
    margin-top: 8px;
  }
  .tariff-plan-title {
    font-size: 13.5px;
    font-weight: 800;
    color: var(--genesis-orange);
    margin-bottom: 8px;
  }
  .tariff-item {
    display: flex;
    justify-content: space-between;
    font-size: 12.5px;
    margin: 4px 0;
    color: var(--genesis-muted);
  }
  .tariff-item strong { color: var(--genesis-text); font-weight: 700; }

  .modal {
    align-items: center;
    background: rgba(0,0,0,.68);
    display: flex;
    inset: 0;
    justify-content: center;
    padding: 18px;
    position: fixed;
    z-index: 9999;
    backdrop-filter: blur(5px);
  }
  .dialog {
    background: var(--genesis-card-bg);
    border: 1px solid var(--genesis-border);
    border-radius: 20px;
    box-shadow: 0 24px 80px rgba(0,0,0,.6);
    color: var(--genesis-text);
    max-width: 400px;
    padding: 22px;
    width: 100%;
  }
  .dialog h3 { font-size: 20px; font-weight: 800; margin-bottom: 6px; color: var(--genesis-text); }
  .dialog .dialog-sub { color: var(--genesis-muted); font-size: 13px; margin-bottom: 14px; }
  .dialog .summary-box {
    background: var(--genesis-surface);
    border: 1px solid var(--genesis-border);
    border-radius: 12px;
    padding: 12px;
    margin: 10px 0;
    max-height: 220px;
    overflow-y: auto;
  }
  .dialog .summary-row {
    display: flex;
    justify-content: space-between;
    font-size: 13.5px;
    margin: 5px 0;
    color: var(--genesis-text);
  }
  .dialog .summary-row b { color: var(--genesis-orange); }
  .dialog .warning {
    background: rgba(241, 91, 41, 0.14);
    border: 1px solid rgba(241, 91, 41, 0.28);
    border-radius: 10px;
    color: var(--genesis-text);
    font-size: 12px;
    line-height: 1.45;
    margin-top: 12px;
    padding: 10px;
  }
  .dialog-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 18px; }
  .dialog button {
    appearance: none;
    border: 0;
    border-radius: 10px;
    cursor: pointer;
    font: inherit;
    font-size: 13.5px;
    font-weight: 700;
    padding: 11px 16px;
  }
  .primary { background: var(--genesis-orange); color: #fff; }
  .secondary {
    background: var(--genesis-surface);
    color: var(--genesis-text) !important;
    border: 1px solid var(--genesis-border);
  }

  .spin {
    animation: spin .7s linear infinite;
    border: 2px solid currentColor;
    border-radius: 50%;
    border-right-color: transparent;
    display: inline-block;
    height: 13px;
    margin-right: 7px;
    vertical-align: -2px;
    width: 13px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
`;

function buildTemplate(logoUrl) {
  const hours = build24HourOptions();

  return `
    <style>${CARD_CSS}</style>
    <div class="card">

      <div class="hero">
        <div class="hero-left">
          <div class="hero-logo-ps" id="powershout-logo-wrap">
            <img id="hero-logo-img" src="${logoUrl}" alt="Power Shout">
          </div>
          <div class="hero-logo-std" id="standard-logo-wrap" hidden>
            <svg width="34" height="34" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2L4 14H11V22L19 10H12V2Z"/>
            </svg>
          </div>
          <div class="balwrap" id="powershout-hero-wrap">
            <span class="n" id="bal-num">—</span>
            <span class="u">hr</span>
          </div>
          <div class="account-hero-info" id="standard-hero-wrap" hidden>
            <div class="account-hero-title" id="account-title-label">Genesis Energy</div>
            <div class="account-hero-sub" id="account-sub-label">Energy Account</div>
          </div>
        </div>
        <span class="elig ok" id="bill-due-pill">ELIGIBLE</span>
      </div>

      <div class="sum-card" id="top-billing-box">
        <div class="sum-hero">
          <div>
            <div class="sum-hero-lbl">Used Since Last Bill</div>
            <div class="sum-hero-val" id="top-used-val">$—</div>
          </div>
          <div style="text-align:right">
            <div class="sum-hero-lbl">Forecast Total</div>
            <div class="sum-forecast-val" id="top-forecast-val">$—</div>
          </div>
        </div>

        <div class="sum-bar-wrap">
          <div class="sum-bar-header">
            <span id="top-period-dates">Current Billing Period</span>
            <strong id="top-period-days">—</strong>
          </div>
          <div class="sum-bar-track">
            <div class="sum-bar-fill" id="top-progress-fill" style="width:0%"></div>
          </div>
        </div>
      </div>

      <div class="live" id="live-bar" hidden>
        <span class="ll"><span class="dot"></span>Free power now</span>
        <span class="lr" id="live-end">—</span>
      </div>

      <div class="offer" id="offer-row" hidden>
        <span class="ot" id="offer-lbl">🎁 <b>+1 hr</b> Power Shout offer for you</span>
        <button class="add-btn" id="offer-btn">Add to balance</button>
      </div>

      <div class="expiring-bar" id="expiring-bar" hidden>
        <span class="exp-icon">⏳</span>
        <span class="exp-text" id="expiring-text">—</span>
      </div>

      <div class="tabs" role="tablist" id="card-tabs">
        <button role="tab" id="tab-shout" data-tab="${TAB_SHOUT}" aria-selected="true">Shout</button>
        <button role="tab" id="tab-usage" data-tab="${TAB_USAGE}" aria-selected="false">Usage</button>
        <button role="tab" id="tab-past" data-tab="${TAB_PAST}" aria-selected="false">
          Past hours <span class="cnt" id="past-count" hidden>0</span>
        </button>
        <button role="tab" id="tab-forecast" data-tab="${TAB_FORECAST}" aria-selected="false" hidden>Forecast</button>
        <button role="tab" id="tab-summary" data-tab="${TAB_SUMMARY}" aria-selected="false">Summary</button>

        <!-- Top Menu Right-Aligned Meter Status Pill -->
        <div class="main-sync-badge" id="main-meter-sync" style="display:none;margin-left:auto;"></div>
      </div>

      <!-- ── TAB 1: SHOUT ── -->
      <div class="panel" id="panel-${TAB_SHOUT}" role="tabpanel">
        <div class="picker-grid">
          <div>
            <div class="ctrl-label">Date</div>
            <input type="date" id="book-date" class="ctrl-input">
          </div>
          <div>
            <div class="ctrl-label">Start Time</div>
            <select id="book-hour" class="ctrl-select">${hours}</select>
          </div>
        </div>

        <div class="ctrl-label">Duration</div>
        <div class="seg" id="dur-seg">
          <button data-dur="1">1h</button>
          <button data-dur="2" class="sel">2h</button>
          <button data-dur="3">3h</button>
          <button data-dur="4">4h</button>
        </div>

        <button class="cta" id="book-cta">
          Book Power Shout →
        </button>

        <div class="ctrl-label" id="booked-lbl">Booked</div>
        <div id="booking-list"></div>

        <div class="cost">
          <div>
            <div class="big" id="cost-val">—</div>
            <div class="sub" id="cost-sub">forecast today</div>
          </div>
          <div class="toggle" id="unit-toggle">
            <button class="sel" data-unit="money">$</button>
            <button data-unit="kwh">kWh</button>
          </div>
        </div>
      </div>

      <!-- ── TAB 2: UNIFIED USAGE ── -->
      <div class="panel" id="panel-${TAB_USAGE}" role="tabpanel" hidden>
        
        <div class="detailed-usage-card">
          <div class="service-subtabs-row">
            <div class="service-subtabs" id="service-subtabs">
              <button class="sel" data-service="recent" id="btn-subtab-recent">Recent</button>
              <button data-service="elec" id="btn-subtab-elec">Electricity</button>
              <button data-service="gas" id="btn-subtab-gas">Natural Gas</button>
              <button data-service="ev" id="btn-subtab-ev" style="display:none;">EV</button>
            </div>

            <!-- Targeted Sync Button located in Submenu Row -->
            <button class="sync-action-btn" id="subtab-sync-btn" title="Sync current view data">
              <svg class="sync-icon" viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
                <path d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46A7.93 7.93 0 0020 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74A7.93 7.93 0 004 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z"/>
              </svg>
              <span>Sync</span>
            </button>
          </div>

          <!-- Controls for Recent Mode -->
          <div id="recent-controls-wrap">
            <div class="usage-metrics-row">
              <div class="usage-metric-box">
                <span class="usage-metric-lbl">Daily avg.</span>
                <span class="usage-metric-val" id="usage-daily-avg">$—</span>
              </div>
              <div class="usage-metric-box">
                <span class="usage-metric-lbl">Total used</span>
                <span class="usage-metric-val" id="usage-total-used">$—</span>
              </div>
            </div>
            <div class="usage-period-center" id="usage-period-name">—</div>
          </div>

          <!-- Controls for Historical Browsing Mode (Elec, Gas, EV) -->
          <div id="historical-controls-wrap" style="display:none;">
            <div class="analytics-toolbar">
              <div class="granularity-pill" id="granularity-pill">
                <button data-gran="monthly" id="btn-gran-monthly">Monthly</button>
                <button data-gran="daily" class="sel" id="btn-gran-daily">Daily</button>
              </div>
              <div class="unit-toggle-wrap">
                <span>kWh</span>
                <button class="unit-switch" id="detail-unit-switch" title="Toggle kWh / $"></button>
                <span>$</span>
              </div>
            </div>

            <div class="date-navigator">
              <button class="date-nav-btn" id="date-nav-prev">‹</button>
              <div class="date-nav-label" id="date-nav-label">— ▾</div>
              <button class="date-nav-btn" id="date-nav-next">›</button>

              <div class="date-popover" id="date-popover" hidden>
                <div class="date-popover-header">
                  <span style="font-size:12px;font-weight:700;color:var(--genesis-muted);">Select Period</span>
                  <select class="date-popover-year" id="date-popover-year"></select>
                </div>
                <div class="date-popover-grid" id="date-popover-months"></div>
                <div class="date-popover-footer">
                  <button class="date-popover-clear-btn" id="btn-clear-cache">🗑️ Clear Cached Usage</button>
                </div>
              </div>
            </div>
          </div>

          <!-- Single Unified Chart Canvas -->
          <div class="chart-container" id="chart-wrap">
            <svg class="chart-svg" id="usage-chart-svg" viewBox="0 0 460 195"></svg>
            <div class="chart-tooltip" id="chart-tooltip"></div>
            <div class="chart-loading-overlay" id="chart-loading-overlay" hidden>
              <span class="spin" style="width:22px;height:22px;border-width:2.5px;color:var(--genesis-orange);"></span>
              <span style="font-size:12px;font-weight:700;color:var(--genesis-muted);">Loading usage…</span>
            </div>
            <div class="chart-timeline-track" id="recent-timeline-track">
              <div class="chart-timeline-fill" id="chart-timeline-fill" style="width:0%"></div>
            </div>
          </div>

          <div class="chart-legend" id="usage-legend"></div>
        </div>

      </div>

      <!-- ── TAB 3: PAST HOURS ── -->
      <div class="panel" id="panel-${TAB_PAST}" role="tabpanel" hidden>
        <div id="past-body">
          <div class="ctrl-label">Top Recommended Past Hours (Max Savings)</div>
          <div class="ranked-scroll"><div id="ranked-list"></div></div>
          <div class="selection-help" id="selection-help"></div>
          <button class="wide-btn" id="redeem-selected" disabled>Redeem selected</button>
        </div>
        <div class="result" id="past-result" hidden></div>
      </div>

      <!-- ── TAB 4: FORECAST ── -->
      <div class="panel" id="panel-${TAB_FORECAST}" role="tabpanel" hidden>
        <div class="ctrl-label">Daily Forecast Prediction</div>
        <div class="cost" style="border-top:0;margin-top:6px;padding-top:0;">
          <div>
            <div class="big" id="cost-val-alt">—</div>
            <div class="sub" id="cost-sub-alt">forecast today</div>
          </div>
          <div class="toggle" id="unit-toggle-alt">
            <button class="sel" data-unit="money">$</button>
            <button data-unit="kwh">kWh</button>
          </div>
        </div>
      </div>

      <!-- ── TAB 5: SUMMARY (Current Bill, Services, Tariffs) ── -->
      <div class="panel" id="panel-${TAB_SUMMARY}" role="tabpanel" hidden>
        <div id="summary-content"></div>
      </div>

    </div>

    <div class="modal" id="confirm-modal" hidden>
      <div class="dialog">
        <h3 id="confirm-title">Confirm Power Shout</h3>
        <div class="dialog-sub" id="confirm-sub">Review booking details</div>
        
        <div class="summary-box" id="confirm-summary"></div>

        <div class="warning" id="confirm-warning">
          Free electricity will apply for the selected duration.
        </div>
        
        <div class="dialog-actions">
          <button class="secondary" id="confirm-cancel">Cancel / No</button>
          <button class="primary" id="confirm-submit">Yes, Confirm Booking</button>
        </div>
      </div>
    </div>`;
}

class GenesisPowerShoutCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._built = false;
    this._selectedDuration = 2;
    this._unit = "money";
    this._tab = TAB_SHOUT;

    this._hasPowerShout = true;
    this._hasElectricity = true;
    this._hasGas = false;
    this._hasEv = false;

    this._activeService = "recent";
    this._activeGranularity = "daily";
    this._detailUnit = "dollar";
    this._navDate = new Date();
    this._lastNavDirection = 1;

    this._selectedHours = new Set();
    this._rankedHours = [];
    this._pendingBooking = null;
    this._bookingInProgress = false;
    this._cancellingId = null;
    this._lastBookings = [];
    this._availableBalance = 0;
    this._offerId = null;

    this._currentDaysData = [];
    this._currentDetailData = [];
    this._usageCache = {};
    this._monthDailyCache = { elec: new Map(), gas: new Map(), ev: new Map() };
    this._popoverOpen = false;
    this._loadingDetail = false;
    this._prefetchTimer = null;
  }

  setConfig(config) {
    this._config = config || {};
    if (this._config.default_tab) {
      this._tab = this._config.default_tab;
    }
    if (this._config.clear_cache === true) {
      this._clearAllCache();
    }
    this._applyCustomBannerColors();
  }

  _applyCustomBannerColors() {
    const liveColor = this._config.live_banner_color || this._config.live_color;
    if (liveColor) {
      this.style.setProperty("--live-banner-bg", liveColor);
    }
    const offerColor = this._config.offer_banner_color || this._config.offer_color;
    if (offerColor) {
      this.style.setProperty("--offer-banner-border", offerColor);
    }
    const expColor = this._config.expiring_banner_color || this._config.expiring_color;
    if (expColor) {
      this.style.setProperty("--expiring-banner-border", expColor);
    }
  }

  getCardSize() {
    return 7;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();

    this._applyThemeMode();
    this._update();
  }

  _clearAllCache() {
    this._usageCache = {};
    this._monthDailyCache = { elec: new Map(), gas: new Map(), ev: new Map() };
    try {
      const keysToRemove = [];
      for (let i = 0; i < sessionStorage.length; i++) {
        const k = sessionStorage.key(i);
        if (k && (k.startsWith("genesis_") || k.startsWith("genesisenergy_"))) {
          keysToRemove.push(k);
        }
      }
      keysToRemove.forEach((k) => sessionStorage.removeItem(k));
      console.info("[Genesis Card] Local browser cache cleared.");
    } catch (err) {
      console.warn("Could not clear sessionStorage:", err);
    }
  }

  _applyThemeMode() {
    let isDark = false;
    try {
      const card = this.shadowRoot?.querySelector(".card") || this;
      const comp = getComputedStyle(card);
      const textColor = comp.getPropertyValue("--primary-text-color").trim();
      if (textColor.startsWith("#")) {
        const hex = textColor.replace("#", "");
        const r = parseInt(hex.length === 3 ? hex[0] + hex[0] : hex.slice(0, 2), 16);
        const g = parseInt(hex.length === 3 ? hex[1] + hex[1] : hex.slice(2, 4), 16);
        const b = parseInt(hex.length === 3 ? hex[2] + hex[2] : hex.slice(4, 6), 16);
        isDark = 0.2126 * r + 0.7152 * g + 0.0722 * b > 128;
      } else if (textColor.startsWith("rgb")) {
        const m = textColor.match(/\d+/g);
        if (m && m.length >= 3) {
          isDark = 0.2126 * Number(m[0]) + 0.7152 * Number(m[1]) + 0.0722 * Number(m[2]) > 128;
        }
      }

      if (!isDark && !textColor) {
        isDark = Boolean(
          this._hass?.themes?.darkMode ||
          document.documentElement.getAttribute("data-theme") === "dark" ||
          window.matchMedia("(prefers-color-scheme: dark)").matches
        );
      }
    } catch {
      isDark = Boolean(window.matchMedia("(prefers-color-scheme: dark)").matches);
    }

    this.classList.toggle("theme-dark", isDark);
  }

  _resolveEntities() {
    const states = this._hass.states;
    const findId = (pattern) => Object.keys(states).find((id) => id.includes(pattern));

    return {
      entity_balance: findId("powershout_balance") || findId("power_shout_balance") || "sensor.genesis_energy_power_shout_balance",
      entity_offers_available: findId("powershout_offers_available") || findId("power_shout_offers_available") || "binary_sensor.genesis_energy_power_shout_offers_available",
      entity_eligible: findId("powershout_eligible") || findId("power_shout_eligible") || "sensor.genesis_energy_power_shout_eligible",
      entity_forecast_cost: findId("forecast_cost") || "sensor.genesis_energy_today_s_forecast_cost",
      entity_forecast_usage: findId("forecast_usage") || "sensor.genesis_energy_today_s_forecast_usage",
      entity_estimated_bill: findId("bill_estimated_total") || "sensor.genesis_energy_genesis_bill_estimated_total",
      entity_bill_total_used: findId("bill_total_used") || "sensor.genesis_energy_genesis_bill_total_used",
      entity_account_details: findId("account_details") || "sensor.genesis_energy_account_details",
      entity_lpg: findId("lpg_details") || "sensor.genesis_energy_lpg_details",
      entity_ev_usage: findId("ev_plan_day_usage") || findId("ev_day_usage") || findId("ev_") || "sensor.genesis_energy_ev_plan_day_usage",
      entity_bill_balance: findId("bill_balance") || "sensor.genesis_energy_bill_balance",
      entity_bill_due_date: findId("bill_due_date") || "sensor.genesis_energy_bill_due_date",
      entity_booking_in_progress: findId("powershout_booking_in_progress") || "binary_sensor.genesis_energy_power_shout_booking_in_progress",
      entity_electricity_updater: findId("electricity_statistics_updater") || "sensor.genesis_energy_electricity_statistics_updater",
      entity_gas_updater: findId("gas_statistics_updater") || "sensor.genesis_energy_gas_statistics_updater",
      ...this._config,
    };
  }

  _getHiddenServices() {
    const hidden = new Set();
    const cfgHidden = this._config.hidden_services;
    if (Array.isArray(cfgHidden)) {
      cfgHidden.forEach((s) => hidden.add(String(s).toLowerCase().trim()));
    } else if (typeof cfgHidden === "string") {
      cfgHidden.split(",").forEach((s) => hidden.add(s.toLowerCase().trim()));
    }
    if (this._config.show_ev === false) hidden.add("ev");
    if (this._config.show_gas === false || this._config.show_natural_gas === false) hidden.add("gas");
    if (this._config.show_elec === false || this._config.show_electricity === false) hidden.add("elec");
    if (this._config.show_recent === false) hidden.add("recent");
    return hidden;
  }

  _build() {
    this.shadowRoot.innerHTML = buildTemplate(LOGO_SVG_URL);
    this._built = true;
    this._initDateLimits();
    this._wireListeners();
    this._applyCustomBannerColors();
  }

  _el(id) {
    return this.shadowRoot.getElementById(id);
  }

  _initDateLimits() {
    const today = new Date();
    const past31 = new Date();
    past31.setDate(today.getDate() - 31);
    const future60 = new Date();
    future60.setDate(today.getDate() + 60);

    const pad = (n) => String(n).padStart(2, "0");
    const todayStr = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;

    const dateInput = this._el("book-date");
    dateInput.min = `${past31.getFullYear()}-${pad(past31.getMonth() + 1)}-${pad(past31.getDate())}`;
    dateInput.max = `${future60.getFullYear()}-${pad(future60.getMonth() + 1)}-${pad(future60.getDate())}`;
    dateInput.value = todayStr;

    const nextHour = (today.getHours() + 1) % 24;
    this._el("book-hour").value = String(nextHour).padStart(2, "0");
  }

  _wireListeners() {
    const logoImg = this._el("hero-logo-img");
    if (logoImg) {
      logoImg.addEventListener("error", () => {
        if (!logoImg.dataset.fallbackTried) {
          logoImg.dataset.fallbackTried = "true";
          logoImg.src = LOGO_PNG_URL;
        }
      });
    }

    this.shadowRoot.querySelectorAll('[role="tab"]').forEach((tab) => {
      tab.addEventListener("click", () => this._selectTab(tab.dataset.tab));
    });

    this.shadowRoot.querySelectorAll("#dur-seg button").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.shadowRoot.querySelectorAll("#dur-seg button").forEach((b) => b.classList.remove("sel"));
        btn.classList.add("sel");
        this._selectedDuration = parseInt(btn.dataset.dur, 10);
        this._syncCtaText();
      });
    });

    this._el("book-date").addEventListener("change", () => this._syncCtaText());
    this._el("book-hour").addEventListener("change", () => this._syncCtaText());

    const wireUnitToggle = (containerId) => {
      this.shadowRoot.querySelectorAll(`#${containerId} button`).forEach((btn) => {
        btn.addEventListener("click", () => {
          this.shadowRoot
            .querySelectorAll("#unit-toggle button, #unit-toggle-alt button")
            .forEach((b) => b.classList.remove("sel"));
          
          this.shadowRoot
            .querySelectorAll(`button[data-unit="${btn.dataset.unit}"]`)
            .forEach((b) => b.classList.add("sel"));

          this._unit = btn.dataset.unit;
          this._updateForecast();
        });
      });
    };
    wireUnitToggle("unit-toggle");
    wireUnitToggle("unit-toggle-alt");

    this._el("book-cta").addEventListener("click", () => this._openBookingConfirmation());
    this._el("offer-btn").addEventListener("click", () => this._acceptOffer());

    this._el("booking-list").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-cancel-id]");
      if (btn) this._cancelBooking(btn.dataset.cancelId);
    });

    this._el("ranked-list").addEventListener("change", (event) => {
      const checkbox = event.target.closest("input[data-start]");
      if (!checkbox) return;
      const start = checkbox.dataset.start;

      if (checkbox.checked) {
        if (this._selectedHours.size >= this._availableBalance) {
          checkbox.checked = false;
          this._showFeedback(`You cannot select more than your available balance (${this._availableBalance} hr).`, true);
          return;
        }
        this._selectedHours.add(start);
      } else {
        this._selectedHours.delete(start);
      }
      this._syncSelection();
    });

    this._el("redeem-selected").addEventListener("click", () => {
      const starts = this._rankedHours
        .filter((item) => this._selectedHours.has(item.start_datetime))
        .map((item) => item.start_datetime);
      if (starts.length) this._reviewPastRecommendations(starts);
    });

    this._el("confirm-cancel").addEventListener("click", () => {
      this._el("confirm-modal").setAttribute("hidden", "");
    });
    this._el("confirm-modal").addEventListener("click", (e) => {
      if (e.target.id === "confirm-modal") this._el("confirm-modal").setAttribute("hidden", "");
    });

    this._el("confirm-submit").addEventListener("click", () => {
      this._executeConfirmedBooking();
    });

    // Subtabs within Unified Usage Card
    this.shadowRoot.querySelectorAll("#service-subtabs button").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.shadowRoot.querySelectorAll("#service-subtabs button").forEach((b) => b.classList.remove("sel"));
        btn.classList.add("sel");
        this._activeService = btn.dataset.service;

        // If EV is selected, enforce daily granularity and align date bounds
        if (this._activeService === "ev") {
          this._activeGranularity = "daily";
          const now = new Date();
          const minEv = new Date(now.getFullYear(), now.getMonth() - 1, 1);
          if (this._navDate < minEv) {
            this._navDate = minEv;
          }
        }

        this._updateMainMeterSyncBadge(this._entities);
        this._renderUnifiedUsageGraph();
      });
    });

    // Surgical Targeted Sync Button in Sub-Menu Row
    const syncBtn = this._el("subtab-sync-btn");
    if (syncBtn) {
      syncBtn.addEventListener("click", () => {
        this._triggerTargetedSync();
      });
    }

    // Granularity (Monthly / Daily)
    this.shadowRoot.querySelectorAll("#granularity-pill button").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (this._activeService === "ev" && btn.dataset.gran === "monthly") return;
        this.shadowRoot.querySelectorAll("#granularity-pill button").forEach((b) => b.classList.remove("sel"));
        btn.classList.add("sel");
        this._activeGranularity = btn.dataset.gran;
        this._closePopover();
        this._renderUnifiedUsageGraph();
      });
    });

    const unitSwitch = this._el("detail-unit-switch");
    unitSwitch.classList.toggle("active-dollar", this._detailUnit === "dollar");
    unitSwitch.addEventListener("click", () => {
      this._detailUnit = this._detailUnit === "dollar" ? "kwh" : "dollar";
      unitSwitch.classList.toggle("active-dollar", this._detailUnit === "dollar");
      this._renderUnifiedUsageGraph();
    });

    this._el("date-nav-prev").addEventListener("click", () => {
      this._lastNavDirection = -1;
      this._shiftDate(-1);
    });
    this._el("date-nav-next").addEventListener("click", () => {
      this._lastNavDirection = 1;
      this._shiftDate(1);
    });

    // Calendar Popover Toggle
    this._el("date-nav-label").addEventListener("click", (e) => {
      e.stopPropagation();
      this._togglePopover();
    });

    this.shadowRoot.addEventListener("click", (e) => {
      if (!e.target.closest("#date-popover") && !e.target.closest("#date-nav-label")) {
        this._closePopover();
      }
    });

    // Clear Cache Button in Popover
    this._el("btn-clear-cache").addEventListener("click", () => {
      this._clearAllCache();
      const btn = this._el("btn-clear-cache");
      const origText = btn.textContent;
      btn.textContent = "✓ Cache Cleared!";
      setTimeout(() => {
        btn.textContent = origText;
        this._closePopover();
        this._renderUnifiedUsageGraph();
      }, 600);
    });

    // SVG Hitbox Interaction & Click-to-Drilldown
    const svg = this._el("usage-chart-svg");
    const chartWrap = this._el("chart-wrap");

    svg.addEventListener("pointermove", (e) => {
      const target = e.target.closest(".chart-col-hit");
      if (target) {
        const idx = parseInt(target.dataset.col, 10);
        this._showTooltip(idx);
      }
    });
    chartWrap.addEventListener("pointerleave", () => this._hideTooltip());

    svg.addEventListener("click", (e) => {
      if (this._activeService === "recent") return;
      const target = e.target.closest(".chart-col-hit");
      if (!target) return;
      const idx = parseInt(target.dataset.col, 10);
      const d = this._currentDetailData[idx];
      if (!d) return;

      if (this._activeGranularity === "monthly" && d.hasData) {
        this._navDate.setMonth(idx);
        this._activeGranularity = "daily";

        this.shadowRoot.querySelectorAll("#granularity-pill button").forEach((b) => {
          b.classList.toggle("sel", b.dataset.gran === "daily");
        });

        this._hideTooltip();
        this._renderUnifiedUsageGraph();
      }
    });
  }

  _togglePopover() {
    this._popoverOpen = !this._popoverOpen;
    const pop = this._el("date-popover");
    if (this._popoverOpen) {
      this._renderPopoverContent();
      pop.removeAttribute("hidden");
    } else {
      pop.setAttribute("hidden", "");
    }
  }

  _closePopover() {
    this._popoverOpen = false;
    const pop = this._el("date-popover");
    if (pop) pop.setAttribute("hidden", "");
  }

  _renderPopoverContent() {
    const now = new Date();
    const currentYear = now.getFullYear();
    const currentMonth = now.getMonth();
    const isEv = this._activeService === "ev";
    const minYear = isEv ? EV_START_YEAR : currentYear - 3;

    const yearSelect = this._el("date-popover-year");
    const monthsGrid = this._el("date-popover-months");

    let yearOptions = "";
    for (let y = currentYear; y >= minYear; y--) {
      const sel = y === this._navDate.getFullYear() ? " selected" : "";
      yearOptions += `<option value="${y}"${sel}>${y}</option>`;
    }
    yearSelect.innerHTML = yearOptions;

    const renderMonthsForYear = (chosenYear) => {
      const monthsShort = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
      let mHtml = "";
      for (let m = 0; m < 12; m++) {
        const isFuture = (chosenYear === currentYear && m > currentMonth);
        const isTooOldForEv = isEv && (chosenYear < EV_START_YEAR || (chosenYear === EV_START_YEAR && m < EV_START_MONTH));
        const disabled = isFuture || isTooOldForEv;
        const isSel = (chosenYear === this._navDate.getFullYear() && m === this._navDate.getMonth());
        mHtml += `
          <button class="date-popover-month-btn${isSel ? ' sel' : ''}" data-m="${m}" ${disabled ? 'disabled' : ''}>
            ${monthsShort[m]}
          </button>
        `;
      }
      monthsGrid.innerHTML = mHtml;

      monthsGrid.querySelectorAll(".date-popover-month-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          const m = parseInt(btn.dataset.m, 10);
          this._navDate.setFullYear(chosenYear);
          this._navDate.setMonth(m);
          this._closePopover();
          this._renderUnifiedUsageGraph();
        });
      });
    };

    renderMonthsForYear(this._navDate.getFullYear());

    yearSelect.onchange = () => {
      const newY = parseInt(yearSelect.value, 10);
      if (this._activeGranularity === "monthly") {
        this._navDate.setFullYear(newY);
        this._closePopover();
        this._renderUnifiedUsageGraph();
      } else {
        renderMonthsForYear(newY);
      }
    };
  }

  _shiftDate(direction) {
    const now = new Date();
    const currentYear = now.getFullYear();
    const currentMonth = now.getMonth();
    const isEv = this._activeService === "ev";
    const minYear = isEv ? currentYear : currentYear - 3;

    if (this._activeGranularity === "monthly" && !isEv) {
      const nextY = this._navDate.getFullYear() + direction;
      if (nextY >= minYear && nextY <= currentYear) {
        this._navDate.setFullYear(nextY);
      }
    } else if (this._activeGranularity === "daily") {
      const testD = new Date(this._navDate);
      testD.setMonth(testD.getMonth() + direction);
      const testY = testD.getFullYear();
      const testM = testD.getMonth();

      let isPastLimit = testY < minYear;
      if (isEv) {
        isPastLimit = (testY < EV_START_YEAR) || (testY === EV_START_YEAR && testM < EV_START_MONTH);
      }
      
      const isFutureLimit = (testY > currentYear) || (testY === currentYear && testM > currentMonth);

      if (!isPastLimit && !isFutureLimit) {
        this._navDate = testD;
      }
    }
    this._renderUnifiedUsageGraph();
  }

  _showTooltip(idx) {
    const tooltip = this._el("chart-tooltip");
    const chartWrap = this._el("chart-wrap");

    if (this._activeService === "recent") {
      const d = this._currentDaysData[idx];
      if (!d || !d.hasData) {
        this._hideTooltip();
        return;
      }

      let psBadgeHtml = d.hasPS ? `<div class="tip-ps-badge">${PS_PIN_SVG} Power Shout Applied</div>` : "";
      let gasRowHtml = (this._hasGas || d.gas > 0) ? `
        <div class="tip-row"><span>Gas:</span><span>$${fmtNum(d.gas, 2)}</span></div>
      ` : "";

      tooltip.innerHTML = `
        <div class="tip-date-row"><span>${escapeHtml(fmtTooltipDate(d.date))}</span></div>
        <div class="tip-row"><span>Electricity:</span><span>$${fmtNum(d.elec, 2)}</span></div>
        ${gasRowHtml}
        <div class="tip-divider"></div>
        <div class="tip-row total"><span>Total:</span><span>$${fmtNum(d.total, 2)}</span></div>
        ${psBadgeHtml}
      `;

      const cxPct = d.cx / 460;
      const wrapRect = chartWrap.getBoundingClientRect();
      const isRightHalf = (cxPct * wrapRect.width) > (wrapRect.width / 2);
      tooltip.style.left = isRightHalf ? "8px" : "auto";
      tooltip.style.right = isRightHalf ? "auto" : "8px";
      tooltip.style.top = "6px";
      tooltip.classList.add("visible");
    } else if (this._activeService === "ev") {
      const d = this._currentDetailData[idx];
      if (!d || !d.hasData) {
        this._hideTooltip();
        return;
      }

      let savingsHtml = d.savings > 0 ? `
        <div class="tip-divider"></div>
        <div class="tip-row" style="color:#00838f;font-weight:800;">
          <span>💰 Off-Peak Savings:</span>
          <span>+$${fmtNum(d.savings, 2)}</span>
        </div>
      ` : "";

      tooltip.innerHTML = `
        <div class="tip-date-row">
          <span>${escapeHtml(d.title)}</span>
          <span class="tip-kwh">${fmtNum(d.kw, 2)} kWh</span>
        </div>
        <div class="tip-row total">
          <span>Total Cost:</span>
          <span style="font-weight:800;">$${fmtNum(d.cost, 2)}</span>
        </div>
        <div class="tip-divider"></div>
        <div class="tip-row">
          <span>☀️ Day:</span>
          <span>${fmtNum(d.kwDay, 2)} kWh ($${fmtNum(d.costDay, 2)})</span>
        </div>
        <div class="tip-row">
          <span>🌙 Night (EV):</span>
          <span>${fmtNum(d.kwNight, 2)} kWh ($${fmtNum(d.costNight, 2)})</span>
        </div>
        ${savingsHtml}
      `;

      const cxPct = d.cx / 460;
      const wrapRect = chartWrap.getBoundingClientRect();
      const isRightHalf = (cxPct * wrapRect.width) > (wrapRect.width / 2);
      tooltip.style.left = isRightHalf ? "8px" : "auto";
      tooltip.style.right = isRightHalf ? "auto" : "8px";
      tooltip.style.top = "6px";
      tooltip.classList.add("visible");
    } else {
      const d = this._currentDetailData[idx];
      if (!d || !d.hasData) {
        this._hideTooltip();
        return;
      }

      let psBadgeHtml = "";
      if (d.hasPS) {
        let extraInfo = "";
        if (d.psCredits > 0) extraInfo += ` · $${fmtNum(d.psCredits, 2)} credited`;
        if (d.psConsumptions > 0) extraInfo += ` (${fmtNum(d.psConsumptions, 2)} kWh free)`;
        psBadgeHtml = `<div class="tip-ps-badge">${PS_PIN_SVG} Power Shout${extraInfo || " Applied"}</div>`;
      }

      let drillHint = (this._activeGranularity === "monthly" && d.hasData)
        ? `<div class="tip-drilldown">Click bar to view daily usage ↗</div>`
        : "";

      tooltip.innerHTML = `
        <div class="tip-date-row">
          <span>${escapeHtml(d.title)}</span>
          <span class="tip-kwh">${fmtNum(d.kw, 2)} kWh</span>
        </div>
        <div class="tip-row total">
          <span>${escapeHtml(d.label)}</span>
          <span style="font-weight:800;">$${fmtNum(d.cost, 2)}</span>
        </div>
        ${psBadgeHtml}
        ${drillHint}
      `;

      const cxPct = d.cx / 460;
      const wrapRect = chartWrap.getBoundingClientRect();
      const isRightHalf = (cxPct * wrapRect.width) > (wrapRect.width / 2);
      tooltip.style.left = isRightHalf ? "8px" : "auto";
      tooltip.style.right = isRightHalf ? "auto" : "8px";
      tooltip.style.top = "6px";
      tooltip.classList.add("visible");
    }
  }

  _hideTooltip() {
    const tooltip = this._el("chart-tooltip");
    if (tooltip) tooltip.classList.remove("visible");
  }

  _syncCtaText() {
    const dateStr = this._el("book-date").value;
    const hourStr = this._el("book-hour").value;
    if (!dateStr || hourStr === "") return;

    const endLabel = calculateEndHour(dateStr, hourStr, this._selectedDuration);
    const selHourOption = this._el("book-hour").selectedOptions[0];
    const hourLabel = selHourOption ? selHourOption.textContent : "";

    this._el("book-cta").textContent = `Book ${this._selectedDuration}h (${hourLabel} – ${endLabel}) →`;
  }

  _selectTab(tab) {
    if (!tab) return;
    this._tab = tab;
    this.shadowRoot.querySelectorAll('[role="tab"]').forEach((btn) => {
      btn.setAttribute("aria-selected", String(btn.dataset.tab === tab));
    });
    for (const name of [TAB_SHOUT, TAB_USAGE, TAB_PAST, TAB_FORECAST, TAB_SUMMARY]) {
      const panel = this._el(`panel-${name}`);
      if (panel) panel.toggleAttribute("hidden", name !== tab);
    }
    this._updateMainMeterSyncBadge(this._entities);

    // Lazy load the usage canvas ONLY when navigating to the Usage tab
    if (tab === TAB_USAGE) {
      this._renderUnifiedUsageGraph();
    }
  }

  _openBookingConfirmation() {
    const dateStr = this._el("book-date").value;
    const hourStr = this._el("book-hour").value;
    if (!dateStr || hourStr === "") return;

    const [y, m, d] = dateStr.split("-").map(Number);
    const pad = (n) => String(n).padStart(2, "0");
    const startDatetime = `${y}-${pad(m)}-${pad(d)} ${pad(hourStr)}:00:00`;
    const endLabel = calculateEndHour(dateStr, hourStr, this._selectedDuration);
    const selHourOption = this._el("book-hour").selectedOptions[0];
    const hourLabel = selHourOption ? selHourOption.textContent : "";

    this._pendingBooking = {
      items: [{ start_datetime: startDatetime, duration_hours: this._selectedDuration }],
    };

    this._el("confirm-title").textContent = "Book Power Shout?";
    this._el("confirm-sub").textContent = "Please confirm your session:";
    this._el("confirm-warning").textContent = "Free electricity will apply for the selected duration.";
    this._el("confirm-summary").innerHTML = `
      <div class="summary-row"><span>Date:</span> <strong>${fmtDisplayDate(dateStr)}</strong></div>
      <div class="summary-row"><span>Time:</span> <strong>${hourLabel} – ${endLabel}</strong></div>
      <div class="summary-row"><span>Duration:</span> <b>${this._selectedDuration} hour${this._selectedDuration === 1 ? "" : "s"}</b></div>
    `;
    this._el("confirm-modal").removeAttribute("hidden");
  }

  _reviewPastRecommendations(starts) {
    const items = starts.map((s) => ({ start_datetime: s, duration_hours: 1 }));
    this._pendingBooking = { items };

    const listHtml = starts
      .map((s) => `
        <div class="summary-row">
          <span>${fmtPastHour(s)}</span>
          <b>1 hr</b>
        </div>
      `)
      .join("");

    this._el("confirm-title").textContent = "Redeem Past Hours?";
    this._el("confirm-sub").textContent = `Apply free power to ${starts.length} past session(s):`;
    this._el("confirm-warning").textContent = "Credits will be retroactively applied to your billing account.";
    this._el("confirm-summary").innerHTML = listHtml;
    this._el("confirm-modal").removeAttribute("hidden");
  }

  async _executeConfirmedBooking() {
    if (!this._pendingBooking || this._bookingInProgress) return;

    this._bookingInProgress = true;
    const submit = this._el("confirm-submit");
    const originalText = submit.textContent;
    submit.innerHTML = '<span class="spin"></span>Booking…';
    submit.disabled = true;

    try {
      for (const item of this._pendingBooking.items) {
        const normalizedDt = item.start_datetime.replace("T", " ").split(".")[0];
        await this._hass.callService(DOMAIN, "add_powershout_booking", {
          start_datetime: normalizedDt,
          duration_hours: item.duration_hours,
        });
      }
      this._showFeedback("Power Shout booked successfully!", false);
      this._selectedHours.clear();
      this._syncSelection();
    } catch (err) {
      this._showFeedback(`Booking failed: ${err.message || err}`, true);
    } finally {
      this._bookingInProgress = false;
      submit.textContent = originalText;
      submit.disabled = false;
      this._el("confirm-modal").setAttribute("hidden", "");
    }
  }

  async _cancelBooking(id) {
    if (!this._hass || !id || this._cancellingId) return;
    this._cancellingId = id;
    this._renderBookings(this._lastBookings);

    try {
      await this._hass.callService(DOMAIN, "cancel_powershout_booking", {
        booking_id: id,
      });
      this._showFeedback("Power Shout booking cancelled.", false);
    } catch (err) {
      this._showFeedback(`Cancellation error: ${err.message || err}`, true);
    } finally {
      this._cancellingId = null;
      this._update();
    }
  }

  _showFeedback(msg, isError) {
    const el = this._el("past-result");
    el.className = `result ${isError ? "bad" : "ok"}`;
    el.textContent = msg;
    el.removeAttribute("hidden");
  }

  async _acceptOffer() {
    if (!this._offerId) return;
    const btn = this._el("offer-btn");
    const origText = btn.textContent;
    btn.innerHTML = '<span class="spin"></span>Adding…';
    btn.disabled = true;

    try {
      await this._hass.callService(DOMAIN, "accept_powershout_offer", {
        offer_id: this._offerId,
      });
      this._showFeedback("Power Shout offer added to your balance!", false);
    } catch (err) {
      this._showFeedback(`Could not accept offer: ${err.message || err}`, true);
    } finally {
      btn.textContent = origText;
      btn.disabled = false;
    }
  }

  _showChartLoading(isLoading) {
    const overlay = this._el("chart-loading-overlay");
    const svg = this._el("usage-chart-svg");
    if (overlay) overlay.toggleAttribute("hidden", !isLoading);
    if (svg) svg.style.opacity = isLoading ? "0.38" : "1";
  }

  _update() {
    if (!this._built || !this._hass) return;
    const entities = this._resolveEntities();
    this._entities = entities;

    if (this._config.name || this._config.title) {
      const customTitle = this._config.name || this._config.title;
      this._el("account-title-label").textContent = customTitle;
    }

    const balSt = this._hass.states[entities.entity_balance];
    const eligSt = this._hass.states[entities.entity_eligible];

    const hasBalanceSensor = Boolean(
      balSt &&
      balSt.state !== "unavailable" &&
      balSt.state !== "unknown" &&
      !isNaN(parseFloat(balSt.state))
    );

    let isEligible = true;
    if (eligSt && eligSt.state !== "unavailable" && eligSt.state !== "unknown") {
      const s = String(eligSt.state).trim().toLowerCase();
      isEligible = s === "true" || s === "on" || s === "ok" || s === "eligible";
    }

    let hasPowerShout = hasBalanceSensor && isEligible;
    if (this._config.show_powershout === true) {
      hasPowerShout = true;
    } else if (this._config.show_powershout === false) {
      hasPowerShout = false;
    } else if (!hasPowerShout && hasBalanceSensor) {
      hasPowerShout = true;
    }

    this._hasPowerShout = hasPowerShout;

    const acctDetailsSt = this._hass.states[entities.entity_account_details];
    const attrs = acctDetailsSt?.attributes || {};
    const sidekick = parseData(attrs.widget_sidekick) || parseData(attrs.widget_bill_summary_v2)?.billEstimated;
    const supplies = sidekick?.supplyTypesArea?.supplyTypes || [];
    
    this._hasGas = supplies.some(s => (s.type || s.text || "").toLowerCase().includes("gas"));
    this._hasEv = Boolean(
      this._hass.states[entities.entity_ev_usage] ||
      JSON.stringify(attrs.billing_plans || "").toLowerCase().includes("ev")
    );
    this._hasElectricity = true;

    // Service Filtering via Config (hidden_services)
    const hidden = this._getHiddenServices();
    const showRecent = !hidden.has("recent");
    const showElec = this._hasElectricity && !hidden.has("elec") && !hidden.has("electricity");
    const showGas = this._hasGas && !hidden.has("gas") && !hidden.has("natural_gas") && !hidden.has("naturalgas");
    const showEv = this._hasEv && !hidden.has("ev");

    this._el("btn-subtab-recent").style.display = showRecent ? "inline-block" : "none";
    this._el("btn-subtab-elec").style.display = showElec ? "inline-block" : "none";
    this._el("btn-subtab-gas").style.display = showGas ? "inline-block" : "none";
    
    const evBtn = this._el("btn-subtab-ev");
    evBtn.style.display = showEv ? "inline-block" : "none";
    evBtn.removeAttribute("hidden");

    const visibleServices = [];
    if (showRecent) visibleServices.push("recent");
    if (showElec) visibleServices.push("elec");
    if (showGas) visibleServices.push("gas");
    if (showEv) visibleServices.push("ev");

    if (!visibleServices.includes(this._activeService)) {
      this._activeService = visibleServices[0] || "recent";
    }

    this.shadowRoot.querySelectorAll("#service-subtabs button").forEach((b) => {
      b.classList.toggle("sel", b.dataset.service === this._activeService);
    });

    const psWrap = this._el("powershout-hero-wrap");
    const psLogoWrap = this._el("powershout-logo-wrap");
    const stdLogoWrap = this._el("standard-logo-wrap");
    const stdWrap = this._el("standard-hero-wrap");
    const tabShout = this._el("tab-shout");
    const tabPast = this._el("tab-past");
    const tabForecast = this._el("tab-forecast");

    this._updateDuePill(entities, hasPowerShout);
    this._updateMainMeterSyncBadge(entities);

    if (hasPowerShout) {
      psWrap.removeAttribute("hidden");
      psLogoWrap.removeAttribute("hidden");
      stdLogoWrap.setAttribute("hidden", "");
      stdWrap.setAttribute("hidden", "");
      tabShout.removeAttribute("hidden");
      tabPast.removeAttribute("hidden");
      tabForecast.setAttribute("hidden", "");

      const num = parseFloat(balSt?.state);
      this._availableBalance = !isNaN(num) ? num : 0;
      this._el("bal-num").textContent = !isNaN(num) ? num : "0";

      const expBar = this._el("expiring-bar");
      const expText = this._el("expiring-text");
      const expMsg = balSt?.attributes?.expiring_hours_message || balSt?.attributes?.expiring_hours_tooltip;
      
      if (expMsg && expMsg.trim() && this._hasPowerShout) {
        expText.innerHTML = escapeHtml(expMsg).replace(/(\d+\s*hours?|\d+\s*hrs?)/gi, '<b>$1</b>');
        expBar.removeAttribute("hidden");
      } else {
        expBar.setAttribute("hidden", "");
      }

      this._lastBookings = balSt?.attributes?.bookings || [];
      this._renderBookings(this._lastBookings);
      this._updatePastHours(balSt?.attributes?.recommended_hours);
      this._updateLiveBar(this._lastBookings, entities);
    } else {
      psWrap.setAttribute("hidden", "");
      psLogoWrap.setAttribute("hidden", "");
      stdLogoWrap.removeAttribute("hidden");
      stdWrap.removeAttribute("hidden");
      tabShout.setAttribute("hidden", "");
      tabPast.setAttribute("hidden", "");
      tabForecast.removeAttribute("hidden");

      this._el("expiring-bar").setAttribute("hidden", "");

      if (this._tab === TAB_SHOUT || this._tab === TAB_PAST) {
        this._selectTab(TAB_USAGE);
      }
    }

    this._selectTab(this._tab);
    this._updateTopBillingBox(entities);

    const offerSt = this._hass.states[entities.entity_offers_available];
    const offerRow = this._el("offer-row");
    const isOfferActive = offerSt && (
      offerSt.state === "on" ||
      offerSt.state === "true" ||
      offerSt.state === "True"
    );

    if (isOfferActive && this._hasPowerShout) {
      const offers = balSt?.attributes?.active_offers || 
                     offerSt?.attributes?.activeOffers || 
                     offerSt?.attributes?.active_offers || [];
      if (offers.length > 0) {
        const o = offers[0];
        const offerGuid = o.loyaltyOffer?.guid || o.id;
        const offerAmount = o.loyaltyOffer?.amount || o.amount || 1;
        this._offerId = offerGuid;
        this._el("offer-lbl").innerHTML = `🎁 <b>+${offerAmount} hr</b> Power Shout offer for you`;
        offerRow.removeAttribute("hidden");
      } else {
        offerRow.setAttribute("hidden", "");
      }
    } else {
      offerRow.setAttribute("hidden", "");
    }

    this._syncCtaText();
    this._updateForecast();
    this._updateSummary(entities);

    // Lazy load the usage canvas: ONLY render when Usage tab is active
    if (this._tab === TAB_USAGE) {
      this._renderUnifiedUsageGraph();
    }
  }

  _updateDuePill(entities, hasPowerShout) {
    const pill = this._el("bill-due-pill");
    const balSt = this._hass.states[entities.entity_bill_balance];
    const dueSt = this._hass.states[entities.entity_bill_due_date];

    let label = hasPowerShout ? "ELIGIBLE" : "ACCOUNT ACTIVE";
    let toneClass = "ok";

    if (balSt && balSt.state !== "unavailable" && balSt.state !== "unknown") {
      const bal = parseFloat(balSt.state);
      if (!isNaN(bal)) {
        if (bal < 0) {
          label = `$${Math.abs(bal).toFixed(2)} in credit`;
          toneClass = "ok";
        } else if (bal === 0) {
          label = "Up to date";
          toneClass = "ok";
        } else {
          const dueStr = dueSt?.state;
          const dueDate = dueStr ? new Date(dueStr) : null;
          if (dueDate && !isNaN(dueDate)) {
            const midnight = new Date();
            midnight.setHours(0, 0, 0, 0);
            dueDate.setHours(0, 0, 0, 0);
            const days = Math.round((dueDate - midnight) / 86400000);
            if (days < 0) {
              label = `Overdue · $${bal.toFixed(2)}`;
              toneClass = "bad";
            } else if (days === 0) {
              label = `Due today · $${bal.toFixed(2)}`;
              toneClass = "bad";
            } else {
              label = `Due ${fmtDate(dueStr)} · $${bal.toFixed(2)}`;
              toneClass = "warn";
            }
          } else {
            label = `$${bal.toFixed(2)} owing`;
            toneClass = "warn";
          }
        }
      }
    }

    pill.className = `elig ${toneClass}`;
    pill.textContent = label;
  }

  _updateMainMeterSyncBadge(entities) {
    const el = this._el("main-meter-sync");
    if (!el) return;

    if (this._tab !== TAB_USAGE) {
      el.style.display = "none";
      return;
    }

    let updaterId = entities?.entity_electricity_updater;
    if (this._activeService === "gas") {
      updaterId = entities?.entity_gas_updater;
    }

    if (!updaterId) {
      el.style.display = "none";
      return;
    }

    const updaterSt = this._hass.states[updaterId];
    const latest = updaterSt?.attributes?.latest_reading;
    const daysBehind = updaterSt?.attributes?.days_behind;

    if (!latest) {
      el.style.display = "none";
      return;
    }

    const d = new Date(latest);
    const dateLabel = isNaN(d) ? latest.split("T")[0] : d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
    const lagText = daysBehind != null ? `(${daysBehind}d lag)` : "";

    let dotClass = "usage-sync-dot";
    if (daysBehind > 3) {
      dotClass += " stalled";
    } else if (daysBehind > 2) {
      dotClass += " lagging";
    }

    el.innerHTML = `
      <span class="${dotClass}"></span>
      <span class="sync-text-prefix">Meter:&nbsp;</span>
      <strong>${escapeHtml(dateLabel)}</strong>&nbsp;
      <span style="opacity:0.8;">${escapeHtml(lagText)}</span>
    `;
    el.style.display = "inline-flex";
  }

  async _triggerTargetedSync() {
    const btn = this._el("subtab-sync-btn");
    if (!btn || btn.classList.contains("syncing")) return;
    btn.classList.add("syncing");

    const service = this._activeService;
    const now = new Date();
    const currentYear = now.getFullYear();
    const pad = (n) => String(n).padStart(2, "0");
    const currentMonthKey = `${currentYear}-${pad(now.getMonth() + 1)}`;

    if (service === "recent") {
      this._usageCache = {};
      try {
        await this._hass.callService("genesisenergy", "force_update", { fuel_type: "both" });
      } catch {}
    } else if (service === "ev") {
      delete this._usageCache["ev_DAILY_current"];
      try {
        await this._hass.callService("genesisenergy", "force_update", { fuel_type: "electricity" });
      } catch {}
    } else {
      const isMonthly = this._activeGranularity === "monthly";
      if (isMonthly) {
        const year = this._navDate.getFullYear();
        this._monthDailyCache[service]?.delete(`genesis_monthly_${service}_${year}`);
        delete this._usageCache[`${service === 'gas' ? 'gas' : 'electricity'}_MONTHLY_${year}-01-01_${year}-12-31`];
        if (year === currentYear) {
          try {
            await this._hass.callService("genesisenergy", "force_update", { fuel_type: service === "gas" ? "gas" : "electricity" });
          } catch {}
        }
      } else {
        const viewedMKey = `${this._navDate.getFullYear()}-${pad(this._navDate.getMonth() + 1)}`;
        this._monthDailyCache[service]?.delete(viewedMKey);
        try {
          sessionStorage.removeItem(`genesis_daily_${service}_${viewedMKey}`);
        } catch {}
        if (viewedMKey === currentMonthKey) {
          try {
            await this._hass.callService("genesisenergy", "force_update", { fuel_type: service === "gas" ? "gas" : "electricity" });
          } catch {}
        }
      }
    }

    try {
      await this._renderUnifiedUsageGraph();
    } finally {
      setTimeout(() => {
        btn.classList.remove("syncing");
      }, 500);
    }
  }

  _updateTopBillingBox(entities) {
    const acctDetailsSt = this._hass.states[entities.entity_account_details];
    const totalUsedSt = this._hass.states[entities.entity_bill_total_used];
    const estTotalSt = this._hass.states[entities.entity_estimated_bill];

    const attrs = acctDetailsSt?.attributes || {};
    const sidekick = parseData(attrs.widget_sidekick) || parseData(attrs.widget_bill_summary_v2)?.billEstimated;

    let usedVal = null;
    if (sidekick?.titleArea?.value != null) {
      usedVal = `$${fmtNum(sidekick.titleArea.value, 2)}`;
    } else if (totalUsedSt && !isNaN(parseFloat(totalUsedSt.state))) {
      usedVal = `$${fmtNum(totalUsedSt.state, 2)}`;
    }
    this._el("top-used-val").textContent = usedVal || "$—";

    let forecastVal = null;
    if (sidekick?.billArea?.title) {
      const cleaned = sidekick.billArea.title
        .replace(/Estimated bill\s*/i, "")
        .replace(/\$/g, "")
        .trim();
      forecastVal = `$${cleaned}`;
    } else if (estTotalSt && !isNaN(parseFloat(estTotalSt.state))) {
      forecastVal = `$${fmtNum(estTotalSt.state, 2)}`;
    }
    this._el("top-forecast-val").textContent = forecastVal || "$—";

    const periodDates = sidekick?.barArea?.leftText || "Current Billing Period";
    const periodDays = sidekick?.barArea?.rightText || "";
    const ratio = Math.min(100, Math.max(0, parseFloat(sidekick?.barArea?.ratioPercentage) || 0));

    this._el("top-period-dates").textContent = periodDates;
    this._el("top-period-days").textContent = periodDays;
    this._el("top-progress-fill").style.width = `${ratio}%`;
  }

  _updateLiveBar(bookings, entities) {
    const bar = this._el("live-bar");
    const inProgSt = entities?.entity_booking_in_progress ? this._hass.states[entities.entity_booking_in_progress] : null;

    if (inProgSt && inProgSt.state === "on") {
      const current = inProgSt.attributes?.current_booking;
      if (current?.startDateTime) {
        const end = new Date(new Date(current.startDateTime).getTime() + (Number(current.duration) || 1) * 3600000);
        this._el("live-end").textContent = `ends ${fmtHour(end.toISOString())}`;
      } else {
        this._el("live-end").textContent = "ends soon";
      }
      bar.removeAttribute("hidden");
      return;
    }

    if (!Array.isArray(bookings)) {
      bar.setAttribute("hidden", "");
      return;
    }
    const now = Date.now();
    const active = bookings.find((b) => {
      const start = new Date(b.startDateTime).getTime();
      const end = start + (Number(b.duration) || 1) * 3600000;
      return now >= start && now <= end;
    });

    if (active) {
      const end = new Date(new Date(active.startDateTime).getTime() + (Number(active.duration) || 1) * 3600000);
      this._el("live-end").textContent = `ends ${fmtHour(end.toISOString())}`;
      bar.removeAttribute("hidden");
    } else {
      bar.setAttribute("hidden", "");
    }
  }

  _renderBookings(bookings) {
    const list = this._el("booking-list");
    if (!Array.isArray(bookings) || bookings.length === 0) {
      list.innerHTML = '<div class="empty">Nothing booked yet.</div>';
      return;
    }
    const now = Date.now();

    const upcoming = bookings
      .filter((b) => {
        const start = new Date(b.startDateTime).getTime();
        const end = start + (Number(b.duration) || 1) * 3600000;
        return end > now;
      })
      .sort((a, b) => new Date(a.startDateTime) - new Date(b.startDateTime));

    if (!upcoming.length) {
      list.innerHTML = '<div class="empty">Nothing booked yet.</div>';
      return;
    }

    list.innerHTML = upcoming
      .map((b) => {
        const id = b.id || b.bookingId;
        const hours = Number(b.duration) || 1;
        const start = fmtPastHour(b.startDateTime);
        const end = endHourLabel(b.startDateTime, hours);
        const isCancelling = this._cancellingId && this._cancellingId === id;
        const isLive = now >= new Date(b.startDateTime).getTime();
        const tag = isLive
          ? ' <span style="color:var(--genesis-orange);font-weight:700;">(In Progress)</span>'
          : "";

        return `
          <div class="bk">
            <span class="w">${escapeHtml(start)} – ${escapeHtml(end)}${tag}<small>${hours} hr session</small></span>
            ${
              id
                ? `
              <button data-cancel-id="${escapeHtml(id)}"${isCancelling ? " disabled" : ""}>
                ${isCancelling ? '<span class="spin"></span>Cancelling…' : "Cancel"}
              </button>
            `
                : ""
            }
          </div>`;
      })
      .join("");
  }

  _updatePastHours(recommendedHours) {
    const count = this._el("past-count");
    if (!Array.isArray(recommendedHours) || recommendedHours.length === 0) {
      this._rankedHours = [];
      count.setAttribute("hidden", "");
      this._el("ranked-list").innerHTML = '<div class="empty">No past recommended hours available.</div>';
      this._syncSelection();
      return;
    }

    this._rankedHours = recommendedHours.map((r) => ({
      start_datetime: r.dateTime,
      day: r.day,
      time: r.time,
      cost: r.dollars,
      kwh: r.kwh,
    }));

    count.textContent = String(this._rankedHours.length);
    count.removeAttribute("hidden");

    this._el("ranked-list").innerHTML = this._rankedHours
      .map((item, idx) => {
        const checked = this._selectedHours.has(item.start_datetime) ? " checked" : "";
        const badge = idx === 0 ? '<span class="rank best">Top Pick</span>' : "";
        return `
          <div class="row">
            <input type="checkbox" id="hour-${idx}" data-start="${escapeHtml(item.start_datetime)}"${checked}>
            <label for="hour-${idx}">
              <span class="when">${escapeHtml(item.day)} · ${escapeHtml(item.time)}</span>
              <small>${item.kwh} kWh · <b>$${item.cost}</b> back</small>
            </label>
            ${badge}
          </div>`;
      })
      .join("");

    this._syncSelection();
  }

  _syncSelection() {
    const count = this._selectedHours.size;
    const credit = this._rankedHours
      .filter((item) => this._selectedHours.has(item.start_datetime))
      .reduce((sum, item) => sum + Number(item.cost || 0), 0);

    const button = this._el("redeem-selected");
    button.disabled = count === 0;
    button.textContent = count
      ? `Redeem ${count} hour${count === 1 ? "" : "s"} · $${credit.toFixed(2)} back`
      : "Redeem selected";

    const help = this._el("selection-help");
    if (this._availableBalance > 0) {
      help.textContent = `Selected ${count} of ${this._availableBalance} available hour(s).`;
    } else {
      help.textContent = `No available Power Shout balance to redeem past hours.`;
    }
  }

  _updateForecast() {
    const costSt = this._hass.states[this._entities.entity_forecast_cost];
    const usageSt = this._hass.states[this._entities.entity_forecast_usage];

    let val = "—";
    let sub = "forecast today";

    if (this._unit === "money") {
      const num = costSt ? fmtNum(costSt.state, 2) : null;
      const lo = costSt?.attributes?.prediction_low_cost != null ? fmtNum(costSt.attributes.prediction_low_cost, 2) : null;
      const hi = costSt?.attributes?.prediction_high_cost != null ? fmtNum(costSt.attributes.prediction_high_cost, 2) : null;

      val = num != null ? `$${num}` : "—";
      sub = lo != null && hi != null ? `forecast today · $${lo}–$${hi}` : "forecast today";
    } else {
      const num = usageSt ? fmtNum(usageSt.state, 1) : null;
      const lo = usageSt?.attributes?.prediction_low_kwh != null ? fmtNum(usageSt.attributes.prediction_low_kwh, 0) : null;
      const hi = usageSt?.attributes?.prediction_high_kwh != null ? fmtNum(usageSt.attributes.prediction_high_kwh, 0) : null;

      val = num != null ? `${num} kWh` : "—";
      sub = lo != null && hi != null ? `forecast today · ${lo}–${hi} kWh` : "forecast today";
    }

    this._el("cost-val").textContent = val;
    this._el("cost-sub").textContent = sub;
    this._el("cost-val-alt").textContent = val;
    this._el("cost-sub-alt").textContent = sub;
  }

  _getMonthFromCache(service, monthKey) {
    const now = new Date();
    const currentMonthKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    const isLiveMonth = (monthKey === currentMonthKey) || monthKey.startsWith(`genesis_monthly_${service}_${now.getFullYear()}`);

    if (this._monthDailyCache[service]?.has(monthKey)) {
      const entry = this._monthDailyCache[service].get(monthKey);
      if (!isLiveMonth || (Date.now() - (entry.ts || 0) < LIVE_DATA_CACHE_TTL_MS)) {
        return entry.data || entry;
      }
    }
    try {
      const raw = sessionStorage.getItem(`genesis_daily_${service}_${monthKey}`);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length > 0) {
          this._monthDailyCache[service].set(monthKey, { data: parsed, ts: Date.now() });
          return parsed;
        }
      }
    } catch {}
    return null;
  }

  _saveMonthToCache(service, monthKey, items) {
    if (!items || !items.length) return;
    const now = new Date();
    const currentMonthKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    const isLiveMonth = (monthKey === currentMonthKey) || monthKey.startsWith(`genesis_monthly_${service}_${now.getFullYear()}`);

    this._monthDailyCache[service].set(monthKey, { data: items, ts: Date.now() });

    if (!isLiveMonth) {
      try {
        sessionStorage.setItem(`genesis_daily_${service}_${monthKey}`, JSON.stringify(items));
      } catch {}
    }
  }

  _scheduleBackgroundPrefetch(service, year, month) {
    if (service === "ev") return;
    clearTimeout(this._prefetchTimer);
    this._prefetchTimer = setTimeout(async () => {
      const now = new Date();
      const currentYear = now.getFullYear();
      const currentMonth = now.getMonth();
      const minYear = currentYear - 3;
      const pad = (n) => String(n).padStart(2, "0");

      let targetYear = year;
      let targetMonth = month + (this._lastNavDirection * 3);
      const testD = new Date(targetYear, targetMonth, 1);
      targetYear = testD.getFullYear();
      targetMonth = testD.getMonth();

      if (targetYear < minYear || (targetYear > currentYear) || (targetYear === currentYear && targetMonth > currentMonth)) {
        return;
      }

      const targetKey = `${targetYear}-${pad(targetMonth + 1)}`;
      if (this._getMonthFromCache(service, targetKey)) {
        return;
      }

      try {
        const fetchStart = new Date(targetYear, targetMonth - 1, 1);
        if (fetchStart.getFullYear() < minYear) fetchStart.setFullYear(minYear, 0, 1);
        const fetchEnd = new Date(targetYear, targetMonth + 2, 0);

        const startDateStr = `${fetchStart.getFullYear()}-${pad(fetchStart.getMonth() + 1)}-01`;
        const endDateStr = `${fetchEnd.getFullYear()}-${pad(fetchEnd.getMonth() + 1)}-${pad(fetchEnd.getDate())}`;

        const rawBatch = await this._fetchGenesisUsage(service, startDateStr, endDateStr, "DAILY");
        const byMonth = {};
        for (const item of rawBatch) {
          const dtStr = item.startDate || item.date;
          if (!dtStr) continue;
          const mKey = dtStr.slice(0, 7);
          if (!byMonth[mKey]) byMonth[mKey] = [];
          byMonth[mKey].push(item);
        }
        for (const [mKey, monthItems] of Object.entries(byMonth)) {
          this._saveMonthToCache(service, mKey, monthItems);
        }
      } catch {}
    }, 1000);
  }

  async _fetchGenesisUsage(fuel, startDateStr, endDateStr, intervalType) {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const todayStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;

    const isLivePeriod = (intervalType === "MONTHLY" && startDateStr.startsWith(String(now.getFullYear()))) || (endDateStr >= todayStr);

    const cacheKey = `${fuel}_${intervalType}_${startDateStr}_${endDateStr}`;
    const storageKey = `genesis_usage_${cacheKey}`;

    // 4-Hour in-memory cache check
    if (this._usageCache[cacheKey]) {
      const entry = this._usageCache[cacheKey];
      const isFresh = !isLivePeriod || (Date.now() - (entry.ts || 0) < LIVE_DATA_CACHE_TTL_MS);
      if (isFresh) {
        return entry.data || entry;
      }
    }

    // Disk cache check for completed past periods
    if (!isLivePeriod) {
      try {
        const sessionData = sessionStorage.getItem(storageKey);
        if (sessionData) {
          const parsed = JSON.parse(sessionData);
          if (Array.isArray(parsed) && parsed.length > 0) {
            this._usageCache[cacheKey] = { data: parsed, ts: Date.now() };
            return parsed;
          }
        }
      } catch {}
    }

    if (!this._hass) return [];

    try {
      const resp = await this._hass.callWS({
        type: "genesisenergy/usage",
        fuel: fuel === "gas" ? "gas" : (fuel === "ev" ? "ev" : "electricity"),
        start_date: startDateStr,
        end_date: endDateStr,
        interval_type: intervalType,
      });

      if (resp && Array.isArray(resp.usage)) {
        this._usageCache[cacheKey] = { data: resp.usage, ts: Date.now() };
        if (!isLivePeriod) {
          try {
            sessionStorage.setItem(storageKey, JSON.stringify(resp.usage));
          } catch {}
        }
        return resp.usage;
      }
    } catch (err) {
      console.warn("Genesis usage fetch failed:", err);
    }
    return [];
  }

  // ── Unified Graph Rendering Engine (Recent & Historical) ────────────────
  async _renderUnifiedUsageGraph() {
    const isRecent = this._activeService === "recent";
    this._el("recent-controls-wrap").style.display = isRecent ? "block" : "none";
    this._el("historical-controls-wrap").style.display = isRecent ? "none" : "block";
    this._el("recent-timeline-track").style.display = isRecent ? "block" : "none";

    // When EV is active, hide the Monthly toggle because EV only supports Daily
    const isEv = this._activeService === "ev";
    const monthlyBtn = this._el("btn-gran-monthly");
    if (monthlyBtn) {
      monthlyBtn.style.display = isEv ? "none" : "inline-block";
    }

    if (isRecent) {
      await this._renderRecentStackedCanvas();
    } else {
      await this._renderHistoricalCanvas();
    }
  }

  async _renderRecentStackedCanvas() {
    this._showChartLoading(false);
    const entities = this._entities;
    const acctDetailsSt = this._hass.states[entities.entity_account_details];
    const totalUsedSt = this._hass.states[entities.entity_bill_total_used];
    const balSt = this._hass.states[entities.entity_balance];

    const attrs = acctDetailsSt?.attributes || {};
    const sidekick = parseData(attrs.widget_sidekick) || parseData(attrs.widget_bill_summary_v2)?.billEstimated;

    let totalUsedNum = 0;
    if (sidekick?.titleArea?.value != null) {
      totalUsedNum = parseFloat(sidekick.titleArea.value) || 0;
    } else if (totalUsedSt && !isNaN(parseFloat(totalUsedSt.state))) {
      totalUsedNum = parseFloat(totalUsedSt.state) || 0;
    }
    this._el("usage-total-used").textContent = `$${totalUsedNum.toFixed(2)}`;

    let periodStr = sidekick?.barArea?.leftText || "Current Period";
    let periodName = "Billing Period";
    if (periodStr.includes("–") || periodStr.includes("-")) {
      const delim = periodStr.includes("–") ? "–" : "-";
      const parts = periodStr.split(delim).map((s) => s.trim().replace(/[0-9]/g, "").trim());
      if (parts.length === 2 && parts[0] && parts[1]) {
        periodName = `${parts[0]} - ${parts[1]}`;
      }
    }
    this._el("usage-period-name").textContent = periodName;

    const numColumns = parseInt(this._config.chart_days, 10) || 17;
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");

    let startDayNum = 27;
    let startMonthNum = now.getMonth() - 1;
    if (startMonthNum < 0) startMonthNum = 11;

    if (periodStr && periodStr.match(/(\d+)\s+([A-Za-z]+)/)) {
      const m = periodStr.match(/(\d+)\s+([A-Za-z]+)/);
      startDayNum = parseInt(m[1], 10);
      const mName = m[2].toLowerCase().slice(0, 3);
      const months = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"];
      const foundIdx = months.indexOf(mName);
      if (foundIdx !== -1) startMonthNum = foundIdx;
    }

    const startDate = new Date(now.getFullYear(), startMonthNum, startDayNum);
    const dayOfWeekChars = ["S", "M", "T", "W", "Th", "F", "S"];

    const bookings = balSt?.attributes?.bookings || [];
    const psDateSet = new Set();
    for (const b of bookings) {
      const dtStr = b.startDateTime || b.startDate || b.start;
      if (dtStr) {
        const k = parseApiDateKey(dtStr);
        if (k) psDateSet.add(k);
      }
    }

    const diffDays = Math.max(1, Math.floor((now.getTime() - startDate.getTime()) / 86400000) + 1);
    const recordedDaysCount = Math.min(numColumns, diffDays);

    const dailyAvg = recordedDaysCount > 0 ? (totalUsedNum / recordedDaysCount) : 0;
    this._el("usage-daily-avg").textContent = `$${dailyAvg.toFixed(2)}`;

    const cycleStartStr = `${startDate.getFullYear()}-${pad(startDate.getMonth() + 1)}-${pad(startDate.getDate())}`;
    const todayStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;

    const [realElecData, realGasData] = await Promise.all([
      this._fetchGenesisUsage("electricity", cycleStartStr, todayStr, "DAILY"),
      this._hasGas ? this._fetchGenesisUsage("gas", cycleStartStr, todayStr, "DAILY") : Promise.resolve([]),
    ]);

    const elecMap = new Map();
    for (const item of realElecData) {
      const k = parseApiDateKey(item.startDate || item.date);
      const cost = parseFloat(item.costNZD ?? item.cost ?? item.dollars ?? 0);
      const isPS = (
        item.type === "powerShout" ||
        String(item.type).toLowerCase() === "powershout" ||
        (item.powerShoutCredits != null && parseFloat(item.powerShoutCredits) > 0) ||
        (item.powerShoutConsumptions != null && parseFloat(item.powerShoutConsumptions) > 0) ||
        item.powerShoutPending === true
      );
      if (k) elecMap.set(k, { cost, isPS });
    }

    const gasMap = new Map();
    for (const item of realGasData) {
      const k = parseApiDateKey(item.startDate || item.date);
      const cost = parseFloat(item.costNZD ?? item.cost ?? item.dollars ?? 0);
      if (k) gasMap.set(k, { cost });
    }

    const daysData = [];
    const chartWidth = 460;
    const chartHeight = 195;
    const leftPadding = 34;
    const bottomPadding = 42;
    const plotWidth = chartWidth - leftPadding - 10;
    const plotHeight = chartHeight - bottomPadding;
    const colStep = plotWidth / numColumns;
    const barWidth = 19;

    let computedMax = 10;

    for (let i = 0; i < numColumns; i++) {
      const colDate = new Date(startDate.getTime() + i * 86400000);
      const isPastOrToday = colDate <= now;
      const isoKey = `${colDate.getFullYear()}-${pad(colDate.getMonth() + 1)}-${pad(colDate.getDate())}`;

      let elecVal = 0;
      let gasVal = 0;
      let isPSEntry = psDateSet.has(isoKey);

      if (isPastOrToday) {
        if (elecMap.has(isoKey)) {
          const e = elecMap.get(isoKey);
          elecVal = e.cost;
          if (e.isPS) isPSEntry = true;
        }
        if (gasMap.has(isoKey)) {
          gasVal = gasMap.get(isoKey).cost;
        }
      }

      const totalVal = elecVal + gasVal;
      if (totalVal > computedMax) computedMax = totalVal;

      daysData.push({
        date: colDate,
        dayChar: dayOfWeekChars[colDate.getDay()],
        dayNum: String(colDate.getDate()).padStart(2, "0"),
        elec: elecVal,
        gas: gasVal,
        total: totalVal,
        hasPS: isPSEntry,
        hasData: isPastOrToday && totalVal > 0,
      });
    }

    const maxVal = Math.max(12, computedMax * 1.15);

    daysData.forEach((d, idx) => {
      d.cx = leftPadding + idx * colStep + colStep / 2;
      const totalHeight = (d.total / maxVal) * (plotHeight - 16);
      d.yTop = plotHeight - totalHeight;
    });

    this._currentDaysData = daysData;

    const svg = this._el("usage-chart-svg");
    const yGridTicks = [0, maxVal * 0.33, maxVal * 0.66, maxVal];

    let svgHtml = `
      <text x="10" y="13" class="chart-axis-text" font-weight="800" font-size="12">$</text>
    `;

    for (const tick of yGridTicks) {
      const yPos = plotHeight - (tick / maxVal) * (plotHeight - 16);
      svgHtml += `
        <line x1="${leftPadding}" y1="${yPos}" x2="${chartWidth - 8}" y2="${yPos}" class="chart-grid-line" />
        <text x="10" y="${yPos + 4}" class="chart-axis-text">${Math.round(tick)}</text>
      `;
    }

    daysData.forEach((d, idx) => {
      const x = d.cx - barWidth / 2;

      svgHtml += `
        <text x="${d.cx}" y="${plotHeight + 15}" text-anchor="middle" class="chart-axis-text" font-size="10.5">${d.dayChar}</text>
        <text x="${d.cx}" y="${plotHeight + 30}" text-anchor="middle" class="chart-axis-text" font-size="11" font-weight="800" fill="var(--genesis-text)">${d.dayNum}</text>
      `;

      if (d.hasData) {
        const elecHeight = (d.elec / maxVal) * (plotHeight - 16);
        const gasHeight = (d.gas / maxVal) * (plotHeight - 16);

        const yBottom = plotHeight;
        const yElecTop = yBottom - elecHeight;
        const yGasTop = yElecTop - gasHeight;

        svgHtml += `
          <rect x="${x}" y="${yElecTop}" width="${barWidth}" height="${elecHeight}" fill="var(--genesis-orange)" rx="${gasHeight > 0 ? 0 : 3}" />
        `;

        if (gasHeight > 0) {
          svgHtml += `
            <rect x="${x}" y="${yGasTop}" width="${barWidth}" height="${gasHeight}" fill="var(--genesis-plum)" rx="3" />
          `;
        }

        if (d.hasPS) {
          const pinY = yGasTop - 18;
          svgHtml += `
            <g transform="translate(${d.cx}, ${pinY})">
              <circle cx="0" cy="0" r="9" fill="var(--genesis-orange)" />
              <path d="M 0 9 L 3 13 L -3 13 Z" fill="var(--genesis-orange)" />
              <text x="0" y="3.5" text-anchor="middle" fill="#ffffff" font-size="10" font-weight="900" font-family="-apple-system, sans-serif">P</text>
            </g>
          `;
        }
      }

      svgHtml += `
        <rect x="${d.cx - colStep / 2}" y="0" width="${colStep}" height="${chartHeight}" fill="transparent" class="chart-col-hit" data-col="${idx}" style="cursor:pointer;" />
      `;
    });

    svg.innerHTML = svgHtml;

    const timelinePct = Math.min(100, Math.max(0, (recordedDaysCount / numColumns) * 100));
    this._el("chart-timeline-fill").style.width = `${timelinePct}%`;

    // Render Recent Legend
    const legend = this._el("usage-legend");
    legend.innerHTML = `
      <div class="legend-item">
        <span class="legend-dot" style="background:var(--genesis-orange)"></span>
        <span>Electricity</span>
      </div>
      ${this._hasGas ? `
        <div class="legend-item">
          <span class="legend-dot" style="background:var(--genesis-plum)"></span>
          <span>Natural Gas</span>
        </div>
      ` : ''}
      ${this._hasPowerShout ? `
        <div class="legend-item">
          ${PS_PIN_SVG}
          <span>Power Shout</span>
        </div>
      ` : ''}
    `;
  }

  async _renderHistoricalCanvas() {
    if (this._loadingDetail) return;
    this._loadingDetail = true;

    try {
      const isDollar = this._detailUnit === "dollar";
      const service = this._activeService;
      const isEv = service === "ev";
      const gran = isEv ? "daily" : this._activeGranularity;

      let barColor = "var(--genesis-orange)";
      let serviceLabel = "Electricity";
      if (service === "gas") {
        barColor = "var(--genesis-plum)";
        serviceLabel = "Natural Gas";
      } else if (service === "ev") {
        barColor = "var(--genesis-teal)";
        serviceLabel = "EV";
      }

      const monthsFull = ["January","February","March","April","May","June","July","August","September","October","November","December"];
      const monthsShort = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
      const dayOfWeekChars = ["S", "M", "T", "W", "Th", "F", "S"];

      const now = new Date();
      const currentYear = now.getFullYear();
      const currentMonth = now.getMonth();
      const minYear = isEv ? currentYear : currentYear - 3;
      const pad = (n) => String(n).padStart(2, "0");

      let startDateStr = "";
      let endDateStr = "";

      const navLabel = this._el("date-nav-label");
      const prevBtn = this._el("date-nav-prev");
      const nextBtn = this._el("date-nav-next");

      let apiUsageList = [];

      if (gran === "monthly" && !isEv) {
        const year = this._navDate.getFullYear();
        navLabel.textContent = `${year} ▾`;
        startDateStr = `${year}-01-01`;
        endDateStr = `${year}-12-31`;
        prevBtn.disabled = year <= minYear;
        nextBtn.disabled = year >= currentYear;

        const monthlyCacheKey = `genesis_monthly_${service}_${year}`;
        let cachedYear = this._getMonthFromCache(service, monthlyCacheKey);
        if (cachedYear) {
          apiUsageList = cachedYear;
          this._showChartLoading(false);
        } else {
          this._showChartLoading(true);
          apiUsageList = await this._fetchGenesisUsage(service, startDateStr, endDateStr, "MONTHLY");
          this._showChartLoading(false);
          this._saveMonthToCache(service, monthlyCacheKey, apiUsageList);
        }
      } else {
        const year = this._navDate.getFullYear();
        const month = this._navDate.getMonth();
        const numDays = new Date(year, month + 1, 0).getDate();
        navLabel.textContent = `${monthsFull[month]} ${year} ▾`;

        if (isEv) {
          prevBtn.disabled = (year < EV_START_YEAR) || (year === EV_START_YEAR && month <= EV_START_MONTH);
        } else {
          prevBtn.disabled = year <= minYear && month === 0;
        }
        nextBtn.disabled = year >= currentYear && month >= currentMonth;

        const targetMonthKey = `${year}-${pad(month + 1)}`;
        let cachedMonthData = this._getMonthFromCache(service, targetMonthKey);

        if (cachedMonthData) {
          apiUsageList = cachedMonthData;
          this._showChartLoading(false);
        } else {
          this._showChartLoading(true);

          const isCurrentMonth = (year === currentYear && month === currentMonth);
          let fetchStart, fetchEnd;
          if (isCurrentMonth) {
            fetchStart = new Date(year, month - (isEv ? 1 : DAILY_FETCH_PREV_MONTHS), 1);
            fetchEnd = new Date(year, month + 1, 0);
          } else {
            fetchStart = new Date(year, month - 1, 1);
            const aheadMonth = month + (isEv ? 1 : 2);
            fetchEnd = new Date(year, aheadMonth + 1, 0);
            const currentMonthEnd = new Date(currentYear, currentMonth + 1, 0);
            if (fetchEnd > currentMonthEnd) fetchEnd = currentMonthEnd;
          }

          if (fetchStart.getFullYear() < minYear) {
            fetchStart.setFullYear(minYear, isEv ? (currentMonth - 1) : 0, 1);
          }

          startDateStr = `${fetchStart.getFullYear()}-${pad(fetchStart.getMonth() + 1)}-01`;
          endDateStr = `${fetchEnd.getFullYear()}-${pad(fetchEnd.getMonth() + 1)}-${pad(fetchEnd.getDate())}`;

          const rawBatch = await this._fetchGenesisUsage(service, startDateStr, endDateStr, "DAILY");
          this._showChartLoading(false);

          const byMonth = {};
          for (const item of rawBatch) {
            const dtStr = item.startDate || item.date;
            if (!dtStr) continue;
            const mKey = dtStr.slice(0, 7);
            if (!byMonth[mKey]) byMonth[mKey] = [];
            byMonth[mKey].push(item);
          }

          for (const [mKey, monthItems] of Object.entries(byMonth)) {
            this._saveMonthToCache(service, mKey, monthItems);
          }

          apiUsageList = byMonth[targetMonthKey] || rawBatch;
        }

        if (!isEv) {
          this._scheduleBackgroundPrefetch(service, year, month);
        }
      }

      const balSt = this._hass.states[this._resolveEntities().entity_balance];
      const bookings = balSt?.attributes?.bookings || [];
      const psDateSet = new Set();
      for (const b of bookings) {
        const dtStr = b.startDateTime || b.startDate || b.start;
        if (dtStr) {
          const k = parseApiDateKey(dtStr);
          if (k) psDateSet.add(k);
        }
      }

      const apiLookup = new Map();
      for (const item of apiUsageList) {
        const dtStr = item.startDate || item.date;
        if (item && dtStr) {
          const fullKey = parseApiDateKey(dtStr);
          const monthKey = dtStr.slice(0, 7);

          let kw = 0;
          let cost = 0;
          let kwDay = 0;
          let kwNight = 0;
          let costDay = 0;
          let costNight = 0;
          let savings = 0;

          if (service === "ev") {
            kwDay = parseFloat(item.kWhDay || 0);
            kwNight = parseFloat(item.kWhNight || 0);
            costDay = parseFloat(item.usageCostDay || 0);
            costNight = parseFloat(item.usageCostNight || 0);
            kw = kwDay + kwNight;
            cost = costDay + costNight;
            const costAtDay = parseFloat(item.costWithDayRate || 0);
            savings = Math.max(0, costAtDay - costNight);
          } else {
            kw = Math.abs(parseFloat(item.kw ?? item.kWh ?? item.kwh ?? item.usage ?? item.consumption ?? 0));
            cost = parseFloat(item.costNZD ?? item.cost ?? item.dollars ?? item.amount ?? 0);
          }

          const isPS = (
            item.type === "powerShout" ||
            String(item.type).toLowerCase() === "powershout" ||
            (item.powerShoutCredits != null && parseFloat(item.powerShoutCredits) > 0) ||
            (item.powerShoutConsumptions != null && parseFloat(item.powerShoutConsumptions) > 0) ||
            item.powerShoutPending === true ||
            item.isPowerShout === true
          );

          const psCredits = parseFloat(item.powerShoutCredits || 0);
          const psConsumptions = parseFloat(item.powerShoutConsumptions || 0);

          const parsedItem = { 
            kw, cost, isPS, psCredits, psConsumptions,
            kwDay, kwNight, costDay, costNight, savings
          };
          if (fullKey) apiLookup.set(fullKey, parsedItem);

          if (monthKey) {
            if (apiLookup.has(monthKey)) {
              const cur = apiLookup.get(monthKey);
              apiLookup.set(monthKey, {
                kw: cur.kw + kw,
                cost: cur.cost + cost,
                kwDay: (cur.kwDay || 0) + kwDay,
                kwNight: (cur.kwNight || 0) + kwNight,
                costDay: (cur.costDay || 0) + costDay,
                costNight: (cur.costNight || 0) + costNight,
                savings: (cur.savings || 0) + savings,
                isPS: cur.isPS || isPS,
                psCredits: cur.psCredits + psCredits,
                psConsumptions: cur.psConsumptions + psConsumptions,
              });
            } else {
              apiLookup.set(monthKey, parsedItem);
            }
          }
        }
      }

      const detailData = [];

      if (gran === "daily") {
        const year = this._navDate.getFullYear();
        const month = this._navDate.getMonth();
        const numDaysInMonth = new Date(year, month + 1, 0).getDate();

        for (let day = 1; day <= numDaysInMonth; day++) {
          const dObj = new Date(year, month, day);
          const isoKey = `${year}-${pad(month + 1)}-${pad(day)}`;
          const isFuture = dObj > now;

          let kwVal = 0;
          let costVal = 0;
          let isPSEntry = false;
          let psCredits = 0;
          let psConsumptions = 0;
          let hasData = false;
          let kwDay = 0, kwNight = 0, costDay = 0, costNight = 0, savings = 0;

          if (!isFuture && apiLookup.has(isoKey)) {
            const row = apiLookup.get(isoKey);
            kwVal = row.kw;
            costVal = row.cost;
            kwDay = row.kwDay || 0;
            kwNight = row.kwNight || 0;
            costDay = row.costDay || 0;
            costNight = row.costNight || 0;
            savings = row.savings || 0;
            isPSEntry = row.isPS || psDateSet.has(isoKey);
            psCredits = row.psCredits;
            psConsumptions = row.psConsumptions;
            hasData = true;
          } else if (!isFuture && psDateSet.has(isoKey)) {
            isPSEntry = true;
          }

          detailData.push({
            label: serviceLabel,
            title: fmtTooltipDate(dObj),
            bottomChar: dayOfWeekChars[dObj.getDay()],
            bottomNum: String(day).padStart(2, "0"),
            kw: kwVal,
            cost: costVal,
            kwDay, kwNight, costDay, costNight, savings,
            value: isDollar ? costVal : kwVal,
            hasPS: isPSEntry && service === "elec" && this._hasPowerShout,
            psCredits,
            psConsumptions,
            hasData,
          });
        }
      } else if (gran === "monthly") {
        const year = this._navDate.getFullYear();

        for (let m = 0; m < 12; m++) {
          const isFuture = (year > currentYear) || (year === currentYear && m > currentMonth);
          let kwVal = 0;
          let costVal = 0;
          let isPSEntry = false;
          let psCredits = 0;
          let psConsumptions = 0;
          let hasData = false;
          let kwDay = 0, kwNight = 0, costDay = 0, costNight = 0, savings = 0;

          const mKey = `${year}-${pad(m + 1)}`;
          if (!isFuture && apiLookup.has(mKey)) {
            const row = apiLookup.get(mKey);
            kwVal = row.kw;
            costVal = row.cost;
            kwDay = row.kwDay || 0;
            kwNight = row.kwNight || 0;
            costDay = row.costDay || 0;
            costNight = row.costNight || 0;
            savings = row.savings || 0;
            isPSEntry = row.isPS;
            psCredits = row.psCredits;
            psConsumptions = row.psConsumptions;
            hasData = true;
          }

          detailData.push({
            label: serviceLabel,
            title: `${monthsFull[m]} ${year}`,
            bottomChar: monthsShort[m],
            bottomNum: "",
            kw: kwVal,
            cost: costVal,
            kwDay, kwNight, costDay, costNight, savings,
            value: isDollar ? costVal : kwVal,
            hasPS: isPSEntry && service === "elec" && this._hasPowerShout,
            psCredits,
            psConsumptions,
            hasData,
          });
        }
      }

      const svg = this._el("usage-chart-svg");
      const chartWidth = 460;
      const chartHeight = 195;
      const leftPadding = 36;
      const bottomPadding = 38;
      const topMargin = 26;
      const plotWidth = chartWidth - leftPadding - 10;
      const plotHeight = chartHeight - bottomPadding;

      const maxVal = Math.max(1, ...detailData.map(d => d.value)) * 1.15;
      const step = maxVal / 3;
      const yGridTicks = [0, step, step * 2, maxVal];

      let svgHtml = `
        <text x="12" y="12" class="chart-axis-text" font-weight="900" font-size="12">${isDollar ? "$" : "kWh"}</text>
      `;

      for (const tick of yGridTicks) {
        const yPos = plotHeight - (tick / maxVal) * (plotHeight - topMargin);
        svgHtml += `
          <line x1="${leftPadding}" y1="${yPos}" x2="${chartWidth - 8}" y2="${yPos}" class="chart-grid-line" />
          <text x="10" y="${yPos + 4}" class="chart-axis-text">${Math.round(tick)}</text>
        `;
      }

      const numCols = detailData.length;
      const colStep = plotWidth / numCols;
      const barWidth = Math.max(6, Math.min(18, colStep * 0.72));

      detailData.forEach((d, idx) => {
        const cx = leftPadding + idx * colStep + colStep / 2;
        const x = cx - barWidth / 2;
        const barHeight = d.hasData ? (d.value / maxVal) * (plotHeight - topMargin) : 0;
        const yTop = plotHeight - barHeight;

        d.cx = cx;
        d.yTop = yTop;

        svgHtml += `
          <text x="${cx}" y="${plotHeight + 14}" text-anchor="middle" class="chart-axis-text" font-size="${gran === 'daily' ? '9.5' : '11'}">${d.bottomChar}</text>
          ${d.bottomNum ? `<text x="${cx}" y="${plotHeight + 27}" text-anchor="middle" class="chart-axis-text" font-size="10" font-weight="800" fill="var(--genesis-text)">${d.bottomNum}</text>` : ''}
        `;

        if (d.hasData) {
          if (service === "ev") {
            const nightVal = isDollar ? d.costNight : d.kwNight;
            const dayVal = isDollar ? d.costDay : d.kwDay;

            const nightHeight = (nightVal / maxVal) * (plotHeight - topMargin);
            const dayHeight = (dayVal / maxVal) * (plotHeight - topMargin);

            const yNightTop = plotHeight - nightHeight;
            const yDayTop = yNightTop - dayHeight;

            svgHtml += `
              <rect x="${x}" y="${yNightTop}" width="${barWidth}" height="${nightHeight}" fill="var(--genesis-teal)" rx="${dayHeight > 0 ? 0 : 2.5}" />
            `;

            if (dayHeight > 0) {
              svgHtml += `
                <rect x="${x}" y="${yDayTop}" width="${barWidth}" height="${dayHeight}" fill="var(--genesis-orange)" rx="2.5" />
              `;
            }
          } else {

            svgHtml += `
              <rect x="${x}" y="${yTop}" width="${barWidth}" height="${barHeight}" fill="${barColor}" rx="2.5" />
            `;

            if (d.hasPS) {
              const pinY = yTop - 16;
              svgHtml += `
                <g transform="translate(${cx}, ${pinY})">
                  <circle cx="0" cy="0" r="8" fill="var(--genesis-orange)" />
                  <path d="M 0 8 L 2.5 11.5 L -2.5 11.5 Z" fill="var(--genesis-orange)" />
                  <text x="0" y="3" text-anchor="middle" fill="#ffffff" font-size="9" font-weight="900" font-family="-apple-system, sans-serif">P</text>
                </g>
              `;
            }
          }
        }

        svgHtml += `
          <rect x="${cx - colStep / 2}" y="0" width="${colStep}" height="${chartHeight}" fill="transparent" class="chart-col-hit" data-col="${idx}" style="cursor:pointer;" />
        `;
      });

      svg.innerHTML = svgHtml;
      this._currentDetailData = detailData;

      // Render Historical Legend
      const legend = this._el("usage-legend");
      if (service === "ev") {
        legend.innerHTML = `
          <div class="legend-item">
            <span class="legend-dot" style="background:var(--genesis-teal)"></span>
            <span>🌙 Night (Off-Peak)</span>
          </div>
          <div class="legend-item">
            <span class="legend-dot" style="background:var(--genesis-orange)"></span>
            <span>☀️ Day (Standard)</span>
          </div>
        `;
      } else {
        legend.innerHTML = `
          <div class="legend-item">
            <span class="legend-dot" style="background:${barColor}"></span>
            <span>${escapeHtml(serviceLabel)}</span>
          </div>
          ${(this._hasPowerShout && service === "elec") ? `
            <div class="legend-item">
              ${PS_PIN_SVG}
              <span>Power Shout</span>
            </div>
          ` : ''}
        `;
      }

    } catch (err) {
      console.warn("[Genesis Card] Error rendering usage chart:", err);
    } finally {
      this._loadingDetail = false;
      this._showChartLoading(false);
    }
  }

  _updateSummary(entities) {
    const container = this._el("summary-content");
    if (!container) return;

    const acctDetailsSt = this._hass.states[entities.entity_account_details];
    const lpgSt = this._hass.states[entities.entity_lpg];

    if (!acctDetailsSt && !lpgSt) {
      container.innerHTML = '<div class="empty">Account details are currently syncing.</div>';
      return;
    }

    const attrs = acctDetailsSt?.attributes || {};
    const billSummaryV2 = parseData(attrs.widget_bill_summary_v2);
    const sidekick = parseData(attrs.widget_sidekick) || billSummaryV2?.billEstimated;
    const plans = parseData(attrs.billing_plans);
    const eco = parseData(attrs.widget_eco_tracker);
    const lpgDetails = parseData(attrs.lpg_details) || parseData(lpgSt?.attributes?.data);

    let html = "";

    // 1. Current Bill Card
    const billSum = billSummaryV2?.billSummary;
    if (billSum && billSum.totalAmountNzd != null) {
      const title = (billSum.totalAmountTitles && billSum.totalAmountTitles[0]) || "Amount due";
      const amount = fmtNum(billSum.totalAmountNzd, 2);

      let desc = billSum.description || "";
      const subs = billSum.descriptionSubstrings || [];
      subs.forEach((s, idx) => {
        const text = s.text || "";
        desc = desc.replace(new RegExp(`\\{\\{${idx}\\}\\}`, 'g'), `<b>${escapeHtml(text)}</b>`);
      });

      html += `
        <div class="ctrl-label">Current Bill</div>
        <div class="sum-card" style="margin-top:4px;">
          <div style="display:flex;justify-content:space-between;align-items:flex-end;">
            <div>
              <div class="sum-hero-lbl">${escapeHtml(title)}</div>
              <div class="sum-hero-val" style="font-size:32px;">$${escapeHtml(amount)}</div>
            </div>
            ${billSummaryV2.common?.accountStatus ? `
              <span class="elig" style="margin-bottom:4px;">${escapeHtml(billSummaryV2.common.accountStatus)}</span>
            ` : ""}
          </div>
          ${desc ? `
            <div style="margin-top:10px;font-size:12.5px;color:var(--genesis-muted);line-height:1.45;">
              ${desc}
            </div>
          ` : ""}
        </div>
      `;
    }

    // 2. Service Usage Breakdown
    const supplies = sidekick?.supplyTypesArea?.supplyTypes;
    if (Array.isArray(supplies) && supplies.length > 0) {
      html += `<div class="ctrl-label">Service Usage</div><div class="sum-card" style="padding:4px 14px;">`;
      for (const s of supplies) {
        html += `
          <div class="sum-row">
            <span>${escapeHtml(s.text || s.type)}</span>
            <b>$${escapeHtml(fmtNum(s.value, 2))}</b>
          </div>
        `;
      }
      html += `</div>`;
    }

    // 3. Bottled Gas (LPG) Section
    if (lpgDetails && Object.keys(lpgDetails).length > 0) {
      html += `<div class="ctrl-label">Bottled Gas (LPG)</div>`;
      for (const spId of Object.keys(lpgDetails)) {
        const item = lpgDetails[spId];
        const status = item.order_status || {};
        const summary = item.delivery_summary || {};
        const lastDate = summary.lastDeliveryDate ? fmtDisplayDate(summary.lastDeliveryDate.split("T")[0]) : (status.orderDate ? fmtDisplayDate(status.orderDate.split("T")[0]) : null);
        const qty = summary.bottlesDelivered || status.quantity || "45kg";
        const orderStatus = status.orderStatus || status.status || "Active supply";

        html += `
          <div class="tariff-plan-box" style="margin-top:4px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
              <div class="tariff-plan-title" style="margin-bottom:0;">🛢️ LPG Cylinders</div>
              <span class="elig" style="padding:2px 8px;font-size:10px;">${escapeHtml(orderStatus)}</span>
            </div>
            ${lastDate ? `
              <div class="tariff-item">
                <span>Last Delivery:</span>
                <strong>${escapeHtml(lastDate)} (${escapeHtml(qty)} bottles)</strong>
              </div>
            ` : ""}
            ${summary.estimatedNextOrderDate ? `
              <div class="tariff-item">
                <span>Next Estimated Order:</span>
                <strong style="color:var(--genesis-orange)">${escapeHtml(fmtDisplayDate(summary.estimatedNextOrderDate.split("T")[0]))}</strong>
              </div>
            ` : ""}
          </div>
        `;
      }
    }

    // 4. Eco Tracker Widget
    if (eco && eco.percentage != null) {
      html += `
        <div class="sum-card" style="display:flex;align-items:center;gap:12px;margin-top:12px;">
          <div style="font-size:24px;color:#4caf50;">🌱</div>
          <div style="font-size:12.5px;color:var(--genesis-muted);line-height:1.4;">
            <b style="color:#4caf50;">${escapeHtml(eco.percentage)}%</b> of NZ's electricity is currently generated from <b>${escapeHtml(eco.source || "renewable sources")}</b>.
          </div>
        </div>
      `;
    }

    // 5. Active Plan Tariffs
    if (plans && Array.isArray(plans.billingAccountSites)) {
      html += `<div class="ctrl-label">Active Plan Tariffs</div>`;
      for (const site of plans.billingAccountSites) {
        for (const sp of site.supplyPoints || []) {
          const planName = sp.planDisplay || `${sp.supplyTypeDisplay || "Energy"} (${sp.plan})`;
          html += `
            <div class="tariff-plan-box">
              <div class="tariff-plan-title">${escapeHtml(planName)}</div>
          `;
          for (const tariff of sp.tariffs || []) {
            const rawVal = parseFloat(tariff.value);
            let displayVal = "";
            let unitStr = "";

            if (tariff.unit?.toLowerCase() === "kwh") {
              displayVal = `${(rawVal * 100).toFixed(2)}`;
              unitStr = "c/kWh";
            } else if (tariff.unit?.toLowerCase() === "day") {
              displayVal = `$${rawVal.toFixed(3)}`;
              unitStr = "/day";
            } else {
              displayVal = `$${rawVal.toFixed(2)}`;
              unitStr = `/${tariff.unit || "bottle"}`;
            }

            html += `
              <div class="tariff-item">
                <span>${escapeHtml(tariff.name)}</span>
                <strong>${escapeHtml(displayVal)} ${escapeHtml(unitStr)}</strong>
              </div>
            `;
          }
          html += `</div>`;
        }
      }
    }

    container.innerHTML = html;
  }
}

customElements.define("genesisenergy-powershout-card", GenesisPowerShoutCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "genesisenergy-powershout-card",
  name: "Genesis Energy — Power Shout & Account Card",
  description: "Interactive Power Shout, retroactive redemption, recent usage stacked chart, and billing cycle forecast.",
  preview: false,
});