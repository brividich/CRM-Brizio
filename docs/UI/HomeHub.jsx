/* global React, Icons, Card, Button, Badge, OctTile, Topbar */
/* ──────────────────────────────────────────────────────────
   HOME PORTAL — dashboard interattiva di NOVICROM HUB.
   Mostra TUTTI i moduli (con awareness dei permessi ACL),
   KPI cross‑modulo, code di lavoro personali, attività e
   stato sistema. Sostituisce la vecchia DashboardScreen.
   ────────────────────────────────────────────────────────── */
const { useState: useHH, useMemo: useHM, useEffect: useHE } = React;

/* ── Catalogo moduli (allineato a docs/ai + CLAUDE.md) ─────────────────── */
const HH_MODULES = [
  /* Operations */
  { id:"anomalie",   cat:"ops", icon:"warning",    label:"Anomalie",            sub:"Eventi e segnalazioni",   kpi:{ n:3,  unit:"aperte",       tone:"danger" },  perm:["it","dir","capo","preposto"] },
  { id:"ticket",     cat:"ops", icon:"ticket",     label:"Ticket",              sub:"Interventi e richieste",  kpi:{ n:14, unit:"attivi",       tone:"warning" }, perm:["it","dir","hr","capo","preposto","op"] },
  { id:"task",       cat:"ops", icon:"task",       label:"Task / Kick‑off",     sub:"Attività di reparto",     kpi:{ n:27, unit:"in corso",     tone:"info" },    perm:["it","dir","hr","capo","preposto","op"] },
  { id:"diario",     cat:"ops", icon:"clipboard",  label:"Diario preposto",     sub:"Giornale di sicurezza",   kpi:{ n:2,  unit:"da firmare",   tone:"warning" }, perm:["it","dir","capo","preposto"] },
  { id:"incidenti",  cat:"ops", icon:"flag",       label:"Rilevazione incidenti", sub:"Near miss e infortuni", kpi:{ n:1,  unit:"in analisi",   tone:"danger" },  perm:["it","dir","hr","capo","preposto"] },
  { id:"procedure",  cat:"ops", icon:"refresh",    label:"Procedure refresh",   sub:"Procedure CN aggiornate", kpi:{ n:4,  unit:"da rivedere",  tone:"info" },    perm:["it","dir","capo","preposto"] },

  /* Persone */
  { id:"anagrafica", cat:"hr",  icon:"people",     label:"Anagrafica HR",       sub:"148 dipendenti attivi",   kpi:{ n:148,unit:"dipendenti",   tone:"info" },    perm:["it","dir","hr","capo"] },
  { id:"assenze",    cat:"hr",  icon:"calendar",   label:"Assenze",             sub:"Ferie, malattia, permessi", kpi:{ n:11, unit:"oggi assenti", tone:"warning" }, perm:["it","dir","hr","capo","preposto","op"] },
  { id:"timbri",     cat:"hr",  icon:"clock",      label:"Timbri",              sub:"Presenze e timbrature",   kpi:{ n:142,unit:"in turno",     tone:"success" }, perm:["it","dir","hr","capo","preposto","op"] },
  { id:"formazione", cat:"hr",  icon:"graduation", label:"Formazione",          sub:"Corsi e aggiornamenti",   kpi:{ n:12, unit:"scaduti",      tone:"warning" }, perm:["it","dir","hr","capo"] },
  { id:"dpi",        cat:"hr",  icon:"shield",     label:"DPI",                 sub:"Consegne e firma",        kpi:{ n:9,  unit:"da firmare",   tone:"danger" },  perm:["it","dir","hr","capo","preposto","op"] },
  { id:"sicurezza",  cat:"hr",  icon:"heart",      label:"Sorv. sanitaria",     sub:"Visite mediche",          kpi:{ n:7,  unit:"da pianific.", tone:"danger" },  perm:["it","dir","hr"] },
  { id:"notizie",    cat:"hr",  icon:"bell",       label:"Notizie aziendali",   sub:"Comunicazioni interne",   kpi:{ n:3,  unit:"nuove",        tone:"info" },    perm:["it","dir","hr","capo","preposto","op"] },

  /* Stabilimento / Asset */
  { id:"asset",      cat:"plant", icon:"asset",    label:"Attrezzature",        sub:"Asset register",          kpi:{ n:512,unit:"asset",        tone:"info" },    perm:["it","dir","capo"] },
  { id:"planimetria",cat:"plant", icon:"building", label:"Planimetria",         sub:"Layout stabilimenti",     kpi:{ n:6,  unit:"reparti",      tone:"info" },    perm:["it","dir","capo","preposto"] },
  { id:"fornitori",  cat:"plant", icon:"briefcase",label:"Fornitori",           sub:"Anagrafica fornitori",    kpi:{ n:87, unit:"attivi",       tone:"info" },    perm:["it","dir","capo"] },
  { id:"monitoring", cat:"plant", icon:"gear",     label:"Monitoring",          sub:"Telemetria di linea",     kpi:{ n:0,  unit:"allarmi",      tone:"success" }, perm:["it","dir","capo"] },

  /* Compliance */
  { id:"rentri",     cat:"comp", icon:"folder",    label:"Rentri",              sub:"Tracciamento rifiuti",    kpi:{ n:2,  unit:"FIR da firmare",tone:"warning" }, perm:["it","dir","capo"] },
  { id:"documenti",  cat:"comp", icon:"doc",       label:"Documenti",           sub:"Contratti, ACL, audit",   kpi:{ n:21, unit:"in attesa",    tone:"warning" }, perm:["it","dir","hr","capo"] },

  /* Automazione / Sistema */
  { id:"automazioni",cat:"sys",  icon:"refresh",   label:"Automazioni",         sub:"Workflow designer",       kpi:{ n:18, unit:"flussi attivi", tone:"success" }, perm:["it","dir"] },
  { id:"ai",         cat:"sys",  icon:"badgeCheck",label:"Assistente AI",       sub:"Knowledge & helper",      kpi:{ n:"online", unit:"",         tone:"success" }, perm:["it","dir","hr","capo","preposto","op"] },
  { id:"hubtools",   cat:"sys",  icon:"gear",      label:"Hub Tools",           sub:"Branding & pulsanti",     kpi:{ n:null,unit:"strumenti",    tone:"info" },    perm:["it"] },
  { id:"admin",      cat:"sys",  icon:"lock",      label:"Admin portale",       sub:"Utenze e impersonificaz.",kpi:{ n:null,unit:"riservato",    tone:"info" },    perm:["it"] },
  { id:"setup",      cat:"sys",  icon:"plus",      label:"Setup wizard",        sub:"Provisioning",            kpi:{ n:null,unit:"riservato",    tone:"info" },    perm:["it"] },
  { id:"permessi",   cat:"sys",  icon:"lock",      label:"Permessi e ruoli",    sub:"ACL v2",                  kpi:{ n:14, unit:"ruoli",        tone:"info" },    perm:["it","dir"] },
];

const HH_CATEGORIES = [
  { key:"ops",   label:"Operations",          hint:"Eventi e ciclo di lavoro" },
  { key:"hr",    label:"Persone & sicurezza", hint:"Anagrafica, assenze, formazione, DPI" },
  { key:"plant", label:"Stabilimento",        hint:"Asset, planimetria, fornitori" },
  { key:"comp",  label:"Compliance",          hint:"Documenti, rifiuti, audit" },
  { key:"sys",   label:"Automazione & sistema", hint:"Workflow, AI, ACL, amministrazione" },
];

const HH_ROLES = {
  it:       { code:"IT",   label:"IT Administrator",  hint:"Accesso completo, configurazione" },
  dir:      { code:"DIR",  label:"Direzione",         hint:"Visione completa, lettura prevalente" },
  hr:       { code:"HR",   label:"HR Specialist",     hint:"Persone, contratti, formazione, sicurezza" },
  capo:     { code:"CR",   label:"Capo reparto",      hint:"Operations + persone del reparto" },
  preposto: { code:"PR",   label:"Preposto",          hint:"Diario, DPI, anomalie del turno" },
  op:       { code:"OP",   label:"Operatore",         hint:"Sue richieste, suoi turni, news" },
};

/* ── KPI di hero (somma dei moduli con priorità) ──────────────────────── */
const HH_PRIORITY = [
  { id:"anomalie", tone:"red",    icon:"warning",  num:3,  label:"Anomalie aperte",    sub:"2 critiche · 1 alta",     route:"anomalie" },
  { id:"ticket",   tone:"orange", icon:"ticket",   num:14, label:"Ticket attivi",      sub:"3 in scadenza oggi",      route:"ticket" },
  { id:"task",     tone:"blue",   icon:"task",     num:27, label:"Task in corso",      sub:"5 assegnate a te",        route:"task" },
  { id:"appr",     tone:"green",  icon:"check",    num:8,  label:"Approvazioni",       sub:"4 CAR · 4 automazioni",   route:"assenze" },
];

/* ── Dati operativi (mock realistici, copy italiano) ──────────────────── */
const HH_MY_TASKS = [
  { code:"T-2041", t:"Sostituzione filtro aria CRT‑09",      due:"Oggi 16:00", prio:"Alta",   tone:"danger",  route:"ticket" },
  { code:"T-2040", t:"Calibrazione bilancia BIL‑03",         due:"Domani",     prio:"Media",  tone:"warning", route:"ticket" },
  { code:"K-118",  t:"Kick‑off VRF reparto Fusione",         due:"Mer 28/05",  prio:"Media",  tone:"warning", route:"task"   },
  { code:"D-072",  t:"Firma diario preposto turno notte",    due:"Oggi",       prio:"Alta",   tone:"danger",  route:"diario" },
];

const HH_APPROVALS = [
  { code:"CAR-0231", t:"Ferie 28/05 → 02/06", who:"M. Bianchi",  cat:"Assenze",   route:"assenze" },
  { code:"CAR-0230", t:"Permesso 8h",          who:"S. Greco",    cat:"Assenze",   route:"assenze" },
  { code:"FLW-0114", t:"Acquisto filtri CRT",  who:"L. Romano",   cat:"Automazioni", route:"automazioni" },
  { code:"FIR-0042", t:"FIR rifiuti pericolosi", who:"E. Ferri",  cat:"Rentri",    route:"rentri" },
];

const HH_ANOMALIE = [
  { code:"A-1284", t:"Pressione fuori soglia — Linea 3",     area:"Stab. Nord",   time:"12 min", tone:"danger",  st:"Aperta" },
  { code:"A-1283", t:"Vibrazione anomala compressore C2",     area:"Utilities",    time:"38 min", tone:"warning", st:"In analisi" },
  { code:"A-1278", t:"Calo pressione circuito secondario",    area:"Stab. Sud",    time:"2 ore",  tone:"warning", st:"In analisi" },
];

const HH_CALENDAR = [
  { day:"Lun", n:27, tag:null,         abs:0 },
  { day:"Mar", n:28, tag:"oggi",       abs:11 },
  { day:"Mer", n:29, tag:null,         abs:8 },
  { day:"Gio", n:30, tag:null,         abs:6 },
  { day:"Ven", n:31, tag:null,         abs:9 },
  { day:"Sab", n:1,  tag:"weekend",    abs:0 },
  { day:"Dom", n:2,  tag:"weekend",    abs:0 },
];

const HH_NEWS = [
  { t:"Chiusura aziendale ponte 2 giugno",  m:"Comunicato Direzione",    time:"oggi" },
  { t:"Nuova procedura CN aggiornata",       m:"Reparto qualità",         time:"ieri" },
  { t:"Audit ISO 45001 — kick‑off",          m:"Sicurezza & ambiente",    time:"2 gg" },
];

const HH_ACTIVITY = [
  { ic:"check",     t:"Anomalia #A‑1271 risolta",          m:"M. Bianchi · Reparto fusione", time:"08:42" },
  { ic:"plus",      t:"Ticket T‑2041 creato",              m:"L. Romano · Utilities",        time:"08:14" },
  { ic:"userPlus",  t:"Nuovo onboarding: Sara Neri",       m:"HR",                            time:"ieri 17:20" },
  { ic:"refresh",   t:"Procedura CN P‑104 rev. 7",         m:"Qualità",                       time:"ieri 14:08" },
  { ic:"shield",    t:"DPI consegnati — Cantiere A",       m:"6 firme registrate",            time:"ieri 11:30" },
];

const HH_SAFETY = [
  { lbl:"TRIR",                   val:"0.42",  tone:"success" },
  { lbl:"Giorni senza infortuni", val:"312",   tone:"success" },
  { lbl:"Near miss YTD",          val:"7",     tone:"info"    },
  { lbl:"Incidenti YTD",          val:"1",     tone:"warning" },
];

const HH_SYSTEM = [
  { lbl:"ACL v2",              val:"Operativo",  tone:"success" },
  { lbl:"Microsoft Graph",     val:"OK",         tone:"success" },
  { lbl:"LDAP / AD",           val:"OK",         tone:"success" },
  { lbl:"Code automazioni",    val:"3 in coda",  tone:"warning" },
  { lbl:"Cache DB",            val:"OK",         tone:"success" },
  { lbl:"Backup notturno",     val:"02:14",     tone:"info" },
];

/* ── Helpers ──────────────────────────────────────────────────────────── */
function hhClock() {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2,"0");
  const mm = String(d.getMinutes()).padStart(2,"0");
  return `${hh}:${mm}`;
}
function hhGreeting() {
  const h = new Date().getHours();
  if (h < 12) return "Buongiorno";
  if (h < 18) return "Buon pomeriggio";
  return "Buonasera";
}
function hhDateLabel() {
  const d = new Date();
  const giorni = ["domenica","lunedì","martedì","mercoledì","giovedì","venerdì","sabato"];
  const mesi = ["gennaio","febbraio","marzo","aprile","maggio","giugno","luglio","agosto","settembre","ottobre","novembre","dicembre"];
  return `${giorni[d.getDay()]} ${d.getDate()} ${mesi[d.getMonth()]} ${d.getFullYear()}`;
}

/* ── MODULE TILE (octagonal, con KPI e stato permesso) ────────────────── */
function HHTile({ mod, locked, onClick, dense }) {
  const tone = mod.kpi?.tone || "info";
  return (
    <button className={`hht ${locked ? "hht-lock" : ""} ${dense ? "hht-dense":""}`} onClick={onClick} disabled={locked} title={locked ? `Modulo non accessibile con il tuo ruolo` : `Apri ${mod.label}`}>
      <span className="hht-ico" data-tone={tone}>{Icons[mod.icon]}</span>
      <span className="hht-body">
        <span className="hht-lbl">{mod.label}</span>
        <span className="hht-sub">{locked ? "Accesso non consentito" : mod.sub}</span>
      </span>
      {!locked && mod.kpi?.n !== null && (
        <span className={`hht-kpi tone-${tone}`}>
          <span className="hht-kpi-n">{mod.kpi.n}</span>
          {mod.kpi.unit && <span className="hht-kpi-u">{mod.kpi.unit}</span>}
        </span>
      )}
      {locked && <span className="hht-lock-ic">{Icons.lock}</span>}
      <span className="hht-corner"/>
      <style>{`
        .hht{
          position:relative; display:grid; grid-template-columns:44px 1fr auto;
          gap:12px; align-items:center;
          padding:12px 16px 12px 14px; min-height:72px;
          background:#fff; color:#0c2545; font:inherit; font-family:"Outfit",sans-serif;
          cursor:pointer; text-align:left; border:none;
          clip-path: polygon(0 0, calc(100% - 14px) 0, 100% 14px, 100% 100%, 14px 100%, 0 calc(100% - 14px));
          box-shadow: inset 0 0 0 1.5px #0c2545;
          transition:transform .12s, box-shadow .12s;
        }
        .hht-dense{ min-height:60px; padding:10px 14px 10px 12px; grid-template-columns:38px 1fr auto; gap:10px }
        .hht:hover{ transform:translateY(-1px); box-shadow:inset 0 0 0 1.5px #0c2545, 0 8px 18px rgba(0,43,92,.14) }
        .hht:active{ transform:translateY(1px) }
        .hht.hht-lock{
          background:#f4f6fb; color:#94a3b8; cursor:not-allowed;
          box-shadow: inset 0 0 0 1.5px #cfd8e3;
        }
        .hht.hht-lock:hover{ transform:none; box-shadow: inset 0 0 0 1.5px #cfd8e3 }
        .hht-corner{
          position:absolute; top:0; right:0;
          width:32px; height:14px; background:#ff6b00;
          clip-path: polygon(0 0, 100% 0, 100% 100%);
        }
        .hht.hht-lock .hht-corner{ background:#cfd8e3 }
        .hht-ico{
          width:44px; height:44px; flex:0 0 44px; border-radius:8px;
          display:flex; align-items:center; justify-content:center;
          background:#f4f6fb; color:#0c2545;
        }
        .hht-dense .hht-ico{ width:38px; height:38px; flex:0 0 38px }
        .hht-ico[data-tone="danger"]{  background:#fff5f5; color:#c53030 }
        .hht-ico[data-tone="warning"]{ background:#fff3e6; color:#c2410c }
        .hht-ico[data-tone="info"]{    background:#e8f3fb; color:#1f5fb3 }
        .hht-ico[data-tone="success"]{ background:#ecfdf3; color:#15803d }
        .hht.hht-lock .hht-ico{ background:#eef2f7; color:#94a3b8 }
        .hht-body{ display:flex; flex-direction:column; gap:1px; min-width:0 }
        .hht-lbl{ font-size:14px; font-weight:800; line-height:1.15 }
        .hht-sub{ font-size:11px; color:#6b7a90; font-weight:500 }
        .hht.hht-lock .hht-sub{ color:#a8b2c0 }
        .hht-kpi{
          display:flex; flex-direction:column; align-items:flex-end; gap:0; line-height:1;
          padding:5px 10px 6px; border-radius:8px; min-width:62px;
        }
        .hht-kpi-n{ font-family:ui-monospace,Menlo,monospace; font-size:18px; font-weight:800 }
        .hht-kpi-u{ font-family:ui-monospace,Menlo,monospace; font-size:9.5px; font-weight:700;
                    text-transform:uppercase; letter-spacing:.06em; margin-top:3px }
        .hht-kpi.tone-danger { background:#fff5f5; color:#c53030 }
        .hht-kpi.tone-warning{ background:#fff3e6; color:#c2410c }
        .hht-kpi.tone-info   { background:#e8f3fb; color:#1f5fb3 }
        .hht-kpi.tone-success{ background:#ecfdf3; color:#15803d }
        .hht-lock-ic{
          width:30px; height:30px; border-radius:8px;
          background:#eef2f7; color:#94a3b8;
          display:flex; align-items:center; justify-content:center;
        }
      `}</style>
    </button>
  );
}

/* ── PRIORITY CARD (hero stat) ────────────────────────────────────────── */
function HHPriority({ tone, icon, num, label, sub, onClick }) {
  return (
    <button className={`hhp tone-${tone}`} onClick={onClick}>
      <span className="hhp-ic">{Icons[icon]}</span>
      <span className="hhp-num">{num}</span>
      <span className="hhp-lbl">{label}</span>
      <span className="hhp-sub">{sub}</span>
      <span className="hhp-arr">{Icons.chevronR}</span>
      <style>{`
        .hhp{
          position:relative; display:grid;
          grid-template-columns:44px 1fr auto;
          grid-template-rows:auto auto;
          gap:2px 14px; padding:14px 14px 12px;
          background:#fff; border:1px solid #e7edf3;
          border-radius:12px; cursor:pointer; text-align:left;
          font:inherit; font-family:"Outfit",sans-serif;
          transition:transform .12s, box-shadow .12s, border-color .12s;
          box-shadow:0 1px 3px rgba(0,0,0,.04);
        }
        .hhp:hover{ transform:translateY(-1px); box-shadow:0 8px 22px rgba(0,43,92,.10); border-color:#cfd8e3 }
        .hhp-ic{ grid-row:1/3; grid-column:1; width:44px; height:44px; border-radius:10px;
                 display:flex; align-items:center; justify-content:center; align-self:center }
        .hhp-num{ grid-row:1; grid-column:2; font-size:30px; font-weight:800; line-height:1; color:#0c2545; letter-spacing:-.02em }
        .hhp-lbl{ grid-row:1; grid-column:3; align-self:end;
                  font-family:ui-monospace,Menlo,monospace; font-size:10px; font-weight:700;
                  text-transform:uppercase; letter-spacing:.06em; color:#0c2545 }
        .hhp-sub{ grid-row:2; grid-column:2/4; font-size:11.5px; color:#6b7a90; margin-top:2px }
        .hhp-arr{ position:absolute; top:12px; right:14px; opacity:.35 }
        .tone-red    .hhp-ic{ background:#fff5f5; color:#c53030 }
        .tone-orange .hhp-ic{ background:#fff3e6; color:#c2410c }
        .tone-blue   .hhp-ic{ background:#e8f3fb; color:#1f5fb3 }
        .tone-green  .hhp-ic{ background:#ecfdf3; color:#15803d }
      `}</style>
    </button>
  );
}

/* ── HERO ─────────────────────────────────────────────────────────────── */
function HHHero({ role, time, density, onAction }) {
  const r = HH_ROLES[role];
  return (
    <section className="hhh">
      <div className="hhh-bg"/>
      <div className="hhh-inner">
        <div className="hhh-left">
          <div className="hhh-eyebrow">
            <span className="hhh-dot"/>
            {hhDateLabel()} · {time}
          </div>
          <h1 className="hhh-title">
            {hhGreeting()}, Marco.<br/>
            <span className="hhh-sub">Hai 5 attività in scadenza oggi e 8 richieste in approvazione.</span>
          </h1>
          <div className="hhh-meta">
            <span className="hhh-pill">
              <span className="hhh-pill-code">{r.code}</span>
              <span>{r.label}</span>
            </span>
            <span className="hhh-pill ghost">
              <span className="hhh-pill-dot"/>Sessione attiva
            </span>
            <span className="hhh-pill ghost">Stab. Nord · Reparto utilities</span>
          </div>
        </div>
        <div className="hhh-right">
          <button className="hhh-cta" onClick={() => onAction?.("ticket")}>
            <span>{Icons.plus}</span>Nuovo ticket
          </button>
          <button className="hhh-cta ghost" onClick={() => onAction?.("anomalie")}>
            <span>{Icons.warning}</span>Segnala anomalia
          </button>
          <button className="hhh-cta ghost" onClick={() => onAction?.("assenze")}>
            <span>{Icons.calendar}</span>Richiedi permesso
          </button>
        </div>
      </div>
      <style>{`
        .hhh{
          position:relative; overflow:hidden; color:#fff;
          background:
            radial-gradient(circle at 85% -10%, rgba(255,107,0,.30), transparent 38%),
            radial-gradient(circle at 0% 100%, rgba(31,135,205,.30), transparent 50%),
            linear-gradient(135deg,#001b3a 0%,#002b5c 50%,#0a3266 100%);
          padding:24px 26px 22px; margin-bottom:14px;
          border-radius:14px;
          clip-path: polygon(0 0, calc(100% - 22px) 0, 100% 22px, 100% 100%, 22px 100%, 0 calc(100% - 22px));
        }
        .hhh-bg{
          position:absolute; inset:0; opacity:.45; pointer-events:none;
          background-image: radial-gradient(rgba(255,255,255,.08) 1px, transparent 1.4px);
          background-size: 18px 18px;
          mask-image: linear-gradient(135deg, transparent, rgba(0,0,0,.7));
        }
        .hhh-inner{ position:relative; display:flex; align-items:flex-start;
                    justify-content:space-between; gap:22px; flex-wrap:wrap }
        .hhh-eyebrow{
          display:inline-flex; align-items:center; gap:8px;
          font-family:ui-monospace,Menlo,monospace; font-size:11px; font-weight:700;
          letter-spacing:.14em; text-transform:uppercase;
          color:#ff8a1f; margin-bottom:6px;
        }
        .hhh-dot{ width:7px; height:7px; border-radius:50%; background:#ff8a1f;
                  box-shadow:0 0 0 4px rgba(255,138,31,.18); display:inline-block }
        .hhh-title{ margin:0; font-size:30px; font-weight:800; line-height:1.1; letter-spacing:-.01em }
        .hhh-sub{ display:block; margin-top:4px; font-size:14px; font-weight:500; color:rgba(255,255,255,.78); line-height:1.45 }
        .hhh-meta{ display:flex; gap:8px; flex-wrap:wrap; margin-top:14px }
        .hhh-pill{
          display:inline-flex; align-items:center; gap:8px;
          padding:5px 10px 5px 5px; border-radius:999px;
          background:rgba(255,255,255,.10); border:1px solid rgba(255,255,255,.16);
          font-size:11.5px; font-weight:600;
        }
        .hhh-pill.ghost{ padding:5px 12px; background:transparent }
        .hhh-pill-code{
          display:inline-flex; align-items:center; justify-content:center;
          min-width:32px; height:22px; padding:0 6px; border-radius:999px;
          background:#ff6b00; color:#fff; font-family:ui-monospace,Menlo,monospace;
          font-size:10px; font-weight:800; letter-spacing:.04em;
        }
        .hhh-pill-dot{ width:6px; height:6px; border-radius:50%; background:#16a34a;
                       box-shadow:0 0 0 3px rgba(22,163,74,.25) }
        .hhh-right{ display:flex; flex-direction:column; gap:8px; min-width:220px }
        .hhh-cta{
          display:inline-flex; align-items:center; gap:10px;
          padding:10px 14px; border-radius:10px; border:none;
          background:#ff6b00; color:#fff; font:inherit; font-weight:700; font-size:13px;
          cursor:pointer; transition:filter .15s, box-shadow .15s, transform .1s;
          box-shadow:0 6px 16px rgba(255,107,0,.30);
          white-space:nowrap;
        }
        .hhh-cta:hover{ filter:brightness(1.05) }
        .hhh-cta:active{ transform:translateY(1px) }
        .hhh-cta.ghost{
          background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.18);
          box-shadow:none; color:#fff;
        }
        .hhh-cta.ghost:hover{ background:rgba(255,255,255,.14) }
        .hhh-cta span{ display:inline-flex }
        @media (max-width:1100px){
          .hhh-title{ font-size:24px }
          .hhh-right{ width:100% }
          .hhh-right .hhh-cta{ flex:1 }
        }
      `}</style>
    </section>
  );
}

/* ── MODULE HUB grid ───────────────────────────────────────────────────── */
function HHModuleHub({ role, density, showLocked, onOpen }) {
  const visible = HH_MODULES.filter(m => showLocked || m.perm.includes(role));
  const groups = HH_CATEGORIES.map(c => ({
    ...c, mods: visible.filter(m => m.cat === c.key)
  })).filter(g => g.mods.length);

  return (
    <section className="hhm">
      <div className="hhm-head">
        <div>
          <h2 className="hhm-t">Moduli del portale</h2>
          <p className="hhm-s">Tutti i moduli del NOVICROM HUB con stato live. Clic per aprire.</p>
        </div>
        <div className="hhm-legend">
          <span><span className="hhm-leg hhm-leg-on"/>Accessibili</span>
          <span><span className="hhm-leg hhm-leg-lock"/>Non consentiti dal ruolo</span>
        </div>
      </div>

      {groups.map(g => (
        <div key={g.key} className="hhm-grp">
          <div className="hhm-grp-h">
            <span className="hhm-grp-l">{g.label}</span>
            <span className="hhm-grp-c">{g.mods.filter(m => m.perm.includes(role)).length}/{g.mods.length} accessibili</span>
            <span className="hhm-grp-rule"/>
            <span className="hhm-grp-hint">{g.hint}</span>
          </div>
          <div className={`hhm-grid ${density === "dense" ? "dense":""}`}>
            {g.mods.map(m => (
              <HHTile key={m.id}
                mod={m}
                dense={density === "dense"}
                locked={!m.perm.includes(role)}
                onClick={() => onOpen?.(m.id)}/>
            ))}
          </div>
        </div>
      ))}

      <style>{`
        .hhm{ margin-bottom:14px }
        .hhm-head{ display:flex; align-items:flex-end; justify-content:space-between;
                   gap:18px; margin-bottom:10px; flex-wrap:wrap }
        .hhm-t{ margin:0; font-size:18px; font-weight:800; color:#0c2545; letter-spacing:-.005em }
        .hhm-s{ margin:2px 0 0; font-size:12.5px; color:#6b7a90 }
        .hhm-legend{ display:flex; gap:14px; font-size:11px; color:#6b7a90; font-weight:600 }
        .hhm-legend span{ display:inline-flex; align-items:center; gap:6px }
        .hhm-leg{ width:10px; height:10px; border-radius:3px; display:inline-block }
        .hhm-leg-on{ background:#fff; box-shadow: inset 0 0 0 1.5px #0c2545; position:relative }
        .hhm-leg-on::after{ content:""; position:absolute; right:-2px; top:-2px;
                            width:6px; height:6px; background:#ff6b00; border-radius:1px }
        .hhm-leg-lock{ background:#f4f6fb; box-shadow:inset 0 0 0 1.5px #cfd8e3 }

        .hhm-grp{ margin-top:14px }
        .hhm-grp:first-of-type{ margin-top:8px }
        .hhm-grp-h{ display:flex; align-items:center; gap:10px; margin:0 0 8px;
                    font-family:ui-monospace,Menlo,monospace; font-size:10.5px; font-weight:700;
                    letter-spacing:.10em; text-transform:uppercase; color:#94a3b8 }
        .hhm-grp-l{ color:#0c2545 }
        .hhm-grp-c{ color:#1f5fb3 }
        .hhm-grp-rule{ flex:1; height:1px; background:#e1e8f0 }
        .hhm-grp-hint{ color:#94a3b8; font-weight:500 }
        .hhm-grid{ display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:10px }
        .hhm-grid.dense{ grid-template-columns:repeat(4, minmax(0,1fr)); gap:8px }
        @media (max-width:1100px){
          .hhm-grid, .hhm-grid.dense{ grid-template-columns:repeat(2, minmax(0,1fr)) }
        }
      `}</style>
    </section>
  );
}

/* ── PANELS ───────────────────────────────────────────────────────────── */
function HHPanelHead({ title, hint, action }) {
  return (
    <div className="hhpan-h">
      <div>
        <h3 className="hhpan-t">{title}</h3>
        {hint && <p className="hhpan-s">{hint}</p>}
      </div>
      {action}
      <style>{`
        .hhpan-h{ display:flex; align-items:flex-start; justify-content:space-between;
                  gap:12px; padding:12px 14px; border-bottom:1px solid #eef2f7 }
        .hhpan-t{ margin:0; font-size:13.5px; font-weight:800; color:#0c2545 }
        .hhpan-s{ margin:1px 0 0; font-size:11px; color:#94a3b8 }
      `}</style>
    </div>
  );
}

function HHList({ children }) {
  return (
    <ul className="hhlst">{children}
      <style>{`
        .hhlst{ list-style:none; margin:0; padding:0 }
        .hhlst li{ border-top:1px solid #f0f3f7 }
        .hhlst li:first-child{ border-top:none }
        .hhlst button{
          display:grid; grid-template-columns:auto 1fr auto; gap:12px; align-items:center;
          width:100%; padding:10px 14px; background:#fff; border:none; cursor:pointer;
          font:inherit; font-family:"Outfit",sans-serif; text-align:left; transition:background .12s;
        }
        .hhlst button:hover{ background:#fafbfd }
        .hhlst .lc{ font-family:ui-monospace,Menlo,monospace; font-size:11px; font-weight:700;
                    color:#94a3b8; padding:3px 6px; border-radius:4px; background:#f4f6fb }
        .hhlst .lt{ font-size:12.5px; font-weight:700; color:#0c2545; overflow:hidden;
                    text-overflow:ellipsis; white-space:nowrap }
        .hhlst .lm{ font-size:11px; color:#94a3b8 }
        .hhlst .lh{ display:flex; gap:8px; align-items:baseline }
      `}</style>
    </ul>
  );
}

function HHMyTasks({ onOpen }) {
  return (
    <Card padded={false}>
      <HHPanelHead title="Le mie attività" hint="Ticket, task e firme assegnate a Marco Rossi"
        action={<button className="hhlink" onClick={() => onOpen("ticket")}>Tutte →</button>}/>
      <HHList>
        {HH_MY_TASKS.map(x => (
          <li key={x.code}>
            <button onClick={() => onOpen(x.route)}>
              <span className="lc">{x.code}</span>
              <span>
                <span className="lh"><span className="lt">{x.t}</span></span>
                <span className="lm">scadenza {x.due}</span>
              </span>
              <Badge tone={x.tone}>{x.prio}</Badge>
            </button>
          </li>
        ))}
      </HHList>
      <style>{`
        .hhlink{ background:none; border:none; color:#1f5fb3; font:inherit; font-size:11.5px;
                 font-weight:700; cursor:pointer }
        .hhlink:hover{ text-decoration:underline }
      `}</style>
    </Card>
  );
}

function HHApprovals({ onOpen }) {
  return (
    <Card padded={false}>
      <HHPanelHead title="Da approvare" hint="Richieste, automazioni, FIR rifiuti"
        action={<span className="hhcnt">{HH_APPROVALS.length}</span>}/>
      <ul className="hhapr">
        {HH_APPROVALS.map(a => (
          <li key={a.code}>
            <button className="hhapr-row" onClick={() => onOpen(a.route)}>
              <span className="lc">{a.code}</span>
              <span className="hhapr-body">
                <span className="lt">{a.t}</span>
                <span className="lm">{a.who} · {a.cat}</span>
              </span>
            </button>
            <span className="hhok">
              <button className="hhok-y" title="Approva" onClick={(e) => e.stopPropagation()}>{Icons.check}</button>
              <button className="hhok-n" title="Rifiuta" onClick={(e) => e.stopPropagation()}>{Icons.x}</button>
            </span>
          </li>
        ))}
      </ul>
      <style>{`
        .hhapr{ list-style:none; margin:0; padding:0 }
        .hhapr li{ display:grid; grid-template-columns:1fr auto; align-items:center;
                   gap:8px; padding:0 12px 0 0; border-top:1px solid #f0f3f7; background:#fff;
                   transition:background .12s }
        .hhapr li:first-child{ border-top:none }
        .hhapr li:hover{ background:#fafbfd }
        .hhapr-row{
          display:grid; grid-template-columns:auto 1fr; gap:12px; align-items:center;
          padding:10px 14px; background:transparent; border:none; cursor:pointer;
          font:inherit; font-family:"Outfit",sans-serif; text-align:left;
        }
        .hhapr-body{ display:flex; flex-direction:column; gap:1px; min-width:0 }
        .hhcnt{ display:inline-flex; align-items:center; justify-content:center;
                min-width:22px; height:22px; padding:0 8px; border-radius:999px;
                background:#fff3e6; color:#c2410c; font-family:ui-monospace,Menlo,monospace;
                font-size:11px; font-weight:800 }
        .hhok{ display:flex; gap:4px }
        .hhok-y, .hhok-n{ width:28px; height:28px; border-radius:6px; border:none; cursor:pointer;
                          display:flex; align-items:center; justify-content:center }
        .hhok-y{ background:#ecfdf3; color:#15803d }
        .hhok-y:hover{ background:#d1fae5 }
        .hhok-n{ background:#fff5f5; color:#c53030 }
        .hhok-n:hover{ background:#fecaca }
      `}</style>
    </Card>
  );
}

function HHAnomalie({ onOpen }) {
  return (
    <Card padded={false}>
      <HHPanelHead title="Anomalie aperte" hint="Eventi rilevati su linee e impianti"
        action={<button className="hhlink" onClick={() => onOpen("anomalie")}>Apri modulo →</button>}/>
      <HHList>
        {HH_ANOMALIE.map(a => (
          <li key={a.code}>
            <button onClick={() => onOpen("anomalie")}>
              <span className={`hhdot dot-${a.tone}`}/>
              <span>
                <span className="lh"><span className="lc">{a.code}</span><span className="lt">{a.t}</span></span>
                <span className="lm">{a.area} · {a.time} fa</span>
              </span>
              <Badge tone={a.tone}>{a.st}</Badge>
            </button>
          </li>
        ))}
      </HHList>
      <style>{`
        .hhdot{ width:8px; height:32px; border-radius:4px; background:#cbd5e0 }
        .dot-danger{ background:#dc2626 }
        .dot-warning{ background:#f59e0b }
        .dot-info{ background:#1f5fb3 }
        .dot-success{ background:#16a34a }
      `}</style>
    </Card>
  );
}

function HHCalendar({ onOpen }) {
  return (
    <Card padded={false}>
      <HHPanelHead title="Presenze settimana" hint="Assenze pianificate · clic per dettaglio"
        action={<button className="hhlink" onClick={() => onOpen("assenze")}>Calendario completo →</button>}/>
      <div className="hhcal">
        {HH_CALENDAR.map(d => (
          <button key={d.day+d.n} className={`hhcal-c ${d.tag === "oggi" ? "now":""} ${d.tag === "weekend" ? "we":""}`}
            onClick={() => onOpen("assenze")}>
            <span className="hhcal-d">{d.day}</span>
            <span className="hhcal-n">{d.n}</span>
            {d.tag === "oggi" && <span className="hhcal-tag">oggi</span>}
            {d.abs > 0 && <span className="hhcal-abs">{d.abs}</span>}
          </button>
        ))}
      </div>
      <style>{`
        .hhcal{ display:grid; grid-template-columns:repeat(7, 1fr); gap:6px; padding:12px 14px }
        .hhcal-c{
          position:relative; display:flex; flex-direction:column; align-items:center; gap:4px;
          padding:8px 4px 10px; background:#fff; border:1px solid #e7edf3; border-radius:8px;
          cursor:pointer; font:inherit; font-family:"Outfit",sans-serif;
          transition:background .12s, border-color .12s;
        }
        .hhcal-c:hover{ background:#fafbfd; border-color:#cfd8e3 }
        .hhcal-c.we{ background:#fafbfd }
        .hhcal-c.now{ background:#fff3e6; border-color:#ff6b00 }
        .hhcal-d{ font-family:ui-monospace,Menlo,monospace; font-size:9.5px; font-weight:800;
                  letter-spacing:.06em; text-transform:uppercase; color:#94a3b8 }
        .hhcal-c.now .hhcal-d{ color:#c2410c }
        .hhcal-n{ font-size:18px; font-weight:800; color:#0c2545; line-height:1 }
        .hhcal-c.now .hhcal-n{ color:#c2410c }
        .hhcal-tag{ font-family:ui-monospace,Menlo,monospace; font-size:8.5px; font-weight:800;
                    letter-spacing:.06em; text-transform:uppercase; color:#c2410c; margin-top:1px }
        .hhcal-abs{ position:absolute; top:4px; right:5px; min-width:18px; height:18px; padding:0 5px;
                    border-radius:999px; background:#fff5f5; color:#c53030;
                    display:inline-flex; align-items:center; justify-content:center;
                    font-family:ui-monospace,Menlo,monospace; font-size:10px; font-weight:800 }
      `}</style>
    </Card>
  );
}

function HHNewsActivity({ onOpen }) {
  return (
    <Card padded={false}>
      <HHPanelHead title="Comunicazioni e attività" hint="News aziendali e ultime azioni nel portale"
        action={<button className="hhlink" onClick={() => onOpen("notizie")}>News →</button>}/>
      <div className="hhna">
        <div className="hhna-col">
          <div className="hhna-lbl">News</div>
          <ul className="hhna-news">
            {HH_NEWS.map(n => (
              <li key={n.t}><button onClick={() => onOpen("notizie")}>
                <span className="hhna-mark"/>
                <span>
                  <span className="hhna-t">{n.t}</span>
                  <span className="hhna-m">{n.m}</span>
                </span>
                <span className="hhna-time">{n.time}</span>
              </button></li>
            ))}
          </ul>
        </div>
        <div className="hhna-col">
          <div className="hhna-lbl">Attività recenti</div>
          <ul className="hhna-act">
            {HH_ACTIVITY.map(a => (
              <li key={a.t}>
                <span className="hhna-ic">{Icons[a.ic]}</span>
                <span>
                  <span className="hhna-t">{a.t}</span>
                  <span className="hhna-m">{a.m}</span>
                </span>
                <span className="hhna-time">{a.time}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <style>{`
        .hhna{ display:grid; grid-template-columns:1fr; }
        .hhna-col{ padding:10px 14px; border-top:1px solid #f0f3f7 }
        .hhna-col:first-child{ border-top:none }
        .hhna-lbl{ font-family:ui-monospace,Menlo,monospace; font-size:10px; font-weight:800;
                   letter-spacing:.08em; text-transform:uppercase; color:#94a3b8; margin:2px 0 8px }
        .hhna-news, .hhna-act{ list-style:none; margin:0; padding:0;
                               display:flex; flex-direction:column; gap:0 }
        .hhna-news li{ border-top:1px solid #f0f3f7 }
        .hhna-news li:first-child{ border-top:none }
        .hhna-news button{
          display:grid; grid-template-columns:6px 1fr auto; gap:10px; align-items:center;
          width:100%; padding:8px 0; background:transparent; border:none; cursor:pointer;
          font:inherit; font-family:"Outfit",sans-serif; text-align:left;
        }
        .hhna-news button:hover .hhna-t{ color:#1f5fb3 }
        .hhna-mark{ width:6px; height:24px; border-radius:3px; background:#ff6b00 }
        .hhna-t{ display:block; font-size:12.5px; font-weight:700; color:#0c2545; line-height:1.25 }
        .hhna-m{ display:block; font-size:10.5px; color:#94a3b8; margin-top:1px }
        .hhna-time{ font-family:ui-monospace,Menlo,monospace; font-size:10px; font-weight:700;
                    color:#94a3b8; text-transform:uppercase; letter-spacing:.04em }
        .hhna-act li{ display:grid; grid-template-columns:24px 1fr auto; gap:10px; align-items:center;
                      padding:8px 0; border-top:1px solid #f0f3f7 }
        .hhna-act li:first-child{ border-top:none }
        .hhna-ic{ width:24px; height:24px; border-radius:6px; background:#e8f3fb; color:#1f5fb3;
                  display:flex; align-items:center; justify-content:center }
        @media (max-width:1100px){
          .hhna-col{ border-top:1px solid #f0f3f7 }
          .hhna-col:first-child{ border-top:none }
        }
      `}</style>
    </Card>
  );
}

function HHSafety() {
  return (
    <Card padded={false}>
      <HHPanelHead title="KPI sicurezza" hint="Anno in corso · aggiornato in tempo reale"/>
      <div className="hhsaf">
        {HH_SAFETY.map(m => (
          <div key={m.lbl} className={`hhsaf-c tone-${m.tone}`}>
            <span className="hhsaf-v">{m.val}</span>
            <span className="hhsaf-l">{m.lbl}</span>
          </div>
        ))}
      </div>
      <style>{`
        .hhsaf{ display:grid; grid-template-columns:repeat(2, 1fr); gap:1px; background:#eef2f7; padding:1px }
        .hhsaf-c{ background:#fff; padding:11px 14px;
                  display:flex; flex-direction:column; gap:2px; min-height:60px; justify-content:center }
        .hhsaf-v{ font-size:22px; font-weight:800; line-height:1; color:#0c2545; letter-spacing:-.01em }
        .hhsaf-l{ font-family:ui-monospace,Menlo,monospace; font-size:9.5px; font-weight:700;
                  letter-spacing:.06em; text-transform:uppercase; color:#94a3b8 }
        .hhsaf-c.tone-success .hhsaf-v{ color:#15803d }
        .hhsaf-c.tone-warning .hhsaf-v{ color:#c2410c }
        .hhsaf-c.tone-danger  .hhsaf-v{ color:#c53030 }
      `}</style>
    </Card>
  );
}

function HHSystem() {
  return (
    <Card padded={false}>
      <HHPanelHead title="Stato sistema" hint="Servizi integrati e job"/>
      <ul className="hhsys">
        {HH_SYSTEM.map(s => (
          <li key={s.lbl}>
            <span className={`hhsys-d tone-${s.tone}`}/>
            <span className="hhsys-l">{s.lbl}</span>
            <span className={`hhsys-v tone-${s.tone}`}>{s.val}</span>
          </li>
        ))}
      </ul>
      <style>{`
        .hhsys{ list-style:none; margin:0; padding:6px 0 }
        .hhsys li{ display:grid; grid-template-columns:14px 1fr auto; gap:10px; align-items:center;
                   padding:7px 14px; }
        .hhsys-d{ width:8px; height:8px; border-radius:50%; background:#cbd5e0 }
        .hhsys-d.tone-success{ background:#16a34a; box-shadow:0 0 0 3px rgba(22,163,74,.18) }
        .hhsys-d.tone-warning{ background:#f59e0b; box-shadow:0 0 0 3px rgba(245,158,11,.18) }
        .hhsys-d.tone-info   { background:#1f5fb3; box-shadow:0 0 0 3px rgba(31,95,179,.18) }
        .hhsys-l{ font-size:12px; color:#0c2545; font-weight:600 }
        .hhsys-v{ font-family:ui-monospace,Menlo,monospace; font-size:11px; font-weight:700; color:#6b7a90 }
        .hhsys-v.tone-success{ color:#15803d }
        .hhsys-v.tone-warning{ color:#c2410c }
      `}</style>
    </Card>
  );
}

/* ── ROOT — HOME HUB ──────────────────────────────────────────────────── */
function HomeHubScreen({ onNav }) {
  const tweakDefaults = /*EDITMODE-BEGIN*/{
    "role": "capo",
    "density": "comfortable",
    "showLocked": true,
    "showSafety": true,
    "showSystem": true
  }/*EDITMODE-END*/;

  const [tw, setTw] = useHH(tweakDefaults);
  const [time, setTime] = useHH(hhClock());

  useHE(() => {
    const t = setInterval(() => setTime(hhClock()), 30_000);
    return () => clearInterval(t);
  }, []);

  /* Tweaks panel wiring */
  useHE(() => {
    if (typeof window === "undefined") return;
    const onMsg = (e) => {
      const d = e.data || {};
      if (d.type === "__activate_edit_mode") setShowTweaks(true);
      if (d.type === "__deactivate_edit_mode") setShowTweaks(false);
    };
    window.addEventListener("message", onMsg);
    window.parent?.postMessage({ type: "__edit_mode_available" }, "*");
    return () => window.removeEventListener("message", onMsg);
  }, []);
  const [showTweaks, setShowTweaks] = useHH(false);

  const setTweak = (k, v) => {
    const next = typeof k === "object" ? { ...tw, ...k } : { ...tw, [k]: v };
    setTw(next);
    window.parent?.postMessage({ type: "__edit_mode_set_keys",
      edits: typeof k === "object" ? k : { [k]: v }}, "*");
  };

  const role = tw.role || "capo";

  return (
    <div className="hh-root" data-screen-label="01 Home portale">
      <HHHero role={role} time={time} density={tw.density}
        onAction={(id) => onNav?.(id)}/>

      <section className="hh-prio">
        {HH_PRIORITY.map(p => (
          <HHPriority key={p.id} {...p} onClick={() => onNav?.(p.route)}/>
        ))}
      </section>

      <HHModuleHub
        role={role}
        density={tw.density === "dense" ? "dense" : "comfortable"}
        showLocked={tw.showLocked}
        onOpen={(id) => onNav?.(id)}/>

      <section className="hh-board">
        <div className="hh-col-l">
          <HHMyTasks onOpen={onNav}/>
          <HHAnomalie onOpen={onNav}/>
          <HHCalendar onOpen={onNav}/>
        </div>
        <div className="hh-col-r">
          <HHApprovals onOpen={onNav}/>
          <HHNewsActivity onOpen={onNav}/>
        </div>
      </section>

      {(tw.showSafety || tw.showSystem) && (
        <section className="hh-bottom">
          {tw.showSafety && <HHSafety/>}
          {tw.showSystem && <HHSystem/>}
        </section>
      )}

      <footer className="hh-foot">
        <span>NOVICROM HUB · v 1.0.2 · {HH_MODULES.length} moduli registrati</span>
        <span className="hh-foot-r">
          ACL v2 attivo · Microsoft Graph OK · LDAP/AD OK
        </span>
      </footer>

      {/* Tweaks */}
      {showTweaks && (
        <HHTweaks
          tw={tw}
          setTweak={setTweak}
          onClose={() => {
            setShowTweaks(false);
            window.parent?.postMessage({ type: "__edit_mode_dismissed" }, "*");
          }}/>
      )}

      <style>{`
        .hh-root{ display:block; max-width:1280px; margin:0 auto }
        .hh-prio{ display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:10px; margin-bottom:14px }
        .hh-board{ display:grid; grid-template-columns:1.45fr .85fr; gap:12px; margin-bottom:14px }
        .hh-col-l, .hh-col-r{ display:flex; flex-direction:column; gap:12px; min-width:0 }
        .hh-bottom{ display:grid; grid-template-columns:1.1fr .9fr; gap:12px; margin-bottom:14px }
        .hh-foot{ display:flex; align-items:center; justify-content:space-between;
                  gap:12px; padding:14px 4px 6px;
                  font-family:ui-monospace,Menlo,monospace; font-size:10.5px; font-weight:600;
                  color:#94a3b8; border-top:1px dashed #e1e8f0 }
        .hh-foot-r{ color:#6b7a90 }
        @media (max-width:1100px){
          .hh-prio{ grid-template-columns:repeat(2, 1fr) }
          .hh-board{ grid-template-columns:1fr }
          .hh-bottom{ grid-template-columns:1fr }
        }
      `}</style>
    </div>
  );
}

/* ── Tweaks panel ─────────────────────────────────────────────────────── */
function HHTweaks({ tw, setTweak, onClose }) {
  const roleOptions = Object.entries(HH_ROLES);
  return (
    <div className="twk-pan">
      <div className="twk-h">
        <span>Tweaks</span>
        <button onClick={onClose} className="twk-x" aria-label="Chiudi">×</button>
      </div>

      <div className="twk-sec">
        <div className="twk-lbl">Ruolo attivo</div>
        <div className="twk-roles">
          {roleOptions.map(([k, r]) => (
            <button key={k}
              className={`twk-r ${tw.role===k?"on":""}`}
              onClick={() => setTweak("role", k)}>
              <span className="twk-r-code">{r.code}</span>
              <span className="twk-r-meta">
                <span className="twk-r-lbl">{r.label}</span>
                <span className="twk-r-hint">{r.hint}</span>
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="twk-sec">
        <div className="twk-lbl">Densità griglia moduli</div>
        <div className="twk-seg">
          {[["comfortable","Comoda"],["dense","Densa"]].map(([k,l]) => (
            <button key={k} className={tw.density===k?"on":""} onClick={() => setTweak("density", k)}>{l}</button>
          ))}
        </div>
      </div>

      <div className="twk-sec">
        <label className="twk-tg">
          <input type="checkbox" checked={tw.showLocked}
                 onChange={e => setTweak("showLocked", e.target.checked)}/>
          <span>Mostra moduli non accessibili (locked)</span>
        </label>
        <label className="twk-tg">
          <input type="checkbox" checked={tw.showSafety}
                 onChange={e => setTweak("showSafety", e.target.checked)}/>
          <span>KPI sicurezza in fondo</span>
        </label>
        <label className="twk-tg">
          <input type="checkbox" checked={tw.showSystem}
                 onChange={e => setTweak("showSystem", e.target.checked)}/>
          <span>Stato sistema in fondo</span>
        </label>
      </div>

      <style>{`
        .twk-pan{
          position:fixed; right:18px; bottom:18px; z-index:9999; width:280px;
          background:#0c2545; color:#fff; border-radius:12px;
          box-shadow:0 20px 50px rgba(8,20,45,.45);
          font-family:"Outfit",sans-serif; font-size:12px;
          overflow:hidden;
        }
        .twk-h{ display:flex; align-items:center; justify-content:space-between;
                padding:10px 14px; background:rgba(255,255,255,.06);
                font-weight:800; font-size:13px; letter-spacing:.04em; text-transform:uppercase;
                border-bottom:1px solid rgba(255,255,255,.10) }
        .twk-x{ background:transparent; border:none; color:#fff; font-size:18px;
                width:24px; height:24px; cursor:pointer; line-height:1; opacity:.7 }
        .twk-x:hover{ opacity:1 }
        .twk-sec{ padding:12px 14px; border-bottom:1px solid rgba(255,255,255,.08) }
        .twk-sec:last-child{ border-bottom:none }
        .twk-lbl{ font-family:ui-monospace,Menlo,monospace; font-size:10px; font-weight:700;
                  letter-spacing:.10em; text-transform:uppercase; color:rgba(255,255,255,.55);
                  margin-bottom:8px }
        .twk-roles{ display:flex; flex-direction:column; gap:4px }
        .twk-r{
          display:grid; grid-template-columns:34px 1fr; gap:10px; align-items:center;
          padding:7px 8px; border-radius:8px; cursor:pointer; font:inherit;
          background:transparent; border:1px solid rgba(255,255,255,.08); color:#fff; text-align:left;
        }
        .twk-r:hover{ background:rgba(255,255,255,.06) }
        .twk-r.on{ background:rgba(255,107,0,.18); border-color:#ff6b00 }
        .twk-r-code{ display:inline-flex; align-items:center; justify-content:center;
                     width:30px; height:24px; border-radius:6px;
                     background:rgba(255,255,255,.10); color:#fff;
                     font-family:ui-monospace,Menlo,monospace; font-size:10.5px; font-weight:800;
                     letter-spacing:.04em }
        .twk-r.on .twk-r-code{ background:#ff6b00 }
        .twk-r-meta{ display:flex; flex-direction:column; gap:1px; min-width:0 }
        .twk-r-lbl{ font-size:12px; font-weight:700 }
        .twk-r-hint{ font-size:10.5px; color:rgba(255,255,255,.55) }

        .twk-seg{ display:flex; background:rgba(255,255,255,.06); border-radius:8px; padding:3px; gap:3px }
        .twk-seg button{
          flex:1; background:transparent; border:none; color:rgba(255,255,255,.7);
          font:inherit; font-weight:700; font-size:12px; padding:6px 8px; border-radius:6px; cursor:pointer;
        }
        .twk-seg button.on{ background:#ff6b00; color:#fff }

        .twk-tg{ display:flex; align-items:center; gap:8px; padding:5px 0; color:rgba(255,255,255,.85);
                 font-size:12px; cursor:pointer }
        .twk-tg input{ accent-color:#ff6b00 }
      `}</style>
    </div>
  );
}

Object.assign(window, { HomeHubScreen });
