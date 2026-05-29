/* global React */

/* ────────── BUTTON ──────────
   Variants mirror theme.css: accent (orange), cyan, secondary, danger, ghost. */
function Button({ variant = "accent", size = "md", icon, children, ...rest }) {
  const cls = `btn btn-${variant} btn-${size}`;
  return (
    <button className={cls} {...rest}>
      {icon && <span className="btn-ic">{icon}</span>}
      {children}
      <style>{`
        .btn{
          display:inline-flex; align-items:center; justify-content:center; gap:6px;
          font-family:"Outfit",sans-serif; font-weight:700; cursor:pointer;
          border:none; border-radius:8px; transition:filter .15s, box-shadow .15s, transform .1s;
          white-space:nowrap;
        }
        .btn:active{ transform:translateY(1px); filter:brightness(.94) }
        .btn-md{ min-height:40px; padding:0 14px; font-size:13px }
        .btn-sm{ min-height:32px; padding:0 10px; font-size:12px; border-radius:7px }
        .btn-lg{ min-height:48px; padding:0 18px; font-size:14px; border-radius:10px }
        .btn-accent{ background:#ff6b00; color:#fff; box-shadow:0 2px 10px rgba(249,115,22,.22) }
        .btn-accent:hover{ filter:brightness(1.04); box-shadow:0 4px 14px rgba(249,115,22,.30) }
        .btn-cyan{ background:#1f5fb3; color:#fff; box-shadow:0 10px 20px rgba(31,95,179,.25) }
        .btn-cyan:hover{ filter:brightness(1.04) }
        .btn-secondary{ background:#fff; color:#1a202c; border:1px solid #d7e0ea }
        .btn-secondary:hover{ background:#f4f6fb }
        .btn-danger{ background:#e53e3e; color:#fff }
        .btn-danger:hover{ box-shadow:0 2px 10px rgba(229,62,62,.25) }
        .btn-ghost{ background:transparent; color:#4a5568; border:1px solid #d7e0ea }
        .btn-ghost:hover{ background:#f4f6fb; color:#1a202c }
        .btn-ic{ display:inline-flex; align-items:center }
      `}</style>
    </button>
  );
}

/* ────────── CARD ────────── */
function Card({ title, action, children, accent = false, padded = true }) {
  return (
    <section className={`card ${accent ? "card-accent" : ""}`}>
      {(title || action) && (
        <header className="card-h">
          {title && <h3 className="card-t">{title}</h3>}
          {action}
        </header>
      )}
      <div className={padded ? "card-b" : "card-b card-b-flush"}>{children}</div>
      <style>{`
        .card{ background:#fff; border-radius:12px;
               box-shadow: 0 1px 3px rgba(0,0,0,.06), 0 4px 16px rgba(0,0,0,.04) }
        .card-accent{ border-top:3px solid #ff6b00 }
        .card-h{ display:flex; align-items:center; justify-content:space-between; gap:12px;
                 padding:12px 16px; border-bottom:1px solid #d7e0ea }
        .card-t{ margin:0; font-size:14px; font-weight:700; color:#1a202c }
        .card-b{ padding:14px 16px; font-size:13px; color:#1a202c; line-height:1.45 }
        .card-b-flush{ padding:0 }
      `}</style>
    </section>
  );
}

/* ────────── STAT CARD ────────── */
function Stat({ icon, num, label, tone = "blue" }) {
  return (
    <div className={`stat tone-${tone}`}>
      <div className="stat-iw">{icon}</div>
      <div>
        <div className="stat-num">{num}</div>
        <div className="stat-lbl">{label}</div>
      </div>
      <style>{`
        .stat{
          display:flex; align-items:center; gap:14px;
          padding:14px 18px; background:#fff; border-radius:12px;
          box-shadow:0 1px 3px rgba(0,0,0,.06), 0 4px 16px rgba(0,0,0,.04);
        }
        .stat-iw{ width:46px; height:46px; border-radius:12px;
                  display:flex; align-items:center; justify-content:center; flex:0 0 46px }
        .tone-blue   .stat-iw{ background:#ebf4ff; color:#2563eb }
        .tone-orange .stat-iw{ background:#fff4ed; color:#ff6b00 }
        .tone-green  .stat-iw{ background:#f0fff4; color:#38a169 }
        .tone-red    .stat-iw{ background:#fff5f5; color:#e53e3e }
        .stat-num{ font-size:26px; font-weight:800; line-height:1; color:#1a202c }
        .stat-lbl{ font-size:11px; color:#94a3b8; font-weight:600;
                   text-transform:uppercase; letter-spacing:.04em; margin-top:3px }
      `}</style>
    </div>
  );
}

/* ────────── BADGE ────────── */
function Badge({ tone = "default", children }) {
  return (
    <span className={`b b-${tone}`}>{children}
      <style>{`
        .b{ display:inline-flex; align-items:center; min-height:22px; padding:0 10px;
            border-radius:999px; border:1px solid #d7e0ea; background:#edf2f7;
            color:#4a5568; font-size:11px; font-weight:700 }
        .b-success{ background:#f0fff4; color:#276749; border-color:#c6f6d5 }
        .b-warning{ background:#fffff0; color:#7b5e0a; border-color:#fde68a }
        .b-danger { background:#fff5f5; color:#c53030; border-color:#fed7d7 }
        .b-info   { background:#ebf8ff; color:#2c5282; border-color:#bee3f8 }
        .b-accent { background:#fff4ed; color:#c2410c; border-color:#fed7aa }
      `}</style>
    </span>
  );
}

/* ────────── INPUT FIELD ────────── */
function Field({ label, hint, children }) {
  return (
    <label className="f">
      {label && <span className="f-l">{label}</span>}
      {children}
      {hint && <span className="f-h">{hint}</span>}
      <style>{`
        .f{ display:flex; flex-direction:column; gap:6px }
        .f-l{ font-size:12px; color:#4a5568; font-weight:600 }
        .f-h{ font-size:11px; color:#94a3b8 }
        .f input,.f select,.f textarea{
          min-height:40px; padding:0 12px; border:1px solid #d7e0ea;
          background:#fff; color:#1a202c; border-radius:8px;
          font:inherit; font-size:13px; font-family:"Outfit",sans-serif;
        }
        .f input:focus,.f select:focus,.f textarea:focus{
          outline:none; border-color:rgba(249,115,22,.5);
          box-shadow:0 0 0 3px rgba(249,115,22,.15);
        }
      `}</style>
    </label>
  );
}

Object.assign(window, { Button, Card, Stat, Badge, Field });
