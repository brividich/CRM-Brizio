/* global React */
const { useState } = React;

/* ────────── ICON SET ──────────
   Stroke 1.7, currentColor — matches the codebase's inline SVG aesthetic */
const Icon = ({ d, size = 18, sw = 1.7, fill = "none" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill}
       stroke="currentColor" strokeWidth={sw}
       strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    {d}
  </svg>
);
const Icons = {
  dashboard: <Icon d={<><rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="5" rx="1.5"/><rect x="13" y="10" width="8" height="11" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/></>}/>,
  warning:   <Icon d={<><path d="M12 3 2 20h20Z"/><path d="M12 10v5M12 18v.5"/></>}/>,
  ticket:    <Icon d={<><path d="M3 8a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v3a2 2 0 0 0 0 4v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-3a2 2 0 0 0 0-4Z"/><path d="M11 6v12"/></>}/>,
  task:      <Icon d={<><rect x="4" y="4" width="16" height="16" rx="2"/><path d="m9 12 2 2 4-4"/></>}/>,
  asset:     <Icon d={<><path d="m12 3 9 5-9 5-9-5Z"/><path d="m3 13 9 5 9-5M3 8v8M21 8v8"/></>}/>,
  people:    <Icon d={<><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>}/>,
  calendar:  <Icon d={<><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 9h18M8 3v4M16 3v4"/></>}/>,
  clock:     <Icon d={<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>}/>,
  bell:      <Icon d={<><path d="M6 8a6 6 0 1 1 12 0v5l2 3H4l2-3Z"/><path d="M10 19a2 2 0 0 0 4 0"/></>}/>,
  search:    <Icon d={<><circle cx="11" cy="11" r="7"/><path d="m21 21-5-5"/></>}/>,
  gear:      <Icon d={<><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.4.9a7 7 0 0 0-2-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2 1.2l-2.4-.9-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.4-.9a7 7 0 0 0 2 1.2L10 21h4l.5-2.6a7 7 0 0 0 2-1.2l2.4.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2Z"/></>}/>,
  logout:    <Icon d={<><path d="M9 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4"/><path d="M16 17l5-5-5-5M21 12H9"/></>}/>,
  user:      <Icon d={<><path d="M20 21a8 8 0 0 0-16 0"/><circle cx="12" cy="7" r="4"/></>}/>,
  lock:      <Icon d={<><rect x="4" y="11" width="16" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/><circle cx="12" cy="15.5" r="1.4"/></>}/>,
  eye:       <Icon d={<><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6Z"/><circle cx="12" cy="12" r="2.8"/></>}/>,
  chevronR:  <Icon d={<path d="m9 6 6 6-6 6"/>} sw={2}/>,
  chevronD:  <Icon d={<path d="m6 9 6 6 6-6"/>} sw={2}/>,
  plus:      <Icon d={<path d="M12 5v14M5 12h14"/>} sw={2}/>,
  doc:       <Icon d={<><path d="M7 4h7l4 4v12H7z"/><path d="M14 4v4h4"/></>}/>,
  refresh:   <Icon d={<><path d="M4 12a8 8 0 0 1 14-5.5L21 8"/><path d="M21 4v4h-4"/><path d="M20 12a8 8 0 0 1-14 5.5L3 16"/><path d="M3 20v-4h4"/></>}/>,
  flag:      <Icon d={<><path d="M5 21V4M5 4h12l-2 4 2 4H5"/></>}/>,
  building:  <Icon d={<><rect x="4" y="3" width="16" height="18" rx="1"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2M10 21v-3h4v3"/></>}/>,

  /* ─── HR-specific icons (Anagrafica HR module) ─── */
  userPlus:   <Icon d={<><path d="M20 21a7 7 0 0 0-13 0"/><circle cx="10.5" cy="7" r="4"/><path d="M19 8v6M16 11h6"/></>}/>,
  userCheck:  <Icon d={<><path d="M16 21a7 7 0 0 0-13 0"/><circle cx="9.5" cy="7" r="4"/><path d="m17 11 2 2 4-4"/></>}/>,
  shield:     <Icon d={<><path d="M12 3 4 6v6c0 5 3.5 8.5 8 9 4.5-.5 8-4 8-9V6Z"/><path d="m9 12 2 2 4-4"/></>}/>,
  graduation: <Icon d={<><path d="M2 9l10-5 10 5-10 5Z"/><path d="M6 11v5c0 1 3 2 6 2s6-1 6-2v-5"/></>}/>,
  briefcase:  <Icon d={<><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M2 13h20"/></>}/>,
  badgeCheck: <Icon d={<><path d="m12 3 2.5 2L18 4l1 3.5L22 9l-2 3 2 3-3 1.5L18 20l-3.5-1L12 21l-2.5-2L6 20l-1-3.5L2 15l2-3-2-3 3-1.5L6 4l3.5 1Z"/><path d="m9 12 2 2 4-4"/></>}/>,
  heart:      <Icon d={<><path d="M12 21s-7-4.5-9-9c-1.5-3.5 1-7 4.5-7 2 0 3.5 1.2 4.5 3 1-1.8 2.5-3 4.5-3 3.5 0 6 3.5 4.5 7-2 4.5-9 9-9 9Z"/><path d="M3 14h4l1.5-3 2 6 1.5-3h9"/></>}/>,
  folder:     <Icon d={<><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></>}/>,
  clipboard:  <Icon d={<><rect x="7" y="4" width="10" height="17" rx="1.5"/><path d="M9 4V3a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1M10 11h4M10 15h3"/></>}/>,
  filter:     <Icon d={<path d="M3 5h18l-7 9v6l-4-2v-4Z"/>}/>,
  download:   <Icon d={<><path d="M12 4v12M6 12l6 5 6-5M5 20h14"/></>}/>,
  check:      <Icon d={<path d="M5 12l4 4 10-10"/>} sw={2.2}/>,
  x:          <Icon d={<path d="m6 6 12 12M18 6 6 18"/>} sw={2}/>,
};

/* ────────── BRAND ──────────
   Recreates the "CN NOVICROM HUB" mark from the splash artwork. */
const BrandMark = ({ size = 36 }) => (
  <div style={{ width: size, height: size, borderRadius: 10, background: "#fff",
    display: "flex", alignItems: "center", justifyContent: "center",
    fontWeight: 800, fontSize: size * 0.38, color: "#002b5c", letterSpacing: "-.02em" }}>
    CN
  </div>
);

const BrandLockup = ({ subtitle = "Operativa" }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
    <BrandMark/>
    <div style={{ minWidth: 0, lineHeight: 1.15 }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: "#fff", whiteSpace: "nowrap" }}>NOVICROM HUB</div>
      <div style={{ fontSize: 9, fontWeight: 500, color: "rgba(255,255,255,.72)",
                    letterSpacing: ".08em", textTransform: "uppercase" }}>{subtitle}</div>
    </div>
  </div>
);

/* ────────── OCTAGONAL TILE ──────────
   Signature brand motif: chamfered right corners + orange notch. */
const OctTile = ({ icon, label, onClick }) => (
  <button onClick={onClick} className="oct-tile">
    <span className="oct-ico">{icon}</span>
    <span className="oct-lbl">{label}</span>
    <style>{`
      .oct-tile{
        position:relative; display:flex; align-items:center; gap:14px;
        padding:14px 24px 14px 16px; min-height:64px;
        background:#fff; color:#0c2545; font:inherit; cursor:pointer;
        font-weight:800; font-size:15px; line-height:1.15; text-align:left;
        clip-path: polygon(0 0, calc(100% - 14px) 0, 100% 14px, 100% calc(100% - 14px), calc(100% - 14px) 100%, 0 100%);
        border:none;
        box-shadow: inset 0 0 0 2px #0c2545;
        transition: transform .12s, box-shadow .12s;
      }
      .oct-tile::before{
        content:""; position:absolute; top:0; right:0;
        width:38px; height:14px; background:#ff6b00;
        clip-path: polygon(0 0, 100% 0, 100% 100%);
      }
      .oct-tile:hover{ transform: translateY(-1px); box-shadow: inset 0 0 0 2px #0c2545, 0 8px 18px rgba(0,43,92,.18); }
      .oct-tile:active{ transform: translateY(1px); }
      .oct-ico{
        width:38px; height:38px; flex:0 0 38px; border:2px solid #0c2545;
        border-radius:6px; display:flex; align-items:center; justify-content:center; color:#0c2545;
      }
      .oct-lbl{ flex:1; min-width:0 }
    `}</style>
  </button>
);

Object.assign(window, { Icon, Icons, BrandMark, BrandLockup, OctTile });
