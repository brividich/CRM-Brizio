/* global React, Icons, BrandLockup */
const { useState: useStateChrome } = React;

/* ────────── SIDEBAR ──────────
   Mirrors core/components/sidebar.html: navy chrome, categories,
   item badges, footer user panel, search button. */
function Sidebar({ active = "dashboard", onNav }) {
  const [open, setOpen] = useStateChrome("operations");

  const cats = [
    { key: "operations", label: "Operations", items: [
      { id: "dashboard", icon: Icons.dashboard, label: "Dashboard" },
      { id: "anomalie",  icon: Icons.warning,   label: "Anomalie", badge: 3 },
      { id: "ticket",    icon: Icons.ticket,    label: "Ticket" },
      { id: "task",      icon: Icons.task,      label: "Task", dot: true },
    ]},
    { key: "people", label: "Persone", items: [
      { id: "anagrafica", icon: Icons.people,   label: "Anagrafica" },
      { id: "assenze",    icon: Icons.calendar, label: "Assenze" },
      { id: "timbri",     icon: Icons.clock,    label: "Timbri" },
    ]},
    { key: "config", label: "Configurazione", items: [
      { id: "asset",      icon: Icons.asset,    label: "Asset" },
      { id: "automazioni",icon: Icons.refresh,  label: "Automazioni" },
      { id: "permessi",   icon: Icons.lock,     label: "Permessi e ruoli" },
    ]},
  ];

  return (
    <aside className="sb">
      <div className="sb-head">
        <BrandLockup/>
      </div>

      <nav className="sb-nav">
        {cats.map(c => {
          const isOpen = open === c.key || c.items.some(i => i.id === active);
          return (
            <div key={c.key} className={`sb-cat ${isOpen ? "open" : ""}`}>
              <button className="sb-cat-btn" onClick={() => setOpen(isOpen ? null : c.key)}>
                <span className="sb-lbl">{c.label}</span>
                <span className="sb-arr">{isOpen ? Icons.chevronD : Icons.chevronR}</span>
              </button>
              {isOpen && (
                <div className="sb-cat-items">
                  {c.items.map(i => (
                    <button key={i.id}
                      className={`sb-item ${active === i.id ? "active" : ""}`}
                      onClick={() => onNav?.(i.id)}>
                      <span className="sb-ico">{i.icon}</span>
                      <span className="sb-lbl">{i.label}</span>
                      {i.badge && <span className="sb-badge">{i.badge}</span>}
                      {i.dot && <span className="sb-dot"/>}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      <div className="sb-search">
        <button className="sb-search-btn">
          <span className="sb-search-ic">{Icons.search}</span>
          <span className="sb-search-copy">
            <span className="sb-search-t">Cerca nel portale</span>
            <span className="sb-search-s">Asset, ticket, task e persone</span>
          </span>
          <span className="sb-search-kbd"><kbd>Ctrl</kbd>+<kbd>K</kbd></span>
        </button>
      </div>

      <div className="sb-foot">
        <div className="sb-user">
          <div className="sb-av">MR</div>
          <div className="sb-u-meta">
            <div className="sb-u-name">Marco Rossi</div>
            <div className="sb-u-role">Capo reparto</div>
          </div>
        </div>
        <button className="sb-logout">{Icons.logout}<span>Esci</span></button>
      </div>

      <style>{`
        .sb{
          width:256px; flex:0 0 256px; min-height:100vh;
          background:#002b5c; color:#fff;
          display:flex; flex-direction:column;
          box-shadow: 2px 0 16px rgba(0,0,0,.15);
        }
        .sb-head{ padding:14px 14px 12px; border-bottom:1px solid rgba(255,255,255,.10) }
        .sb-nav{ flex:1; overflow-y:auto; padding:8px 0 }
        .sb-cat{ margin:2px 0 }
        .sb-cat-btn{
          width:calc(100% - 16px); margin:1px 8px; padding:0 12px;
          height:34px; display:flex; align-items:center; justify-content:space-between;
          border:none; background:transparent;
          color:rgba(255,255,255,.48); font:inherit;
          font-size:11px; font-weight:700; letter-spacing:.04em; text-transform:uppercase;
          cursor:pointer; border-radius:8px;
        }
        .sb-cat.open .sb-cat-btn{ color:#fff; background:rgba(255,255,255,.06) }
        .sb-arr{ display:inline-flex; opacity:.7 }
        .sb-cat-items{
          margin:2px 12px 8px 18px; padding:6px 0;
          border-left:1px solid rgba(255,255,255,.18);
          background: linear-gradient(90deg,rgba(255,255,255,.06),rgba(255,255,255,0));
        }
        .sb-item{
          width:calc(100% - 12px); margin:1px 0 1px 10px; padding:0 10px 0 14px;
          height:34px; display:flex; align-items:center; gap:10px;
          background:transparent; border:none; cursor:pointer; border-radius:8px;
          color:rgba(255,255,255,.72); font:inherit; font-size:13px; font-weight:500;
          text-align:left; transition:background .15s,color .15s;
        }
        .sb-item:hover{ background:rgba(255,255,255,.10); color:#fff }
        .sb-item.active{ background:rgba(255,255,255,.16); color:#fff; font-weight:600;
                         box-shadow:inset 2px 0 0 #fff }
        .sb-ico{ width:18px; display:inline-flex; justify-content:center; flex:0 0 18px }
        .sb-lbl{ flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
        .sb-badge{
          min-width:20px; height:20px; padding:0 6px; border-radius:999px;
          background:rgba(255,255,255,.16); color:#fff;
          display:inline-flex; align-items:center; justify-content:center;
          font-size:10px; font-weight:700;
        }
        .sb-dot{ width:6px; height:6px; border-radius:999px; background:#ff6b00 }

        .sb-search{ padding:10px; border-top:1px solid rgba(255,255,255,.08) }
        .sb-search-btn{
          width:100%; padding:10px; border-radius:14px;
          border:1px solid rgba(255,255,255,.14);
          background:linear-gradient(135deg,rgba(255,255,255,.14),rgba(255,255,255,.05));
          color:#fff; cursor:pointer; font:inherit;
          display:flex; align-items:center; gap:10px;
          box-shadow: inset 0 1px 0 rgba(255,255,255,.14);
        }
        .sb-search-ic{
          width:32px; height:32px; border-radius:10px; flex:0 0 32px;
          background:linear-gradient(135deg,rgba(249,115,22,.28),rgba(249,115,22,.12));
          display:flex; align-items:center; justify-content:center;
        }
        .sb-search-copy{ flex:1; min-width:0; text-align:left }
        .sb-search-t{ display:block; font-size:13px; font-weight:700 }
        .sb-search-s{ display:block; font-size:10px; color:rgba(255,255,255,.62) }
        .sb-search-kbd{ font-size:10px; color:rgba(255,255,255,.7); display:flex; gap:2px; align-items:center }
        .sb-search-kbd kbd{
          font-family:ui-monospace,Menlo,monospace; font-size:10px;
          padding:0 5px; height:18px; line-height:18px;
          border-radius:4px; background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.12);
        }

        .sb-foot{ padding:8px; border-top:1px solid rgba(255,255,255,.08) }
        .sb-user{ display:flex; align-items:center; gap:10px; padding:8px;
                  border-radius:12px; background:rgba(255,255,255,.06); margin-bottom:6px }
        .sb-av{ width:32px; height:32px; border-radius:8px; background:#ff6b00; color:#fff;
                display:flex; align-items:center; justify-content:center; font-weight:700; font-size:12px }
        .sb-u-meta{ min-width:0; line-height:1.2 }
        .sb-u-name{ font-size:13px; font-weight:600 }
        .sb-u-role{ font-size:10px; color:rgba(255,255,255,.6) }
        .sb-logout{
          width:100%; height:36px; border-radius:8px; border:1px solid rgba(239,68,68,.3);
          background:rgba(239,68,68,.10); color:#fecaca; font:inherit; font-size:12px; font-weight:600;
          display:flex; align-items:center; justify-content:center; gap:6px; cursor:pointer;
        }
        .sb-logout:hover{ background:rgba(239,68,68,.2); color:#fff }
      `}</style>
    </aside>
  );
}

/* ────────── TOP BAR ──────────
   Page-level top bar that sits above content (used inside main column). */
function Topbar({ title, sub, actions }) {
  return (
    <div className="tb">
      <div className="tb-h">
        <div>
          <h1 className="tb-title">{title}</h1>
          {sub && <p className="tb-sub">{sub}</p>}
        </div>
        {actions && <div className="tb-actions">{actions}</div>}
      </div>
      <style>{`
        .tb{ margin-bottom:18px }
        .tb-h{ display:flex; align-items:flex-start; justify-content:space-between; gap:12px }
        .tb-title{ margin:0; font-size:22px; font-weight:800; color:#1a202c; letter-spacing:-.005em }
        .tb-sub{ margin:2px 0 0; font-size:14px; color:#4a5568 }
        .tb-actions{ display:flex; gap:8px; align-items:center; flex-shrink:0 }
      `}</style>
    </div>
  );
}

Object.assign(window, { Sidebar, Topbar });
