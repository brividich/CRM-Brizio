/* global React, Icons, Card, Stat, Badge, Button, Topbar, OctTile */

/* ────────── DASHBOARD ──────────
   Recreates Operativa landing: stats row, octagonal module tiles,
   recent anomalies/tickets list, plus a calendar-ish strip. */
function DashboardScreen({ onNav }) {
  const tiles = [
    { id:"anomalie", icon:Icons.warning,  label:"Anomalie" },
    { id:"ticket",   icon:Icons.ticket,   label:"Ticket"   },
    { id:"task",     icon:Icons.task,     label:"Task"     },
    { id:"asset",    icon:Icons.asset,    label:"Asset"    },
    { id:"persone",  icon:Icons.people,   label:"Persone"  },
    { id:"timbri",   icon:Icons.clock,    label:"Timbri"   },
    { id:"assenze",  icon:Icons.calendar, label:"Assenze"  },
    { id:"docs",     icon:Icons.doc,      label:"Documenti"},
  ];

  const anomalie = [
    { code:"#A-1284", title:"Pressione fuori soglia — Linea 3",  area:"Stabilimento Nord", time:"12 min fa", tone:"danger",  st:"Aperta" },
    { code:"#A-1283", title:"Vibrazione anomala compressore C2",  area:"Reparto utilities", time:"38 min fa", tone:"warning", st:"In analisi" },
    { code:"#A-1278", title:"Calo pressione circuito secondario", area:"Stabilimento Sud",  time:"2 ore fa",  tone:"warning", st:"In analisi" },
    { code:"#A-1271", title:"Soglia temperatura forno 4 superata",area:"Reparto fusione",   time:"4 ore fa",  tone:"success", st:"Risolta" },
  ];

  const tickets = [
    { code:"T-2041", title:"Sostituzione filtro aria CRT-09", owner:"M. Bianchi",  due:"Oggi 16:00", priority:"Alta",   tone:"danger" },
    { code:"T-2040", title:"Calibrazione bilancia BIL-03",     owner:"S. Greco",    due:"Domani",     priority:"Media",  tone:"warning" },
    { code:"T-2038", title:"Verifica chiusura valvola V-117",  owner:"L. Romano",   due:"Mer 28/04",  priority:"Bassa",  tone:"info" },
  ];

  return (
    <>
      <Topbar
        title="Buongiorno, Marco"
        sub="3 anomalie aperte richiedono la tua attenzione"
        actions={
          <>
            <Button variant="ghost" icon={Icons.refresh}>Aggiorna</Button>
            <Button icon={Icons.plus}>Nuovo ticket</Button>
          </>
        }/>

      <div className="grid-stats">
        <Stat tone="red"    icon={Icons.warning}  num="3"   label="Anomalie aperte"/>
        <Stat tone="orange" icon={Icons.ticket}   num="14"  label="Ticket attivi"/>
        <Stat tone="blue"   icon={Icons.task}     num="27"  label="Task in corso"/>
        <Stat tone="green"  icon={Icons.people}   num="142" label="Persone in turno"/>
      </div>

      <Card title="Moduli" action={<Button variant="ghost" size="sm">Personalizza</Button>}>
        <div className="grid-tiles">
          {tiles.map(t => <OctTile key={t.id} {...t} onClick={() => onNav?.(t.id)} />)}
        </div>
      </Card>

      <div className="grid-2">
        <Card
          title="Anomalie recenti"
          action={<button className="link" onClick={() => onNav?.("anomalie")}>Vedi tutte →</button>}
          padded={false}>
          <ul className="lst">
            {anomalie.map(a => (
              <li key={a.code} className="lst-row">
                <div className={`lst-dot dot-${a.tone}`}/>
                <div className="lst-main">
                  <div className="lst-t">
                    <span className="lst-code">{a.code}</span>
                    <span className="lst-title">{a.title}</span>
                  </div>
                  <div className="lst-meta">{a.area} · {a.time}</div>
                </div>
                <Badge tone={a.tone}>{a.st}</Badge>
              </li>
            ))}
          </ul>
        </Card>

        <Card
          title="Ticket prioritari"
          action={<button className="link" onClick={() => onNav?.("ticket")}>Tutti i ticket →</button>}
          padded={false}>
          <ul className="lst">
            {tickets.map(t => (
              <li key={t.code} className="lst-row">
                <div className="lst-tk">{t.code.slice(0, 1)}</div>
                <div className="lst-main">
                  <div className="lst-t">
                    <span className="lst-code">{t.code}</span>
                    <span className="lst-title">{t.title}</span>
                  </div>
                  <div className="lst-meta">{t.owner} · scadenza {t.due}</div>
                </div>
                <Badge tone={t.tone}>{t.priority}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <style>{`
        .grid-stats{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:18px }
        .grid-tiles{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px }
        .grid-2{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:18px }
        .lst{ list-style:none; margin:0; padding:0 }
        .lst-row{
          display:grid; grid-template-columns:6px 1fr auto;
          align-items:center; gap:12px;
          padding:12px 16px; border-bottom:1px solid #f0f3f7;
        }
        .lst-row:last-child{ border-bottom:none }
        .lst-dot{ width:6px; height:36px; border-radius:6px; background:#cbd5e0 }
        .lst-tk{ width:32px; height:32px; border-radius:8px; background:#fff4ed; color:#c2410c;
                 display:flex; align-items:center; justify-content:center;
                 font-weight:800; font-size:13px; font-family:ui-monospace,Menlo,monospace; flex:0 0 32px;
                 grid-row:1; grid-column:1 }
        .dot-danger{ background:#e53e3e }
        .dot-warning{ background:#f59e0b }
        .dot-info{ background:#1f5fb3 }
        .dot-success{ background:#38a169 }
        .lst-main{ min-width:0 }
        .lst-t{ display:flex; gap:8px; align-items:baseline }
        .lst-code{ font-family:ui-monospace,Menlo,monospace; font-size:11px; color:#94a3b8; font-weight:700 }
        .lst-title{ font-size:13px; font-weight:600; color:#1a202c;
                    overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
        .lst-meta{ font-size:11px; color:#94a3b8; margin-top:2px }
        .link{ background:none; border:none; color:#1f5fb3; font:inherit; font-size:12px;
               font-weight:600; cursor:pointer }
        .link:hover{ text-decoration:underline }
      `}</style>
    </>
  );
}

/* ────────── ANOMALIES TABLE ────────── */
function AnomalieScreen() {
  const rows = [
    ["#A-1284","Pressione fuori soglia — Linea 3","Stabilimento Nord","M. Rossi","26/04 09:48","Critica","Aperta","danger"],
    ["#A-1283","Vibrazione anomala compressore C2","Reparto utilities","S. Greco","26/04 09:22","Alta","In analisi","warning"],
    ["#A-1278","Calo pressione circuito secondario","Stabilimento Sud","L. Romano","26/04 07:55","Media","In analisi","warning"],
    ["#A-1271","Soglia temperatura forno 4 superata","Reparto fusione","M. Bianchi","26/04 06:10","Bassa","Risolta","success"],
    ["#A-1268","Allarme livello serbatoio S-22","Stoccaggio","A. Costa","25/04 22:14","Media","Chiusa","success"],
    ["#A-1265","Ritardo ciclo compressione CMP-02","Reparto utilities","E. Ferri","25/04 18:40","Bassa","Risolta","success"],
  ];
  return (
    <>
      <Topbar
        title="Anomalie"
        sub="Eventi rilevati dai sensori e dagli operatori sul campo"
        actions={
          <>
            <Button variant="ghost" icon={Icons.flag}>Filtri</Button>
            <Button icon={Icons.plus}>Segnala anomalia</Button>
          </>
        }/>

      <Card padded={false}>
        <div className="tbl-tools">
          <div className="tbl-tabs">
            <button className="tt active">Tutte <span>32</span></button>
            <button className="tt">Aperte <span>3</span></button>
            <button className="tt">In analisi <span>5</span></button>
            <button className="tt">Risolte <span>24</span></button>
          </div>
          <div className="tbl-search">
            {Icons.search}<input placeholder="Cerca anomalia, asset, area…"/>
          </div>
        </div>

        <table className="tbl">
          <thead><tr>
            <th>Codice</th><th>Anomalia</th><th>Area</th><th>Assegnata a</th>
            <th>Apertura</th><th>Priorità</th><th>Stato</th>
          </tr></thead>
          <tbody>
            {rows.map(r => (
              <tr key={r[0]}>
                <td><span className="cell-code">{r[0]}</span></td>
                <td className="cell-title">{r[1]}</td>
                <td>{r[2]}</td>
                <td>
                  <span className="cell-av">{r[3].split(". ")[1]?.[0] ?? r[3][0]}</span>
                  <span style={{marginLeft:8}}>{r[3]}</span>
                </td>
                <td className="muted">{r[4]}</td>
                <td><Badge tone={r[7]}>{r[5]}</Badge></td>
                <td><Badge tone={r[7]}>{r[6]}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <style>{`
        .tbl-tools{ display:flex; align-items:center; justify-content:space-between;
                    padding:10px 14px; border-bottom:1px solid #d7e0ea; gap:12px }
        .tbl-tabs{ display:flex; gap:4px }
        .tt{ background:transparent; border:none; padding:8px 12px; border-radius:8px;
             font:inherit; font-size:12px; font-weight:600; color:#4a5568; cursor:pointer;
             display:inline-flex; align-items:center; gap:8px }
        .tt span{ font-size:10px; color:#94a3b8;
                  background:#edf2f7; padding:2px 6px; border-radius:999px }
        .tt.active{ background:#fff4ed; color:#c2410c }
        .tt.active span{ background:#fed7aa; color:#9a3412 }
        .tbl-search{ display:flex; align-items:center; gap:8px;
                     padding:0 10px; height:34px; min-width:280px;
                     border:1px solid #d7e0ea; border-radius:8px; color:#94a3b8; background:#f4f6fb }
        .tbl-search input{ border:none; background:transparent; outline:none; flex:1; font:inherit; font-size:13px }
        .tbl{ width:100%; border-collapse:collapse; font-size:13px }
        .tbl th{ text-align:left; padding:10px 14px; font-size:11px; font-weight:700;
                 color:#94a3b8; text-transform:uppercase; letter-spacing:.04em;
                 border-bottom:1px solid #d7e0ea; background:#f4f6fb }
        .tbl td{ padding:12px 14px; border-bottom:1px solid #f0f3f7; vertical-align:middle }
        .tbl tr:last-child td{ border-bottom:none }
        .tbl tr:hover td{ background:#f9fafb }
        .cell-code{ font-family:ui-monospace,Menlo,monospace; font-size:12px; color:#4a5568; font-weight:700 }
        .cell-title{ font-weight:600; color:#1a202c }
        .cell-av{ display:inline-flex; width:24px; height:24px; border-radius:999px;
                  background:#1f5fb3; color:#fff; font-size:11px; font-weight:700;
                  align-items:center; justify-content:center; vertical-align:middle }
        .muted{ color:#94a3b8 }
      `}</style>
    </>
  );
}

/* ────────── TICKET DETAIL ────────── */
function TicketScreen() {
  return (
    <>
      <Topbar
        title="Ticket T-2041"
        sub="Sostituzione filtro aria CRT-09"
        actions={<>
          <Button variant="ghost">Riassegna</Button>
          <Button>Aggiorna stato</Button>
        </>}/>
      <div className="grid-2">
        <Card title="Dettagli intervento">
          <div className="kv">
            <div><dt>Asset</dt><dd>CRT-09 — Compressore aria principale</dd></div>
            <div><dt>Area</dt><dd>Stabilimento Nord — Reparto utilities</dd></div>
            <div><dt>Apertura</dt><dd>26/04/2026 alle 08:14 da L. Romano</dd></div>
            <div><dt>Scadenza</dt><dd>Oggi entro le 16:00</dd></div>
            <div><dt>Anomalia collegata</dt><dd>#A-1283 — Vibrazione anomala</dd></div>
          </div>
          <p className="ticket-desc">
            Sostituzione del filtro aria sul compressore CRT-09 a seguito di
            anomalia di vibrazione. Verificare anche tenuta condotti e lettura sensore VBR-02.
          </p>
          <div className="ticket-actions">
            <Button variant="cyan" size="sm">Apri checklist</Button>
            <Button variant="ghost" size="sm" icon={Icons.doc}>Allega documento</Button>
          </div>
        </Card>
        <Card title="Cronologia">
          <ul className="tl">
            <li><span className="tl-d dot-info"/>
              <div><b>Ticket aperto</b> da L. Romano<div className="tl-m">26/04 08:14</div></div></li>
            <li><span className="tl-d dot-warning"/>
              <div><b>Assegnato</b> a M. Bianchi<div className="tl-m">26/04 08:22</div></div></li>
            <li><span className="tl-d dot-info"/>
              <div><b>Materiale richiesto</b> — Filtro CRT-FA-09<div className="tl-m">26/04 09:05</div></div></li>
            <li><span className="tl-d dot-success"/>
              <div><b>In corso</b> — operatore in reparto<div className="tl-m">26/04 10:40</div></div></li>
          </ul>
        </Card>
      </div>
      <style>{`
        .kv{ display:flex; flex-direction:column; gap:6px; margin-bottom:10px }
        .kv > div{ display:grid; grid-template-columns:140px 1fr; gap:10px;
                   font-size:13px; line-height:1.5 }
        .kv dt{ color:#94a3b8; font-weight:600; margin:0 }
        .kv dd{ color:#1a202c; margin:0 }
        .ticket-desc{ font-size:13px; color:#4a5568; line-height:1.55; margin:8px 0 12px }
        .ticket-actions{ display:flex; gap:8px }
        .tl{ list-style:none; margin:0; padding:0 0 0 4px }
        .tl li{ display:flex; gap:12px; padding:8px 0; align-items:flex-start }
        .tl-d{ width:10px; height:10px; border-radius:999px; margin-top:5px; flex:0 0 10px }
        .tl-m{ font-size:11px; color:#94a3b8; margin-top:2px }
      `}</style>
    </>
  );
}

/* ────────── LOGIN SCREEN ──────────
   Mirrors auth/login.html: full-bleed navy bg, centered white card,
   orange accent, "CN NOVICROM HUB" lockup. */
function LoginScreen({ onLogin }) {
  const [pw, setPw] = React.useState("");
  const [show, setShow] = React.useState(false);
  return (
    <div className="lg-bg">
      <div className="lg-card">
        <div className="lg-brand">
          <div className="lg-mark">CN</div>
          <div>
            <div className="lg-name">NOVICROM HUB</div>
            <div className="lg-sub">Operativa</div>
          </div>
        </div>
        <h2 className="lg-title">Accedi al tuo account</h2>
        <p className="lg-cap">Inserisci le tue credenziali per accedere al portale.</p>

        <form className="lg-form" onSubmit={e => { e.preventDefault(); onLogin?.(); }}>
          <Field label="Email aziendale">
            <input type="email" defaultValue="marco.rossi@novicrom.it" />
          </Field>
          <Field label="Password">
            <div className="lg-pw">
              <input type={show ? "text" : "password"} value={pw}
                     onChange={e => setPw(e.target.value)} placeholder="••••••••"/>
              <button type="button" className="lg-eye" onClick={() => setShow(!show)} aria-label="Mostra password">
                {Icons.eye}
              </button>
            </div>
          </Field>
          <div className="lg-row">
            <label className="lg-rem"><input type="checkbox" defaultChecked/> Ricordami</label>
            <a href="#" className="lg-fp">Password dimenticata?</a>
          </div>
          <Button size="lg" style={{ width: "100%" }}>Entra nel portale</Button>
        </form>

        <div className="lg-foot">
          Hai problemi di accesso? <a href="#">Contatta IT</a>
        </div>
      </div>
      <div className="lg-version">v 2.4.1 · Novicrom Industries S.p.A.</div>

      <style>{`
        .lg-bg{
          min-height:100vh; display:flex; align-items:center; justify-content:center;
          padding:24px;
          background:
            radial-gradient(1200px 500px at 80% 0%, rgba(249,115,22,.18), transparent 60%),
            radial-gradient(900px 600px at 0% 100%, rgba(31,95,179,.32), transparent 70%),
            linear-gradient(180deg, #001b3a 0%, #002b5c 100%);
          position:relative;
        }
        .lg-card{
          width:100%; max-width:440px; background:#fff; border-radius:18px;
          padding:32px; box-shadow: 0 30px 80px rgba(0,0,0,.35);
        }
        .lg-brand{ display:flex; align-items:center; gap:12px; margin-bottom:24px }
        .lg-mark{ width:46px; height:46px; border-radius:12px; background:#002b5c; color:#fff;
                  display:flex; align-items:center; justify-content:center; font-weight:800; font-size:18px }
        .lg-name{ font-size:18px; font-weight:800; color:#0c2545 }
        .lg-sub{ font-size:11px; color:#94a3b8; letter-spacing:.08em; text-transform:uppercase; font-weight:600 }
        .lg-title{ margin:0 0 4px; font-size:22px; font-weight:800; color:#1a202c }
        .lg-cap{ margin:0 0 22px; font-size:13px; color:#4a5568 }
        .lg-form{ display:flex; flex-direction:column; gap:14px }
        .lg-pw{ position:relative }
        .lg-pw input{ width:100%; padding-right:42px; box-sizing:border-box }
        .lg-eye{ position:absolute; top:50%; right:6px; transform:translateY(-50%);
                 width:32px; height:32px; border-radius:6px; border:none; background:transparent;
                 color:#94a3b8; cursor:pointer; display:flex; align-items:center; justify-content:center }
        .lg-eye:hover{ background:#f4f6fb; color:#1a202c }
        .lg-row{ display:flex; align-items:center; justify-content:space-between; font-size:12px; margin-top:-2px }
        .lg-rem{ display:inline-flex; gap:8px; align-items:center; color:#4a5568 }
        .lg-fp{ color:#1f5fb3; text-decoration:none; font-weight:600 }
        .lg-fp:hover{ text-decoration:underline }
        .lg-foot{ text-align:center; font-size:12px; color:#94a3b8; margin-top:18px }
        .lg-foot a{ color:#1f5fb3; text-decoration:none; font-weight:600 }
        .lg-version{ position:absolute; bottom:18px; left:0; right:0; text-align:center;
                     color:rgba(255,255,255,.5); font-size:11px }
      `}</style>
    </div>
  );
}

Object.assign(window, { DashboardScreen, AnomalieScreen, TicketScreen, LoginScreen });
