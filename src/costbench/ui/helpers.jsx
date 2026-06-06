/* costbench — formatting helpers + tiny shared components. Exports to window. */

function fmtCost(v) {
  if (v === null || v === undefined) return "—";
  if (v === Infinity) return "∞";
  if (v === 0) return "$0";
  if (v < 0.01) return "$" + v.toFixed(6);
  return "$" + v.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 4 });
}
function fmtPct(v) { return Math.round(v * 100) + "%"; }
function fmtLat(v) { return v.toFixed(2) + "s"; }

function fmtTokens(v) {
  if (v === null || v === undefined) return "—";
  if (v >= 1000) return (v / 1000).toFixed(v >= 10000 ? 0 : 1) + "K";
  return String(Math.round(v));
}
function fmtInt(v) {
  if (v === null || v === undefined) return "—";
  return Math.round(v).toLocaleString();
}

const VENDOR_STYLE = {
  Anthropic:   { bg: "#d4a27f", fg: "#1d1d1f", ab: "An" },
  OpenAI:      { bg: "#10a37f", fg: "#ffffff", ab: "AI" },
  Google:      { bg: "#4285f4", fg: "#ffffff", ab: "Go" },
  Mistral:     { bg: "#fa520f", fg: "#ffffff", ab: "Mi" },
  Qwen:        { bg: "#6e56cf", fg: "#ffffff", ab: "Qw" },
  DeepSeek:    { bg: "#2c6bed", fg: "#ffffff", ab: "Ds" },
  "Self-hosted": { bg: "#8e8e93", fg: "#ffffff", ab: "Lo" },
  Endpoint:    { bg: "#48484a", fg: "#ffffff", ab: "Ep" },
};

function VendorMark({ vendor, size }) {
  const s = VENDOR_STYLE[vendor] || VENDOR_STYLE.Endpoint;
  const px = size || 18;
  return (
    <span
      className="vmark"
      style={{ background: s.bg, color: s.fg, width: px, height: px, fontSize: px * 0.5 }}
      title={vendor}
    >
      {s.ab}
    </span>
  );
}

/* short display id: strip provider prefix for readability but keep it monospace */
function shortId(id) {
  return id;
}

/* price label for a target chip */
function priceLabel(r) {
  if (r.type === "endpoint") return "$0.002/req";
  if (r.basis === "amortized GPU (batch 1)") return "GPU amortized";
  return `$${r.inPrice}/$${r.outPrice} per M`;
}

/* SF-style stroke icons */
function Icon({ name, size }) {
  const s = size || 16;
  const common = { width: s, height: s, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round" };
  switch (name) {
    case "play": return <svg {...common}><path d="M7 5l12 7-12 7V5z" fill="currentColor" stroke="none" /></svg>;
    case "sun": return <svg {...common}><circle cx="12" cy="12" r="4.2" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19" /></svg>;
    case "moon": return <svg {...common}><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" /></svg>;
    case "plug": return <svg {...common}><path d="M9 2v6M15 2v6M7 8h10v3a5 5 0 0 1-10 0V8zM12 16v6" /></svg>;
    case "chev": return <svg {...common}><path d="M9 6l6 6-6 6" /></svg>;
    case "plus": return <svg {...common}><path d="M12 5v14M5 12h14" /></svg>;
    case "close": return <svg {...common}><path d="M6 6l12 12M18 6L6 18" /></svg>;
    case "spark": return <svg {...common}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" fill="currentColor" stroke="none" /></svg>;
    case "check": return <svg {...common}><path d="M5 12l4.5 4.5L19 7" /></svg>;
    default: return null;
  }
}

Object.assign(window, { fmtCost, fmtPct, fmtLat, fmtTokens, fmtInt, VendorMark, VENDOR_STYLE, shortId, priceLabel, Icon });
