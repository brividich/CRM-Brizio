/* global React, Icons, Icon, Card, Button, Badge, OctTile */
const { useState: useStateHR } = React;

/* ────────── ANAGRAFICA HR — brand-correct ──────────
   Variante del prototipo Anagrafica HR aderente al brand Novicrom HUB:
   - Tinte: navy #0c2545, cyan #1f87cd, orange #ff8a1f, grey #8e9296
   - Spotlight industriale con dot-grid e cornici a corner-bracket
   - Octagonal slash in alto a sinistra sulle "module spotlight cards"
   - Etichette mono uppercase per codici/categorie
   - Raggi compressi (6-12px) — niente rounded-2xl
*/

/* ── DATI (semplificati dal mockup originale) ── */
const HR_PEOPLE = [
  { id:1, code:"DIP-1024", name:"Marco Rossi",      dept:"Produzione",       role:"Saldatore",         status:"Attivo",     risk:"Doc. in scadenza",  riskTone:"warning", score:82, contract:"T. Indeterminato", manager:"L. Verdi",    site:"Officina"   },
  { id:2, code:"DIP-1031", name:"Giulia Bianchi",   dept:"Amministrazione",  role:"Impiegata",         status:"Attivo",     risk:"OK",                riskTone:"success", score:96, contract:"T. Indeterminato", manager:"Direzione",   site:"Sede"       },
  { id:3, code:"DIP-1042", name:"Luca Verdi",       dept:"Cantiere",         role:"Preposto",          status:"Attivo",     risk:"Formazione",        riskTone:"warning", score:74, contract:"T. Indeterminato", manager:"Dir. Tecnica",site:"Cantieri"   },
  { id:4, code:"DIP-1058", name:"Sara Neri",        dept:"HR",               role:"HR Specialist",     status:"Onboarding", risk:"Contratto firma",   riskTone:"danger",  score:68, contract:"Nuova assunzione", manager:"Direzione",   site:"Sede"       },
  { id:5, code:"DIP-1063", name:"Francesco Conti",  dept:"Magazzino",        role:"Addetto logistica", status:"Attivo",     risk:"DPI da firmare",    riskTone:"warning", score:79, contract:"T. Determinato",   manager:"M. Rossi",    site:"Magazzino"  },
];

const HR_EXPIRING = [
  { label:"Visite mediche",         value:7,  tone:"danger",  hint:"Sorveglianza sanitaria"  },
  { label:"Formazione sicurezza",   value:12, tone:"warning", hint:"Aggiornamenti scaduti"   },
  { label:"Contratti / proroghe",   value:3,  tone:"warning", hint:"TD in scadenza 30 gg"   },
  { label:"DPI da consegnare",      value:9,  tone:"danger",  hint:"Firme richieste"         },
];

const HR_ACTIVITIES = [
  { ic:Icons.userPlus,   t:"Nuovo onboarding creato",    m:"Sara Neri · HR",                 time:"09:12" },
  { ic:Icons.clipboard,  t:"Corso sicurezza aggiornato", m:"Produzione · 8 partecipanti",    time:"ieri"  },
  { ic:Icons.doc,        t:"Documento caricato",         m:"Contratto apprendistato · Rossi",time:"ieri"  },
  { ic:Icons.shield,     t:"DPI confermati",             m:"Cantiere · 6 consegne validate", time:"2 gg"  },
];

const HR_MATURITY = [
  ["Anagrafica base",   92],
  ["Documentale",       76],
  ["Formazione",        64],
  ["Sicurezza lavoro",  71],
  ["Retribuzioni",      42],
];

/* ────────── COMPONENTI LOCALI ────────── */

/* HERO: spotlight industriale, riprende il pattern delle "blueprint cards" */
function HRHero() {
  return (
    <section className="hr-hero">
      <div className="hr-hero-bg"/>
      <div className="hr-hero-inner">
        <div>
          <div className="hr-hero-eyebrow">
            <span className="hr-dot"/>Anagrafica HR · console operativa
          </div>
          <h1 className="hr-hero-title">
            Persone, contratti, assenze e<br/>
            compliance in un'unica vista.
          </h1>
          <p className="hr-hero-sub">
            Pensata per Direzione, HR e responsabili reparto. Indicatori immediati,
            scadenze critiche e stato documentale del personale.
          </p>
        </div>

        <div className="hr-hero-side">
          <button className="hr-hero-tile">
            <span className="hr-hero-num">86<small>%</small></span>
            <span className="hr-hero-lbl">Compliance HR</span>
            <span className="hr-hero-corner"/>
          </button>
          <button className="hr-hero-tile alt">
            <span className="hr-hero-num">21</span>
            <span className="hr-hero-lbl">Azioni aperte</span>
            <span className="hr-hero-corner"/>
          </button>
        </div>
      </div>

      <style>{`
        .hr-hero{
          position:relative; overflow:hidden;
          background:linear-gradient(135deg,#08142d 0%,#0c2545 55%,#1a3a66 100%);
          color:#fff; padding:28px 28px 26px; margin-bottom:18px;
          /* chamfered top-right corner — brand handshake */
          clip-path:polygon(0 0, calc(100% - 22px) 0, 100% 22px, 100% 100%, 0 100%);
        }
        .hr-hero-bg{
          position:absolute; inset:0; pointer-events:none; opacity:.5;
          background-image:
            radial-gradient(circle at 80% 20%, rgba(255,138,31,.25), transparent 40%),
            radial-gradient(rgba(31,135,205,.20) 1px, transparent 1.4px);
          background-size: auto, 16px 16px;
        }
        .hr-hero-inner{ position:relative; display:flex; gap:24px;
                        align-items:center; justify-content:space-between; flex-wrap:wrap }
        .hr-hero-eyebrow{
          display:inline-flex; align-items:center; gap:8px;
          font-family:ui-monospace,Menlo,monospace; font-size:11px;
          font-weight:700; letter-spacing:.14em; text-transform:uppercase;
          color:#ff8a1f; padding:4px 0; margin-bottom:10px;
        }
        .hr-dot{ width:7px; height:7px; border-radius:50%; background:#ff8a1f;
                 box-shadow:0 0 0 4px rgba(255,138,31,.18) }
        .hr-hero-title{ margin:0 0 8px; font-size:30px; font-weight:800;
                        line-height:1.1; letter-spacing:-.01em }
        .hr-hero-sub{ margin:0; font-size:13px; color:rgba(255,255,255,.72);
                      line-height:1.55; max-width:480px }

        .hr-hero-side{ display:grid; gap:10px; grid-template-columns:1fr 1fr; min-width:280px }
        .hr-hero-tile{
          position:relative; padding:14px 16px 12px;
          background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.14);
          color:#fff; cursor:pointer; font:inherit;
          display:flex; flex-direction:column; gap:2px; text-align:left;
          /* small chamfer on top-left — matches the brand octagonal motif */
          clip-path:polygon(12px 0, 100% 0, 100% 100%, 0 100%, 0 12px);
          transition:background .15s;
        }
        .hr-hero-tile:hover{ background:rgba(255,255,255,.10) }
        .hr-hero-tile.alt{ border-color:rgba(255,138,31,.35); background:rgba(255,138,31,.10) }
        .hr-hero-tile.alt:hover{ background:rgba(255,138,31,.18) }
        .hr-hero-num{ font-size:30px; font-weight:800; line-height:1; letter-spacing:-.02em }
        .hr-hero-num small{ font-size:14px; opacity:.7; margin-left:2px }
        .hr-hero-lbl{
          font-family:ui-monospace,Menlo,monospace; font-size:10px; font-weight:700;
          letter-spacing:.10em; text-transform:uppercase; color:rgba(255,255,255,.72);
          margin-top:4px;
        }
        /* the orange slash on top-left — like the octagonal tiles */
        .hr-hero-corner{
          position:absolute; top:0; left:0;
          width:20px; height:4px; background:#ff8a1f;
          transform:translate(-2px,3px) rotate(-45deg); transform-origin:left center;
        }
      `}</style>
    </section>
  );
}

/* METRIC: stat card brand-correct (raggio piccolo, eyebrow mono, ribbon laterale) */
function HRMetric({ icon, tone="cyan", label, value, sub, onClick }) {
  return (
    <button className={`hr-mtr tone-${tone}`} onClick={onClick}>
      <span className="hr-mtr-ribbon"/>
      <span className="hr-mtr-ic">{icon}</span>
      <span className="hr-mtr-body">
        <span className="hr-mtr-lbl">{label}</span>
        <span className="hr-mtr-val">{value}</span>
        <span className="hr-mtr-sub">{sub}</span>
      </span>
      <style>{`
        .hr-mtr{
          position:relative; display:flex; align-items:center; gap:12px;
          padding:12px 14px 12px 16px; background:#fff; border:1px solid #e7edf3;
          border-radius:10px; cursor:pointer; font:inherit; text-align:left; width:100%;
          transition:transform .12s, box-shadow .12s, border-color .12s;
          box-shadow:0 1px 3px rgba(0,0,0,.04);
        }
        .hr-mtr:hover{ transform:translateY(-1px); box-shadow:0 6px 18px rgba(12,37,69,.08); border-color:#cfd8e3 }
        .hr-mtr-ribbon{ position:absolute; left:0; top:10px; bottom:10px; width:3px; border-radius:0 3px 3px 0 }
        .hr-mtr-ic{
          width:38px; height:38px; flex:0 0 38px;
          display:flex; align-items:center; justify-content:center;
          border-radius:8px;
        }
        .hr-mtr-body{ display:flex; flex-direction:column; gap:1px; min-width:0; flex:1 }
        .hr-mtr-lbl{
          font-family:ui-monospace,Menlo,monospace; font-size:10px; font-weight:700;
          letter-spacing:.06em; text-transform:uppercase; color:#94a3b8;
        }
        .hr-mtr-val{ font-size:22px; font-weight:800; line-height:1.1; color:#0c2545 }
        .hr-mtr-sub{ font-size:11px; color:#6b7a90; margin-top:1px }

        .tone-cyan   .hr-mtr-ribbon{ background:#1f87cd }
        .tone-cyan   .hr-mtr-ic{ background:#e8f3fb; color:#1f87cd }
        .tone-orange .hr-mtr-ribbon{ background:#ff8a1f }
        .tone-orange .hr-mtr-ic{ background:#fff3e6; color:#ff8a1f }
        .tone-green  .hr-mtr-ribbon{ background:#16a34a }
        .tone-green  .hr-mtr-ic{ background:#ecfdf3; color:#15803d }
        .tone-red    .hr-mtr-ribbon{ background:#dc2626 }
        .tone-red    .hr-mtr-ic{ background:#fff5f5; color:#c53030 }
      `}</style>
    </button>
  );
}

/* PROGRESS — sottile, navy/cyan */
function HRProgress({ value, tone="navy" }) {
  const fill = tone === "cyan" ? "#1f87cd" : tone === "orange" ? "#ff8a1f" : "#0c2545";
  return (
    <div style={{height:5,background:"#eef2f7",borderRadius:3,overflow:"hidden"}}>
      <div style={{height:5,width:`${value}%`,background:fill,borderRadius:3,transition:"width .3s"}}/>
    </div>
  );
}

/* SECTION HEADER */
function HRSection({ title, sub, action }) {
  return (
    <header style={{display:"flex",alignItems:"flex-end",justifyContent:"space-between",gap:12,marginBottom:10}}>
      <div>
        <h3 style={{margin:0,fontSize:15,fontWeight:800,color:"#0c2545"}}>{title}</h3>
        {sub && <p style={{margin:"2px 0 0",fontSize:12,color:"#6b7a90"}}>{sub}</p>}
      </div>
      {action}
    </header>
  );
}

/* PERSON ROW + expandable mini-page (la feature distintiva) */
function HRPersonRow({ p, expanded, onToggle, onNav }) {
  return (
    <>
      <button className="hr-row" onClick={onToggle} aria-expanded={expanded}>
        <span className="hr-av" style={{ background: p.riskTone === "danger" ? "#fff3e6" : p.riskTone === "warning" ? "#fff8e6" : "#e8f3fb",
                                          color:      p.riskTone === "danger" ? "#c2410c" : p.riskTone === "warning" ? "#8a6500" : "#1f5fb3" }}>
          {p.name.split(" ").map(n=>n[0]).join("").slice(0,2)}
        </span>
        <span className="hr-row-main">
          <span className="hr-row-name">{p.name}</span>
          <span className="hr-row-meta"><code className="hr-code">{p.code}</code> · {p.role} · {p.dept}</span>
        </span>
        <span className="hr-row-status"><Badge tone={p.riskTone}>{p.risk}</Badge></span>
        <span className="hr-row-score">
          <span className="hr-score-num">{p.score}<small>/100</small></span>
          <HRProgress value={p.score} tone={p.score >= 90 ? "cyan" : p.score >= 75 ? "navy" : "orange"}/>
        </span>
        <span className="hr-row-chev" data-open={expanded ? "1" : "0"}>{Icons.chevronD}</span>
      </button>

      {expanded && (
        <div className="hr-row-detail">
          <div className="hr-detail-head">
            <div>
              <div className="hr-detail-eyebrow">Scheda dipendente · {p.code}</div>
              <h4 className="hr-detail-title">{p.name}</h4>
              <p className="hr-detail-sub">{p.role} · {p.dept} · {p.site} · resp. {p.manager}</p>
            </div>
            <div className="hr-detail-actions">
              <Button variant="ghost" size="sm" icon={Icons.doc}     onClick={() => onNav?.("docs")}>Documenti</Button>
              <Button variant="ghost" size="sm" icon={Icons.graduation} onClick={() => onNav?.("formazione")}>Formazione</Button>
              <Button variant="cyan"  size="sm" icon={Icons.shield}   onClick={() => onNav?.("sicurezza")}>Sicurezza</Button>
            </div>
          </div>

          <div className="hr-detail-grid">
            <div className="hr-detail-cell">
              <div className="hr-cell-lbl">Contratto</div>
              <div className="hr-cell-val">{p.contract}</div>
              <div className="hr-cell-meta">{p.status}</div>
            </div>
            <div className="hr-detail-cell">
              <div className="hr-cell-lbl">Documenti</div>
              <div className="hr-cell-val">8</div>
              <div className="hr-cell-meta"><Badge tone={p.riskTone}>1 azione</Badge></div>
            </div>
            <div className="hr-detail-cell">
              <div className="hr-cell-lbl">Formazione</div>
              <div className="hr-cell-val">4 corsi</div>
              <div className="hr-cell-meta">copertura 78%</div>
            </div>
            <div className="hr-detail-cell">
              <div className="hr-cell-lbl">Sicurezza</div>
              <div className="hr-cell-val">{p.riskTone === "danger" ? "Da verificare" : "OK"}</div>
              <div className="hr-cell-meta">DPI · idoneità</div>
            </div>
          </div>
        </div>
      )}

      <style>{`
        .hr-row{
          display:grid; width:100%;
          grid-template-columns: 36px minmax(0,1.4fr) auto minmax(140px,.9fr) 18px;
          gap:12px; align-items:center;
          padding:10px 14px; border-top:1px solid #f0f3f7;
          background:#fff; cursor:pointer; font:inherit; text-align:left;
          transition:background .12s;
        }
        .hr-row:first-child{ border-top:none }
        .hr-row:hover{ background:#fafbfd }
        .hr-row[aria-expanded="true"]{ background:#f4f8fc }
        .hr-av{
          width:36px; height:36px; border-radius:8px; display:flex; align-items:center;
          justify-content:center; font-weight:800; font-size:12px; flex:0 0 36px;
        }
        .hr-row-main{ min-width:0; display:flex; flex-direction:column; gap:1px }
        .hr-row-name{ font-size:13px; font-weight:700; color:#0c2545 }
        .hr-row-meta{ font-size:11px; color:#6b7a90 }
        .hr-code{ font-family:ui-monospace,Menlo,monospace; font-size:10.5px; color:#94a3b8; font-weight:700 }
        .hr-row-score{ display:flex; flex-direction:column; gap:4px; min-width:140px }
        .hr-score-num{ font-family:ui-monospace,Menlo,monospace; font-size:11px; font-weight:700; color:#0c2545 }
        .hr-score-num small{ color:#94a3b8; font-weight:500 }
        .hr-row-chev{ color:#94a3b8; display:inline-flex; transition:transform .15s }
        .hr-row-chev[data-open="1"]{ transform:rotate(180deg); color:#1f87cd }

        .hr-row-detail{
          background:linear-gradient(180deg,#f4f8fc 0,#fafbfd 100%);
          border-top:1px solid #e1e8f0; padding:16px 18px;
          position:relative;
        }
        .hr-row-detail::before{
          content:""; position:absolute; left:14px; top:-1px;
          width:14px; height:3px; background:#ff8a1f; transform:translateY(-50%)
        }
        .hr-detail-head{ display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:14px; flex-wrap:wrap }
        .hr-detail-eyebrow{
          font-family:ui-monospace,Menlo,monospace; font-size:10px; font-weight:700;
          letter-spacing:.12em; text-transform:uppercase; color:#1f87cd;
        }
        .hr-detail-title{ margin:2px 0 0; font-size:18px; font-weight:800; color:#0c2545 }
        .hr-detail-sub{ margin:2px 0 0; font-size:12px; color:#6b7a90 }
        .hr-detail-actions{ display:flex; gap:6px; flex-wrap:wrap }
        .hr-detail-grid{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px }
        .hr-detail-cell{
          background:#fff; border:1px solid #e7edf3; border-radius:8px; padding:10px 12px;
        }
        .hr-cell-lbl{
          font-family:ui-monospace,Menlo,monospace; font-size:9.5px; font-weight:700;
          letter-spacing:.08em; text-transform:uppercase; color:#94a3b8; margin-bottom:4px;
        }
        .hr-cell-val{ font-size:15px; font-weight:800; color:#0c2545; line-height:1.2 }
        .hr-cell-meta{ font-size:11px; color:#6b7a90; margin-top:3px }
      `}</style>
    </>
  );
}

/* ────────── SCREEN ────────── */
function AnagraficaHRScreen({ onNav }) {
  const [openId, setOpenId] = useStateHR(1);

  return (
    <>
      <HRHero/>

      {/* KPI strip */}
      <section className="hr-kpi">
        <HRMetric tone="cyan"   icon={Icons.people}    label="Dipendenti attivi"  value="148" sub="+4 nel mese corrente"   onClick={()=>onNav?.("persone")}/>
        <HRMetric tone="orange" icon={Icons.calendar}  label="Assenze oggi"       value="11"  sub="7 ferie · 4 malattia"  onClick={()=>onNav?.("assenze")}/>
        <HRMetric tone="green"  icon={Icons.shield}    label="Idoneità valide"    value="93%" sub="7 visite da pianificare" onClick={()=>onNav?.("sicurezza")}/>
        <HRMetric tone="red"    icon={Icons.flag}      label="Scadenze HR"        value="31"  sub="10 priorità alta"      onClick={()=>onNav?.("docs")}/>
      </section>

      {/* Two-column: people + side stack */}
      <section className="hr-grid">
        <Card padded={false}>
          <div style={{padding:"12px 14px 8px",borderBottom:"1px solid #eef2f7",display:"flex",alignItems:"center",justifyContent:"space-between"}}>
            <div>
              <h3 style={{margin:0,fontSize:14,fontWeight:800,color:"#0c2545"}}>Persone da presidiare</h3>
              <p style={{margin:"2px 0 0",fontSize:11,color:"#6b7a90"}}>
                Priorità calcolata da documenti, formazione, ruolo e stato onboarding · clicca per espandere
              </p>
            </div>
            <Button variant="ghost" size="sm" icon={Icons.filter}>Filtri</Button>
          </div>
          <div>
            {HR_PEOPLE.map(p => (
              <HRPersonRow key={p.id} p={p}
                expanded={openId === p.id}
                onToggle={() => setOpenId(openId === p.id ? null : p.id)}
                onNav={onNav}/>
            ))}
          </div>
        </Card>

        <div className="hr-side">
          <Card title="Scadenze critiche"
                action={<button className="hr-link" onClick={()=>onNav?.("docs")}>Tutte →</button>}
                padded={false}>
            <ul className="hr-exp">
              {HR_EXPIRING.map(e => (
                <li key={e.label}>
                  <span className={`hr-exp-ic tone-${e.tone}`}>
                    {e.tone === "danger" ? Icons.warning : Icons.clock}
                  </span>
                  <span className="hr-exp-body">
                    <span className="hr-exp-t">{e.label}</span>
                    <span className="hr-exp-m">{e.hint}</span>
                  </span>
                  <span className={`hr-exp-n tone-${e.tone}`}>{e.value}</span>
                </li>
              ))}
            </ul>
          </Card>

          <Card title="Onboarding rapido" padded={false}>
            <div className="hr-quick">
              <button className="hr-quick-tile" onClick={()=>onNav?.("docs")}>
                <span className="hr-quick-ic">{Icons.briefcase}</span>
                <span className="hr-quick-lbl">Contratto</span>
              </button>
              <button className="hr-quick-tile" onClick={()=>onNav?.("persone")}>
                <span className="hr-quick-ic">{Icons.badgeCheck}</span>
                <span className="hr-quick-lbl">Mansione</span>
              </button>
              <button className="hr-quick-tile" onClick={()=>onNav?.("formazione")}>
                <span className="hr-quick-ic">{Icons.graduation}</span>
                <span className="hr-quick-lbl">Formazione</span>
              </button>
              <button className="hr-quick-tile" onClick={()=>onNav?.("sicurezza")}>
                <span className="hr-quick-ic">{Icons.heart}</span>
                <span className="hr-quick-lbl">Sorveglianza</span>
              </button>
            </div>
          </Card>
        </div>
      </section>

      {/* Activities + maturity */}
      <section className="hr-grid hr-grid-2">
        <Card title="Timeline attività HR" padded={false}>
          <ul className="hr-act">
            {HR_ACTIVITIES.map(a => (
              <li key={a.t}>
                <span className="hr-act-ic">{a.ic}</span>
                <span className="hr-act-body">
                  <span className="hr-act-t">{a.t}</span>
                  <span className="hr-act-m">{a.m}</span>
                </span>
                <span className="hr-act-time">{a.time}</span>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Maturità modulo" padded={true}>
          <p style={{margin:"0 0 14px",fontSize:12,color:"#6b7a90"}}>
            Indicazione visiva per il rollout Anagrafica HR.
          </p>
          <div style={{display:"flex",flexDirection:"column",gap:12}}>
            {HR_MATURITY.map(([label, value]) => (
              <div key={label}>
                <div style={{display:"flex",justifyContent:"space-between",fontSize:12,marginBottom:5}}>
                  <span style={{fontWeight:600,color:"#0c2545"}}>{label}</span>
                  <span style={{fontFamily:"ui-monospace,Menlo,monospace",color:"#6b7a90",fontWeight:700}}>{value}%</span>
                </div>
                <HRProgress value={value} tone={value >= 80 ? "cyan" : value >= 60 ? "navy" : "orange"}/>
              </div>
            ))}
          </div>
        </Card>
      </section>

      <style>{`
        .hr-kpi{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:18px }
        .hr-grid{ display:grid; grid-template-columns:1.4fr .8fr; gap:14px; margin-bottom:18px }
        .hr-grid-2{ grid-template-columns:1.4fr .8fr }
        .hr-side{ display:flex; flex-direction:column; gap:14px }
        .hr-link{ font:inherit; font-size:11px; font-weight:700; color:#1f87cd; background:none; border:none; cursor:pointer }
        .hr-link:hover{ text-decoration:underline }

        .hr-exp{ list-style:none; margin:0; padding:0 }
        .hr-exp li{ display:grid; grid-template-columns:34px 1fr auto; gap:10px; align-items:center; padding:10px 14px; border-top:1px solid #f0f3f7 }
        .hr-exp li:first-child{ border-top:none }
        .hr-exp-ic{ width:30px; height:30px; border-radius:8px; display:flex; align-items:center; justify-content:center }
        .hr-exp-ic.tone-danger{ background:#fff5f5; color:#c53030 }
        .hr-exp-ic.tone-warning{ background:#fff3e6; color:#c2410c }
        .hr-exp-body{ display:flex; flex-direction:column; gap:1px; min-width:0 }
        .hr-exp-t{ font-size:12.5px; font-weight:700; color:#0c2545 }
        .hr-exp-m{ font-size:10.5px; color:#94a3b8 }
        .hr-exp-n{
          font-family:ui-monospace,Menlo,monospace; font-weight:800; font-size:18px;
          padding:2px 10px; border-radius:6px;
        }
        .hr-exp-n.tone-danger{ background:#fff5f5; color:#c53030 }
        .hr-exp-n.tone-warning{ background:#fff3e6; color:#c2410c }

        .hr-quick{ display:grid; grid-template-columns:1fr 1fr; gap:8px; padding:12px }
        .hr-quick-tile{
          background:#fafbfd; border:1px solid #e7edf3; border-radius:8px;
          padding:11px 12px; display:flex; flex-direction:column; gap:6px;
          cursor:pointer; font:inherit; text-align:left; color:#0c2545;
          transition:background .12s, border-color .12s;
        }
        .hr-quick-tile:hover{ background:#fff; border-color:#1f87cd; box-shadow:0 4px 12px rgba(31,135,205,.08) }
        .hr-quick-ic{ color:#1f87cd }
        .hr-quick-lbl{ font-size:12.5px; font-weight:700 }

        .hr-act{ list-style:none; margin:0; padding:0 }
        .hr-act li{ display:grid; grid-template-columns:32px 1fr auto; gap:12px; align-items:center; padding:10px 14px; border-top:1px solid #f0f3f7 }
        .hr-act li:first-child{ border-top:none }
        .hr-act-ic{ width:28px; height:28px; border-radius:8px; background:#e8f3fb; color:#1f87cd; display:flex; align-items:center; justify-content:center }
        .hr-act-body{ display:flex; flex-direction:column; gap:1px }
        .hr-act-t{ font-size:12.5px; font-weight:700; color:#0c2545 }
        .hr-act-m{ font-size:10.5px; color:#94a3b8 }
        .hr-act-time{
          font-family:ui-monospace,Menlo,monospace; font-size:10.5px; font-weight:700;
          color:#94a3b8; text-transform:uppercase; letter-spacing:.04em;
        }

        @media (max-width: 1100px){
          .hr-grid, .hr-grid-2{ grid-template-columns:1fr }
          .hr-kpi{ grid-template-columns:repeat(2,1fr) }
        }
      `}</style>
    </>
  );
}

Object.assign(window, { AnagraficaHRScreen });
