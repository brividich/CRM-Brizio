/* global React, Icons, Card, Button, Badge,
          PersonePage, AssenzePage, FormazionePage, DocumentiPage, SicurezzaPage */
/* ──────────────────────────────────────────────────────────
   ANAGRAFICA HR — orchestratore (con tabs interne) + Dashboard.
   Adattamento brand‑correct del prototipo `anagrafica_hr_dashboard_novicrom.jsx`
   ai token Novicrom HUB (navy/cyan/orange, Outfit, raggi 6–12, mono per codici).
   Pagine secondarie: vedi AnagraficaHR_Pages.jsx.
   ────────────────────────────────────────────────────────── */
const { useState: useStateHR } = React;

/* ── Dati locali per il Dashboard ── */
const HR_PEOPLE_BRIEF = [
  { id:1, code:"DIP-1024", name:"Marco Rossi",     dept:"Produzione",      role:"Saldatore",         risk:"Doc. in scadenza", riskTone:"warning", score:82 },
  { id:2, code:"DIP-1031", name:"Giulia Bianchi",  dept:"Amministrazione", role:"Impiegata",         risk:"OK",               riskTone:"success", score:96 },
  { id:3, code:"DIP-1042", name:"Luca Verdi",      dept:"Cantiere",        role:"Preposto",          risk:"Formazione",       riskTone:"warning", score:74 },
  { id:4, code:"DIP-1058", name:"Sara Neri",       dept:"HR",              role:"HR Specialist",     risk:"Contratto firma",  riskTone:"danger",  score:68 },
  { id:5, code:"DIP-1063", name:"Francesco Conti", dept:"Magazzino",       role:"Addetto logistica", risk:"DPI da firmare",   riskTone:"warning", score:79 },
];

const HR_EXPIRING = [
  { label:"Visite mediche",       value:7,  tone:"danger",  hint:"Sorveglianza sanitaria", target:"sicurezza"  },
  { label:"Formazione sicurezza", value:12, tone:"warning", hint:"Aggiornamenti scaduti",  target:"formazione" },
  { label:"Contratti / proroghe", value:3,  tone:"warning", hint:"TD in scadenza 30 gg",   target:"documenti"  },
  { label:"DPI da consegnare",    value:9,  tone:"danger",  hint:"Firme richieste",        target:"sicurezza"  },
];

const HR_ACTIVITIES = [
  { ic:"userPlus",  t:"Nuovo onboarding creato",    m:"Sara Neri · HR",                    time:"09:12", target:"persone"     },
  { ic:"clipboard", t:"Corso sicurezza aggiornato", m:"Produzione · 8 partecipanti",       time:"ieri",  target:"formazione"  },
  { ic:"doc",       t:"Documento caricato",         m:"Contratto apprendistato · Rossi",   time:"ieri",  target:"documenti"   },
  { ic:"shield",    t:"DPI confermati",             m:"Cantiere · 6 consegne validate",    time:"2 gg",  target:"sicurezza"   },
];

const HR_MATURITY = [
  ["Anagrafica base",  92], ["Documentale",      76],
  ["Formazione",       64], ["Sicurezza lavoro", 71],
  ["Retribuzioni",     42],
];

/* ====== HERO DASHBOARD ====== */
function HRHero({ onJump }) {
  return (
    <section className="hr-hero" data-screen-label="03 Anagrafica HR · Hero">
      <div className="hr-hero-bg"/>
      <div className="hr-hero-inner">
        <div>
          <div className="hr-hero-eyebrow"><span className="hr-dot"/>Anagrafica HR · console operativa</div>
          <h1 className="hr-hero-title">Persone, contratti, assenze e<br/>compliance in un'unica vista.</h1>
          <p className="hr-hero-sub">
            Pensata per Direzione, HR e responsabili reparto. Indicatori immediati,
            scadenze critiche e stato documentale del personale.
          </p>
        </div>
        <div className="hr-hero-side">
          <button className="hr-hero-tile" onClick={() => onJump?.("sicurezza")}>
            <span className="hr-hero-num">86<small>%</small></span>
            <span className="hr-hero-lbl">Compliance HR</span>
            <span className="hr-hero-corner"/>
          </button>
          <button className="hr-hero-tile alt" onClick={() => onJump?.("documenti")}>
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
          color:#fff; padding:26px 26px 22px; margin-bottom:14px;
          clip-path:polygon(0 0, calc(100% - 22px) 0, 100% 22px, 100% 100%, 0 100%);
        }
        .hr-hero-bg{
          position:absolute; inset:0; pointer-events:none; opacity:.5;
          background-image:
            radial-gradient(circle at 80% 20%, rgba(255,138,31,.25), transparent 40%),
            radial-gradient(rgba(31,135,205,.20) 1px, transparent 1.4px);
          background-size: auto, 16px 16px;
        }
        .hr-hero-inner{ position:relative; display:flex; gap:22px;
                        align-items:center; justify-content:space-between; flex-wrap:wrap }
        .hr-hero-eyebrow{
          display:inline-flex; align-items:center; gap:8px;
          font-family:ui-monospace,Menlo,monospace; font-size:11px;
          font-weight:700; letter-spacing:.14em; text-transform:uppercase;
          color:#ff8a1f; padding:4px 0; margin-bottom:8px;
        }
        .hr-dot{ width:7px; height:7px; border-radius:50%; background:#ff8a1f;
                 box-shadow:0 0 0 4px rgba(255,138,31,.18) }
        .hr-hero-title{ margin:0 0 6px; font-size:28px; font-weight:800;
                        line-height:1.1; letter-spacing:-.01em }
        .hr-hero-sub{ margin:0; font-size:13px; color:rgba(255,255,255,.72);
                      line-height:1.55; max-width:520px }
        .hr-hero-side{ display:grid; gap:10px; grid-template-columns:1fr 1fr; min-width:260px }
        .hr-hero-tile{
          position:relative; padding:14px 16px 12px;
          background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.14);
          color:#fff; cursor:pointer; font:inherit;
          display:flex; flex-direction:column; gap:2px; text-align:left;
          clip-path:polygon(12px 0, 100% 0, 100% 100%, 0 100%, 0 12px);
          transition:background .15s;
        }
        .hr-hero-tile:hover{ background:rgba(255,255,255,.10) }
        .hr-hero-tile.alt{ border-color:rgba(255,138,31,.35); background:rgba(255,138,31,.10) }
        .hr-hero-tile.alt:hover{ background:rgba(255,138,31,.18) }
        .hr-hero-num{ font-size:28px; font-weight:800; line-height:1; letter-spacing:-.02em }
        .hr-hero-num small{ font-size:14px; opacity:.7; margin-left:2px }
        .hr-hero-lbl{
          font-family:ui-monospace,Menlo,monospace; font-size:10px; font-weight:700;
          letter-spacing:.10em; text-transform:uppercase; color:rgba(255,255,255,.72);
          margin-top:4px;
        }
        .hr-hero-corner{
          position:absolute; top:0; left:0;
          width:20px; height:4px; background:#ff8a1f;
          transform:translate(-2px,3px) rotate(-45deg); transform-origin:left center;
        }
      `}</style>
    </section>
  );
}

/* ====== METRIC CARD ====== */
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
        .hr-mtr-ic{ width:38px; height:38px; flex:0 0 38px;
                    display:flex; align-items:center; justify-content:center; border-radius:8px }
        .hr-mtr-body{ display:flex; flex-direction:column; gap:1px; min-width:0; flex:1 }
        .hr-mtr-lbl{ font-family:ui-monospace,Menlo,monospace; font-size:10px; font-weight:700;
                     letter-spacing:.06em; text-transform:uppercase; color:#94a3b8 }
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

function HRProgress({ value, tone="navy" }) {
  const fill = tone === "cyan" ? "#1f87cd" : tone === "orange" ? "#ff8a1f" : "#0c2545";
  return (
    <div style={{height:5,background:"#eef2f7",borderRadius:3,overflow:"hidden"}}>
      <div style={{height:5,width:`${value}%`,background:fill,borderRadius:3,transition:"width .3s"}}/>
    </div>
  );
}

/* ====== DASHBOARD ====== */
function DashboardPage({ onJump, onNav }) {
  return (
    <>
      <HRHero onJump={onJump}/>

      <section className="hr-kpi">
        <HRMetric tone="cyan"   icon={Icons.people}   label="Dipendenti attivi" value="148" sub="+4 nel mese corrente"   onClick={() => onJump("persone")}/>
        <HRMetric tone="orange" icon={Icons.calendar} label="Assenze oggi"      value="11"  sub="7 ferie · 4 malattia"   onClick={() => onJump("assenze")}/>
        <HRMetric tone="green"  icon={Icons.shield}   label="Idoneità valide"   value="93%" sub="7 visite da pianificare" onClick={() => onJump("sicurezza")}/>
        <HRMetric tone="red"    icon={Icons.flag}     label="Scadenze HR"       value="31"  sub="10 priorità alta"        onClick={() => onJump("documenti")}/>
      </section>

      <section className="hr-grid">
        <Card padded={false}>
          <div className="hr-card-head">
            <div>
              <h3 style={{margin:0,fontSize:14,fontWeight:800,color:"#0c2545"}}>Persone da presidiare</h3>
              <p style={{margin:"2px 0 0",fontSize:11,color:"#6b7a90"}}>Priorità documenti, formazione, sicurezza · clicca per scheda completa</p>
            </div>
            <Button variant="ghost" size="sm" icon={Icons.filter} onClick={() => onJump("persone")}>Apri elenco</Button>
          </div>
          <div className="hr-rows">
            <div className="hr-rows-th">
              <span>Persona</span><span>Reparto</span><span>Stato</span><span>HR score</span>
            </div>
            {HR_PEOPLE_BRIEF.map(p => (
              <button key={p.id} className="hr-row" onClick={() => onJump("persone")}>
                <span className="hr-row-people">
                  <span className="hr-av" style={{
                    background: p.riskTone==="danger"?"#fff5f5":p.riskTone==="warning"?"#fff3e6":"#e8f3fb",
                    color:      p.riskTone==="danger"?"#c53030":p.riskTone==="warning"?"#c2410c":"#1f5fb3" }}>
                    {p.name.split(" ").map(n=>n[0]).join("").slice(0,2)}
                  </span>
                  <span>
                    <span className="hr-row-name">{p.name}</span>
                    <span className="hr-row-meta"><code className="hr-code">{p.code}</code> · {p.role}</span>
                  </span>
                </span>
                <span className="hr-mut">{p.dept}</span>
                <span><Badge tone={p.riskTone}>{p.risk}</Badge></span>
                <span className="hr-row-score">
                  <span className="hr-score-num">{p.score}<small>/100</small></span>
                  <HRProgress value={p.score} tone={p.score>=90?"cyan":p.score>=75?"navy":"orange"}/>
                </span>
              </button>
            ))}
          </div>
        </Card>

        <div className="hr-side">
          <Card title="Scadenze critiche" padded={false}
                action={<button className="hr-link" onClick={() => onJump("documenti")}>Tutte →</button>}>
            <ul className="hr-exp">
              {HR_EXPIRING.map(e => (
                <li key={e.label}>
                  <button className="hr-exp-btn" onClick={() => onJump(e.target)}>
                    <span className={`hr-exp-ic tone-${e.tone}`}>
                      {e.tone === "danger" ? Icons.warning : Icons.clock}
                    </span>
                    <span className="hr-exp-body">
                      <span className="hr-exp-t">{e.label}</span>
                      <span className="hr-exp-m">{e.hint}</span>
                    </span>
                    <span className={`hr-exp-n tone-${e.tone}`}>{e.value}</span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>

          <Card title="Onboarding rapido" padded={false}>
            <div className="hr-quick">
              <button className="hr-quick-tile" onClick={() => onJump("documenti")}>
                <span className="hr-quick-ic">{Icons.briefcase}</span><span className="hr-quick-lbl">Contratto</span>
              </button>
              <button className="hr-quick-tile" onClick={() => onJump("persone")}>
                <span className="hr-quick-ic">{Icons.badgeCheck}</span><span className="hr-quick-lbl">Mansione</span>
              </button>
              <button className="hr-quick-tile" onClick={() => onJump("formazione")}>
                <span className="hr-quick-ic">{Icons.graduation}</span><span className="hr-quick-lbl">Formazione</span>
              </button>
              <button className="hr-quick-tile" onClick={() => onJump("sicurezza")}>
                <span className="hr-quick-ic">{Icons.heart}</span><span className="hr-quick-lbl">Sorveglianza</span>
              </button>
            </div>
          </Card>
        </div>
      </section>

      <section className="hr-grid">
        <Card title="Timeline attività HR" padded={false}>
          <ul className="hr-act">
            {HR_ACTIVITIES.map(a => (
              <li key={a.t}>
                <button className="hr-act-btn" onClick={() => onJump(a.target)}>
                  <span className="hr-act-ic">{Icons[a.ic]}</span>
                  <span className="hr-act-body">
                    <span className="hr-act-t">{a.t}</span>
                    <span className="hr-act-m">{a.m}</span>
                  </span>
                  <span className="hr-act-time">{a.time}</span>
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Maturità modulo" padded={true}>
          <p style={{margin:"0 0 12px",fontSize:12,color:"#6b7a90"}}>Stato del rollout Anagrafica HR sui sotto‑moduli.</p>
          <div style={{display:"flex",flexDirection:"column",gap:11}}>
            {HR_MATURITY.map(([label, value]) => (
              <div key={label}>
                <div style={{display:"flex",justifyContent:"space-between",fontSize:12,marginBottom:5}}>
                  <span style={{fontWeight:600,color:"#0c2545"}}>{label}</span>
                  <span style={{fontFamily:"ui-monospace,Menlo,monospace",color:"#6b7a90",fontWeight:700}}>{value}%</span>
                </div>
                <HRProgress value={value} tone={value>=80?"cyan":value>=60?"navy":"orange"}/>
              </div>
            ))}
          </div>
        </Card>
      </section>

      <style>{`
        .hr-kpi{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:14px }
        .hr-grid{ display:grid; grid-template-columns:1.4fr .8fr; gap:12px; margin-bottom:14px }
        .hr-side{ display:flex; flex-direction:column; gap:12px }
        .hr-link{ font:inherit; font-size:11px; font-weight:700; color:#1f87cd; background:none; border:none; cursor:pointer }
        .hr-link:hover{ text-decoration:underline }

        .hr-card-head{
          display:flex; align-items:center; justify-content:space-between; gap:12px;
          padding:12px 14px; border-bottom:1px solid #eef2f7;
        }
        .hr-rows{ display:flex; flex-direction:column }
        .hr-rows-th{
          display:grid; grid-template-columns:1.6fr .9fr .9fr .9fr; gap:12px;
          padding:7px 14px; background:#fafbfd; border-bottom:1px solid #eef2f7;
          font-family:ui-monospace,Menlo,monospace; font-size:10px; font-weight:700;
          letter-spacing:.06em; text-transform:uppercase; color:#94a3b8;
        }
        .hr-row{
          display:grid; grid-template-columns:1.6fr .9fr .9fr .9fr; gap:12px;
          padding:10px 14px; align-items:center; background:#fff; border:none;
          border-top:1px solid #f0f3f7; cursor:pointer; font:inherit; text-align:left;
          transition:background .12s;
        }
        .hr-row:hover{ background:#fafbfd }
        .hr-row-people{ display:flex; align-items:center; gap:10px; min-width:0 }
        .hr-av{
          width:32px; height:32px; flex:0 0 32px; border-radius:8px;
          display:flex; align-items:center; justify-content:center; font-weight:800; font-size:11.5px;
        }
        .hr-row-name{ display:block; font-size:12.5px; font-weight:700; color:#0c2545 }
        .hr-row-meta{ display:block; font-size:11px; color:#6b7a90 }
        .hr-mut{ font-size:12.5px; color:#4a5568 }
        .hr-code{ font-family:ui-monospace,Menlo,monospace; font-size:10.5px; color:#94a3b8; font-weight:700 }
        .hr-row-score{ display:flex; flex-direction:column; gap:4px; min-width:120px }
        .hr-score-num{ font-family:ui-monospace,Menlo,monospace; font-size:11px; font-weight:700; color:#0c2545 }
        .hr-score-num small{ color:#94a3b8; font-weight:500 }

        .hr-exp{ list-style:none; margin:0; padding:0 }
        .hr-exp li{ border-top:1px solid #f0f3f7 }
        .hr-exp li:first-child{ border-top:none }
        .hr-exp-btn{
          display:grid; grid-template-columns:34px 1fr auto; gap:10px; align-items:center;
          width:100%; padding:10px 14px; background:#fff; border:none; cursor:pointer; font:inherit; text-align:left;
          transition:background .12s;
        }
        .hr-exp-btn:hover{ background:#fafbfd }
        .hr-exp-ic{ width:30px; height:30px; border-radius:8px; display:flex; align-items:center; justify-content:center }
        .hr-exp-ic.tone-danger{ background:#fff5f5; color:#c53030 }
        .hr-exp-ic.tone-warning{ background:#fff3e6; color:#c2410c }
        .hr-exp-body{ display:flex; flex-direction:column; gap:1px; min-width:0 }
        .hr-exp-t{ font-size:12.5px; font-weight:700; color:#0c2545 }
        .hr-exp-m{ font-size:10.5px; color:#94a3b8 }
        .hr-exp-n{
          font-family:ui-monospace,Menlo,monospace; font-weight:800; font-size:17px;
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
        .hr-act li{ border-top:1px solid #f0f3f7 }
        .hr-act li:first-child{ border-top:none }
        .hr-act-btn{
          display:grid; grid-template-columns:32px 1fr auto; gap:12px; align-items:center;
          width:100%; padding:10px 14px; background:#fff; border:none; cursor:pointer; font:inherit; text-align:left;
          transition:background .12s;
        }
        .hr-act-btn:hover{ background:#fafbfd }
        .hr-act-ic{ width:28px; height:28px; border-radius:8px; background:#e8f3fb; color:#1f87cd;
                    display:flex; align-items:center; justify-content:center }
        .hr-act-body{ display:flex; flex-direction:column; gap:1px }
        .hr-act-t{ font-size:12.5px; font-weight:700; color:#0c2545 }
        .hr-act-m{ font-size:10.5px; color:#94a3b8 }
        .hr-act-time{
          font-family:ui-monospace,Menlo,monospace; font-size:10.5px; font-weight:700;
          color:#94a3b8; text-transform:uppercase; letter-spacing:.04em;
        }

        @media (max-width: 1100px){
          .hr-grid{ grid-template-columns:1fr }
          .hr-kpi{ grid-template-columns:repeat(2,1fr) }
        }
      `}</style>
    </>
  );
}

/* ====== ORCHESTRATORE ====== */
function AnagraficaHRScreen({ onNav }) {
  const [tab, setTab] = useStateHR("dashboard");

  const TABS = [
    { id:"dashboard",  label:"Dashboard",  ic:Icons.dashboard },
    { id:"persone",    label:"Persone",    ic:Icons.people },
    { id:"assenze",    label:"Assenze",    ic:Icons.calendar },
    { id:"formazione", label:"Formazione", ic:Icons.graduation },
    { id:"documenti",  label:"Documenti",  ic:Icons.folder },
    { id:"sicurezza",  label:"Sicurezza",  ic:Icons.shield },
  ];

  const ContentByTab = {
    dashboard:  <DashboardPage onJump={setTab} onNav={onNav}/>,
    persone:    <PersonePage    onNav={(target) => { if (["formazione","documenti","sicurezza","assenze"].includes(target)) setTab(target); else onNav?.(target); }}/>,
    assenze:    <AssenzePage/>,
    formazione: <FormazionePage/>,
    documenti:  <DocumentiPage/>,
    sicurezza:  <SicurezzaPage/>,
  };

  const label = TABS.find(t => t.id===tab)?.label || "Anagrafica HR";

  return (
    <div className="hr-app" data-screen-label={`03 Anagrafica HR · ${label}`}>
      <div className="hr-modtabs">
        <div className="hr-modtabs-inner">
          {TABS.map(t => (
            <button key={t.id} className={`hr-modtab ${tab===t.id?"on":""}`} onClick={() => setTab(t.id)}>
              <span className="hr-modtab-ic">{t.ic}</span>
              <span>{t.label}</span>
              {tab===t.id && <span className="hr-modtab-mark"/>}
            </button>
          ))}
        </div>
      </div>

      <div className="hr-modview">
        {ContentByTab[tab]}
      </div>

      <style>{`
        .hr-app{ display:flex; flex-direction:column; gap:0 }
        .hr-modtabs{
          position:sticky; top:0; z-index:5; background:#f4f6fb;
          padding:0 0 12px; margin:-22px -28px 14px; padding:18px 28px 12px;
          border-bottom:1px solid #e1e8f0;
        }
        .hr-modtabs-inner{
          display:flex; gap:4px; background:#fff; padding:5px;
          border:1px solid #e7edf3; border-radius:10px;
          box-shadow:0 1px 3px rgba(0,0,0,.04);
          overflow-x:auto;
        }
        .hr-modtab{
          position:relative; display:inline-flex; align-items:center; gap:7px;
          padding:8px 14px; font:inherit; font-size:12.5px; font-weight:700;
          color:#6b7a90; background:transparent; border:none; cursor:pointer;
          border-radius:7px; white-space:nowrap;
          transition:background .12s, color .12s;
        }
        .hr-modtab:hover{ background:#f4f6fb; color:#0c2545 }
        .hr-modtab.on{ background:#0c2545; color:#fff }
        .hr-modtab-ic{ display:inline-flex; opacity:.85 }
        .hr-modtab.on .hr-modtab-ic{ opacity:1 }
        .hr-modtab-mark{
          position:absolute; left:50%; transform:translateX(-50%);
          bottom:-7px; width:18px; height:3px; background:#ff8a1f; border-radius:3px;
        }
        .hr-modview{ display:block }
      `}</style>
    </div>
  );
}

Object.assign(window, { AnagraficaHRScreen });
