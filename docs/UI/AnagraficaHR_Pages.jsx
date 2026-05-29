/* global React, Icons, Card, Button, Badge */
/* ──────────────────────────────────────────────────────────
   ANAGRAFICA HR — pagine secondarie e dati condivisi
   Adattamento brand‑correct del prototipo "anagrafica_hr_dashboard_novicrom.jsx".
   Tutto in linea con i token Novicrom HUB:
   - Navy #0c2545, Cyan #1f87cd, Orange #ff8a1f, Grey #6b7a90
   - Outfit body, mono per codici / eyebrow
   - Raggi 6–12px (mai rounded‑2xl)
   - Eyebrow mono UPPERCASE, ribbon laterale arancio per accenti
   ────────────────────────────────────────────────────────── */
const { useState: useStateHRP, useMemo: useMemoHRP } = React;

/* ====== DATI ====== */
const HRP_PEOPLE = [
  { id:1, code:"DIP-1024", name:"Marco Rossi",     dept:"Produzione",      role:"Saldatore",         status:"Attivo",     risk:"Doc. in scadenza", riskTone:"warning", score:82, contract:"T. Indeterminato", manager:"L. Verdi",     site:"Officina"  },
  { id:2, code:"DIP-1031", name:"Giulia Bianchi",  dept:"Amministrazione", role:"Impiegata",         status:"Attivo",     risk:"OK",               riskTone:"success", score:96, contract:"T. Indeterminato", manager:"Direzione",    site:"Sede"      },
  { id:3, code:"DIP-1042", name:"Luca Verdi",      dept:"Cantiere",        role:"Preposto",          status:"Attivo",     risk:"Formazione",       riskTone:"warning", score:74, contract:"T. Indeterminato", manager:"Dir. Tecnica", site:"Cantieri"  },
  { id:4, code:"DIP-1058", name:"Sara Neri",       dept:"HR",              role:"HR Specialist",     status:"Onboarding", risk:"Contratto firma",  riskTone:"danger",  score:68, contract:"Nuova assunzione", manager:"Direzione",    site:"Sede"      },
  { id:5, code:"DIP-1063", name:"Francesco Conti", dept:"Magazzino",       role:"Addetto logistica", status:"Attivo",     risk:"DPI da firmare",   riskTone:"warning", score:79, contract:"T. Determinato",   manager:"M. Rossi",     site:"Magazzino" },
];

const HRP_ABSENCES = [
  { id:1, person:"Marco Rossi",     type:"Ferie",    period:"22/05 → 24/05",    status:"In approvazione", tone:"warning", days:"3 g" },
  { id:2, person:"Giulia Bianchi",  type:"Permesso", period:"23/05 · mattina",  status:"Approvata",       tone:"success", days:"4 h" },
  { id:3, person:"Luca Verdi",      type:"Malattia", period:"20/05 → 21/05",    status:"Registrata",      tone:"info",    days:"2 g" },
  { id:4, person:"Francesco Conti", type:"ROL",      period:"27/05 · pomeriggio", status:"Da validare",   tone:"warning", days:"4 h" },
  { id:5, person:"Marco Rossi",     type:"Ferie",    period:"03/06 → 07/06",    status:"Pianificata",     tone:"info",    days:"5 g" },
];

const HRP_TRAINING = [
  { course:"Sicurezza generale lavoratori", audience:"Tutti",                  coverage:94, missing:8,  due:"30 gg", mandatory:true,  owner:"HR / RSPP", risk:"Basso", hours:4,  format:"E-learning + test" },
  { course:"Preposto",                      audience:"Capi reparto / cantiere",coverage:71, missing:4,  due:"15 gg", mandatory:true,  owner:"RSPP",      risk:"Alto",  hours:8,  format:"Aula" },
  { course:"Antincendio",                   audience:"Squadra emergenza",      coverage:88, missing:2,  due:"60 gg", mandatory:true,  owner:"HSE",       risk:"Medio", hours:8,  format:"Aula + prova pratica" },
  { course:"Carrelli elevatori",            audience:"Magazzino",              coverage:76, missing:3,  due:"45 gg", mandatory:true,  owner:"Logistica", risk:"Medio", hours:12, format:"Aula + pratica" },
  { course:"Privacy e trattamento dati HR", audience:"HR / Amministrazione",   coverage:67, missing:5,  due:"20 gg", mandatory:true,  owner:"IT / HR",   risk:"Alto",  hours:2,  format:"E-learning" },
  { course:"Qualità e non conformità",      audience:"Produzione / Cantiere",  coverage:58, missing:11, due:"90 gg", mandatory:false, owner:"Qualità",   risk:"Medio", hours:3,  format:"Workshop" },
];

const HRP_DOCUMENTS = [
  { id:1,  title:"Carta identità",                    owner:"Marco Rossi",          ownerType:"Lavoratore", cat:"Personali",   area:"Anagrafica",            status:"In scadenza",     tone:"danger",  expiry:"12/06/2026" },
  { id:2,  title:"Codice fiscale / tessera sanitaria", owner:"Giulia Bianchi",      ownerType:"Lavoratore", cat:"Personali",   area:"Anagrafica",            status:"Valido",          tone:"success", expiry:"—" },
  { id:3,  title:"Contratto di lavoro",                owner:"Sara Neri",            ownerType:"Lavoratore", cat:"Contratti",   area:"Rapporto di lavoro",    status:"Firma mancante",  tone:"warning", expiry:"Da firmare" },
  { id:4,  title:"Proroga contratto TD",               owner:"Francesco Conti",      ownerType:"Lavoratore", cat:"Contratti",   area:"Rapporto di lavoro",    status:"Da predisporre",  tone:"warning", expiry:"30/06/2026" },
  { id:5,  title:"Scheda mansione",                    owner:"Luca Verdi",           ownerType:"Lavoratore", cat:"Mansioni",    area:"Organizzazione",        status:"Aggiornata",      tone:"success", expiry:"Revisione annuale" },
  { id:6,  title:"Attestato formazione sicurezza",     owner:"Marco Rossi",          ownerType:"Lavoratore", cat:"Formazione",  area:"Sicurezza lavoro",      status:"Valido",          tone:"success", expiry:"18/11/2027" },
  { id:7,  title:"Idoneità sanitaria",                 owner:"Luca Verdi",           ownerType:"Lavoratore", cat:"Sicurezza",   area:"Sorveglianza sanitaria",status:"In scadenza",     tone:"danger",  expiry:"05/06/2026" },
  { id:8,  title:"Consegna DPI",                       owner:"Francesco Conti",      ownerType:"Lavoratore", cat:"Sicurezza",   area:"DPI",                   status:"Firma richiesta", tone:"warning", expiry:"Aperta" },
  { id:9,  title:"Cedolino paga",                      owner:"Giulia Bianchi",       ownerType:"Lavoratore", cat:"Retribuzione",area:"Amm. personale",        status:"Riservato",       tone:"info",    expiry:"Maggio 2026" },
  { id:10, title:"Organigramma aziendale",             owner:"Costruzioni Novicrom", ownerType:"Azienda",    cat:"Aziendali",   area:"Organizzazione",        status:"Pubblicato",      tone:"success", expiry:"Revisione Q3" },
  { id:11, title:"Procedura ferie e permessi",         owner:"Costruzioni Novicrom", ownerType:"Azienda",    cat:"Aziendali",   area:"Procedure HR",          status:"Pubblicato",      tone:"success", expiry:"Revisione annuale" },
  { id:12, title:"Policy privacy dipendenti",          owner:"Costruzioni Novicrom", ownerType:"Azienda",    cat:"Aziendali",   area:"Privacy",               status:"Da revisionare",  tone:"warning", expiry:"31/07/2026" },
  { id:13, title:"DVR — Valutazione Rischi",           owner:"Costruzioni Novicrom", ownerType:"Azienda",    cat:"Sicurezza",   area:"Sicurezza lavoro",      status:"Aggiornato",      tone:"success", expiry:"Revisione 2026" },
];

const HRP_SAFETY = [
  { area:"Sorveglianza sanitaria", open:7, ok:141, note:"Visite da pianificare",            ic:"heart"    },
  { area:"DPI",                    open:9, ok:132, note:"Consegne da confermare",           ic:"shield"   },
  { area:"Idoneità mansione",      open:4, ok:144, note:"Cambio mansione / rinnovi",        ic:"badgeCheck" },
  { area:"Abilitazioni operative", open:6, ok:118, note:"Patenti, carrelli, piattaforme",   ic:"flag"     },
];

const HRP_DOC_VIEWS = ["Tutti","Lavoratori","Aziendali","Contratti","Sicurezza","Scadenze","Riservati"];

/* ====== HELPER LOCALI ====== */

/* Page header brand‑correct: eyebrow mono arancio, titolo navy, action a dx */
function HRPPageHead({ eyebrow, title, sub, actionLabel, actionIcon, onAction }) {
  return (
    <header className="hrp-head">
      <div>
        <div className="hrp-eyebrow"><span className="hrp-dot"/>{eyebrow}</div>
        <h2 className="hrp-title">{title}</h2>
        {sub && <p className="hrp-sub">{sub}</p>}
      </div>
      {actionLabel && (
        <Button variant="accent" size="md" icon={actionIcon} onClick={onAction}>{actionLabel}</Button>
      )}
      <style>{`
        .hrp-head{
          display:flex; align-items:center; justify-content:space-between; gap:14px;
          padding:14px 16px; background:#fff; border:1px solid #e7edf3;
          border-radius:10px; margin-bottom:14px; flex-wrap:wrap;
          box-shadow:0 1px 3px rgba(0,0,0,.04);
          position:relative; overflow:hidden;
        }
        .hrp-head::before{
          content:""; position:absolute; left:0; top:14px; bottom:14px; width:3px;
          background:#ff8a1f; border-radius:0 3px 3px 0;
        }
        .hrp-eyebrow{
          display:inline-flex; align-items:center; gap:7px;
          font-family:ui-monospace,Menlo,monospace; font-size:10.5px; font-weight:700;
          letter-spacing:.14em; text-transform:uppercase; color:#1f87cd;
        }
        .hrp-dot{ width:6px; height:6px; border-radius:50%; background:#ff8a1f;
                  box-shadow:0 0 0 3px rgba(255,138,31,.18) }
        .hrp-title{ margin:4px 0 0; font-size:20px; font-weight:800; color:#0c2545; letter-spacing:-.005em }
        .hrp-sub{ margin:3px 0 0; font-size:12.5px; color:#6b7a90; max-width:780px; line-height:1.5 }
      `}</style>
    </header>
  );
}

/* Riga di sub‑tabs in stile pillole su barra bianca */
function HRPSubTabs({ items, value, onChange }) {
  return (
    <div className="hrp-st">
      {items.map(v => (
        <button key={v} className={`hrp-st-b ${value===v?"on":""}`} onClick={() => onChange(v)}>{v}</button>
      ))}
      <style>{`
        .hrp-st{ display:flex; gap:4px; overflow-x:auto; padding:5px;
                 background:#fff; border:1px solid #e7edf3; border-radius:10px;
                 margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,.04) }
        .hrp-st-b{
          font:inherit; font-size:11.5px; font-weight:700; padding:7px 12px;
          border:none; background:transparent; color:#6b7a90; cursor:pointer;
          border-radius:7px; white-space:nowrap; transition:background .12s, color .12s;
        }
        .hrp-st-b:hover{ background:#f4f6fb; color:#0c2545 }
        .hrp-st-b.on{ background:#0c2545; color:#fff }
      `}</style>
    </div>
  );
}

/* Mini KPI strip (riusa il pattern HRMetric dal Dashboard) */
function HRPKpi({ tone="cyan", icon, label, value, sub, onClick }) {
  return (
    <button className={`hrp-mtr tone-${tone}`} onClick={onClick}>
      <span className="hrp-mtr-ribbon"/>
      <span className="hrp-mtr-ic">{icon}</span>
      <span className="hrp-mtr-body">
        <span className="hrp-mtr-lbl">{label}</span>
        <span className="hrp-mtr-val">{value}</span>
        <span className="hrp-mtr-sub">{sub}</span>
      </span>
      <style>{`
        .hrp-mtr{
          position:relative; display:flex; align-items:center; gap:12px;
          padding:12px 14px 12px 16px; background:#fff; border:1px solid #e7edf3;
          border-radius:10px; cursor:pointer; font:inherit; text-align:left; width:100%;
          transition:transform .12s, box-shadow .12s, border-color .12s;
          box-shadow:0 1px 3px rgba(0,0,0,.04);
        }
        .hrp-mtr:hover{ transform:translateY(-1px); box-shadow:0 6px 18px rgba(12,37,69,.08); border-color:#cfd8e3 }
        .hrp-mtr-ribbon{ position:absolute; left:0; top:10px; bottom:10px; width:3px; border-radius:0 3px 3px 0 }
        .hrp-mtr-ic{ width:36px; height:36px; flex:0 0 36px;
                     display:flex; align-items:center; justify-content:center; border-radius:8px }
        .hrp-mtr-body{ display:flex; flex-direction:column; gap:1px; min-width:0; flex:1 }
        .hrp-mtr-lbl{ font-family:ui-monospace,Menlo,monospace; font-size:10px; font-weight:700;
                      letter-spacing:.06em; text-transform:uppercase; color:#94a3b8 }
        .hrp-mtr-val{ font-size:21px; font-weight:800; line-height:1.1; color:#0c2545 }
        .hrp-mtr-sub{ font-size:11px; color:#6b7a90; margin-top:1px }
        .tone-cyan   .hrp-mtr-ribbon{ background:#1f87cd }
        .tone-cyan   .hrp-mtr-ic{ background:#e8f3fb; color:#1f87cd }
        .tone-orange .hrp-mtr-ribbon{ background:#ff8a1f }
        .tone-orange .hrp-mtr-ic{ background:#fff3e6; color:#ff8a1f }
        .tone-green  .hrp-mtr-ribbon{ background:#16a34a }
        .tone-green  .hrp-mtr-ic{ background:#ecfdf3; color:#15803d }
        .tone-red    .hrp-mtr-ribbon{ background:#dc2626 }
        .tone-red    .hrp-mtr-ic{ background:#fff5f5; color:#c53030 }
      `}</style>
    </button>
  );
}

/* Info "cella" per dettagli espansi */
function HRPInfo({ label, value, meta }) {
  return (
    <div className="hrp-info">
      <div className="hrp-info-lbl">{label}</div>
      <div className="hrp-info-val">{value}</div>
      {meta && <div className="hrp-info-meta">{meta}</div>}
      <style>{`
        .hrp-info{ background:#fff; border:1px solid #e7edf3; border-radius:8px; padding:9px 11px }
        .hrp-info-lbl{ font-family:ui-monospace,Menlo,monospace; font-size:9.5px; font-weight:700;
                       letter-spacing:.08em; text-transform:uppercase; color:#94a3b8; margin-bottom:3px }
        .hrp-info-val{ font-size:13px; font-weight:700; color:#0c2545; line-height:1.2;
                       overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
        .hrp-info-meta{ font-size:10.5px; color:#6b7a90; margin-top:2px }
      `}</style>
    </div>
  );
}

/* Progress sottile usabile ovunque */
function HRPBar({ value, tone="navy" }) {
  const fill = tone==="cyan" ? "#1f87cd" : tone==="orange" ? "#ff8a1f" : tone==="green" ? "#16a34a" : "#0c2545";
  return (
    <div style={{height:5,background:"#eef2f7",borderRadius:3,overflow:"hidden"}}>
      <div style={{height:5,width:`${value}%`,background:fill,borderRadius:3,transition:"width .3s"}}/>
    </div>
  );
}

/* ============================================================ */
/*  PERSONE — tabella + mini‑pagina espandibile per dipendente    */
/* ============================================================ */
function PersonePage({ onNav }) {
  const [query, setQuery] = useStateHRP("");
  const [openId, setOpenId] = useStateHRP(1);
  const [sectionMap, setSectionMap] = useStateHRP({});
  const sections = ["Riepilogo","Anagrafica civile","Contratto","Ferie","Corsi","Documenti","DPI","Visite","Asset"];

  const filtered = useMemoHRP(() => {
    const q = query.trim().toLowerCase();
    if (!q) return HRP_PEOPLE;
    return HRP_PEOPLE.filter(p => `${p.name} ${p.code} ${p.dept} ${p.role} ${p.contract} ${p.site}`.toLowerCase().includes(q));
  }, [query]);

  const personData = (p) => ({
    company: { matricola:p.code, badge:`B-${1200+p.id}`, email:`${p.name.toLowerCase().replaceAll(" ",".")}@costruzioninovicrom.it`,
               reparto:p.dept, mansione:p.role, sede:p.site, responsabile:p.manager },
    civil:   { cf:`${p.name.split(" ").map(x=>x[0]).join("")}RSS80A01G702X`,
               nascita: p.id%2 ? "Pisa, 14/03/1986" : "Pontedera, 22/09/1991",
               residenza: p.id%2 ? "Via Roma 18, S.M. a Monte" : "Via Tosco Romagnola 44, Pontedera",
               telefono:`+39 333 45${p.id} 77${p.id}2`,
               emergenza: p.id%2 ? "Anna Rossi · moglie" : "Mario Bianchi · padre" },
    reserved:{ contratto:p.contract,
               assunzione: p.id===4 ? "01/06/2026" : "03/04/2021",
               livello: p.dept==="Produzione" ? "C2 Metalmeccanico" : p.dept==="Cantiere" ? "C3 Edile" : "B2 Impiegato",
               retribuzione:"Visibile solo HR/Payroll",
               iban:"IT** **** **** **** 1289",
               note: p.risk==="Contratto firma" ? "Documentazione assunzione da completare" : "Nessuna nota critica" },
    ferie:   { ferieResidue: p.id%2 ? "72 h" : "48 h",
               rolResidui:   p.id%2 ? "18 h" : "26 h",
               exFestivita:"8 h",
               ultimo: HRP_ABSENCES.find(a=>a.person===p.name)?.period || "—",
               statoRich: HRP_ABSENCES.find(a=>a.person===p.name)?.status || "Nessuna" },
    dpi: [
      { item:"Scarpe antinfortunistiche", consegna:"12/01/2026", stato: p.risk==="DPI da firmare" ? "Firma richiesta" : "Consegnato", tone: p.risk==="DPI da firmare" ? "warning":"success" },
      { item:"Casco protettivo",          consegna:"12/01/2026", stato:"Consegnato",   tone:"success" },
      { item:"Guanti da lavoro",          consegna:"10/04/2026", stato:"Da rinnovare", tone:"warning" },
    ],
    medical: [
      { visita:"Idoneità mansione",     data:"05/06/2026", esito: p.risk==="Doc. in scadenza" ? "In scadenza" : "Idoneo", tone: p.risk==="Doc. in scadenza" ? "danger" : "success" },
      { visita:"Sorveglianza sanitaria",data:"18/11/2026", esito:"Programmabile", tone:"info" },
    ],
    assets: [
      { tag:`NB-${220+p.id}`,   type:"Notebook",       status:"Assegnato" },
      { tag:`TEL-${310+p.id}`,  type:"Smartphone",     status: p.dept==="Produzione" ? "Non assegnato" : "Assegnato" },
      { tag:`BADGE-${1200+p.id}`,type:"Badge accesso", status:"Attivo" },
    ],
  });

  const renderSection = (p, sec) => {
    const d = personData(p);
    const docs = HRP_DOCUMENTS.filter(x=>x.owner===p.name);
    const courses = HRP_TRAINING.slice(0,4);
    if (sec==="Anagrafica civile") return (
      <div className="hrp-grid g6">
        <HRPInfo label="Codice fiscale" value={d.civil.cf}/>
        <HRPInfo label="Nascita" value={d.civil.nascita}/>
        <HRPInfo label="Residenza" value={d.civil.residenza}/>
        <HRPInfo label="Telefono" value={d.civil.telefono}/>
        <HRPInfo label="Emergenza" value={d.civil.emergenza}/>
        <HRPInfo label="Domicilio" value="Coincide con residenza"/>
      </div>
    );
    if (sec==="Contratto") return (
      <div className="hrp-grid g3">
        <HRPInfo label="Contratto" value={d.reserved.contratto} meta={d.reserved.assunzione}/>
        <HRPInfo label="Livello / CCNL" value={d.reserved.livello}/>
        <HRPInfo label="Retribuzione" value={d.reserved.retribuzione}/>
        <HRPInfo label="IBAN" value={d.reserved.iban}/>
        <HRPInfo label="Stato" value={p.status}/>
        <HRPInfo label="Note riservate" value={d.reserved.note}/>
      </div>
    );
    if (sec==="Ferie") return (
      <div className="hrp-grid g5">
        <HRPInfo label="Ferie residue" value={d.ferie.ferieResidue}/>
        <HRPInfo label="ROL residui" value={d.ferie.rolResidui}/>
        <HRPInfo label="Ex festività" value={d.ferie.exFestivita}/>
        <HRPInfo label="Ultimo periodo" value={d.ferie.ultimo}/>
        <HRPInfo label="Stato richieste" value={d.ferie.statoRich}/>
      </div>
    );
    if (sec==="Corsi") return (
      <div className="hrp-list">
        {courses.map(c => (
          <div className="hrp-li" key={c.course}>
            <div className="hrp-li-main">
              <div className="hrp-li-t">{c.course}</div>
              <div className="hrp-li-m">{c.format} · {c.hours}h · {c.owner}</div>
            </div>
            <div style={{minWidth:120}}><HRPBar value={c.coverage} tone={c.coverage>=85?"cyan":c.coverage>=75?"orange":"orange"}/></div>
            <Badge tone={c.coverage>=85?"success":c.coverage>=75?"warning":"danger"}>{c.coverage}%</Badge>
          </div>
        ))}
      </div>
    );
    if (sec==="Documenti") return (
      <div className="hrp-list">
        {docs.length === 0 && <div className="hrp-empty">Nessun documento personale collegato</div>}
        {docs.map(doc => (
          <div className="hrp-li" key={doc.id}>
            <div className="hrp-li-main">
              <div className="hrp-li-t">{doc.title}</div>
              <div className="hrp-li-m">{doc.cat} · scadenza {doc.expiry}</div>
            </div>
            <Badge tone={doc.tone}>{doc.status}</Badge>
          </div>
        ))}
      </div>
    );
    if (sec==="DPI") return (
      <div className="hrp-list">
        {d.dpi.map(x => (
          <div className="hrp-li" key={x.item}>
            <div className="hrp-li-main">
              <div className="hrp-li-t">{x.item}</div>
              <div className="hrp-li-m">Consegna {x.consegna}</div>
            </div>
            <Badge tone={x.tone}>{x.stato}</Badge>
          </div>
        ))}
      </div>
    );
    if (sec==="Visite") return (
      <div className="hrp-list">
        {d.medical.map(v => (
          <div className="hrp-li" key={v.visita}>
            <div className="hrp-li-main">
              <div className="hrp-li-t">{v.visita}</div>
              <div className="hrp-li-m">Programmata {v.data}</div>
            </div>
            <Badge tone={v.tone}>{v.esito}</Badge>
          </div>
        ))}
      </div>
    );
    if (sec==="Asset") return (
      <div className="hrp-list">
        {d.assets.map(a => (
          <div className="hrp-li" key={a.tag}>
            <div className="hrp-li-main">
              <div className="hrp-li-t"><code className="hrp-code">{a.tag}</code> {a.type}</div>
              <div className="hrp-li-m">Asset aziendale</div>
            </div>
            <Badge tone={a.status==="Assegnato"||a.status==="Attivo" ? "success":"default"}>{a.status}</Badge>
          </div>
        ))}
      </div>
    );
    /* Riepilogo */
    return (
      <div className="hrp-grid g4">
        <HRPInfo label="Matricola" value={d.company.matricola}/>
        <HRPInfo label="Badge" value={d.company.badge}/>
        <HRPInfo label="Email" value={d.company.email}/>
        <HRPInfo label="Reparto" value={d.company.reparto}/>
        <HRPInfo label="Mansione" value={d.company.mansione}/>
        <HRPInfo label="Sede" value={d.company.sede}/>
        <HRPInfo label="Responsabile" value={d.company.responsabile}/>
        <HRPInfo label="HR Score" value={`${p.score}%`} meta={p.risk}/>
      </div>
    );
  };

  return (
    <>
      <HRPPageHead
        eyebrow="Persone · fascicolo HR"
        title="Persone e fascicolo dipendenti"
        sub="Clicca un dipendente per aprire la scheda inline: anagrafica civile, contratto, ferie, corsi, documenti, DPI, visite e asset assegnati."
        actionLabel="Nuovo dipendente" actionIcon={Icons.userPlus}/>

      <section className="hrp-kpi">
        <HRPKpi tone="cyan"   icon={Icons.people}      label="Totale persone"   value="148" sub="136 attivi · 12 esterni"/>
        <HRPKpi tone="orange" icon={Icons.userPlus}    label="Onboarding"       value="5"   sub="2 bloccati da documenti"/>
        <HRPKpi tone="green"  icon={Icons.briefcase}   label="Cambi mansione"   value="8"   sub="Da validare questo mese"/>
        <HRPKpi tone="red"    icon={Icons.warning}     label="Azioni HR"        value="21"  sub="Doc · DPI · formazione"/>
      </section>

      <Card padded={false}>
        <div className="hrp-tbl-head">
          <div>
            <h3 style={{margin:0,fontSize:14,fontWeight:800,color:"#0c2545"}}>Elenco dipendenti</h3>
            <p style={{margin:"2px 0 0",fontSize:11,color:"#6b7a90"}}>5 di 148 risultati · ordinamento per priorità</p>
          </div>
          <div className="hrp-search">
            <span className="hrp-search-ic">{Icons.search}</span>
            <input value={query} onChange={e=>setQuery(e.target.value)}
                   placeholder="Cerca persona, codice, mansione…"/>
          </div>
        </div>

        <div className="hrp-tbl">
          <div className="hrp-tbl-th">
            <span>Dipendente</span>
            <span>Reparto</span>
            <span>Mansione</span>
            <span>Contratto</span>
            <span>Stato</span>
            <span></span>
          </div>
          {filtered.map(p => {
            const exp = openId === p.id;
            const sec = sectionMap[p.id] || "Riepilogo";
            return (
              <div key={p.id} className={`hrp-tbl-row-wrap ${exp?"open":""}`}>
                <button className="hrp-tbl-row" onClick={() => setOpenId(exp ? null : p.id)}>
                  <span className="hrp-cell-people">
                    <span className="hrp-av" style={{
                      background: p.riskTone==="danger"?"#fff5f5":p.riskTone==="warning"?"#fff3e6":"#e8f3fb",
                      color:      p.riskTone==="danger"?"#c53030":p.riskTone==="warning"?"#c2410c":"#1f5fb3" }}>
                      {p.name.split(" ").map(n=>n[0]).join("").slice(0,2)}
                    </span>
                    <span>
                      <span className="hrp-tbl-name">{p.name}</span>
                      <span className="hrp-tbl-meta"><code className="hrp-code">{p.code}</code> · resp. {p.manager}</span>
                    </span>
                  </span>
                  <span className="hrp-mut">{p.dept}</span>
                  <span className="hrp-mut">{p.role}</span>
                  <span className="hrp-mut">{p.contract}</span>
                  <span><Badge tone={p.riskTone}>{p.status}</Badge></span>
                  <span className="hrp-chev" data-open={exp?"1":"0"}>{Icons.chevronD}</span>
                </button>

                {exp && (
                  <div className="hrp-tbl-detail">
                    <div className="hrp-detail-head">
                      <div>
                        <div className="hrp-detail-eyebrow">Scheda dipendente · {p.code}</div>
                        <h4 className="hrp-detail-title">{p.name}</h4>
                        <p className="hrp-detail-sub">{p.role} · {p.dept} · {p.site} · resp. {p.manager}</p>
                      </div>
                      <div className="hrp-detail-actions">
                        <Button variant="ghost" size="sm" icon={Icons.doc}        onClick={()=>onNav?.("docs")}>Documenti</Button>
                        <Button variant="ghost" size="sm" icon={Icons.graduation} onClick={()=>onNav?.("formazione")}>Formazione</Button>
                        <Button variant="cyan"  size="sm" icon={Icons.shield}     onClick={()=>onNav?.("sicurezza")}>Sicurezza</Button>
                      </div>
                    </div>

                    <div className="hrp-st-inline">
                      {sections.map(s => (
                        <button key={s}
                          className={`hrp-st-b ${sec===s?"on":""}`}
                          onClick={() => setSectionMap({...sectionMap, [p.id]: s})}>{s}</button>
                      ))}
                    </div>

                    <div className="hrp-detail-body">{renderSection(p, sec)}</div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      <style>{`
        .hrp-kpi{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:14px }

        .hrp-tbl-head{
          display:flex; align-items:center; justify-content:space-between; gap:14px;
          padding:12px 14px; border-bottom:1px solid #eef2f7; flex-wrap:wrap;
        }
        .hrp-search{
          display:flex; align-items:center; gap:8px; padding:0 10px;
          height:34px; min-width:260px; border:1px solid #e7edf3; border-radius:8px;
          background:#fafbfd; color:#6b7a90;
        }
        .hrp-search-ic{ color:#94a3b8; display:inline-flex }
        .hrp-search input{
          border:none; background:transparent; outline:none; flex:1;
          font:inherit; font-family:"Outfit",sans-serif; font-size:12.5px; color:#0c2545;
        }

        .hrp-tbl{ display:flex; flex-direction:column }
        .hrp-tbl-th{
          display:grid; grid-template-columns: 1.5fr .9fr .9fr 1.1fr .9fr 18px;
          gap:14px; padding:8px 14px; background:#fafbfd; border-bottom:1px solid #eef2f7;
          font-family:ui-monospace,Menlo,monospace; font-size:10px; font-weight:700;
          letter-spacing:.06em; text-transform:uppercase; color:#94a3b8;
        }
        .hrp-tbl-row-wrap{ border-top:1px solid #f0f3f7 }
        .hrp-tbl-row-wrap:first-child{ border-top:none }
        .hrp-tbl-row{
          display:grid; grid-template-columns: 1.5fr .9fr .9fr 1.1fr .9fr 18px;
          gap:14px; width:100%; padding:10px 14px; align-items:center;
          background:#fff; border:none; font:inherit; text-align:left; cursor:pointer;
          transition:background .12s;
        }
        .hrp-tbl-row:hover{ background:#fafbfd }
        .hrp-tbl-row-wrap.open .hrp-tbl-row{ background:#f4f8fc }
        .hrp-cell-people{ display:flex; align-items:center; gap:10px; min-width:0 }
        .hrp-av{
          width:34px; height:34px; flex:0 0 34px; border-radius:8px;
          display:flex; align-items:center; justify-content:center;
          font-weight:800; font-size:11.5px;
        }
        .hrp-tbl-name{ display:block; font-size:13px; font-weight:700; color:#0c2545 }
        .hrp-tbl-meta{ display:block; font-size:11px; color:#6b7a90 }
        .hrp-mut{ font-size:12.5px; color:#4a5568 }
        .hrp-code{ font-family:ui-monospace,Menlo,monospace; font-size:10.5px; color:#94a3b8; font-weight:700 }
        .hrp-chev{ color:#94a3b8; display:inline-flex; transition:transform .15s }
        .hrp-chev[data-open="1"]{ transform:rotate(180deg); color:#1f87cd }

        .hrp-tbl-detail{
          background:linear-gradient(180deg,#f4f8fc 0,#fafbfd 100%);
          border-top:1px solid #e1e8f0; padding:14px 16px; position:relative;
        }
        .hrp-tbl-detail::before{
          content:""; position:absolute; left:14px; top:0; width:14px; height:3px; background:#ff8a1f;
        }
        .hrp-detail-head{
          display:flex; align-items:flex-start; justify-content:space-between;
          gap:12px; margin-bottom:12px; flex-wrap:wrap;
        }
        .hrp-detail-eyebrow{
          font-family:ui-monospace,Menlo,monospace; font-size:10px; font-weight:700;
          letter-spacing:.12em; text-transform:uppercase; color:#1f87cd;
        }
        .hrp-detail-title{ margin:2px 0 0; font-size:17px; font-weight:800; color:#0c2545 }
        .hrp-detail-sub{ margin:2px 0 0; font-size:12px; color:#6b7a90 }
        .hrp-detail-actions{ display:flex; gap:6px; flex-wrap:wrap }

        .hrp-st-inline{
          display:flex; gap:4px; padding:4px; border-radius:8px;
          background:#fff; border:1px solid #e7edf3; margin-bottom:12px;
          overflow-x:auto;
        }
        .hrp-st-inline .hrp-st-b{
          font:inherit; font-size:11px; font-weight:700; padding:6px 10px;
          border:none; background:transparent; color:#6b7a90; cursor:pointer;
          border-radius:6px; white-space:nowrap;
        }
        .hrp-st-inline .hrp-st-b.on{ background:#0c2545; color:#fff }

        .hrp-detail-body{ padding:0 }
        .hrp-grid{ display:grid; gap:8px }
        .hrp-grid.g3{ grid-template-columns:repeat(3,1fr) }
        .hrp-grid.g4{ grid-template-columns:repeat(4,1fr) }
        .hrp-grid.g5{ grid-template-columns:repeat(5,1fr) }
        .hrp-grid.g6{ grid-template-columns:repeat(6,1fr) }
        .hrp-list{ display:flex; flex-direction:column; gap:6px }
        .hrp-li{
          display:grid; grid-template-columns: 1fr minmax(0,140px) auto;
          align-items:center; gap:12px;
          background:#fff; border:1px solid #e7edf3; border-radius:8px; padding:9px 12px;
        }
        .hrp-li-main{ min-width:0 }
        .hrp-li-t{ font-size:13px; font-weight:700; color:#0c2545 }
        .hrp-li-m{ font-size:11px; color:#6b7a90; margin-top:1px }
        .hrp-empty{ font-size:12px; color:#94a3b8; padding:12px; text-align:center;
                    background:#fff; border:1px dashed #e7edf3; border-radius:8px }

        @media (max-width: 1100px){
          .hrp-kpi{ grid-template-columns:repeat(2,1fr) }
          .hrp-grid.g3,.hrp-grid.g4,.hrp-grid.g5,.hrp-grid.g6{ grid-template-columns:repeat(2,1fr) }
          .hrp-tbl-th,.hrp-tbl-row{ grid-template-columns: 1.4fr .9fr 1fr 18px }
          .hrp-tbl-th span:nth-child(3),.hrp-tbl-th span:nth-child(4),
          .hrp-tbl-row > span:nth-child(3),.hrp-tbl-row > span:nth-child(4){ display:none }
        }
      `}</style>
    </>
  );
}

/* ============================================================ */
/*  ASSENZE                                                       */
/* ============================================================ */
function AssenzePage() {
  const [open, setOpen] = useStateHRP(null);
  return (
    <>
      <HRPPageHead
        eyebrow="Presenze e assenze"
        title="Ferie, permessi, ROL e malattie"
        sub="Approvazioni inline. Clicca una richiesta per espandere il dettaglio sotto la riga."
        actionLabel="Nuova richiesta" actionIcon={Icons.calendar}/>

      <section className="hrp-kpi">
        <HRPKpi tone="orange" icon={Icons.calendar} label="Assenze oggi"     value="11" sub="7 ferie · 4 malattia"/>
        <HRPKpi tone="red"    icon={Icons.warning}  label="Da approvare"     value="6"  sub="Responsabili reparto"/>
        <HRPKpi tone="green"  icon={Icons.check}    label="Approvate mese"   value="42" sub="Ferie / ROL / permessi"/>
        <HRPKpi tone="cyan"   icon={Icons.clock}    label="Scoperte reparto" value="2"  sub="Produzione · Magazzino"/>
      </section>

      <Card padded={false} title="Richieste recenti">
        <div className="hrp-tbl">
          <div className="hrp-tbl-th" style={{gridTemplateColumns:"1.4fr .8fr 1.2fr .7fr .9fr 18px"}}>
            <span>Persona</span><span>Tipo</span><span>Periodo</span><span>Durata</span><span>Stato</span><span/>
          </div>
          {HRP_ABSENCES.map(a => {
            const exp = open === a.id;
            return (
              <div key={a.id} className={`hrp-tbl-row-wrap ${exp?"open":""}`}>
                <button className="hrp-tbl-row" style={{gridTemplateColumns:"1.4fr .8fr 1.2fr .7fr .9fr 18px"}}
                        onClick={() => setOpen(exp?null:a.id)}>
                  <span style={{fontWeight:700,color:"#0c2545"}}>{a.person}</span>
                  <span className="hrp-mut">{a.type}</span>
                  <span className="hrp-mut">{a.period}</span>
                  <span className="hrp-mut"><code className="hrp-code">{a.days}</code></span>
                  <span><Badge tone={a.tone}>{a.status}</Badge></span>
                  <span className="hrp-chev" data-open={exp?"1":"0"}>{Icons.chevronD}</span>
                </button>
                {exp && (
                  <div className="hrp-tbl-detail">
                    <div className="hrp-grid g4">
                      <HRPInfo label="Tipo" value={a.type}/>
                      <HRPInfo label="Periodo" value={a.period} meta={`Durata ${a.days}`}/>
                      <HRPInfo label="Stato" value={a.status}/>
                      <HRPInfo label="Copertura" value="Verificata" meta="Responsabile · OK"/>
                    </div>
                    <div style={{marginTop:12,display:"flex",gap:6,flexWrap:"wrap"}}>
                      <Button variant="cyan"  size="sm" icon={Icons.check}>Approva</Button>
                      <Button variant="ghost" size="sm" icon={Icons.x}>Rifiuta</Button>
                      <Button variant="ghost" size="sm" icon={Icons.doc}>Allegati</Button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Card>
    </>
  );
}

/* ============================================================ */
/*  FORMAZIONE                                                    */
/* ============================================================ */
function FormazionePage() {
  const [view, setView] = useStateHRP("Catalogo");
  const [open, setOpen] = useStateHRP(null);
  return (
    <>
      <HRPPageHead
        eyebrow="Formazione e competenze"
        title="Training Center HR"
        sub="Catalogo corsi, copertura, scadenze e gap formativi. Tutti i corsi obbligatori sono tracciati con scadenza personale."
        actionLabel="Pianifica corso" actionIcon={Icons.graduation}/>

      <section className="hrp-kpi">
        <HRPKpi tone="cyan"   icon={Icons.graduation} label="Copertura media" value="82%" sub="Corsi obbligatori"/>
        <HRPKpi tone="red"    icon={Icons.warning}    label="Scadenze 30 gg"  value="12"  sub="Priorità sicurezza"/>
        <HRPKpi tone="green"  icon={Icons.badgeCheck} label="Abilitazioni"    value="54"  sub="Attive"/>
        <HRPKpi tone="orange" icon={Icons.clipboard}  label="Da pianificare"  value="9"   sub="Sessioni"/>
      </section>

      <HRPSubTabs items={["Catalogo","Matrice competenze","Sessioni","Gap persone"]} value={view} onChange={setView}/>

      {view === "Catalogo" && (
        <Card padded={false} title="Catalogo corsi obbligatori">
          <div className="hrp-tbl">
            <div className="hrp-tbl-th" style={{gridTemplateColumns:"1.5fr 1fr .8fr .8fr .8fr 18px"}}>
              <span>Corso</span><span>Audience</span><span>Copertura</span><span>Owner</span><span>Scadenza</span><span/>
            </div>
            {HRP_TRAINING.map(t => {
              const exp = open === t.course;
              return (
                <div key={t.course} className={`hrp-tbl-row-wrap ${exp?"open":""}`}>
                  <button className="hrp-tbl-row" style={{gridTemplateColumns:"1.5fr 1fr .8fr .8fr .8fr 18px"}}
                          onClick={() => setOpen(exp?null:t.course)}>
                    <span>
                      <span className="hrp-tbl-name">{t.course}</span>
                      <span className="hrp-tbl-meta">{t.format} · {t.hours}h</span>
                    </span>
                    <span className="hrp-mut">{t.audience}</span>
                    <span><Badge tone={t.coverage>=85?"success":t.coverage>=75?"warning":"danger"}>{t.coverage}%</Badge></span>
                    <span className="hrp-mut">{t.owner}</span>
                    <span className="hrp-mut">{t.due}</span>
                    <span className="hrp-chev" data-open={exp?"1":"0"}>{Icons.chevronD}</span>
                  </button>
                  {exp && (
                    <div className="hrp-tbl-detail">
                      <div className="hrp-grid g4">
                        <HRPInfo label="Copertura" value={`${t.coverage}%`} meta={`${t.missing} persone mancanti`}/>
                        <HRPInfo label="Formato" value={t.format} meta={`${t.hours} ore`}/>
                        <HRPInfo label="Scadenza" value={t.due}/>
                        <HRPInfo label="Rischio" value={t.risk}/>
                      </div>
                      <div style={{marginTop:10}}><HRPBar value={t.coverage} tone={t.coverage>=85?"cyan":t.coverage>=75?"orange":"orange"}/></div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {view === "Matrice competenze" && (
        <div className="hrp-grid g2">
          {[
            { role:"Saldatore",         req:["Sicurezza","DPI","Qualità","Antincendio"],     cov:78, crit:"Qualità" },
            { role:"Preposto cantiere", req:["Preposto","Sicurezza","Antincendio","Primo soccorso"], cov:71, crit:"Preposto" },
            { role:"Addetto logistica", req:["Carrelli","DPI","Sicurezza","Movimentazione"], cov:83, crit:"Carrelli" },
            { role:"HR / Amministrazione", req:["Privacy","Cyber awareness","Procedure HR"], cov:67, crit:"Privacy" },
          ].map(m => (
            <Card key={m.role}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",gap:10}}>
                <div>
                  <h4 style={{margin:0,fontSize:14,fontWeight:800,color:"#0c2545"}}>{m.role}</h4>
                  <p style={{margin:"2px 0 0",fontSize:11.5,color:"#6b7a90"}}>Competenze richieste · criticità su <b>{m.crit}</b></p>
                </div>
                <Badge tone={m.cov>=80?"success":"warning"}>{m.cov}%</Badge>
              </div>
              <div style={{display:"flex",gap:6,flexWrap:"wrap",marginTop:10}}>
                {m.req.map(r => (
                  <span key={r} style={{
                    display:"inline-flex",alignItems:"center",padding:"3px 9px",borderRadius:999,
                    fontFamily:"ui-monospace,Menlo,monospace",fontSize:10.5,fontWeight:700,
                    background: r===m.crit ? "#fff5f5" : "#e8f3fb",
                    color:      r===m.crit ? "#c53030" : "#1f5fb3",
                    border:"1px solid",borderColor: r===m.crit ? "#fed7d7" : "#bee3f8",
                    letterSpacing:".04em",textTransform:"uppercase"
                  }}>{r}</span>
                ))}
              </div>
              <div style={{marginTop:12}}><HRPBar value={m.cov} tone={m.cov>=80?"cyan":"orange"}/></div>
            </Card>
          ))}
          <style>{`.hrp-grid.g2{ grid-template-columns:repeat(2,1fr) } @media(max-width:1000px){ .hrp-grid.g2{grid-template-columns:1fr} }`}</style>
        </div>
      )}

      {view === "Sessioni" && (
        <Card padded={false} title="Sessioni in programma">
          <div className="hrp-tbl">
            {[
              { t:"Preposto · aggiornamento",   d:"24 maggio", h:"09:00 – 13:00", loc:"Sala riunioni", seats:"6/10",  s:"Da confermare", tone:"warning" },
              { t:"Carrelli elevatori · pratica", d:"28 maggio", h:"08:30 – 12:30", loc:"Magazzino",   seats:"8/8",   s:"Completa",     tone:"success" },
              { t:"Privacy HR",                 d:"03 giugno", h:"14:00 – 15:30", loc:"Online",        seats:"12/20", s:"Aperta",       tone:"info" },
              { t:"Antincendio · prova pratica",d:"10 giugno", h:"09:00 – 17:00", loc:"Campo prova",   seats:"4/12",  s:"Da riempire",  tone:"warning" },
            ].map(s => (
              <div key={s.t} className="hrp-tbl-row-wrap">
                <div className="hrp-tbl-row" style={{cursor:"default",gridTemplateColumns:"1.5fr .8fr .8fr 1fr .8fr 18px"}}>
                  <span><span className="hrp-tbl-name">{s.t}</span><span className="hrp-tbl-meta">{s.loc}</span></span>
                  <span className="hrp-mut">{s.d}</span>
                  <span className="hrp-mut"><code className="hrp-code">{s.h}</code></span>
                  <span className="hrp-mut">Posti <b style={{color:"#0c2545"}}>{s.seats}</b></span>
                  <span><Badge tone={s.tone}>{s.s}</Badge></span>
                  <span/>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {view === "Gap persone" && (
        <Card padded={false} title="Persone con gap formativo">
          <div className="hrp-tbl">
            {[
              { p:"Luca Verdi",      r:"Preposto",         iss:"Aggiornamento preposto in scadenza",    due:"15 gg", sev:"Alto",  tone:"danger" },
              { p:"Francesco Conti", r:"Addetto logistica",iss:"Modulo carrelli da rinnovare",          due:"45 gg", sev:"Medio", tone:"warning" },
              { p:"Sara Neri",       r:"HR Specialist",    iss:"Privacy HR non completata",             due:"20 gg", sev:"Alto",  tone:"danger" },
              { p:"Marco Rossi",     r:"Saldatore",        iss:"Qualità e non conformità mancante",     due:"90 gg", sev:"Medio", tone:"warning" },
            ].map(g => (
              <div key={g.p} className="hrp-tbl-row-wrap">
                <div className="hrp-tbl-row" style={{cursor:"default",gridTemplateColumns:"1.2fr 1fr 1.5fr .7fr .8fr 18px"}}>
                  <span><span className="hrp-tbl-name">{g.p}</span><span className="hrp-tbl-meta">{g.r}</span></span>
                  <span className="hrp-mut">{g.r}</span>
                  <span className="hrp-mut">{g.iss}</span>
                  <span className="hrp-mut"><code className="hrp-code">{g.due}</code></span>
                  <span><Badge tone={g.tone}>{g.sev}</Badge></span>
                  <span/>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </>
  );
}

/* ============================================================ */
/*  DOCUMENTI                                                     */
/* ============================================================ */
function DocumentiPage() {
  const [view, setView] = useStateHRP("Tutti");
  const [open, setOpen] = useStateHRP(null);
  const [q, setQ] = useStateHRP("");
  const filtered = useMemoHRP(() => HRP_DOCUMENTS.filter(d => {
    const qq = q.toLowerCase().trim();
    const ok = !qq || `${d.title} ${d.owner} ${d.cat} ${d.area}`.toLowerCase().includes(qq);
    if (!ok) return false;
    if (view==="Lavoratori") return d.ownerType==="Lavoratore";
    if (view==="Aziendali")  return d.ownerType==="Azienda";
    if (view==="Contratti")  return d.cat==="Contratti";
    if (view==="Sicurezza")  return d.cat==="Sicurezza";
    if (view==="Scadenze")   return ["danger","warning"].includes(d.tone);
    if (view==="Riservati")  return d.cat==="Retribuzione";
    return true;
  }), [view, q]);

  return (
    <>
      <HRPPageHead
        eyebrow="Archivio anagrafico documentale"
        title="Documenti aziendali e fascicoli lavoratori"
        sub="Archivio unico per personali, contratti, sicurezza, procedure aziendali, dati riservati. ACL automatiche per categoria."
        actionLabel="Carica documento" actionIcon={Icons.doc}/>

      <HRPSubTabs items={HRP_DOC_VIEWS} value={view} onChange={setView}/>

      <Card padded={false}>
        <div className="hrp-tbl-head">
          <div>
            <h3 style={{margin:0,fontSize:14,fontWeight:800,color:"#0c2545"}}>{view} · {filtered.length} documenti</h3>
            <p style={{margin:"2px 0 0",fontSize:11,color:"#6b7a90"}}>Categoria, scadenza, ACL accesso</p>
          </div>
          <div className="hrp-search">
            <span className="hrp-search-ic">{Icons.search}</span>
            <input value={q} onChange={e=>setQ(e.target.value)} placeholder="Cerca documento, intestatario, area…"/>
          </div>
        </div>
        <div className="hrp-tbl">
          <div className="hrp-tbl-th" style={{gridTemplateColumns:"1.5fr 1fr 1fr .9fr .9fr 18px"}}>
            <span>Titolo</span><span>Intestatario</span><span>Categoria</span><span>Scadenza</span><span>Stato</span><span/>
          </div>
          {filtered.map(d => {
            const exp = open === d.id;
            return (
              <div key={d.id} className={`hrp-tbl-row-wrap ${exp?"open":""}`}>
                <button className="hrp-tbl-row" style={{gridTemplateColumns:"1.5fr 1fr 1fr .9fr .9fr 18px"}}
                        onClick={() => setOpen(exp?null:d.id)}>
                  <span>
                    <span className="hrp-tbl-name">{d.title}</span>
                    <span className="hrp-tbl-meta">{d.area}</span>
                  </span>
                  <span className="hrp-mut">{d.owner}</span>
                  <span className="hrp-mut">{d.cat}</span>
                  <span className="hrp-mut"><code className="hrp-code">{d.expiry}</code></span>
                  <span><Badge tone={d.tone}>{d.status}</Badge></span>
                  <span className="hrp-chev" data-open={exp?"1":"0"}>{Icons.chevronD}</span>
                </button>
                {exp && (
                  <div className="hrp-tbl-detail">
                    <div className="hrp-grid g4">
                      <HRPInfo label="Categoria" value={d.cat} meta={d.area}/>
                      <HRPInfo label="Intestatario" value={d.owner} meta={d.ownerType}/>
                      <HRPInfo label="Scadenza" value={d.expiry}/>
                      <HRPInfo label="Stato" value={d.status}/>
                    </div>
                    <div style={{marginTop:10,display:"flex",gap:6,flexWrap:"wrap"}}>
                      <Button variant="cyan"  size="sm" icon={Icons.download}>Scarica</Button>
                      <Button variant="ghost" size="sm" icon={Icons.refresh}>Rinnova</Button>
                      <Button variant="ghost" size="sm" icon={Icons.eye}>Versioni</Button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Card>
    </>
  );
}

/* ============================================================ */
/*  SICUREZZA                                                     */
/* ============================================================ */
function SicurezzaPage() {
  const [open, setOpen] = useStateHRP("Sorveglianza sanitaria");
  return (
    <>
      <HRPPageHead
        eyebrow="Sicurezza lavoro · D.Lgs 81/08"
        title="Sorveglianza, DPI, idoneità, abilitazioni"
        sub="Quattro aree presidiate. Clicca una card per il piano operativo: scadenze, owner, priorità."
        actionLabel="Apri piano sicurezza" actionIcon={Icons.shield}/>

      <section className="hrp-kpi">
        <HRPKpi tone="green"  icon={Icons.shield}     label="Idoneità valide" value="93%" sub="7 visite"/>
        <HRPKpi tone="red"    icon={Icons.heart}      label="Sorveglianza"    value="7"   sub="Scadenze"/>
        <HRPKpi tone="orange" icon={Icons.badgeCheck} label="DPI aperti"      value="9"   sub="Consegna · firma"/>
        <HRPKpi tone="cyan"   icon={Icons.flag}       label="Abilitazioni"    value="54"  sub="Patenti operative"/>
      </section>

      <div className="hrp-safety-grid">
        {HRP_SAFETY.map(s => {
          const exp = open === s.area;
          const tone = s.open > 7 ? "danger" : s.open > 4 ? "warning" : "info";
          return (
            <div key={s.area}>
              <button className={`hrp-safety-card ${exp?"open":""}`} onClick={() => setOpen(exp?null:s.area)}>
                <span className="hrp-safety-ribbon" data-tone={tone}/>
                <span className="hrp-safety-head">
                  <span className="hrp-safety-ic">{Icons[s.ic] || Icons.shield}</span>
                  <span style={{flex:1,minWidth:0,textAlign:"left"}}>
                    <span className="hrp-safety-t">{s.area}</span>
                    <span className="hrp-safety-m">{s.note}</span>
                  </span>
                  <Badge tone={tone}>{s.open} aperti</Badge>
                </span>
                <span className="hrp-safety-mini">
                  <span className="hrp-safety-cell">
                    <span className="hrp-safety-num">{s.ok}</span>
                    <span className="hrp-safety-lbl">In regola</span>
                  </span>
                  <span className="hrp-safety-cell">
                    <span className="hrp-safety-num" style={{color: tone==="danger" ? "#c53030" : tone==="warning" ? "#c2410c" : "#1f5fb3"}}>{s.open}</span>
                    <span className="hrp-safety-lbl">Da gestire</span>
                  </span>
                  <span className="hrp-safety-cell" style={{textAlign:"right"}}>
                    <span className="hrp-safety-num" style={{fontFamily:"ui-monospace,Menlo,monospace",fontSize:14}}>
                      {Math.round((s.ok/(s.ok+s.open))*100)}%
                    </span>
                    <span className="hrp-safety-lbl">Compliance</span>
                  </span>
                </span>
              </button>
              {exp && (
                <div className="hrp-safety-detail">
                  <div className="hrp-grid g4">
                    <HRPInfo label="Area" value={s.area}/>
                    <HRPInfo label="Owner" value="HR + HSE"/>
                    <HRPInfo label="Priorità" value={s.open > 7 ? "Alta" : s.open > 4 ? "Media" : "Pianificata"}/>
                    <HRPInfo label="Prossimo step" value="Crea attività"/>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <style>{`
        .hrp-safety-grid{ display:grid; grid-template-columns:repeat(2,1fr); gap:12px }
        .hrp-safety-card{
          position:relative; display:flex; flex-direction:column; gap:10px;
          padding:14px 16px 14px 18px; background:#fff; border:1px solid #e7edf3;
          border-radius:10px; cursor:pointer; font:inherit; text-align:left; width:100%;
          transition:transform .12s, box-shadow .12s, border-color .12s;
          box-shadow:0 1px 3px rgba(0,0,0,.04);
        }
        .hrp-safety-card:hover{ transform:translateY(-1px); box-shadow:0 6px 18px rgba(12,37,69,.08); border-color:#cfd8e3 }
        .hrp-safety-card.open{ border-color:#1f87cd; box-shadow:0 6px 18px rgba(31,135,205,.12) }
        .hrp-safety-ribbon{ position:absolute; left:0; top:14px; bottom:14px; width:3px; border-radius:0 3px 3px 0; background:#1f87cd }
        .hrp-safety-ribbon[data-tone="warning"]{ background:#ff8a1f }
        .hrp-safety-ribbon[data-tone="danger"]{ background:#dc2626 }
        .hrp-safety-head{ display:flex; align-items:center; gap:12px; width:100% }
        .hrp-safety-ic{
          width:38px; height:38px; flex:0 0 38px; border-radius:8px;
          background:#e8f3fb; color:#1f87cd;
          display:flex; align-items:center; justify-content:center;
        }
        .hrp-safety-t{ display:block; font-size:14px; font-weight:800; color:#0c2545 }
        .hrp-safety-m{ display:block; font-size:11px; color:#6b7a90; margin-top:1px }
        .hrp-safety-mini{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px;
                          background:#fafbfd; padding:10px 12px; border-radius:8px; }
        .hrp-safety-cell{ display:flex; flex-direction:column; gap:1px }
        .hrp-safety-num{ font-size:18px; font-weight:800; color:#0c2545; line-height:1.1 }
        .hrp-safety-lbl{ font-family:ui-monospace,Menlo,monospace; font-size:9.5px;
                         font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:#94a3b8 }
        .hrp-safety-detail{
          margin-top:8px; padding:12px 14px;
          background:linear-gradient(180deg,#f4f8fc 0,#fafbfd 100%);
          border:1px solid #e1e8f0; border-radius:10px; position:relative;
        }
        .hrp-safety-detail::before{
          content:""; position:absolute; left:14px; top:0; width:14px; height:3px; background:#ff8a1f;
        }
        @media (max-width: 1100px){ .hrp-safety-grid{ grid-template-columns:1fr } }
      `}</style>
    </>
  );
}

Object.assign(window, {
  HRP_PEOPLE, HRP_ABSENCES, HRP_TRAINING, HRP_DOCUMENTS, HRP_SAFETY,
  HRPPageHead, HRPSubTabs, HRPKpi, HRPInfo, HRPBar,
  PersonePage, AssenzePage, FormazionePage, DocumentiPage, SicurezzaPage,
});
