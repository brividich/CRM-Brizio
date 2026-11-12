/* eslint-disable */
/* SORGENTE del bundle UI Gestione Anomalie.
   Estratto dallo <script type="text/babel"> inline e transpilato offline
   con @babel/preset-react in ../gestione_anomalie.bundle.js (committato).
   Per rigenerare: vedi tools/build_anomalie_ui.ps1. NON modificare il bundle a mano. */
const {
  useState,
  useEffect,
  useMemo,
  useRef
} = React;
const IS_ADMIN = window.IS_ADMIN;
const ADMIN_URL = window.ADMIN_URL || "";
const CONFIG_LISTS = window.ANOMALIE_CONFIG_LISTS || {};
const CURRENT_USER_NAME = String(window.CURRENT_USER_NAME || "").trim();
const CURRENT_USER_EMAIL = String(window.CURRENT_USER_EMAIL || "").trim();
const CURRENT_USER_NAME_NORMS = Array.isArray(window.CURRENT_USER_NAME_NORMS) ? window.CURRENT_USER_NAME_NORMS : [];
const API = window.ANOMALIE_API || {
  ordini: "/api/anomalie/ordini",
  anomalie: "/api/anomalie/anomalie",
  salva: "/api/anomalie/salva",
  allegati_list: "/api/anomalie/allegati",
  allegati_upload: "/api/anomalie/allegati/upload",
  allegati_delete: "/api/anomalie/allegati/delete",
  allegati_file: "/api/anomalie/allegati/file",
  segnalato: "/api/anomalie/segnalato",
  elimina: "/api/anomalie/elimina",
  sposta: "/api/anomalie/sposta",
  seriali_op: "/api/anomalie/seriali-op"
};
API.qualita_salva = API.qualita_salva || "/api/anomalie/qualita/salva";
API.qualita_richiedi_info = API.qualita_richiedi_info || "/api/anomalie/qualita/richiedi-info";
API.qualita_rispondi_info = API.qualita_rispondi_info || "/api/anomalie/qualita/rispondi-info";
const EDIT_NAME_WHITELIST = Array.isArray(CONFIG_LISTS.autorizzati_modifica) ? CONFIG_LISTS.autorizzati_modifica : [];
const ACCESS_CONTEXT = window.ANOMALIE_ACCESS || {};
// Decisione qualità (Configurazione): chi decide, scelte di «Avanzamento qualità»
// (più «nessuno stato») e se il capocommessa può chiudere da solo.
const CAN_QUALITA = !!ACCESS_CONTEXT.can_qualita;
const AVANZAMENTO_CHIARIMENTI = "In attesa chiarimenti";
const AVANZAMENTI_QUALITA = Array.isArray(ACCESS_CONTEXT.avanzamenti_qualita) && ACCESS_CONTEXT.avanzamenti_qualita.length ? ACCESS_CONTEXT.avanzamenti_qualita : ["In attesa", AVANZAMENTO_CHIARIMENTI];
const CC_PUO_CHIUDERE = ACCESS_CONTEXT.cc_puo_chiudere !== false;
const ROLE_ACCESS = ACCESS_CONTEXT.role_access || {};
const ACCESS_ORDER = {
  NONE: 0,
  READ_ALL: 1,
  EDIT_ASSIGNED: 2,
  EDIT_ALL: 3
};
const BASE_AVANZAMENTO_OPTIONS = Array.isArray(CONFIG_LISTS.avanzamenti) && CONFIG_LISTS.avanzamenti.length ? CONFIG_LISTS.avanzamenti : ["Accetto lo stato", "In attesa", "Finito trattato"];
const DEFAULT_AVANZAMENTO = BASE_AVANZAMENTO_OPTIONS[0] || "Accetto lo stato";
const normalizeChoice = value => String(value || "").trim();
const dedupeChoices = values => {
  const out = [];
  const seen = new Set();
  values.forEach(value => {
    const clean = normalizeChoice(value);
    if (!clean) return;
    const key = clean.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    out.push(clean);
  });
  return out;
};
const normalizeIdentity = value => String(value || "").trim().replace(/\s+/g, " ").toLowerCase();
const splitPeopleTokens = rawValue => String(rawValue || "").split(/[,\n;|]+/).map(part => String(part || "").trim().replace(/^["'\[\]()]+|["'\[\]()]+$/g, "")).filter(Boolean);
const USER_NAME_NORM = normalizeIdentity(CURRENT_USER_NAME);
const USER_NAME_NORMS = new Set([USER_NAME_NORM, ...CURRENT_USER_NAME_NORMS].filter(Boolean));
const EDIT_NAME_WHITELIST_SET = new Set(EDIT_NAME_WHITELIST.map(name => normalizeIdentity(name)));
const accessAtLeast = (level, minimum) => (ACCESS_ORDER[String(level || "NONE")] || 0) >= (ACCESS_ORDER[String(minimum || "NONE")] || 0);
const peopleMatchCurrentUser = rawPeople => {
  const tokens = splitPeopleTokens(rawPeople);
  if (!tokens.length || !USER_NAME_NORMS.size) return false;
  return tokens.some(token => USER_NAME_NORMS.has(normalizeIdentity(token)));
};
const QUERY_PARAMS = new URLSearchParams(window.location.search || "");
const INITIAL_FILTER = normalizeChoice(QUERY_PARAMS.get("filter")).toLowerCase();
// Di default solo gli OP con anomalie aperte: le chiuse restano sotto «Tutti».
const ACTIVE_FILTER = ["tutti", "aperte", "in_carico"].includes(INITIAL_FILTER) ? INITIAL_FILTER : "aperte";
// ?op=<titolo OP>: arrivo da un promemoria in dashboard o da una mail -> preseleziona l'OP.
const INITIAL_OP = normalizeChoice(QUERY_PARAMS.get("op")).toLowerCase();
const canUserEditOp = (opCapocommessa, opCar) => {
  if (IS_ADMIN) return true;
  if (ACCESS_CONTEXT.can_edit_all) return true;
  if (USER_NAME_NORM && EDIT_NAME_WHITELIST_SET.has(USER_NAME_NORM)) return true;
  const roleChecks = [["CC", opCapocommessa], ["CAR", opCar]];
  const globalLevel = String(ACCESS_CONTEXT.global_level || "NONE");
  if (accessAtLeast(globalLevel, "EDIT_ASSIGNED") && roleChecks.some(([, rawPeople]) => peopleMatchCurrentUser(rawPeople))) {
    return true;
  }
  for (const [roleCode, rawPeople] of roleChecks) {
    const roleLevel = String(ROLE_ACCESS[roleCode] || "NONE");
    if (!accessAtLeast(roleLevel, "EDIT_ASSIGNED")) continue;
    if (peopleMatchCurrentUser(rawPeople)) return true;
  }
  return false;
};

// «Segnalato al cliente/terzista» porta l'anomalia in attesa della risposta
// (resta aperta; quando arriva la risposta si sceglie lo stato definitivo).
const AVANZAMENTO_RISPOSTA_CLIENTE = "In attesa risposta cliente";
const AVANZAMENTO_RISPOSTA_TERZISTA = "In attesa risposta terzista";
const AVANZAMENTO_RISPOSTA = {
  cliente: AVANZAMENTO_RISPOSTA_CLIENTE,
  terzista: AVANZAMENTO_RISPOSTA_TERZISTA
};
const STATI_RISPOSTA = [AVANZAMENTO_RISPOSTA_CLIENTE.toLowerCase(), AVANZAMENTO_RISPOSTA_TERZISTA.toLowerCase()];
const DESTINATARI = [{
  chi: "cliente",
  segnalato: "Segnalato al cliente",
  risposta: "Risposta del cliente",
  tipo: "RISPOSTA_CLIENTE",
  a: "il cliente"
}, {
  chi: "terzista",
  segnalato: "Segnalato al terzista",
  risposta: "Risposta del terzista",
  tipo: "RISP_TERZISTA",
  a: "il terzista"
}];

// Risposta del referente RDC: rimanda l'anomalia al capocommessa con le spunte aperte.
const AVANZAMENTO_INFO_RICHIESTE = "In attesa di ulteriori informazioni";
const STATI_ATTESA = [...STATI_RISPOSTA, AVANZAMENTO_INFO_RICHIESTE.toLowerCase()];

// Regola PowerApps: la prima scelta cambia in base a "Aprire RDC?". Con RDC o
// cliente spuntati c'è anche «In attesa di ulteriori informazioni»; con il
// terzista «In attesa risposta terzista».
const buildAvanzamentoOptions = (isAprireRdc, conRdcOCliente = false, conTerzista = false) => {
  const dynamicFirst = isAprireRdc ? "Apertura ORE/RIPI" : "Azione di recupero";
  const dynamicAlt = isAprireRdc ? "Azione di recupero" : "Apertura ORE/RIPI";
  const sanitizedBase = BASE_AVANZAMENTO_OPTIONS.filter(opt => normalizeChoice(opt).toLowerCase() !== dynamicAlt.toLowerCase());
  return dedupeChoices([dynamicFirst, ...sanitizedBase, AVANZAMENTO_RISPOSTA_CLIENTE, ...(conTerzista ? [AVANZAMENTO_RISPOSTA_TERZISTA] : []), ...(conRdcOCliente ? [AVANZAMENTO_INFO_RICHIESTE] : [])]);
};

// Chiusura automatica, stessa regola del server (views.chiusura_automatica):
// attese e chiarimenti aperti la tengono aperta; «Segnalare…» chiede «Segnalato…»;
// con RDC si chiude col numero (lo scrive la qualità); senza RDC le segnalazioni
// fatte chiudono; senza spunte chiude lo stato, se il capocommessa può chiudere.
const shouldAutoClose = (isAprireRdc, avanzamentoValue, numeroRdc = "", segnalare = false, segnalatoFatto = false, terzista = false, segnalatoTerzista = false, chiarimenti = false) => {
  const avanz = normalizeChoice(avanzamentoValue).toLowerCase();
  if (STATI_ATTESA.includes(avanz) || chiarimenti) return false;
  if (segnalare && !segnalatoFatto) return false;
  if (terzista && !segnalatoTerzista) return false;
  if (isAprireRdc) return Boolean(String(numeroRdc || "").trim());
  if (segnalare || terzista) return true;
  return CC_PUO_CHIUDERE && (avanz === "accetto lo stato" || avanz === "apertura ore/ripi");
};
const richiestaAperta = (a, ruolo) => (a.richieste_info || []).some(r => r.aperta && (!ruolo || (r.destinatari || []).includes(ruolo)));
const ruoloSegnalato = (a, chi) => a && a[`segnalato_${chi}`] && a[`segnalato_${chi}`].ruolo || "cc";
const NOTA_STATO_MSG = "Hai scritto una nota: scegli anche lo stato di avanzamento, l'anomalia non può restare «In attesa».";
const RISPOSTA_STATO_MSG = "Hai scritto la risposta: scegli lo stato definitivo (oppure spunta «Chiudi l'anomalia»).";

// --- CSRF helper ---
const getCsrfToken = () => (document.cookie.split(';').find(c => c.trim().startsWith('csrftoken=')) || '').split('=')[1] || '';
const readJsonOrThrow = async (response, contextLabel) => {
  const ct = String(response.headers.get("content-type") || "").toLowerCase();
  if (!ct.includes("application/json")) {
    const text = await response.text();
    const looksHtml = /<!doctype html/i.test(text || "");
    const extra = looksHtml ? " (probabile redirect login/404)" : "";
    throw new Error(`${contextLabel}: risposta non JSON (HTTP ${response.status})${extra}`);
  }
  try {
    return await response.json();
  } catch (e) {
    throw new Error(`${contextLabel}: JSON non valido`);
  }
};
const formatBytes = value => {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let idx = 0;
  let n = bytes;
  while (n >= 1024 && idx < units.length - 1) {
    n /= 1024;
    idx += 1;
  }
  return `${n.toFixed(n >= 10 || idx === 0 ? 0 : 1)} ${units[idx]}`;
};
const fileExt = name => {
  const idx = String(name || "").lastIndexOf(".");
  return idx >= 0 ? String(name).slice(idx).toLowerCase() : "";
};

//â"€â"€â"€ Utility: colore per avanzamento â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
const snColor = avanz => {
  if (avanz === "Accetto lo stato") return "#10b981";
  if (avanz === "In attesa") return "#f59e0b";
  if (avanz === "Finito trattato") return "#6366f1";
  if (avanz === AVANZAMENTO_RISPOSTA_CLIENTE) return "#0ea5e9";
  if (avanz === AVANZAMENTO_RISPOSTA_TERZISTA) return "#0891b2";
  if (avanz === AVANZAMENTO_INFO_RICHIESTE) return "#f97316";
  return "#94a3b8";
};

// â"€â"€â"€ Componenti UI riutilizzabili â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
const StatusBadge = ({
  text,
  variant
}) => {
  const colors = {
    benestare: {
      bg: "#dcfce7",
      text: "#166534",
      border: "#86efac"
    },
    aperto: {
      bg: "#dbeafe",
      text: "#1e40af",
      border: "#93c5fd"
    },
    attesa: {
      bg: "#fef3c7",
      text: "#92400e",
      border: "#fcd34d"
    },
    accettato: {
      bg: "#d1fae5",
      text: "#065f46",
      border: "#6ee7b7"
    },
    chiuso: {
      bg: "#f3f4f6",
      text: "#374151",
      border: "#d1d5db"
    }
  };
  const c = colors[variant] || colors.aperto;
  return /*#__PURE__*/React.createElement("span", {
    className: "text-xs font-semibold",
    style: {
      display: "inline-block",
      padding: "2px 10px",
      borderRadius: "99px",
      fontWeight: 600,
      letterSpacing: "0.03em",
      background: c.bg,
      color: c.text,
      border: `1px solid ${c.border}`,
      textTransform: "uppercase",
      whiteSpace: "nowrap"
    }
  }, text);
};
const IconBtn = ({
  children,
  onClick,
  title,
  accent,
  disabled
}) => /*#__PURE__*/React.createElement("button", {
  className: "text-sm font-medium",
  onClick: onClick,
  title: title,
  disabled: disabled,
  style: {
    background: accent ? "var(--accent)" : "transparent",
    border: accent ? "none" : "1px solid var(--border)",
    borderRadius: 8,
    padding: accent ? "6px 14px" : "6px 8px",
    cursor: disabled ? "not-allowed" : "pointer",
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    color: accent ? "#fff" : "var(--text-mid)",
    fontWeight: 500,
    transition: "all 0.15s ease",
    opacity: disabled ? 0.6 : 1
  }
}, children);
const FieldLabel = ({
  children,
  required
}) => /*#__PURE__*/React.createElement("label", {
  className: "text-xs font-semibold",
  style: {
    display: "block",
    fontWeight: 600,
    color: "var(--text-light)",
    textTransform: "uppercase",
    letterSpacing: "0.06em",
    marginBottom: 6
  }
}, children, required && /*#__PURE__*/React.createElement("span", {
  style: {
    color: "#ef4444",
    marginLeft: 2
  }
}, "*"));

// ─── Percorso dell'anomalia: eventi veri con le date (api/anomalie/esiti) ───
// Segnalata → Decisa → (cliente) → (azione effettuata) → Chiusa; i passi che non
// riguardano l'anomalia non compaiono. Il primo passo senza data è quello in corso.
const PercorsoAnomalia = ({
  passi
}) => {
  if (!Array.isArray(passi) || !passi.length) return null;
  const quando = iso => iso ? new Date(iso).toLocaleString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }) : "";
  return /*#__PURE__*/React.createElement("ol", {
    className: "ga-percorso",
    "aria-label": "Percorso dell'anomalia"
  }, passi.map((p, i) => /*#__PURE__*/React.createElement("li", {
    key: p.chiave,
    className: `ga-percorso__passo is-${p.stato}`
  }, /*#__PURE__*/React.createElement("span", {
    className: "ga-percorso__dot"
  }, p.stato === "fatto" ? Ico.check : i + 1), /*#__PURE__*/React.createElement("span", {
    className: "ga-percorso__label"
  }, p.label), p.dettaglio ? /*#__PURE__*/React.createElement("span", {
    className: "ga-percorso__det"
  }, p.dettaglio) : null, /*#__PURE__*/React.createElement("span", {
    className: "ga-percorso__data"
  }, p.data ? quando(p.data) : p.stato === "attuale" ? "in corso" : ""))));
};

// â"€â"€â"€ Pannello timeline azioni OP (#2) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
// Consuma /api/anomalie/timeline (aggregata per OP). Lazy: carica al cambio OP.
// ─── Tempi ed esiti dell'anomalia: risposta del cliente, azione effettuata ───
// Tempi in giorni lavorativi (anomalie/tempi_service.py); gli allegati degli esiti
// finiscono nella cartella dell'anomalia, insieme agli altri.
const AZIONI_EFFETTUATE = Array.isArray(CONFIG_LISTS.azioni_effettuate) && CONFIG_LISTS.azioni_effettuate.length ? CONFIG_LISTS.azioni_effettuate : ["Rilavorato", "Riparato", "Scartato", "Reso al fornitore", "Accettato in deroga"];
const ESITI_ACCEPT = ".jpg,.jpeg,.png,.gif,.bmp,.webp,.pdf,.doc,.docx,.xls,.xlsx,.xlsm,.csv,.msg,.eml,.txt";
const chiedeRiverifica = azione => /rilavor|ripar/i.test(String(azione || ""));
const FileEsito = ({
  files,
  setFiles,
  disabled
}) => {
  const ref = useRef(null);
  const [over, setOver] = useState(false);
  const aggiungi = lista => setFiles(prev => {
    const next = [...prev];
    lista.forEach(f => {
      if (!next.some(x => x.name === f.name && x.size === f.size)) next.push(f);
    });
    return next;
  });
  return /*#__PURE__*/React.createElement("div", {
    className: `ga-att ga-att--esito${over ? " is-over" : ""}`,
    tabIndex: disabled ? -1 : 0,
    onDragOver: e => {
      if (disabled) return;
      e.preventDefault();
      setOver(true);
    },
    onDragLeave: () => setOver(false),
    onDrop: e => {
      e.preventDefault();
      setOver(false);
      if (!disabled) aggiungi(Array.from(e.dataTransfer.files || []));
    },
    onPaste: e => {
      const fs = Array.from(e.clipboardData && e.clipboardData.items || []).filter(it => it.kind === "file").map(it => it.getAsFile()).filter(Boolean);
      if (fs.length && !disabled) {
        e.preventDefault();
        aggiungi(nomeAppunti(fs));
      }
    }
  }, /*#__PURE__*/React.createElement("input", {
    ref: ref,
    type: "file",
    multiple: true,
    hidden: true,
    accept: ESITI_ACCEPT,
    onChange: e => {
      const f = Array.from(e.target.files || []);
      e.target.value = "";
      aggiungi(f);
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "ga-att__head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ga-card__sub"
  }, Ico.clip, " Allegati ", files.length ? `(${files.length})` : ""), /*#__PURE__*/React.createElement("span", {
    className: "ga-hint"
  }, "Mail (.msg, .eml), foto, PDF: trascina, ", /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-link",
    disabled: disabled,
    onClick: () => ref.current && ref.current.click()
  }, "sfoglia"), " o clicca e premi Ctrl+V")), files.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "ga-esito__files"
  }, files.map((f, i) => /*#__PURE__*/React.createElement("span", {
    key: f.name + i,
    className: "ga-esito__file"
  }, f.name, " ", /*#__PURE__*/React.createElement("span", {
    className: "ga-hint"
  }, formatBytes(f.size)), /*#__PURE__*/React.createElement("button", {
    type: "button",
    "aria-label": `Togli ${f.name}`,
    onClick: () => setFiles(prev => prev.filter((_, j) => j !== i))
  }, "\xD7")))));
};

// Titolo di una sezione del dettaglio: un clic la chiude o la riapre.
const TitoloSezione = ({
  chiusa,
  onToggle,
  children
}) => /*#__PURE__*/React.createElement("button", {
  type: "button",
  className: "ga-card__title ga-sez-tg",
  "aria-expanded": !chiusa,
  onClick: onToggle,
  title: chiusa ? "Apri la sezione" : "Chiudi la sezione"
}, /*#__PURE__*/React.createElement("span", {
  className: `ga-sez-tg__ico${chiusa ? "" : " is-aperta"}`,
  "aria-hidden": "true"
}, "\u203A"), children);
const EsitiAnomalia = ({
  localId,
  avanzamento,
  chiusa,
  segnalare,
  versione,
  onSaved,
  onInfo,
  flash,
  sezChiusa,
  onToggleSez
}) => {
  const [data, setData] = useState(null);
  const [saving, setSaving] = useState(false);
  const [azioneAperta, setAzioneAperta] = useState(false);
  const [azione, setAzione] = useState("");
  const [notaAzione, setNotaAzione] = useState("");
  const [filesAzione, setFilesAzione] = useState([]);
  const [riverificato, setRiverificato] = useState(false);
  const [chiudi, setChiudi] = useState(true);
  const carica = () => {
    if (!localId || !API.esiti) {
      setData(null);
      if (onInfo) onInfo(null);
      return;
    }
    fetch(`${API.esiti}?local_id=${encodeURIComponent(localId)}`, {
      credentials: "same-origin"
    }).then(r => r.ok ? r.json() : null).then(d => {
      setData(d && d.success ? d : null);
      if (onInfo) onInfo(d && d.success ? d : null);
    }).catch(() => setData(null));
  };
  useEffect(() => {
    setAzione("");
    setNotaAzione("");
    setFilesAzione([]);
    setRiverificato(false);
    setChiudi(true);
    setAzioneAperta(false);
    carica();
  }, [localId, avanzamento, chiusa, segnalare, versione]);
  if (!data) return null;
  const urlFile = fileId => `${API.allegati_file}?local_id=${encodeURIComponent(localId)}&file_id=${encodeURIComponent(fileId)}`;
  const soglia = k => (data.soglie || {})[k];
  const oltre = t => t.in_corso && soglia(t.chiave) && t.giorni > soglia(t.chiave);
  const puoi = data.can_registrare && !data.chiusa;
  const mostraAzione = puoi && (data.recupero || azioneAperta);
  const serveRiverifica = chiudi && chiedeRiverifica(azione) && !riverificato;
  const invia = async tipo => {
    const form = new FormData();
    form.append("local_id", String(localId));
    form.append("tipo", tipo);
    form.append("azione", azione);
    form.append("testo", notaAzione);
    form.append("riverificato", riverificato ? "1" : "");
    form.append("chiudi", chiudi ? "1" : "");
    filesAzione.forEach(f => form.append("files", f));
    setSaving(true);
    try {
      const r = await fetch(API.esito, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCsrfToken()
        },
        body: form,
        credentials: "same-origin"
      });
      const d = await readJsonOrThrow(r, "Registrazione esito");
      if (!r.ok || !d.success) throw new Error(d.error || `HTTP ${r.status}`);
      const avvisi = (d.errors || []).length ? ` · file non salvati: ${d.errors.join("; ")}` : "";
      flash({
        ok: !avvisi,
        text: (d.chiusa ? "Azione effettuata registrata · anomalia chiusa" : "Azione effettuata registrata") + avvisi
      }, avvisi ? 8000 : 4500);
      if (onSaved) onSaved({
        chiusa: !!d.chiusa
      });
      carica();
      setAzione("");
      setNotaAzione("");
      setFilesAzione([]);
      setRiverificato(false);
      setAzioneAperta(false);
    } catch (e) {
      flash({
        ok: false,
        text: "Errore: " + e.message
      }, 7000);
    }
    setSaving(false);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: `ga-card ga-card--esiti${sezChiusa ? " is-chiusa" : ""}`
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-card__head"
  }, /*#__PURE__*/React.createElement(TitoloSezione, {
    chiusa: sezChiusa,
    onToggle: onToggleSez
  }, "Tempi ed esiti"), /*#__PURE__*/React.createElement("span", {
    className: "ga-hint"
  }, data.unita || "ore lavorate, giorni lavorativi")), data.tempi && data.tempi.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "ga-tempi"
  }, data.tempi.map(t => /*#__PURE__*/React.createElement("span", {
    key: t.chiave,
    className: `ga-tempo${t.in_corso ? " is-corso" : ""}${oltre(t) ? " is-oltre" : ""}`,
    title: oltre(t) ? `Oltre l'obiettivo di ${soglia(t.chiave)} giorni lavorativi` : ""
  }, /*#__PURE__*/React.createElement("span", {
    className: "ga-tempo__l"
  }, t.label), /*#__PURE__*/React.createElement("b", null, t.testo), t.in_corso ? /*#__PURE__*/React.createElement("span", {
    className: "ga-tempo__c"
  }, "in corso") : null))), data.esiti && data.esiti.length > 0 && /*#__PURE__*/React.createElement("ol", {
    className: "ga-esiti"
  }, data.esiti.map(e => /*#__PURE__*/React.createElement("li", {
    key: e.id,
    className: "ga-esito"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-esito__head"
  }, /*#__PURE__*/React.createElement("b", null, e.tipo === "AZIONE" ? `Azione effettuata: ${e.azione}` : e.tipo === "RISP_TERZISTA" ? "Risposta del terzista" : "Risposta del cliente"), e.riverificato && /*#__PURE__*/React.createElement("span", {
    className: "ga-pill ga-pill--chiuso"
  }, "Riverificato conforme"), e.chiusa && /*#__PURE__*/React.createElement("span", {
    className: "ga-pill ga-pill--muted"
  }, "Ha chiuso l'anomalia"), /*#__PURE__*/React.createElement("span", {
    className: "ga-hint ga-esito__chi"
  }, e.utente, " \xB7 ", e.data ? new Date(e.data).toLocaleString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }) : "")), e.testo && /*#__PURE__*/React.createElement("div", {
    className: "ga-esito__testo"
  }, e.testo), e.allegati.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "ga-esito__files"
  }, e.allegati.map(f => /*#__PURE__*/React.createElement("a", {
    key: f.file_id,
    className: "ga-esito__file",
    href: urlFile(f.file_id),
    target: "_blank",
    rel: "noopener"
  }, Ico.clip, " ", f.name)))))), puoi && !mostraAzione && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-link ga-esito-apri",
    onClick: () => setAzioneAperta(true)
  }, "+ Registra un'azione effettuata"), mostraAzione && /*#__PURE__*/React.createElement("div", {
    className: "ga-esito-form"
  }, data.serve_azione && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--info"
  }, "Decisione \xABAzione di recupero\xBB: l'anomalia si chiude registrando qui l'azione effettuata."), /*#__PURE__*/React.createElement("div", {
    className: "ga-grid2"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, {
    required: true
  }, "Azione effettuata"), /*#__PURE__*/React.createElement("select", {
    className: "ga-input",
    value: azione,
    onChange: e => setAzione(e.target.value),
    disabled: saving
  }, /*#__PURE__*/React.createElement("option", {
    value: ""
  }, "Scegli\u2026"), AZIONI_EFFETTUATE.map(a => /*#__PURE__*/React.createElement("option", {
    key: a
  }, a)))), /*#__PURE__*/React.createElement("div", {
    className: "ga-esito-form__flags"
  }, /*#__PURE__*/React.createElement(FlagToggle, {
    label: "Pezzo riverificato conforme",
    checked: riverificato,
    disabled: saving,
    onChange: () => setRiverificato(!riverificato)
  }), /*#__PURE__*/React.createElement(FlagToggle, {
    label: "Chiudi l'anomalia",
    checked: chiudi,
    disabled: saving,
    onChange: () => setChiudi(!chiudi)
  }))), /*#__PURE__*/React.createElement("textarea", {
    className: "ga-input",
    rows: 2,
    value: notaAzione,
    onChange: e => setNotaAzione(e.target.value),
    disabled: saving,
    placeholder: "Note: cosa \xE8 stato fatto, da chi, riferimenti\u2026"
  }), /*#__PURE__*/React.createElement(FileEsito, {
    files: filesAzione,
    setFiles: setFilesAzione,
    disabled: saving
  }), serveRiverifica && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--warn"
  }, "Dopo una rilavorazione o riparazione, per chiudere spunta \xABPezzo riverificato conforme\xBB."), /*#__PURE__*/React.createElement("div", {
    className: "ga-esito-form__acts"
  }, !data.recupero && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--ghost",
    disabled: saving,
    onClick: () => setAzioneAperta(false)
  }, "Annulla"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--outline",
    disabled: saving || !azione || serveRiverifica,
    onClick: () => invia("AZIONE")
  }, saving ? "Salvataggio…" : chiudi ? "Registra e chiudi" : "Registra azione"))));
};
const TimelineOp = ({
  opId,
  opItemId
}) => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    if (!opId && !opItemId) {
      setItems([]);
      return;
    }
    if (!API.timeline) return;
    setLoading(true);
    const qs = new URLSearchParams();
    if (opId) qs.set("op_id", opId);
    if (opItemId) qs.set("op_item_id", opItemId);
    fetch(`${API.timeline}?${qs.toString()}`, {
      credentials: "same-origin"
    }).then(r => r.json()).then(d => {
      setItems(Array.isArray(d.items) ? d.items : []);
      setLoading(false);
    }).catch(() => {
      setItems([]);
      setLoading(false);
    });
  }, [open, opId, opItemId]);
  const sourceColor = s => s === "mail_action" ? "#6366f1" : s === "system" ? "#64748b" : "#0ea5e9";
  return /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 20,
      border: "1px solid var(--border)",
      borderRadius: 10,
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => setOpen(v => !v),
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      width: "100%",
      padding: "10px 14px",
      background: "var(--bg)",
      border: "none",
      cursor: "pointer",
      color: "var(--text-mid)"
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2.5",
    viewBox: "0 0 24 24",
    style: {
      transform: open ? "none" : "rotate(-90deg)",
      transition: "transform .15s"
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M6 9l6 6 6-6"
  })), /*#__PURE__*/React.createElement("span", {
    className: "text-sm font-semibold",
    style: {
      fontWeight: 600
    }
  }, "Cronologia azioni", items.length ? ` (${items.length})` : "")), open && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "8px 14px 12px",
      maxHeight: 320,
      overflowY: "auto"
    }
  }, loading ? /*#__PURE__*/React.createElement("div", {
    className: "text-sm",
    style: {
      padding: 12,
      textAlign: "center",
      color: "#94a3b8"
    }
  }, "Caricamento\u2026") : items.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "text-sm",
    style: {
      padding: 12,
      textAlign: "center",
      color: "#94a3b8"
    }
  }, "Nessuna azione registrata per questo OP.") : items.map(it => /*#__PURE__*/React.createElement("div", {
    key: it.id,
    style: {
      display: "flex",
      gap: 10,
      padding: "8px 0",
      borderBottom: "1px solid var(--border)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 8,
      height: 8,
      borderRadius: "50%",
      marginTop: 6,
      flexShrink: 0,
      background: sourceColor(it.source)
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: 8,
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "text-sm font-semibold",
    style: {
      fontWeight: 600,
      color: "var(--text)"
    }
  }, it.action_label), it.previous_status && it.new_status && it.previous_status !== it.new_status && /*#__PURE__*/React.createElement("span", {
    className: "text-2xs",
    style: {
      color: "var(--text-mid)"
    }
  }, it.previous_status, " \u2192 ", it.new_status), /*#__PURE__*/React.createElement("span", {
    className: "text-2xs",
    style: {
      marginLeft: "auto",
      color: "#94a3b8"
    }
  }, it.created_at)), /*#__PURE__*/React.createElement("div", {
    className: "text-2xs",
    style: {
      color: "#94a3b8",
      marginTop: 2
    }
  }, it.user, it.source_label ? ` · ${it.source_label}` : "", it.anomalia_id ? ` · #${it.anomalia_id}` : ""), it.note && /*#__PURE__*/React.createElement("div", {
    className: "text-2xs",
    style: {
      color: "var(--text-mid)",
      marginTop: 2
    }
  }, it.note))))));
};

// --- Scheda qualita' della singola anomalia (classificazione, NC dell'OP, proposta AI) ---
// Consuma /api/anomalie/qualita (GET crea la scheda al primo accesso) e
// /api/anomalie/qualita/copilota (proposta AI, non salva nulla).
const GRAVITA_COLORS = {
  MINORE: {
    bg: "var(--success-bg)",
    fg: "var(--success)"
  },
  MAGGIORE: {
    bg: "var(--warning-bg)",
    fg: "var(--warning)"
  },
  CRITICA: {
    bg: "var(--danger-bg)",
    fg: "var(--danger)"
  }
};
const qInputStyle = enabled => ({
  width: "100%",
  padding: "8px 12px",
  border: "1px solid var(--border)",
  borderRadius: 8,
  color: "var(--text)",
  background: enabled ? "var(--surface)" : "var(--bg)",
  outline: "none",
  cursor: enabled ? "auto" : "not-allowed",
  opacity: enabled ? 1 : 0.8
});
const SCHEDA_FIELDS = ["origine", "tipo_difetto", "gravita", "reparto", "quantita_nc", "quantita_scartata", "disposizione"];
const SchedaQualita = ({
  localId,
  canEdit,
  reloadKey,
  isMobile
}) => {
  const [scheda, setScheda] = useState(null);
  const [scelte, setScelte] = useState(null);
  const [draft, setDraft] = useState({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const [ai, setAi] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [serverCanEdit, setServerCanEdit] = useState(false);
  const toDraft = s => {
    const d = {};
    SCHEDA_FIELDS.forEach(k => {
      d[k] = s && s[k] != null ? String(s[k]) : "";
    });
    return d;
  };
  useEffect(() => {
    setAi(null);
    setMsg(null);
    if (!localId || !API.qualita) {
      setScheda(null);
      return;
    }
    let alive = true;
    setLoading(true);
    fetch(`${API.qualita}?local_id=${encodeURIComponent(localId)}`, {
      credentials: "same-origin"
    }).then(r => readJsonOrThrow(r, "Scheda qualità")).then(d => {
      if (!alive) return;
      if (!d.success) throw new Error(d.error || "Scheda non disponibile");
      setScheda(d.scheda);
      setScelte(d.scelte);
      setDraft(toDraft(d.scheda));
      setServerCanEdit(!!d.can_edit);
    }).catch(e => {
      if (alive) {
        setScheda(null);
        setMsg({
          ok: false,
          text: e.message
        });
      }
    }).finally(() => {
      if (alive) setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [localId, reloadKey]);

  // Tipi difetto raggruppati per famiglia (optgroup). Hook PRIMA di ogni return.
  const famiglie = useMemo(() => {
    const out = [];
    (scelte && scelte.tipi_difetto || []).forEach(t => {
      const fam = t.famiglia || "Altro";
      let g = out.find(x => x.fam === fam);
      if (!g) {
        g = {
          fam,
          items: []
        };
        out.push(g);
      }
      g.items.push(t);
    });
    return out;
  }, [scelte]);
  if (!localId) {
    return /*#__PURE__*/React.createElement("div", {
      className: "text-sm",
      style: {
        marginTop: 20,
        padding: "12px 14px",
        border: "1px dashed var(--border)",
        borderRadius: 10,
        color: "var(--text-light)"
      }
    }, "Scheda qualit\xE0: disponibile dopo il primo salvataggio della segnalazione.");
  }
  const editable = canEdit && serverCanEdit && !!scheda;
  const dirty = scheda && SCHEDA_FIELDS.some(k => (draft[k] || "") !== (scheda[k] != null ? String(scheda[k]) : ""));
  const set = k => e => setDraft(prev => ({
    ...prev,
    [k]: e.target.value
  }));
  const flash = m => {
    setMsg(m);
    setTimeout(() => setMsg(null), 4000);
  };
  const save = async () => {
    setSaving(true);
    try {
      const body = {
        local_id: localId
      };
      SCHEDA_FIELDS.forEach(k => {
        body[k] = draft[k] === "" ? null : draft[k];
      });
      const r = await fetch(API.qualita, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken()
        },
        body: JSON.stringify(body)
      });
      const d = await readJsonOrThrow(r, "Salvataggio scheda qualità");
      if (!d.success) throw new Error(d.error || "Salvataggio non riuscito");
      setScheda(d.scheda);
      setDraft(toDraft(d.scheda));
      flash({
        ok: true,
        text: "Scheda salvata"
      });
    } catch (e) {
      flash({
        ok: false,
        text: e.message
      });
    }
    setSaving(false);
  };
  const askAi = async () => {
    setAiLoading(true);
    setAi(null);
    try {
      const r = await fetch(API.qualita_copilota, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken()
        },
        body: JSON.stringify({
          local_id: localId
        })
      });
      const d = await readJsonOrThrow(r, "Proposta AI");
      if (!r.ok || !d.success) throw new Error(d.error || "Proposta non disponibile");
      setAi(d.proposta);
    } catch (e) {
      flash({
        ok: false,
        text: e.message
      });
    }
    setAiLoading(false);
  };
  const applyAi = () => {
    if (!ai) return;
    setDraft(prev => ({
      ...prev,
      tipo_difetto: ai.tipo_difetto != null ? String(ai.tipo_difetto) : prev.tipo_difetto,
      gravita: ai.gravita || prev.gravita
    }));
  };
  const label = (list, value) => {
    const hit = (list || []).find(o => String(o.value) === String(value));
    return hit ? hit.label : "";
  };
  const nc = scheda && scheda.nc;
  const grav = GRAVITA_COLORS[draft.gravita] || null;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 20,
      border: "1px solid var(--border)",
      borderRadius: 12,
      background: "var(--surface)",
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 10,
      flexWrap: "wrap",
      padding: "12px 16px",
      background: "var(--bg)",
      borderBottom: "1px solid var(--border)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "text-sm font-semibold",
    style: {
      fontWeight: 700,
      color: "var(--text)"
    }
  }, "Scheda qualit\xE0"), grav && /*#__PURE__*/React.createElement("span", {
    className: "text-2xs font-semibold",
    style: {
      padding: "2px 8px",
      borderRadius: 99,
      background: grav.bg,
      color: grav.fg,
      fontWeight: 700,
      textTransform: "uppercase"
    }
  }, label(scelte && scelte.gravita, draft.gravita)), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: "auto"
    }
  }), nc && /*#__PURE__*/React.createElement("a", {
    href: nc.url || "#",
    target: "_blank",
    rel: "noopener",
    className: "text-xs font-semibold",
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      padding: "3px 10px",
      borderRadius: 99,
      textDecoration: "none",
      fontWeight: 700,
      background: nc.chiusa ? "var(--success-bg)" : "var(--warning-bg)",
      color: nc.chiusa ? "var(--success)" : "var(--warning)"
    },
    title: "Non conformit\xE0 dell'OP: contenimento, analisi, azioni e verifica"
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "ui-monospace,monospace"
    }
  }, nc.protocollo), " \xB7 ", nc.stato_label)), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "14px 16px"
    }
  }, loading ? /*#__PURE__*/React.createElement("div", {
    className: "text-sm",
    style: {
      color: "var(--text-light)"
    }
  }, "Caricamento scheda\u2026") : !scheda ? /*#__PURE__*/React.createElement("div", {
    className: "text-sm",
    style: {
      color: "var(--danger)"
    }
  }, msg && msg.text || "Scheda non disponibile.") : /*#__PURE__*/React.createElement(React.Fragment, null, scheda.part_number && /*#__PURE__*/React.createElement("div", {
    className: "text-xs",
    style: {
      color: "var(--text-light)",
      marginBottom: 10
    }
  }, "P/N registrato: ", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "ui-monospace,monospace",
      color: "var(--text-mid)"
    }
  }, scheda.part_number)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: isMobile ? "1fr" : "repeat(3, minmax(0,1fr))",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      gridColumn: isMobile ? "auto" : "span 2"
    }
  }, /*#__PURE__*/React.createElement(FieldLabel, null, "Tipo difetto"), /*#__PURE__*/React.createElement("select", {
    value: draft.tipo_difetto || "",
    onChange: set("tipo_difetto"),
    disabled: !editable,
    style: qInputStyle(editable)
  }, /*#__PURE__*/React.createElement("option", {
    value: ""
  }, "\u2014 da classificare \u2014"), famiglie.map(g => /*#__PURE__*/React.createElement("optgroup", {
    key: g.fam,
    label: g.fam
  }, g.items.map(t => /*#__PURE__*/React.createElement("option", {
    key: t.value,
    value: String(t.value)
  }, t.label)))), draft.tipo_difetto && !(scelte && scelte.tipi_difetto || []).some(t => String(t.value) === draft.tipo_difetto) && /*#__PURE__*/React.createElement("option", {
    value: draft.tipo_difetto
  }, scheda.tipo_difetto_label || "Tipo disattivato"))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "Gravit\xE0"), /*#__PURE__*/React.createElement("select", {
    value: draft.gravita || "",
    onChange: set("gravita"),
    disabled: !editable,
    style: qInputStyle(editable)
  }, /*#__PURE__*/React.createElement("option", {
    value: ""
  }, "\u2014 da valutare \u2014"), (scelte && scelte.gravita || []).map(o => /*#__PURE__*/React.createElement("option", {
    key: o.value,
    value: o.value
  }, o.label)))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "Origine"), /*#__PURE__*/React.createElement("select", {
    value: draft.origine || "",
    onChange: set("origine"),
    disabled: !editable,
    style: qInputStyle(editable)
  }, /*#__PURE__*/React.createElement("option", {
    value: ""
  }, "\u2014"), (scelte && scelte.origini || []).map(o => /*#__PURE__*/React.createElement("option", {
    key: o.value,
    value: o.value
  }, o.label)))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "Reparto"), /*#__PURE__*/React.createElement("select", {
    value: draft.reparto || "",
    onChange: set("reparto"),
    disabled: !editable,
    style: qInputStyle(editable)
  }, /*#__PURE__*/React.createElement("option", {
    value: ""
  }, "\u2014"), (scelte && scelte.reparti || []).map(o => /*#__PURE__*/React.createElement("option", {
    key: o.value,
    value: String(o.value)
  }, o.label)))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "Decisione sul materiale"), /*#__PURE__*/React.createElement("select", {
    value: draft.disposizione || "",
    onChange: set("disposizione"),
    disabled: !editable,
    style: qInputStyle(editable)
  }, (scelte && scelte.disposizioni || []).map(o => /*#__PURE__*/React.createElement("option", {
    key: o.value,
    value: o.value
  }, o.label))), scheda.disposizione_auto && !dirty && /*#__PURE__*/React.createElement("div", {
    className: "text-2xs",
    style: {
      color: "var(--text-light)",
      marginTop: 4
    }
  }, "Dedotta da RDC/avanzamento: cambiala se serve.")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "Q.t\xE0 non conforme"), /*#__PURE__*/React.createElement("input", {
    type: "number",
    min: "0",
    value: draft.quantita_nc || "",
    onChange: set("quantita_nc"),
    disabled: !editable,
    style: qInputStyle(editable)
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "Q.t\xE0 scartata"), /*#__PURE__*/React.createElement("input", {
    type: "number",
    min: "0",
    value: draft.quantita_scartata || "",
    onChange: set("quantita_scartata"),
    disabled: !editable,
    style: qInputStyle(editable)
  }))), ai && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 14,
      padding: "12px 14px",
      borderRadius: 10,
      border: "1px solid var(--border)",
      background: "var(--bg)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      flexWrap: "wrap",
      marginBottom: 6
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "text-xs font-semibold",
    style: {
      fontWeight: 700,
      color: "var(--text)",
      textTransform: "uppercase",
      letterSpacing: "0.05em"
    }
  }, "Proposta ", ai.fonte === "simili" ? "dai casi simili" : "AI"), !ai.ai_disponibile && /*#__PURE__*/React.createElement("span", {
    className: "text-2xs",
    style: {
      color: "var(--text-light)"
    }
  }, "AI non raggiungibile"), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: "auto"
    }
  }), editable && (ai.tipo_difetto != null || ai.gravita) && /*#__PURE__*/React.createElement(IconBtn, {
    onClick: applyAi,
    title: "Copia tipo difetto e gravit\xE0 nel form (poi salva)"
  }, "Applica al form")), /*#__PURE__*/React.createElement("div", {
    className: "text-sm",
    style: {
      color: "var(--text-mid)",
      display: "grid",
      gap: 4
    }
  }, /*#__PURE__*/React.createElement("div", null, "Tipo difetto: ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: "var(--text)"
    }
  }, label(scelte && scelte.tipi_difetto, ai.tipo_difetto) || "—"), " · ", "Gravit\xE0: ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: "var(--text)"
    }
  }, label(scelte && scelte.gravita, ai.gravita) || "—")), ai.causa_probabile && /*#__PURE__*/React.createElement("div", null, "Causa probabile (da verificare): ", ai.causa_probabile), ai.motivazione && /*#__PURE__*/React.createElement("div", {
    style: {
      color: "var(--text-light)"
    }
  }, ai.motivazione)), Array.isArray(ai.simili) && ai.simili.length > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "text-2xs font-semibold",
    style: {
      color: "var(--text-light)",
      textTransform: "uppercase",
      letterSpacing: "0.05em",
      marginBottom: 4
    }
  }, "Casi simili"), ai.simili.map(c => /*#__PURE__*/React.createElement("div", {
    key: c.anomalia_id || c.protocollo,
    className: "text-xs",
    style: {
      color: "var(--text-mid)",
      padding: "3px 0",
      borderTop: "1px solid var(--border)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "ui-monospace,monospace",
      color: "var(--text)"
    }
  }, c.protocollo), " · ", c.tipo_difetto_label, c.part_number ? ` · P/N ${c.part_number}` : "", " \u2014 ", c.descrizione)))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      marginTop: 14,
      flexWrap: "wrap"
    }
  }, msg && /*#__PURE__*/React.createElement("span", {
    className: "text-sm font-semibold",
    style: {
      color: msg.ok ? "var(--success)" : "var(--danger)",
      fontWeight: 600
    }
  }, msg.text), !msg && aiLoading && /*#__PURE__*/React.createElement("span", {
    className: "text-sm",
    style: {
      color: "var(--text-light)"
    }
  }, "L'AI sta analizzando la segnalazione: pu\xF2 servire anche un minuto."), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: "auto"
    }
  }), editable && API.qualita_copilota && /*#__PURE__*/React.createElement(IconBtn, {
    onClick: askAi,
    disabled: aiLoading,
    title: "Proposta di tipo difetto, gravit\xE0 e causa probabile (non salva nulla)"
  }, aiLoading ? "Analisi…" : "Proponi con AI"), editable && /*#__PURE__*/React.createElement(IconBtn, {
    onClick: save,
    disabled: saving || !dirty,
    accent: true,
    title: "Salva la scheda qualit\xE0"
  }, saving ? "Salvataggio…" : "Salva scheda")))));
};
const Toggle = ({
  label,
  checked,
  onChange,
  disabled = false
}) => /*#__PURE__*/React.createElement("div", {
  style: {
    display: "flex",
    alignItems: "center",
    gap: 10
  }
}, /*#__PURE__*/React.createElement("div", {
  onClick: disabled ? undefined : onChange,
  style: {
    width: 40,
    height: 22,
    borderRadius: 11,
    cursor: disabled ? "not-allowed" : "pointer",
    background: checked ? "var(--accent)" : "var(--border)",
    transition: "background 0.2s",
    position: "relative",
    flexShrink: 0,
    opacity: disabled ? 0.7 : 1
  }
}, /*#__PURE__*/React.createElement("div", {
  style: {
    width: 18,
    height: 18,
    borderRadius: "50%",
    background: "#fff",
    position: "absolute",
    top: 2,
    left: checked ? 20 : 2,
    transition: "left 0.2s",
    boxShadow: "0 1px 3px rgba(0,0,0,0.15)"
  }
})), /*#__PURE__*/React.createElement("span", {
  className: "text-base font-medium",
  style: {
    color: "var(--text-mid)",
    fontWeight: 500
  }
}, label));

// ─── Componente principale ───────────────────────────────────────────────
// Tre colonne: Ordini di produzione → anomalie dell'OP (raggruppate per blocco
// di seriali) → dettaglio con «Segnalazione» (cosa ha trovato il reparto) e
// «Decisione del capocommessa» (stato, RDC, cliente, note). Le selezioni sono
// per id, così ricerche e filtri non cambiano l'anomalia aperta né perdono le
// modifiche; le modifiche non salvate chiedono conferma prima di cambiare.
const opKey = o => String((o && (o.item_id ?? o.id)) ?? "");
const isDaDecidere = a => !a.chiudere && !a.aprire_rdc && !a.segnalare && !String(a.note || "").trim() && ["", "in attesa"].includes(String(a.avanzamento || "").trim().toLowerCase());
const statoAnomalia = a => {
  if (!a || !a.item_id) return {
    text: "—",
    variant: "chiuso"
  };
  if (a.chiudere) return {
    text: "Chiusa",
    variant: "chiuso"
  };
  if (isDaDecidere(a)) return {
    text: "Da decidere",
    variant: "attesa"
  };
  return {
    text: a.avanzamento || "In lavorazione",
    variant: "aperto"
  };
};
// Preferenze della pagina nel browser (raggruppamento, gruppi chiusi): se lo
// storage non c'è (finestra privata) la pagina funziona con i valori di serie.
const PREF_RAGGRUPPA = "ga_raggruppa_anomalie";
const PREF_GRUPPI_CHIUSI = "ga_gruppi_chiusi";
const PREF_SEZIONI_CHIUSE = "ga_sezioni_chiuse";
const leggiPref = (k, def) => {
  try {
    const v = window.localStorage.getItem(k);
    return v === null ? def : JSON.parse(v);
  } catch (_) {
    return def;
  }
};
const scriviPref = (k, v) => {
  try {
    window.localStorage.setItem(k, JSON.stringify(v));
  } catch (_) {/* niente storage */}
};
// Gruppi dell'elenco anomalie. «sn»: un gruppo per blocco di seriali (o S/N
// senza blocco), le chiuse in fondo. «stato»: «Da decidere», poi un gruppo per
// avanzamento delle aperte, le chiuse in fondo. Le chiuse partono chiuse.
const raggruppaAnomalie = (list, modo) => {
  const gruppi = [];
  const perKey = new Map();
  const add = (key, def, a) => {
    let g = perKey.get(key);
    if (!g) {
      g = {
        key,
        items: [],
        ...def
      };
      perKey.set(key, g);
      gruppi.push(g);
    }
    g.items.push(a);
  };
  const aperte = list.filter(a => !a.chiudere);
  const chiuse = list.filter(a => a.chiudere);
  if (modo === "stato") {
    const daDec = aperte.filter(isDaDecidere);
    if (daDec.length) daDec.forEach(a => add("stato:da_decidere", {
      label: "Da decidere",
      tone: "attesa"
    }, a));
    aperte.filter(a => !isDaDecidere(a)).forEach(a => {
      const av = String(a.avanzamento || "").trim() || "In lavorazione";
      add(`stato:${av.toLowerCase()}`, {
        label: av,
        tone: "aperto"
      }, a);
    });
    chiuse.forEach(a => add("stato:chiuse", {
      label: "Chiuse",
      tone: "chiuso",
      chiusoDiSerie: true
    }, a));
  } else {
    aperte.forEach(a => {
      const etichetta = a.blocco_label || a.sn || "Senza S/N";
      add(`sn:${a.blocco_id ? `b${a.blocco_id}` : `s${etichetta}`}`, {
        label: etichetta,
        tone: "blocco",
        blocco: a.blocco_id ? a : null
      }, a);
    });
    chiuse.forEach(a => add("sn:chiuse", {
      label: "Chiuse",
      tone: "chiuso",
      chiusoDiSerie: true
    }, a));
  }
  return gruppi;
};
const fmtData = iso => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit"
  });
};
const ALLEGATI_ACCEPT = ".jpg,.jpeg,.png,.gif,.bmp,.webp,.pdf,.doc,.docx,.xls,.xlsx,.xlsm,.csv,.msg,.eml";
const nomeAppunti = files => files.map((f, i) => {
  if (f.name && !/^image\.\w+$/i.test(f.name)) return f;
  const d = new Date();
  const p = n => String(n).padStart(2, "0");
  const ext = fileExt(f.name) || ".png";
  try {
    return new File([f], `appunti-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}-${i + 1}${ext}`, {
      type: f.type || "image/png"
    });
  } catch (_) {
    return f;
  }
});
const Ico = {
  back: /*#__PURE__*/React.createElement("svg", {
    width: "16",
    height: "16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2.2",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M15 18l-6-6 6-6"
  })),
  plus: /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2.4",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M12 5v14m-7-7h14"
  })),
  search: /*#__PURE__*/React.createElement("svg", {
    width: "15",
    height: "15",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("circle", {
    cx: "11",
    cy: "11",
    r: "8"
  }), /*#__PURE__*/React.createElement("path", {
    d: "m21 21-4.35-4.35"
  })),
  more: /*#__PURE__*/React.createElement("svg", {
    width: "16",
    height: "16",
    fill: "currentColor",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("circle", {
    cx: "5",
    cy: "12",
    r: "2"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "12",
    r: "2"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "19",
    cy: "12",
    r: "2"
  })),
  prev: /*#__PURE__*/React.createElement("svg", {
    width: "16",
    height: "16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2.4",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M15 18l-6-6 6-6"
  })),
  next: /*#__PURE__*/React.createElement("svg", {
    width: "16",
    height: "16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2.4",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M9 18l6-6-6-6"
  })),
  user: /*#__PURE__*/React.createElement("svg", {
    width: "12",
    height: "12",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "12",
    cy: "7",
    r: "4"
  })),
  clip: /*#__PURE__*/React.createElement("svg", {
    width: "12",
    height: "12",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"
  })),
  upload: /*#__PURE__*/React.createElement("svg", {
    width: "18",
    height: "18",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"
  }), /*#__PURE__*/React.createElement("polyline", {
    points: "17 8 12 3 7 8"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "12",
    y1: "3",
    x2: "12",
    y2: "15"
  })),
  check: /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2.6",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M5 13l4 4L19 7"
  })),
  list: /*#__PURE__*/React.createElement("svg", {
    width: "20",
    height: "20",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "9",
    y: "3",
    width: "6",
    height: "4",
    rx: "1"
  })),
  rows: /*#__PURE__*/React.createElement("svg", {
    width: "20",
    height: "20",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M4 6h16M4 10h16M4 14h16M4 18h16"
  })),
  copy: /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "9",
    y: "9",
    width: "13",
    height: "13",
    rx: "2"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"
  })),
  edit: /*#__PURE__*/React.createElement("svg", {
    width: "20",
    height: "20",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    viewBox: "0 0 24 24"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"
  }))
};
const Chip = ({
  active,
  onClick,
  children,
  count,
  tone
}) => /*#__PURE__*/React.createElement("button", {
  type: "button",
  className: `ga-chip${active ? " is-on" : ""}${tone ? ` ga-chip--${tone}` : ""}`,
  onClick: onClick
}, children, count !== undefined && /*#__PURE__*/React.createElement("span", {
  className: "ga-chip__n"
}, count));
const FlagToggle = ({
  label,
  hint,
  checked,
  onChange,
  disabled
}) => /*#__PURE__*/React.createElement("label", {
  className: `ga-flag${checked ? " is-on" : ""}${disabled ? " is-disabled" : ""}`,
  title: hint || ""
}, /*#__PURE__*/React.createElement("input", {
  type: "checkbox",
  checked: !!checked,
  disabled: disabled,
  onChange: onChange
}), /*#__PURE__*/React.createElement("span", {
  className: "ga-flag__box"
}, checked ? Ico.check : null), /*#__PURE__*/React.createElement("span", null, label));

// Chip dei seriali: un range «LCN00060-LCN00065» diventa «LCN00060 → LCN00065».
const RANGE_SN_RE = /^([A-Za-z]*\d+)-([A-Za-z]*\d+)$/;
const SnChip = ({
  voce,
  muted
}) => {
  const m = RANGE_SN_RE.exec(String(voce || "").trim());
  return /*#__PURE__*/React.createElement("span", {
    className: `ga-snchip${muted ? " is-muted" : ""}${m ? " is-range" : ""}`,
    title: muted ? "Nello stesso controllo, ma non interessato da questa anomalia" : ""
  }, m ? /*#__PURE__*/React.createElement(React.Fragment, null, m[1], /*#__PURE__*/React.createElement("span", {
    className: "ga-snchip__arrow"
  }, "\u2192"), m[2]) : voce);
};
const PezziInteressati = ({
  sn,
  compact
}) => {
  const coinvolti = Array.isArray(sn.seriali_coinvolti) && sn.seriali_coinvolti.length ? sn.seriali_coinvolti : [sn.blocco_label || sn.sn].filter(Boolean);
  const esclusi = Array.isArray(sn.seriali_esclusi) ? sn.seriali_esclusi : [];
  const pezzi = sn.pezzi_coinvolti || coinvolti.length;
  if (!coinvolti.length) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: `ga-sn${compact ? " ga-sn--compact" : ""}`
  }, !compact && /*#__PURE__*/React.createElement("span", {
    className: "ga-sn__label"
  }, "Pezzi interessati ", /*#__PURE__*/React.createElement("b", {
    className: "ga-sn__count"
  }, pezzi, " pezz", pezzi === 1 ? "o" : "i"), esclusi.length > 0 && /*#__PURE__*/React.createElement("span", {
    className: "ga-sn__of"
  }, "su ", sn.pezzi_blocco, " del controllo")), /*#__PURE__*/React.createElement("div", {
    className: "ga-sn__chips"
  }, coinvolti.map(v => /*#__PURE__*/React.createElement(SnChip, {
    key: `c-${v}`,
    voce: v
  })), !compact && esclusi.map(v => /*#__PURE__*/React.createElement(SnChip, {
    key: `e-${v}`,
    voce: v,
    muted: true
  }))));
};
function GestioneAnomalie() {
  // ── Dati ──
  const fileInputQRef = useRef(null);
  const [ordini, setOrdini] = useState([]);
  const [anomalie, setAnomalie] = useState([]);
  const [loadingOrdini, setLoadingOrdini] = useState(true);
  const [loadingAnom, setLoadingAnom] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState(null); // { ok, text }
  const [currentItemId, setCurrentItemId] = useState(null);
  const [currentLocalId, setCurrentLocalId] = useState(null);
  const [attachments, setAttachments] = useState([]);
  const [loadingAttachments, setLoadingAttachments] = useState(false);
  const [uploadingAttachments, setUploadingAttachments] = useState(false);
  const fileInputRef = useRef(null);
  const fileInputDecRef = useRef(null);

  // ── Selezione, ricerca, filtri ──
  const [selectedOpKey, setSelectedOpKey] = useState("");
  const [selectedSnId, setSelectedSnId] = useState("");
  const [searchOp, setSearchOp] = useState("");
  const [searchSn, setSearchSn] = useState("");
  const [pageFilter, setPageFilter] = useState(ACTIVE_FILTER);
  const [snFilter, setSnFilter] = useState("tutte"); // "tutte" | "da_decidere"
  // Raggruppamento delle anomalie («sn» per blocco di seriali, «stato») e gruppi
  // chiusi: restano nel browser finché la persona non li cambia, per tutti gli OP.
  const [raggruppa, setRaggruppaState] = useState(() => leggiPref(PREF_RAGGRUPPA, "sn") === "stato" ? "stato" : "sn");
  const [gruppiChiusi, setGruppiChiusi] = useState(() => {
    const v = leggiPref(PREF_GRUPPI_CHIUSI, null);
    return v && typeof v === "object" && !Array.isArray(v) ? v : {};
  });
  const setRaggruppa = v => {
    setRaggruppaState(v);
    scriviPref(PREF_RAGGRUPPA, v);
  };
  const gruppoChiuso = g => g.key in gruppiChiusi ? Boolean(gruppiChiusi[g.key]) : Boolean(g.chiusoDiSerie);
  const toggleGruppo = g => setGruppiChiusi(prev => {
    const next = {
      ...prev,
      [g.key]: !gruppoChiuso(g)
    };
    scriviPref(PREF_GRUPPI_CHIUSI, next);
    return next;
  });
  // Clonazione dell'OP: anomalie scelte da copiare su un nuovo OP ({ opKey, ids }).
  const [clona, setClona] = useState(null);
  const [pendingNav, setPendingNav] = useState(null); // azione rinviata per modifiche non salvate
  const [menuOpen, setMenuOpen] = useState(false);
  const [editDesc, setEditDesc] = useState(false);
  const [lightbox, setLightbox] = useState(null); // file_id immagine ingrandita
  const [dropOver, setDropOver] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(null);

  // ── Mobile / tablet ──
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);
  const [isTablet, setIsTablet] = useState(window.innerWidth >= 768 && window.innerWidth < 1180);
  const [mobilePanel, setMobilePanel] = useState("ordini"); // "ordini" | "serie" | "dettaglio"
  useEffect(() => {
    const onResize = () => {
      setIsMobile(window.innerWidth < 768);
      setIsTablet(window.innerWidth >= 768 && window.innerWidth < 1180);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // ── Campi della decisione ──
  const [desc, setDesc] = useState("");
  const [descrizioneAnswers, setDescrizioneAnswers] = useState({});
  const [note, setNote] = useState("");
  const [pezziPrec, setPezziPrec] = useState(false);
  const [aprireRdc, setAprireRdc] = useState(false);
  const [segnalare, setSegnalare] = useState(false);
  const [terzista, setTerzista] = useState(false);
  const [segnalaCar, setSegnalaCar] = useState(false);
  const [carScelti, setCarScelti] = useState([]);
  const [dovePezzi, setDovePezzi] = useState("");
  const [avanzamento, setAvanzamento] = useState(DEFAULT_AVANZAMENTO);
  const [rdcNum, setRdcNum] = useState("");
  // «Segnalato al cliente/terzista» e risposta: si salvano con la decisione.
  const [segnalati, setSegnalati] = useState({
    cliente: false,
    terzista: false
  });
  const [risposte, setRisposte] = useState({
    cliente: "",
    terzista: ""
  });
  // «Chiudi l'anomalia»: chiude al salvataggio anche se mancano i passi.
  const [chiudiManuale, setChiudiManuale] = useState(false);
  const [versioneEsiti, setVersioneEsiti] = useState(0);
  // «In carico a me»: di serie solo le anomalie che toccano a chi guarda.
  const [mostraTutte, setMostraTutte] = useState(false);
  // Sezioni del dettaglio chiuse (controllore, capocommessa, qualità, esiti): restano
  // così per tutte le anomalie finché non le riapri.
  const [sezChiuse, setSezChiuse] = useState(() => {
    const v = leggiPref(PREF_SEZIONI_CHIUSE, []);
    return Array.isArray(v) ? v : [];
  });
  const sezChiusa = k => sezChiuse.includes(k);
  const toggleSez = k => setSezChiuse(prev => {
    const nuovo = prev.includes(k) ? prev.filter(x => x !== k) : [...prev, k];
    scriviPref(PREF_SEZIONI_CHIUSE, nuovo);
    return nuovo;
  });
  // Decisione qualità e richieste di informazioni.
  const [qNum, setQNum] = useState("");
  const [qAv, setQAv] = useState("");
  const [qNote, setQNote] = useState("");
  const [qSeg, setQSeg] = useState({
    cliente: false,
    terzista: false
  });
  const [qRisp, setQRisp] = useState({
    cliente: "",
    terzista: ""
  });
  const [qBusy, setQBusy] = useState(false);
  const [infoModal, setInfoModal] = useState(null); // null | { cc, controllore, messaggio, busy, err }
  const [rispInfo, setRispInfo] = useState("");
  // «Applica la stessa decisione anche a…»: perimetro (solo questa, stesso blocco,
  // tutte le aperte dell'OP, scelte a mano), già decise escluse di serie, riepilogo
  // in un popup prima di salvare.
  const [ambito, setAmbito] = useState("solo");
  const [scelteMano, setScelteMano] = useState([]);
  const [includiDecise, setIncludiDecise] = useState(false);
  const [riepilogo, setRiepilogo] = useState(null); // null | { prossima: bool }
  // «Elimina» / «Taglia» dell'anomalia aperta: { tipo, op, sn, seriali, busy, err }.
  const [azAnom, setAzAnom] = useState(null);
  // «Modifica OP»: popup del controllore che ha creato l'OP dal portale.
  const [modOp, setModOp] = useState(null); // null | { titolo, dati, iniz, motivo, busy, err }
  // Decisioni salvate su questo OP e non ancora partite nel riepilogo (parte dopo
  // la pausa configurata; «Invia ora» lo anticipa).
  const [coda, setCoda] = useState(null); // null | { n, partenza }
  const [adesso, setAdesso] = useState(Date.now());
  const [inviando, setInviando] = useState(false);
  const caricaCoda = () => {
    if (!op.id || op.id === "—" || !API.decisioni_coda || !canEditCurrentOp) {
      setCoda(null);
      return;
    }
    fetch(`${API.decisioni_coda}?op_id=${encodeURIComponent(op.id)}`, {
      credentials: "same-origin"
    }).then(r => r.ok ? r.json() : null).then(d => setCoda(d && d.success && d.coda ? d.coda : null)).catch(() => {});
  };
  const inviaOra = async () => {
    setInviando(true);
    try {
      const r = await fetch(API.decisioni_coda, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken()
        },
        body: JSON.stringify({
          op_id: op.id
        })
      });
      const d = await readJsonOrThrow(r, "Invio riepilogo");
      if (!r.ok || !d.success) throw new Error(d.error || `HTTP ${r.status}`);
      setCoda(null);
      flash({
        ok: true,
        text: d.inviate ? `Riepilogo inviato: ${d.inviate} decision${d.inviate === 1 ? "e" : "i"}` : "Nessuna decisione da inviare"
      });
    } catch (e) {
      flash({
        ok: false,
        text: "Errore: " + e.message
      }, 7000);
      caricaCoda();
    }
    setInviando(false);
  };
  const resetAmbito = () => {
    setAmbito("solo");
    setScelteMano([]);
    setIncludiDecise(false);
  };
  const avanzamentoOptions = useMemo(() => buildAvanzamentoOptions(aprireRdc, aprireRdc || segnalare, terzista), [aprireRdc, segnalare, terzista]);
  // Tempi ed esiti dell'anomalia aperta: «serve_azione» blocca la chiusura senza azione effettuata.
  const [esitiInfo, setEsitiInfo] = useState(null);
  // Una risposta scritta nelle note non può lasciare l'anomalia «In attesa», tranne
  // quando aspetta una segnalazione (RDC, cliente, terzista).
  const notaSenzaStato = !!note.trim() && !(aprireRdc || segnalare || terzista) && ["", "in attesa"].includes(normalizeChoice(avanzamento).toLowerCase());
  // La risposta del destinatario chiede lo stato definitivo (o «Chiudi l'anomalia»).
  const rispostaSenzaStato = !chiudiManuale && DESTINATARI.some(d => (risposte[d.chi] || "").trim()) && STATI_RISPOSTA.includes(normalizeChoice(avanzamento).toLowerCase());

  // Lo stato «di partenza» quando si toglie una spunta che l'aveva cambiato.
  const statoDiPartenza = () => {
    const base = baseline.avanzamento; // dichiarato più sotto: letto solo al clic
    return base && !STATI_RISPOSTA.includes(base.toLowerCase()) ? base : "In attesa";
  };
  // «Segnalare al cliente» spunta anche «Aprire RDC» (si può togliere); lo stato
  // cambia solo con «Segnalato al cliente».
  const toggleSegnalare = () => {
    const on = !segnalare;
    setSegnalare(on);
    if (on) setAprireRdc(true);else if (avanzamento === AVANZAMENTO_RISPOSTA_CLIENTE) setAvanzamento(statoDiPartenza());
  };
  const toggleTerzista = () => {
    const on = !terzista;
    setTerzista(on);
    if (!on && avanzamento === AVANZAMENTO_RISPOSTA_TERZISTA) setAvanzamento(statoDiPartenza());
  };
  // «Segnalato…»: il capocommessa ha già avvisato lui. Senza RDC l'anomalia si
  // chiude; per aspettare la risposta si sceglie «In attesa risposta …».
  const toggleSegnalato = chi => setSegnalati(prev => ({
    ...prev,
    [chi]: !prev[chi]
  }));
  const flash = (msg, ms = 4500) => {
    setSaveMsg(msg);
    if (ms) setTimeout(() => setSaveMsg(cur => cur === msg ? null : cur), ms);
  };
  const clearForm = () => {
    setDesc("");
    setNote("");
    setDescrizioneAnswers({});
    setPezziPrec(false);
    setAprireRdc(false);
    setSegnalare(false);
    setTerzista(false);
    setDovePezzi("");
    setSegnalaCar(false);
    setCarScelti([]);
    setAvanzamento(DEFAULT_AVANZAMENTO);
    setRdcNum("");
    setSegnalati({
      cliente: false,
      terzista: false
    });
    setRisposte({
      cliente: "",
      terzista: ""
    });
    setChiudiManuale(false);
    setCurrentItemId(null);
    setCurrentLocalId(null);
    setAttachments([]);
    resetAmbito();
    setEditDesc(false);
  };
  useEffect(() => {
    const current = normalizeChoice(avanzamento).toLowerCase();
    const exists = avanzamentoOptions.some(opt => normalizeChoice(opt).toLowerCase() === current);
    if (!exists) setAvanzamento(avanzamentoOptions[0] || DEFAULT_AVANZAMENTO);
  }, [avanzamento, avanzamentoOptions]);

  // ── Ordini ──
  const loadOrdini = () => {
    setLoadingOrdini(true);
    fetch(API.ordini, {
      credentials: "same-origin"
    }).then(r => readJsonOrThrow(r, "Caricamento ordini")).then(data => {
      setOrdini(Array.isArray(data) ? data : []);
      setLoadingOrdini(false);
    }).catch(e => {
      console.error("Errore caricamento ordini:", e);
      setLoadingOrdini(false);
    });
  };
  useEffect(() => {
    loadOrdini();
  }, []);
  useEffect(() => {
    const nextUrl = new URL(window.location.href);
    if (pageFilter && pageFilter !== "aperte") nextUrl.searchParams.set("filter", pageFilter);else nextUrl.searchParams.delete("filter");
    window.history.replaceState({}, "", nextUrl.toString());
  }, [pageFilter]);
  const apertiDi = o => Number(o?.anomalie_aperte_count ?? o?.anomalie_count ?? 0);
  const daDecidereDi = o => Number(o?.anomalie_da_decidere_count ?? 0);
  const orderMatches = (o, filtro) => {
    if (filtro === "aperte") return apertiDi(o) > 0;
    // «In carico a me» = sono capocommessa o CAR dell'OP, oppure referente RDC e
    // l'OP ha anomalie aperte RDC / da segnalare al cliente (lo dice il server);
    // poter modificare l'OP non basta.
    if (filtro === "in_carico") return apertiDi(o) > 0 && (o?.in_carico !== undefined ? Boolean(o.in_carico) : peopleMatchCurrentUser(o?.capo) || peopleMatchCurrentUser(o?.car));
    return true;
  };
  const ordiniCercati = useMemo(() => {
    const q = searchOp.trim().toLowerCase();
    if (!q) return ordini;
    return ordini.filter(o => [o.id, o.pn, o.capo, o.car].some(v => String(v || "").toLowerCase().includes(q)));
  }, [ordini, searchOp]);
  const contatoriFiltro = useMemo(() => ({
    tutti: ordiniCercati.length,
    aperte: ordiniCercati.filter(o => orderMatches(o, "aperte")).length,
    in_carico: ordiniCercati.filter(o => orderMatches(o, "in_carico")).length
  }), [ordiniCercati]);
  const filteredOrdini = useMemo(() => {
    const list = ordiniCercati.filter(o => orderMatches(o, pageFilter));
    // Nei filtri operativi prima gli OP con decisioni in sospeso.
    if (pageFilter !== "tutti") return [...list].sort((a, b) => daDecidereDi(b) - daDecidereDi(a));
    return list;
  }, [ordiniCercati, pageFilter]);

  // L'OP resta selezionato anche se una ricerca lo nasconde dall'elenco.
  const op = useMemo(() => ordini.find(o => opKey(o) === selectedOpKey) || filteredOrdini[0] || {}, [ordini, filteredOrdini, selectedOpKey]);
  // Con il sistema dei ruoli il server dice OP per OP se si può modificare.
  const canEditCurrentOp = useMemo(() => op.can_edit !== undefined ? Boolean(op.can_edit) : canUserEditOp(op.capo, op.car), [op.can_edit, op.capo, op.car]);
  useEffect(() => {
    caricaCoda();
  }, [op.id, canEditCurrentOp]);
  useEffect(() => {
    const t = setInterval(() => setAdesso(Date.now()), 20000);
    return () => clearInterval(t);
  }, []);
  // Passata l'ora prevista, si ricontrolla: il riepilogo sarà partito (o in partenza).
  useEffect(() => {
    if (coda && new Date(coda.partenza).getTime() + 70000 < adesso) caricaCoda();
  }, [adesso]);
  const nuovaAnomaliaUrl = op.id && op.id !== "—" ? `/gestione-anomalie/nuova-segnalazione?op_id=${encodeURIComponent(op.id)}` : "/gestione-anomalie/nuova-segnalazione";
  // «Segnala a CAR»: si sceglie fra il CAR dell'OP e i capi reparto di Configurazione.
  const carDellOp = splitPeopleTokens(op.car === "—" ? "" : op.car);
  const carOpzioni = useMemo(() => {
    const visti = new Set();
    const out = [];
    [...carDellOp, ...(Array.isArray(CONFIG_LISTS.capi_reparto) ? CONFIG_LISTS.capi_reparto : []), ...carScelti].forEach(n => {
      const nome = String(n || "").trim();
      if (nome && !visti.has(nome.toLowerCase())) {
        visti.add(nome.toLowerCase());
        out.push(nome);
      }
    });
    return out;
  }, [op.car, carScelti]);
  // Nessun CAR scelto di serie: il CAR dell'OP riceve già il riepilogo delle modifiche,
  // la mail «Segnala a CAR» va solo a chi scegli tu.
  const toggleSegnalaCar = () => setSegnalaCar(!segnalaCar);
  const isCarDellOp = nome => carDellOp.some(n => n.toLowerCase() === String(nome).toLowerCase());
  const toggleCarScelto = nome => setCarScelti(prev => prev.some(n => n.toLowerCase() === nome.toLowerCase()) ? prev.filter(n => n.toLowerCase() !== nome.toLowerCase()) : [...prev, nome]);

  // Preselezione da ?op= (promemoria in dashboard, mail).
  const initialOpApplied = useRef(false);
  useEffect(() => {
    if (initialOpApplied.current || !ordini.length) return;
    initialOpApplied.current = true;
    const found = INITIAL_OP ? ordini.find(o => String(o.id || "").trim().toLowerCase() === INITIAL_OP) : null;
    const target = found || filteredOrdini[0];
    if (target) setSelectedOpKey(opKey(target));
    if (found && isMobile) setMobilePanel("serie");
  }, [ordini]);

  // ── Anomalie dell'OP ──
  const filteredSeriali = useMemo(() => {
    const q = searchSn.trim().toLowerCase();
    return anomalie.filter(a => {
      if (pageFilter === "in_carico" && !mostraTutte && !a.in_carico_a_me) return false;
      // «Per stato» ha già il gruppo «Da decidere»: il filtro vale solo «Per S/N».
      if (raggruppa === "sn" && snFilter === "da_decidere" && !isDaDecidere(a)) return false;
      if (!q) return true;
      return [a.sn, a.blocco_label, a.testo, a.desc, a.fase, a.avanzamento, a.local_id && `#${a.local_id}`].some(v => String(v || "").toLowerCase().includes(q));
    });
  }, [anomalie, searchSn, snFilter, raggruppa, pageFilter, mostraTutte]);
  const nInCarico = useMemo(() => anomalie.filter(a => a.in_carico_a_me).length, [anomalie]);
  const gruppiAnomalie = useMemo(() => raggruppaAnomalie(filteredSeriali, raggruppa), [filteredSeriali, raggruppa]);
  // Ordine di «precedente/successiva»: quello dei gruppi a video.
  const ordineVisibile = useMemo(() => gruppiAnomalie.flatMap(g => g.items), [gruppiAnomalie]);
  const nDaDecidere = useMemo(() => anomalie.filter(isDaDecidere).length, [anomalie]);
  const sn = useMemo(() => anomalie.find(a => a.item_id === selectedSnId) || {}, [anomalie, selectedSnId]);
  // Dopo «sn» (TDZ): la chiusura con «Segnalare…» dipende da «Segnalato…».
  const chiudereAuto = shouldAutoClose(aprireRdc, avanzamento, rdcNum, segnalare, segnalati.cliente, terzista, segnalati.terzista, richiestaAperta(sn));
  const chiudere = chiudereAuto || chiudiManuale && CC_PUO_CHIUDERE;
  // Decisione qualità: valori dell'anomalia aperta (dopo «sn», TDZ).
  useEffect(() => {
    setQNum(sn.numero_rdc || "");
    setQAv(sn.avanzamento_qualita || "");
    setQNote(sn.note_qualita || "");
    setQSeg({
      cliente: !!sn.segnalato_cliente,
      terzista: !!sn.segnalato_terzista
    });
    setQRisp({
      cliente: "",
      terzista: ""
    });
    setRispInfo("");
    setInfoModal(null);
  }, [sn.item_id, sn.numero_rdc, sn.avanzamento_qualita, sn.note_qualita, sn.segnalato_cliente, sn.segnalato_terzista]);
  const posizione = ordineVisibile.findIndex(a => a.item_id === sn.item_id);
  const isSelectedClosed = Boolean(sn.chiudere);
  const canEditSelected = canEditCurrentOp && !isSelectedClosed && !!sn.item_id;
  useEffect(() => {
    clearForm();
    setSelectedSnId("");
    if (!op || !op.item_id) {
      setAnomalie([]);
      return undefined;
    }
    // Una risposta arrivata dopo un cambio di OP va scartata: altrimenti l'elenco
    // mostrerebbe le anomalie di un altro OP sotto l'intestazione di questo, e un
    // salvataggio scriverebbe l'OP sbagliato sulla riga.
    let alive = true;
    setAnomalie([]);
    setLoadingAnom(true);
    fetch(`${API.anomalie}?op_item_id=${encodeURIComponent(op.item_id)}&op_id=${encodeURIComponent(op.id || "")}`, {
      credentials: "same-origin"
    }).then(r => readJsonOrThrow(r, "Caricamento anomalie")).then(data => {
      if (!alive) return;
      const list = Array.isArray(data) ? data : [];
      setAnomalie(list);
      // Si apre la prima anomalia che aspetta una decisione.
      const first = list.find(a => a.in_carico_a_me) || list.find(isDaDecidere) || list.find(a => !a.chiudere);
      setSelectedSnId(first ? first.item_id : "");
      setLoadingAnom(false);
    }).catch(e => {
      if (alive) {
        console.error("Errore caricamento anomalie:", e);
        setLoadingAnom(false);
      }
    });
    return () => {
      alive = false;
    };
  }, [op.item_id]);

  // Valori «di partenza» della decisione: servono a capire se ci sono modifiche.
  const baseline = useMemo(() => {
    const opts = buildAvanzamentoOptions(!!sn.aprire_rdc, !!sn.aprire_rdc || !!sn.segnalare, !!sn.segnala_terzista);
    const av = sn.avanzamento || DEFAULT_AVANZAMENTO;
    return {
      desc: sn.desc || "",
      note: sn.note || "",
      pezziPrec: !!sn.pezzi_prec,
      aprireRdc: !!sn.aprire_rdc,
      rdcNum: sn.numero_rdc || "",
      segnalare: !!sn.segnalare,
      terzista: !!sn.segnala_terzista,
      dovePezzi: sn.dove_pezzi || "",
      segnalaCar: !!sn.segnala_car,
      carScelti: Array.isArray(sn.car_segnalati) ? sn.car_segnalati : [],
      avanzamento: opts.some(o => o.toLowerCase() === av.toLowerCase()) ? av : opts[0] || DEFAULT_AVANZAMENTO,
      risposte: Object.fromEntries((sn.descrizioni || []).map(d => [String(d.id), d.risposta || ""])),
      segnalati: {
        cliente: !!sn.segnalato_cliente,
        terzista: !!sn.segnalato_terzista
      }
    };
  }, [sn.item_id, sn.desc, sn.note, sn.pezzi_prec, sn.aprire_rdc, sn.numero_rdc, sn.segnalare, sn.segnala_terzista, sn.dove_pezzi, sn.segnala_car, sn.car_segnalati, sn.avanzamento, sn.descrizioni, sn.segnalato_cliente, sn.segnalato_terzista]);
  // In attesa di risposta la nota già mandata resta congelata (anche dal server).
  const notaCongelata = STATI_RISPOSTA.includes(normalizeChoice(baseline.avanzamento).toLowerCase()) && !!baseline.note.trim();
  useEffect(() => {
    if (!sn.item_id) {
      clearForm();
      return;
    }
    setCurrentItemId(sn.item_id);
    setCurrentLocalId(sn.local_id || null);
    setDesc(baseline.desc);
    setDescrizioneAnswers(baseline.risposte);
    setNote(baseline.note);
    setPezziPrec(baseline.pezziPrec);
    setAprireRdc(baseline.aprireRdc);
    setRdcNum(baseline.rdcNum);
    setSegnalare(baseline.segnalare);
    setTerzista(baseline.terzista);
    setDovePezzi(baseline.dovePezzi);
    setSegnalaCar(baseline.segnalaCar);
    setCarScelti(baseline.carScelti);
    setAvanzamento(baseline.avanzamento);
    setSegnalati(baseline.segnalati);
    setRisposte({
      cliente: "",
      terzista: ""
    });
    setChiudiManuale(false);
    resetAmbito();
    setEditDesc(false);
  }, [sn.item_id]);
  const dirty = !!sn.item_id && canEditSelected && (desc !== baseline.desc || note !== baseline.note || pezziPrec !== baseline.pezziPrec || aprireRdc !== baseline.aprireRdc || segnalare !== baseline.segnalare || terzista !== baseline.terzista || segnalaCar !== baseline.segnalaCar || segnalaCar && carScelti.join("|") !== baseline.carScelti.join("|") || aprireRdc && rdcNum !== baseline.rdcNum || normalizeChoice(avanzamento).toLowerCase() !== normalizeChoice(baseline.avanzamento).toLowerCase() || Object.keys(descrizioneAnswers).some(k => (descrizioneAnswers[k] || "") !== (baseline.risposte[k] || "")) || segnalare && segnalati.cliente !== baseline.segnalati.cliente || terzista && segnalati.terzista !== baseline.segnalati.terzista || DESTINATARI.some(d => !!(risposte[d.chi] || "").trim()) || chiudiManuale);

  // Cambio di anomalia/OP con modifiche non salvate: si chiede cosa fare.
  const guard = action => {
    if (dirty) {
      setPendingNav(() => action);
      return;
    }
    action();
  };
  const selectSn = a => guard(() => {
    setSelectedSnId(a.item_id);
    if (isMobile) setMobilePanel("dettaglio");
  });
  const selectOp = o => guard(() => {
    setSelectedOpKey(opKey(o));
    if (isMobile) setMobilePanel("serie");
  });
  const avviaClona = o => guard(() => {
    setSelectedOpKey(opKey(o));
    setClona({
      opKey: opKey(o),
      ids: []
    });
    if (isMobile) setMobilePanel("serie");
  });
  const clonaIds = clona && clona.opKey === opKey(op) ? clona.ids : null;
  const toggleClona = (ids, on) => setClona(prev => {
    if (!prev) return prev;
    const resto = prev.ids.filter(x => !ids.includes(x));
    return {
      ...prev,
      ids: on ? [...resto, ...ids] : resto
    };
  });
  const continuaClona = () => {
    if (!clonaIds || !clonaIds.length) return;
    // Stesso ordine dell'elenco, così i blocchi arrivano come li vedi qui.
    const ordinati = anomalie.map(a => a.local_id).filter(x => clonaIds.includes(x));
    window.location.href = `/gestione-anomalie/nuova-segnalazione?clona_da=${encodeURIComponent(op.id)}&anomalie=${ordinati.join(",")}`;
  };
  const vaiA = delta => {
    if (posizione < 0) return;
    const target = ordineVisibile[posizione + delta];
    if (target) selectSn(target);
  };

  // Altre anomalie aperte dello stesso blocco di seriali.
  // Altre anomalie aperte dell'OP; con «includi già decise» spento, solo quelle da decidere.
  const altreAperte = useMemo(() => anomalie.filter(x => x.item_id !== sn.item_id && !x.chiudere && (includiDecise || isDaDecidere(x))), [anomalie, sn && sn.item_id, includiDecise]);
  const stessoBlocco = useMemo(() => sn && sn.blocco_id ? altreAperte.filter(x => x.blocco_id === sn.blocco_id) : [], [altreAperte, sn && sn.blocco_id]);
  const giaDecise = useMemo(() => anomalie.filter(x => x.item_id !== sn.item_id && !x.chiudere && !isDaDecidere(x)).length, [anomalie, sn && sn.item_id]);
  const bersagli = useMemo(() => {
    if (ambito === "blocco") return stessoBlocco;
    if (ambito === "op") return altreAperte;
    if (ambito === "mano") return altreAperte.filter(x => scelteMano.includes(x.item_id));
    return [];
  }, [ambito, stessoBlocco, altreAperte, scelteMano]);
  // Su una «Azione di recupero» senza azione effettuata la chiusura non è ammessa:
  // la decisione si applica, l'anomalia resta aperta.
  // «Segnalato…» vale anche per loro: è la stessa decisione.
  const chiudeBersaglio = x => (chiudiManuale && CC_PUO_CHIUDERE || shouldAutoClose(aprireRdc, avanzamento, x.numero_rdc || "", segnalare, segnalati.cliente, terzista, segnalati.terzista, richiestaAperta(x))) && !(x.serve_azione && !aprireRdc);
  const gruppiPerSn = lista => {
    const out = [];
    lista.forEach(x => {
      const chiave = x.blocco_id ? `b${x.blocco_id}` : `s${x.sn}`;
      let g = out.find(y => y.chiave === chiave);
      if (!g) {
        g = {
          chiave,
          titolo: x.blocco_label || x.sn || "—",
          righe: []
        };
        out.push(g);
      }
      g.righe.push(x);
    });
    return out;
  };

  // ── Allegati ──
  const attachmentsFor = useRef(null);
  const loadAttachments = async localId => {
    attachmentsFor.current = localId;
    setAttachments([]);
    if (!localId) return;
    setLoadingAttachments(true);
    try {
      const r = await fetch(`${API.allegati_list}?local_id=${encodeURIComponent(localId)}`, {
        credentials: "same-origin"
      });
      const d = await readJsonOrThrow(r, "Allegati");
      if (attachmentsFor.current !== localId) return;
      if (!r.ok || !d.success) throw new Error(d.error || "Errore caricamento allegati");
      setAttachments(Array.isArray(d.attachments) ? d.attachments : []);
    } catch (e) {
      setAttachments([]);
      flash({
        ok: false,
        text: "Errore allegati: " + e.message
      });
    }
    setLoadingAttachments(false);
  };
  useEffect(() => {
    loadAttachments(currentLocalId);
  }, [currentLocalId]);
  const uploadFiles = async (files, ambito = "") => {
    if (!files.length) return;
    if (!(ambito === "qualita" ? CAN_QUALITA : canEditCurrentOp)) {
      flash({
        ok: false,
        text: "Permesso negato: non puoi caricare allegati qui"
      });
      return;
    }
    if (!currentLocalId) {
      flash({
        ok: false,
        text: "Seleziona un'anomalia salvata per caricare allegati."
      });
      return;
    }
    setUploadingAttachments(true);
    try {
      const form = new FormData();
      form.append("local_id", String(currentLocalId));
      files.forEach(f => form.append("files", f));
      if (ambito) form.append("ambito", ambito);
      const r = await fetch(API.allegati_upload, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCsrfToken()
        },
        body: form,
        credentials: "same-origin"
      });
      const d = await readJsonOrThrow(r, "Upload allegati");
      if (Array.isArray(d.attachments)) setAttachments(d.attachments);
      if (Array.isArray(d.errors) && d.errors.length) flash({
        ok: false,
        text: "Upload parziale: " + d.errors.join(" | ")
      });else if (!r.ok) throw new Error(d.error || "Upload non riuscito");else flash({
        ok: true,
        text: `${files.length} allegat${files.length === 1 ? "o caricato" : "i caricati"}`
      });
    } catch (e) {
      flash({
        ok: false,
        text: "Errore upload allegati: " + e.message
      });
    }
    setUploadingAttachments(false);
  };
  const handleDeleteAttachment = async fileId => {
    setConfirmDelete(null);
    if (!currentLocalId || !fileId) return;
    try {
      const r = await fetch(API.allegati_delete, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken()
        },
        body: JSON.stringify({
          local_id: currentLocalId,
          file_id: fileId
        }),
        credentials: "same-origin"
      });
      const d = await readJsonOrThrow(r, "Elimina allegato");
      if (!r.ok || !d.success) throw new Error(d.error || "Eliminazione non riuscita");
      setAttachments(Array.isArray(d.attachments) ? d.attachments : []);
    } catch (e) {
      flash({
        ok: false,
        text: "Errore eliminazione allegato: " + e.message
      });
    }
  };
  const getAttachmentUrl = (fileId, forceDownload = false) => `${API.allegati_file}?local_id=${encodeURIComponent(currentLocalId)}&file_id=${encodeURIComponent(fileId)}${forceDownload ? "&download=1" : ""}`;
  const immagini = attachments.filter(f => f.is_image);
  // Gli allegati della decisione del capocommessa stanno nel suo riquadro.
  const attAnomalia = attachments.filter(f => !f.decisione && !f.qualita);
  const attDecisione = attachments.filter(f => f.decisione);
  const attQualita = attachments.filter(f => f.qualita);
  const renderAttGrid = list => /*#__PURE__*/React.createElement("div", {
    className: "ga-att__grid"
  }, list.map(file => /*#__PURE__*/React.createElement("div", {
    key: file.file_id,
    className: "ga-att__item",
    title: `${file.name} · ${formatBytes(file.size)}`
  }, file.is_image ? /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-att__thumb",
    onClick: () => setLightbox(file.file_id)
  }, /*#__PURE__*/React.createElement("img", {
    src: getAttachmentUrl(file.file_id),
    alt: file.name,
    loading: "lazy"
  })) : /*#__PURE__*/React.createElement("a", {
    className: "ga-att__thumb ga-att__thumb--file",
    href: getAttachmentUrl(file.file_id),
    target: "_blank",
    rel: "noopener"
  }, (fileExt(file.name).replace(".", "").toUpperCase() || "FILE").slice(0, 4)), /*#__PURE__*/React.createElement("div", {
    className: "ga-att__name"
  }, file.name), /*#__PURE__*/React.createElement("div", {
    className: "ga-att__acts"
  }, /*#__PURE__*/React.createElement("a", {
    href: getAttachmentUrl(file.file_id, true),
    title: "Scarica"
  }, "Scarica"), canEditCurrentOp && (confirmDelete === file.file_id ? /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "is-danger",
    onClick: () => handleDeleteAttachment(file.file_id)
  }, "Conferma") : /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => setConfirmDelete(file.file_id)
  }, "Elimina"))))));
  const lightboxIdx = immagini.findIndex(f => f.file_id === lightbox);

  // ── Salvataggio ──
  const handleSave = async (confermato = false, prossima = false) => {
    if (!op.id || op.id === "—") {
      flash({
        ok: false,
        text: "Seleziona un ordine prima di salvare"
      });
      return false;
    }
    if (!canEditCurrentOp) {
      flash({
        ok: false,
        text: "Permesso negato: non puoi modificare questo OP"
      });
      return false;
    }
    if (isSelectedClosed) {
      flash({
        ok: false,
        text: "Anomalia chiusa: in sola lettura"
      });
      return false;
    }
    if (!currentItemId) {
      flash({
        ok: false,
        text: "Seleziona un'anomalia"
      });
      return false;
    }
    if (notaSenzaStato) {
      flash({
        ok: false,
        text: NOTA_STATO_MSG
      }, 7000);
      return false;
    }
    if (rispostaSenzaStato) {
      flash({
        ok: false,
        text: RISPOSTA_STATO_MSG
      }, 7000);
      return false;
    }
    if (ambito === "mano" && !bersagli.length) {
      flash({
        ok: false,
        text: "Scegli almeno un'altra anomalia, oppure «Solo questa»."
      }, 6000);
      return false;
    }
    if (bersagli.length && !confermato) {
      setRiepilogo({
        prossima
      });
      return false;
    }
    setSaving(true);
    let ok = false;
    try {
      const r = await fetch(API.salva, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken()
        },
        body: JSON.stringify({
          item_id: currentItemId,
          op_id: op.id,
          sn: sn.sn || "",
          desc,
          descrizioni_risposte: descrizioneAnswers,
          note,
          pezzi_prec: pezziPrec,
          aprire_rdc: aprireRdc,
          segnalare,
          segnala_terzista: terzista,
          segnala_car: segnalaCar,
          car_segnalati: segnalaCar ? carScelti : [],
          segnalato_cliente: segnalare && segnalati.cliente,
          segnalato_terzista: terzista && segnalati.terzista,
          risposta_cliente: segnalare ? risposte.cliente.trim() : "",
          risposta_terzista: terzista ? risposte.terzista.trim() : "",
          chiudi_manuale: chiudiManuale,
          chiudere,
          avanzamento
        }),
        credentials: "same-origin"
      });
      const data = await readJsonOrThrow(r, "Salvataggio anomalia");
      if (!data.success) throw new Error(data.error || "risposta non valida");
      ok = true;
      const oraIt = new Date().toLocaleString("it-IT", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit"
      }).replace(",", "");
      // «Segnalato»: resta quello già registrato (data e autore); uno nuovo vale da adesso.
      const segnalatoDi = (chi, richiesto, prima) => richiesto && segnalati[chi] ? prima || {
        il: oraIt,
        da: ""
      } : richiesto ? null : prima || null;
      const segnalatiSalvati = x => ({
        segnalato_cliente: segnalatoDi("cliente", segnalare, x.segnalato_cliente),
        segnalato_terzista: segnalatoDi("terzista", terzista, x.segnalato_terzista)
      });
      const aggiornato = {
        desc,
        note: notaCongelata ? baseline.note : note,
        pezzi_prec: pezziPrec,
        aprire_rdc: aprireRdc,
        segnalare,
        segnala_terzista: terzista,
        segnala_car: segnalaCar && carScelti.length > 0,
        car_segnalati: segnalaCar ? carScelti : [],
        chiudere,
        avanzamento,
        ...segnalatiSalvati(sn),
        descrizioni: (sn.descrizioni || []).map(d => ({
          ...d,
          risposta: descrizioneAnswers[String(d.id)] || ""
        }))
      };
      setAnomalie(prev => prev.map(a => a.item_id === currentItemId ? {
        ...a,
        ...aggiornato
      } : a));
      setRisposte({
        cliente: "",
        terzista: ""
      });
      setChiudiManuale(false);
      setVersioneEsiti(v => v + 1);
      let testo = chiudere ? "Decisione salvata · anomalia chiusa" : "Decisione salvata";
      if (bersagli.length) {
        let n = 0;
        const errori = [];
        for (const f of bersagli) {
          const chiudeF = chiudeBersaglio(f);
          try {
            const rf = await fetch(API.salva, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCsrfToken()
              },
              body: JSON.stringify({
                item_id: f.item_id,
                op_id: op.id,
                sn: f.sn || "",
                desc: f.desc || "",
                note,
                pezzi_prec: !!f.pezzi_prec,
                aprire_rdc: aprireRdc,
                segnalare,
                segnala_terzista: terzista,
                chiudere: chiudeF,
                avanzamento,
                segnalato_cliente: segnalare && segnalati.cliente,
                segnalato_terzista: terzista && segnalati.terzista,
                chiudi_manuale: chiudiManuale
              }),
              credentials: "same-origin"
            });
            const df = await readJsonOrThrow(rf, "Salvataggio anomalia");
            if (!df.success) throw new Error(df.error || "errore");
            n += 1;
            setAnomalie(prev => prev.map(a => a.item_id === f.item_id ? {
              ...a,
              note,
              aprire_rdc: aprireRdc,
              segnalare,
              segnala_terzista: terzista,
              chiudere: chiudeF,
              avanzamento,
              ...segnalatiSalvati(a)
            } : a));
          } catch (err) {
            errori.push(`#${f.local_id}: ${err.message}`);
          }
        }
        resetAmbito();
        if (errori.length) {
          flash({
            ok: false,
            text: `Salvata; delle altre ${n} aggiornate e ${errori.length} no (${errori.join("; ")})`
          }, 8000);
          testo = "";
        } else {
          testo += ` · applicata anche ad altr${n === 1 ? "a" : "e"} ${n}`;
        }
      }
      if (testo) flash({
        ok: true,
        text: data.protocollo ? `${testo} · ${data.protocollo}` : testo
      });
      loadOrdini();
      caricaCoda();
    } catch (e) {
      flash({
        ok: false,
        text: "Errore: " + e.message
      }, 7000);
    }
    setSaving(false);
    return ok;
  };

  // La prossima è la successiva in elenco ancora da decidere (o la successiva aperta).
  const trovaProssima = (escluse = []) => {
    const via = new Set([sn.item_id, ...escluse]);
    const dopo = ordineVisibile.slice(posizione + 1);
    return dopo.find(a => isDaDecidere(a) && !via.has(a.item_id)) || ordineVisibile.find(a => isDaDecidere(a) && !via.has(a.item_id)) || dopo.find(a => !a.chiudere && !via.has(a.item_id));
  };
  const salvaEProssima = async () => {
    const prossima = trovaProssima(bersagli.map(x => x.item_id));
    if (!(await handleSave(false, true))) return;
    vaiAllaProssima(prossima);
  };
  const vaiAllaProssima = prossima => {
    if (prossima) setSelectedSnId(prossima.item_id);else flash({
      ok: true,
      text: "Decisione salvata · nessun'altra anomalia da decidere su questo OP"
    });
  };
  const annullaModifiche = () => {
    setDesc(baseline.desc);
    setNote(baseline.note);
    setPezziPrec(baseline.pezziPrec);
    setAprireRdc(baseline.aprireRdc);
    setRdcNum(baseline.rdcNum);
    setSegnalare(baseline.segnalare);
    setTerzista(baseline.terzista);
    setDovePezzi(baseline.dovePezzi);
    setSegnalaCar(baseline.segnalaCar);
    setCarScelti(baseline.carScelti);
    setAvanzamento(baseline.avanzamento);
    setDescrizioneAnswers(baseline.risposte);
    setEditDesc(false);
    setSegnalati(baseline.segnalati);
    setRisposte({
      cliente: "",
      terzista: ""
    });
    setChiudiManuale(false);
  };

  // ── Decisione qualità ──
  const postJson = async (url, body, label) => {
    const r = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken()
      },
      body: JSON.stringify(body)
    });
    const d = await readJsonOrThrow(r, label);
    if (!r.ok || !d.success) throw new Error(d.error || `HTTP ${r.status}`);
    return d;
  };
  const aggiornaSn = campi => setAnomalie(prev => prev.map(a => a.item_id === sn.item_id ? {
    ...a,
    ...campi
  } : a));
  const oraBreve = () => new Date().toLocaleString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).replace(",", "");
  const salvaQualita = async (chiudi = false) => {
    if (!sn.local_id || qBusy) return;
    setQBusy(true);
    try {
      const body = {
        local_id: sn.local_id,
        avanzamento_qualita: qAv,
        note_qualita: qNote,
        chiudi
      };
      if (sn.aprire_rdc) body.numero_rdc = qNum;
      if (sn.segnalare) {
        body.segnalato_cliente = qSeg.cliente;
        body.risposta_cliente = qRisp.cliente.trim();
      }
      if (sn.segnala_terzista) {
        body.segnalato_terzista = qSeg.terzista;
        body.risposta_terzista = qRisp.terzista.trim();
      }
      const d = await postJson(API.qualita_salva, body, "Decisione qualità");
      const segnalatoNuovo = chi => qSeg[chi] ? sn[`segnalato_${chi}`] || {
        il: oraBreve(),
        da: CURRENT_USER_NAME,
        ruolo: "qualita"
      } : null;
      aggiornaSn({
        numero_rdc: d.numero_rdc || "",
        avanzamento_qualita: qAv,
        note_qualita: qNote,
        chiudere: !!d.chiusa,
        avanzamento: d.avanzamento || sn.avanzamento,
        qualita_da: CURRENT_USER_NAME,
        qualita_il: oraBreve(),
        ...(sn.segnalare ? {
          segnalato_cliente: segnalatoNuovo("cliente")
        } : {}),
        ...(sn.segnala_terzista ? {
          segnalato_terzista: segnalatoNuovo("terzista")
        } : {}),
        ...(d.chiusa ? {
          can_riaprire: true,
          in_carico_a_me: false
        } : {})
      });
      setQRisp({
        cliente: "",
        terzista: ""
      });
      setVersioneEsiti(v => v + 1);
      flash({
        ok: true,
        text: d.chiusa ? "Decisione qualità salvata · anomalia chiusa" : "Decisione qualità salvata"
      });
      loadOrdini();
    } catch (e) {
      flash({
        ok: false,
        text: "Errore: " + e.message
      }, 7000);
    }
    setQBusy(false);
  };
  const inviaRichiestaInfo = async () => {
    if (!infoModal || infoModal.busy) return;
    const destinatari = [infoModal.cc && "cc", infoModal.controllore && "controllore"].filter(Boolean);
    if (!destinatari.length) {
      setInfoModal({
        ...infoModal,
        err: "Scegli a chi chiedere."
      });
      return;
    }
    if (!infoModal.messaggio.trim()) {
      setInfoModal({
        ...infoModal,
        err: "Scrivi cosa ti serve sapere."
      });
      return;
    }
    setInfoModal({
      ...infoModal,
      busy: true,
      err: ""
    });
    try {
      const d = await postJson(API.qualita_richiedi_info, {
        local_id: sn.local_id,
        destinatari,
        messaggio: infoModal.messaggio.trim()
      }, "Richiesta informazioni");
      aggiornaSn({
        richieste_info: d.richieste || [],
        avanzamento_qualita: d.avanzamento_qualita || AVANZAMENTO_CHIARIMENTI,
        in_carico_a_me: false
      });
      setInfoModal(null);
      const inv = d.invio || {};
      flash({
        ok: true,
        text: `Richiesta inviata${inv.inviate ? ` · ${inv.inviate} mail` : ""}${(inv.senza_email || []).length ? ` · senza email: ${inv.senza_email.join(", ")}` : ""}`
      }, 6000);
      loadOrdini();
    } catch (e) {
      setInfoModal(m => m ? {
        ...m,
        busy: false,
        err: e.message
      } : m);
    }
  };
  const rispondiRichiesta = async () => {
    if (!rispInfo.trim() || !sn.local_id) return;
    try {
      const d = await postJson(API.qualita_rispondi_info, {
        local_id: sn.local_id,
        testo: rispInfo.trim()
      }, "Risposta alla qualità");
      aggiornaSn({
        richieste_info: d.richieste || [],
        ruoli_risposta: [],
        in_carico_a_me: false,
        ...(sn.avanzamento_qualita === AVANZAMENTO_CHIARIMENTI && !(d.richieste || []).some(r => r.aperta) ? {
          avanzamento_qualita: "In attesa"
        } : {})
      });
      setRispInfo("");
      flash({
        ok: true,
        text: "Risposta inviata · l'anomalia torna alla qualità"
      });
      loadOrdini();
    } catch (e) {
      flash({
        ok: false,
        text: "Errore: " + e.message
      }, 7000);
    }
  };
  // Riquadro delle richieste della qualità, con la risposta per chi ne ha una aperta.
  const renderRichieste = ruolo => {
    const tutte = sn.richieste_info || [];
    const mie = tutte.filter(r => (r.destinatari || []).includes(ruolo));
    if (!mie.length) return null;
    const puoRispondere = (sn.ruoli_risposta || []).includes(ruolo) && mie.some(r => r.aperta);
    return /*#__PURE__*/React.createElement("div", {
      className: `ga-richieste${mie.some(r => r.aperta) ? " is-aperta" : ""}`
    }, /*#__PURE__*/React.createElement("div", {
      className: "ga-richieste__t"
    }, "Richieste della qualit\xE0"), mie.map(r => /*#__PURE__*/React.createElement("div", {
      key: r.id,
      className: "ga-richiesta"
    }, /*#__PURE__*/React.createElement("div", {
      className: "ga-hint"
    }, r.da, " \xB7 ", r.il, r.aperta ? " · in attesa di risposta" : ""), /*#__PURE__*/React.createElement("div", {
      className: "ga-richiesta__msg"
    }, r.messaggio), !r.aperta && /*#__PURE__*/React.createElement("div", {
      className: "ga-richiesta__risp"
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-hint"
    }, "Risposta di ", r.risposta_da, " \xB7 ", r.risposta_il), /*#__PURE__*/React.createElement("div", null, r.risposta)))), puoRispondere && /*#__PURE__*/React.createElement("div", {
      className: "ga-richiesta__form"
    }, /*#__PURE__*/React.createElement("textarea", {
      className: "ga-input",
      rows: 2,
      value: rispInfo,
      onChange: e => setRispInfo(e.target.value),
      placeholder: "Scrivi le informazioni richieste\u2026"
    }), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "ga-btn ga-btn--accent ga-btn--sm",
      disabled: !rispInfo.trim(),
      onClick: rispondiRichiesta
    }, "Invia risposta")));
  };

  // Riapertura: capocommessa, CAR, controllore o chi modifica l'OP (deciso dal server).
  const riapri = async () => {
    if (!sn.local_id || !API.riapri) return;
    setSaving(true);
    try {
      const r = await fetch(API.riapri, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken()
        },
        body: JSON.stringify({
          local_id: sn.local_id
        }),
        credentials: "same-origin"
      });
      const data = await readJsonOrThrow(r, "Riapertura anomalia");
      if (!data.success) throw new Error(data.error || "risposta non valida");
      setAnomalie(prev => prev.map(a => a.item_id === sn.item_id ? {
        ...a,
        chiudere: false,
        avanzamento: "In attesa",
        can_riaprire: false
      } : a));
      setAvanzamento("In attesa");
      flash({
        ok: true,
        text: `Anomalia #${sn.local_id} riaperta · in attesa di decisione`
      });
      loadOrdini();
    } catch (e) {
      flash({
        ok: false,
        text: "Errore: " + e.message
      }, 7000);
    }
    setSaving(false);
  };
  const ricaricaAnomalie = async () => {
    if (!op || !op.item_id) return;
    const r = await fetch(`${API.anomalie}?op_item_id=${encodeURIComponent(op.item_id)}&op_id=${encodeURIComponent(op.id || "")}`, {
      credentials: "same-origin"
    });
    const list = await readJsonOrThrow(r, "Caricamento anomalie");
    setAnomalie(Array.isArray(list) ? list : []);
    return Array.isArray(list) ? list : [];
  };
  const postAzione = async (url, body, contesto) => {
    const r = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken()
      },
      body: JSON.stringify(body),
      credentials: "same-origin"
    });
    const data = await readJsonOrThrow(r, contesto);
    if (!data.success) throw new Error(data.error || "risposta non valida");
    return data;
  };
  const apriTaglia = () => {
    setAzAnom({
      tipo: "taglia",
      op: op.id || "",
      sn: "",
      seriali: [],
      busy: false,
      err: ""
    });
  };
  // S/N noti dell'OP di destinazione, come suggerimenti.
  useEffect(() => {
    if (!azAnom || azAnom.tipo !== "taglia" || !API.seriali_op) return undefined;
    const opDest = String(azAnom.op || "").trim();
    if (!opDest) return undefined;
    let alive = true;
    const t = setTimeout(() => {
      fetch(`${API.seriali_op}?op_id=${encodeURIComponent(opDest)}`, {
        credentials: "same-origin"
      }).then(r => r.ok ? r.json() : {
        seriali: []
      }).then(d => {
        if (alive) setAzAnom(p => p ? {
          ...p,
          seriali: Array.isArray(d.seriali) ? d.seriali : []
        } : p);
      }).catch(() => {});
    }, 300);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [azAnom && azAnom.tipo, azAnom && azAnom.op]);
  const confermaAzione = async () => {
    if (!azAnom || !sn.local_id) return;
    const id = sn.local_id;
    if (azAnom.tipo === "taglia") {
      if (!String(azAnom.op || "").trim()) {
        setAzAnom({
          ...azAnom,
          err: "Indica l'OP."
        });
        return;
      }
      if (!String(azAnom.sn || "").trim()) {
        setAzAnom({
          ...azAnom,
          err: "Indica il S/N di destinazione."
        });
        return;
      }
    }
    setAzAnom({
      ...azAnom,
      busy: true,
      err: ""
    });
    try {
      if (azAnom.tipo === "elimina") {
        await postAzione(API.elimina, {
          local_id: id
        }, "Elimina anomalia");
        flash({
          ok: true,
          text: `Anomalia #${id} eliminata`
        });
      } else {
        const dest = ordini.find(o => String(o.id || "").toLowerCase() === String(azAnom.op).trim().toLowerCase());
        const seriali = String(azAnom.sn).split(/[,;\n]+/).map(s => s.trim()).filter(Boolean);
        const data = await postAzione(API.sposta, {
          local_id: id,
          op_id: String(azAnom.op).trim(),
          op_item_id: dest ? dest.item_id : null,
          seriali
        }, "Taglia");
        flash({
          ok: true,
          text: `Anomalia #${id}: ${data.nota || "spostata"}`
        }, 6000);
      }
      setAzAnom(null);
      setCurrentItemId(null);
      const list = await ricaricaAnomalie();
      const ancora = (list || []).find(a => a.local_id === id);
      const first = ancora || (list || []).find(isDaDecidere) || (list || []).find(a => !a.chiudere);
      setSelectedSnId(first ? first.item_id : "");
      loadOrdini();
    } catch (e) {
      setAzAnom(p => p ? {
        ...p,
        busy: false,
        err: e.message
      } : p);
    }
  };
  const apriModificaOp = async o => {
    if (!API.op_modifica) return;
    setModOp({
      titolo: o.id,
      dati: null,
      iniz: null,
      motivo: "",
      busy: true,
      err: ""
    });
    try {
      const r = await fetch(`${API.op_modifica}?item_id=${encodeURIComponent(o.item_id)}`, {
        credentials: "same-origin"
      });
      const d = await readJsonOrThrow(r, "Modifica OP");
      setModOp({
        titolo: o.id,
        dati: {
          ...d.op
        },
        iniz: {
          ...d.op
        },
        motivo: "",
        busy: false,
        err: ""
      });
    } catch (e) {
      setModOp({
        titolo: o.id,
        dati: null,
        iniz: null,
        motivo: "",
        busy: false,
        err: e.message
      });
    }
  };
  const campoModOp = (campo, valore) => setModOp(p => p ? {
    ...p,
    dati: {
      ...p.dati,
      [campo]: valore
    },
    err: ""
  } : p);
  const modOpCambiato = !!(modOp && modOp.dati && modOp.iniz && ["pn", "capocommessa", "car", "fase", "note", "benestare"].some(k => String(modOp.dati[k] ?? "").trim() !== String(modOp.iniz[k] ?? "").trim()));
  const salvaModificaOp = async () => {
    if (!modOp || !modOp.dati) return;
    if (!modOpCambiato) {
      setModOp({
        ...modOp,
        err: "Non hai cambiato nessun dato."
      });
      return;
    }
    if (String(modOp.motivo || "").trim().length < 5) {
      setModOp({
        ...modOp,
        err: "Scrivi il motivo della modifica."
      });
      return;
    }
    setModOp({
      ...modOp,
      busy: true,
      err: ""
    });
    try {
      const {
        item_id,
        pn,
        capocommessa,
        car,
        fase,
        note: noteOp,
        benestare
      } = modOp.dati;
      const data = await postAzione(API.op_modifica, {
        item_id,
        pn,
        capocommessa,
        car,
        fase,
        note: noteOp,
        benestare,
        motivazione: modOp.motivo
      }, "Modifica OP");
      setModOp(null);
      flash({
        ok: true,
        text: `${modOp.titolo}: ${(data.modifiche || []).map(m => m.etichetta).join(", ") || "dati"} modificati`
      }, 5000);
      loadOrdini();
    } catch (e) {
      setModOp(p => p ? {
        ...p,
        busy: false,
        err: e.message
      } : p);
    }
  };
  const duplica = () => {
    setMenuOpen(false);
    setCurrentItemId(null);
    flash({
      ok: true,
      text: "Copia pronta: modifica e salva per creare un nuovo record"
    });
  };

  // Ctrl+S salva, frecce Alt+↑/↓ scorrono le anomalie.
  useEffect(() => {
    const onKey = e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (canEditSelected && !saving) handleSave();
      } else if (e.altKey && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        vaiA(e.key === "ArrowDown" ? 1 : -1);
      } else if (e.key === "Escape") {
        setLightbox(null);
        setMenuOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  useEffect(() => {
    const handler = e => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
  const handleOpenReport = format => {
    setMenuOpen(false);
    const params = new URLSearchParams();
    if (op.item_id) params.set("op_item_id", op.item_id);else if (op.id) params.set("op_id", op.id);else if (currentLocalId) params.set("id", currentLocalId);else return;
    if (format === "pdf") params.set("format", "pdf");
    window.open(`${API.report}?${params.toString()}`, "_blank", "noopener");
  };
  const statoSel = statoAnomalia(sn);
  const isBenestare = String(op.stato || "").toLowerCase() === "benestare";
  const showCol = name => !isMobile || mobilePanel === name;

  // ── Rendering elenco anomalie (con intestazione per blocco di seriali) ──
  const renderAnomalia = a => {
    const st = statoAnomalia(a);
    const selected = a.item_id === sn.item_id;
    const inClona = clonaIds && clonaIds.includes(a.local_id);
    return /*#__PURE__*/React.createElement("button", {
      type: "button",
      key: a.item_id,
      className: `ga-an${selected ? " is-sel" : ""}${a.chiudere ? " is-closed" : ""}${inClona ? " is-clona" : ""}`,
      onClick: () => {
        if (clonaIds) toggleClona([a.local_id], !inClona);
        selectSn(a);
      }
    }, clonaIds ? /*#__PURE__*/React.createElement("span", {
      className: `ga-an__check${inClona ? " is-on" : ""}`,
      "aria-hidden": "true"
    }, inClona ? Ico.check : null) : /*#__PURE__*/React.createElement("span", {
      className: `ga-an__dot ga-an__dot--${st.variant}`
    }), /*#__PURE__*/React.createElement("span", {
      className: "ga-an__main"
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-an__txt"
    }, a.blocco_id ? a.testo || a.desc || "(nessuna descrizione)" : a.sn ? `S/N ${a.sn}` : a.testo || a.desc || "—"), /*#__PURE__*/React.createElement("span", {
      className: "ga-an__meta"
    }, raggruppa !== "stato" && /*#__PURE__*/React.createElement("span", {
      className: `ga-pill ga-pill--${st.variant}`
    }, st.text), a.aprire_rdc && /*#__PURE__*/React.createElement("span", {
      className: "ga-pill ga-pill--rdc"
    }, a.numero_rdc ? `RDC ${a.numero_rdc}` : a.chiudere ? "RDC" : "RDC · manca N°"), a.segnalare && /*#__PURE__*/React.createElement("span", {
      className: "ga-pill ga-pill--cli"
    }, a.chiudere || a.segnalato_cliente ? "Cliente" : "Cliente · da segnalare"), a.segnala_terzista && /*#__PURE__*/React.createElement("span", {
      className: "ga-pill ga-pill--ter"
    }, a.chiudere || a.segnalato_terzista ? "Terzista" : "Terzista · da segnalare"), a.avanzamento_qualita && !a.chiudere && /*#__PURE__*/React.createElement("span", {
      className: "ga-pill ga-pill--muted",
      title: "Avanzamento qualit\xE0"
    }, "Qualit\xE0 \xB7 ", a.avanzamento_qualita), a.in_carico_a_me && pageFilter !== "in_carico" && /*#__PURE__*/React.createElement("span", {
      className: "ga-pill ga-pill--tocca"
    }, "Tocca a te"), a.seriali_parziali && /*#__PURE__*/React.createElement("span", {
      className: "ga-pill ga-pill--muted",
      title: `Solo sui S/N: ${a.seriali_parziali}`
    }, "Solo ", a.seriali_parziali), !a.blocco_id && (a.testo || a.desc) && /*#__PURE__*/React.createElement("span", {
      className: "ga-an__sub"
    }, a.testo || a.desc), /*#__PURE__*/React.createElement("span", {
      className: "ga-an__id"
    }, "#", a.local_id))));
  };
  // Un gruppo: intestazione cliccabile (apre/chiude, scelta ricordata) e righe.
  // Chiuso, mostra comunque l'anomalia aperta a destra se è sua. Durante «Clona»
  // i gruppi sono tutti aperti per poter spuntare anche le chiuse.
  const renderGruppo = g => {
    const chiuso = !clonaIds && gruppoChiuso(g);
    const daDec = g.items.filter(isDaDecidere).length;
    const ids = g.items.map(y => y.local_id);
    const tutto = Boolean(clonaIds) && ids.every(x => clonaIds.includes(x));
    const b = g.blocco;
    const meta = b ? [b.fase ? `Fase ${b.fase}` : "", b.controllo_operatore, fmtData(b.controllo_data)].filter(Boolean).join(" · ") : "";
    const visibili = chiuso ? g.items.filter(a => a.item_id === sn.item_id) : g.items;
    return /*#__PURE__*/React.createElement("div", {
      key: g.key,
      className: `ga-grp ga-grp--${g.tone}${chiuso ? " is-chiuso" : ""}`
    }, /*#__PURE__*/React.createElement("div", {
      className: "ga-grp__head"
    }, clonaIds && /*#__PURE__*/React.createElement("label", {
      className: "ga-blk__clona",
      title: "Copia tutte le anomalie del gruppo"
    }, /*#__PURE__*/React.createElement("input", {
      type: "checkbox",
      checked: tutto,
      onChange: e => toggleClona(ids, e.target.checked)
    })), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "ga-grp__toggle",
      "aria-expanded": !chiuso,
      onClick: () => toggleGruppo(g),
      title: chiuso ? "Apri il gruppo" : "Chiudi il gruppo"
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-grp__line"
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-grp__caret",
      "aria-hidden": "true"
    }, "\u25BE"), /*#__PURE__*/React.createElement("span", {
      className: `ga-grp__label${g.tone === "blocco" ? " ga-grp__label--sn" : ""}`
    }, g.label), /*#__PURE__*/React.createElement("span", {
      className: "ga-grp__n"
    }, g.items.length), g.tone === "blocco" && daDec > 0 && /*#__PURE__*/React.createElement("span", {
      className: "ga-blk__todo"
    }, daDec, " da decidere")), meta && !chiuso && /*#__PURE__*/React.createElement("span", {
      className: "ga-grp__meta"
    }, meta))), visibili.length > 0 && /*#__PURE__*/React.createElement("div", {
      className: "ga-grp__body"
    }, visibili.map(renderAnomalia)));
  };
  return /*#__PURE__*/React.createElement("div", {
    className: `ga${isMobile ? " ga--mobile" : ""}`
  }, /*#__PURE__*/React.createElement("header", {
    className: "ga-top"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-top__left"
  }, /*#__PURE__*/React.createElement("a", {
    href: "/anomalie-menu",
    className: "ga-iconbtn",
    title: "Torna al menu anomalie"
  }, Ico.back), /*#__PURE__*/React.createElement("h1", {
    className: "ga-top__title"
  }, isMobile && mobilePanel !== "ordini" && op.id ? op.id : "Gestione anomalie"), !isMobile && op.id && /*#__PURE__*/React.createElement("span", {
    className: "ga-top__op"
  }, op.id, op.pn && op.pn !== "—" ? ` · ${op.pn}` : "")), /*#__PURE__*/React.createElement("div", {
    className: "ga-top__right"
  }, /*#__PURE__*/React.createElement("a", {
    className: "ga-btn ga-btn--accent",
    href: nuovaAnomaliaUrl,
    title: "Apri un nuovo controllo con segnalazione di anomalie"
  }, Ico.plus, !isMobile && /*#__PURE__*/React.createElement("span", null, "Nuova segnalazione")), !isMobile && API.nc_lista && /*#__PURE__*/React.createElement("a", {
    className: "ga-btn ga-btn--ghost",
    href: API.nc_lista
  }, "Non conformit\xE0"), /*#__PURE__*/React.createElement("div", {
    className: "ga-menu"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-iconbtn",
    title: "Altre azioni",
    "aria-expanded": menuOpen,
    onClick: () => setMenuOpen(v => !v)
  }, Ico.more), menuOpen && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "ga-menu__scrim",
    onClick: () => setMenuOpen(false)
  }), /*#__PURE__*/React.createElement("div", {
    className: "ga-menu__pop",
    role: "menu"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    role: "menuitem",
    disabled: !op.id,
    onClick: () => handleOpenReport()
  }, "Report OP"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    role: "menuitem",
    disabled: !op.id,
    onClick: () => handleOpenReport("pdf")
  }, "Report OP in PDF"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    role: "menuitem",
    disabled: !canEditSelected,
    onClick: duplica
  }, "Duplica anomalia come nuovo record"), isMobile && API.nc_lista && /*#__PURE__*/React.createElement("a", {
    role: "menuitem",
    href: API.nc_lista
  }, "Non conformit\xE0"), IS_ADMIN && ADMIN_URL && /*#__PURE__*/React.createElement("a", {
    role: "menuitem",
    href: ADMIN_URL
  }, "Configurazione modulo")))))), /*#__PURE__*/React.createElement("div", {
    className: "ga-cols",
    style: isMobile ? undefined : {
      gridTemplateColumns: isTablet ? "250px 270px minmax(0,1fr)" : "310px 330px minmax(0,1fr)"
    }
  }, /*#__PURE__*/React.createElement("section", {
    className: "ga-col ga-col--op",
    style: {
      display: showCol("ordini") ? undefined : "none"
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-col__head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-col__title"
  }, "Ordini di produzione"), /*#__PURE__*/React.createElement("div", {
    className: "ga-chips"
  }, [["aperte", "Con aperte"], ["in_carico", "In carico a me"], ["tutti", "Tutti"]].map(([v, l]) => /*#__PURE__*/React.createElement(Chip, {
    key: v,
    active: pageFilter === v,
    count: loadingOrdini ? "…" : contatoriFiltro[v],
    onClick: () => setPageFilter(v)
  }, l))), /*#__PURE__*/React.createElement("div", {
    className: "ga-search"
  }, Ico.search, /*#__PURE__*/React.createElement("input", {
    value: searchOp,
    onChange: e => setSearchOp(e.target.value),
    placeholder: "Cerca OP, P/N, capocommessa, CAR\u2026"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "ga-col__body"
  }, loadingOrdini ? /*#__PURE__*/React.createElement("div", {
    className: "ga-empty"
  }, "Caricamento ordini\u2026") : filteredOrdini.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "ga-empty"
  }, pageFilter === "in_carico" ? "Nessun OP con anomalie aperte in carico a te." : pageFilter === "aperte" ? "Nessun OP con anomalie aperte." : "Nessun ordine trovato.") : filteredOrdini.map(o => {
    // Riga compatta: numero, P/N e contatori; il resto è nella scheda
    // dell'OP in cima alla colonna Anomalie.
    const sel = opKey(o) === opKey(op);
    const tot = Number(o.anomalie_count || 0);
    const aperte = apertiDi(o);
    const daDec = daDecidereDi(o);
    const inCorso = Math.max(0, aperte - daDec);
    return /*#__PURE__*/React.createElement("button", {
      type: "button",
      key: opKey(o),
      className: `ga-opr${sel ? " is-sel" : ""}`,
      onClick: () => selectOp(o),
      title: `Capocommessa ${o.capo || "—"} · CAR ${o.car || "—"}`
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-opr__id"
    }, o.id, String(o.stato || "").toLowerCase() === "benestare" && /*#__PURE__*/React.createElement("span", {
      className: "ga-pill ga-pill--ben"
    }, "Benestare")), /*#__PURE__*/React.createElement("span", {
      className: "ga-opr__cnt"
    }, daDec > 0 && /*#__PURE__*/React.createElement("span", {
      className: "ga-cnt ga-cnt--dec",
      title: "Da decidere"
    }, daDec), inCorso > 0 && /*#__PURE__*/React.createElement("span", {
      className: "ga-cnt ga-cnt--corso",
      title: "Aperte con una decisione, in corso"
    }, inCorso), tot > 0 && aperte === 0 && /*#__PURE__*/React.createElement("span", {
      className: "ga-cnt ga-cnt--ok",
      title: "Tutte chiuse"
    }, "\u2713")), /*#__PURE__*/React.createElement("span", {
      className: "ga-opr__pn"
    }, o.pn && o.pn !== "—" ? o.pn : "—"));
  }))), /*#__PURE__*/React.createElement("section", {
    className: "ga-col ga-col--sn",
    style: {
      display: showCol("serie") ? undefined : "none"
    }
  }, op.id && (() => {
    // Scheda dell'OP scelto: persone, avanzamento e azioni sull'OP. Stessi
    // contatori della riga a sinistra (apertiDi / daDecidereDi).
    const tot = Number(op.anomalie_count || 0);
    const aperte = apertiDi(op);
    const daDec = daDecidereDi(op);
    const inCorso = Math.max(0, aperte - daDec);
    const chiuse = Math.max(0, tot - aperte);
    const perc = n => `${tot ? n / tot * 100 : 0}%`;
    return /*#__PURE__*/React.createElement("div", {
      className: "ga-opsheet"
    }, /*#__PURE__*/React.createElement("div", {
      className: "ga-opsheet__row"
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-opsheet__id"
    }, op.id), op.pn && op.pn !== "—" && /*#__PURE__*/React.createElement("span", {
      className: "ga-opsheet__pn"
    }, op.pn), /*#__PURE__*/React.createElement("span", {
      className: "ga-opsheet__acts"
    }, op.can_modifica_op && /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "ga-op__clona",
      title: "Correggi i dati dell'OP che hai inserito tu",
      onClick: () => apriModificaOp(op)
    }, Ico.edit, /*#__PURE__*/React.createElement("span", null, "Modifica OP")), tot > 0 && /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: `ga-op__clona${clonaIds ? " is-on" : ""}`,
      title: "Clona: scegli le anomalie da copiare su un nuovo OP",
      onClick: () => avviaClona(op)
    }, Ico.copy, /*#__PURE__*/React.createElement("span", null, "Clona")))), /*#__PURE__*/React.createElement("div", {
      className: "ga-opsheet__people"
    }, /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, "Capocommessa"), " ", op.capo || "—"), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, "CAR"), " ", op.car || "—")), tot > 0 ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
      className: "ga-seg",
      role: "img",
      "aria-label": `${daDec} da decidere, ${inCorso} in corso, ${chiuse} chiuse`
    }, /*#__PURE__*/React.createElement("i", {
      className: "ga-seg--dec",
      style: {
        width: perc(daDec)
      }
    }), /*#__PURE__*/React.createElement("i", {
      className: "ga-seg--corso",
      style: {
        width: perc(inCorso)
      }
    }), /*#__PURE__*/React.createElement("i", {
      className: "ga-seg--ok",
      style: {
        width: perc(chiuse)
      }
    })), /*#__PURE__*/React.createElement("div", {
      className: "ga-opsheet__leg"
    }, /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("i", {
      className: "ga-seg--dec"
    }), daDec, " da decidere"), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("i", {
      className: "ga-seg--corso"
    }), inCorso, " in corso"), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("i", {
      className: "ga-seg--ok"
    }), chiuse, " chius", chiuse === 1 ? "a" : "e"))) : /*#__PURE__*/React.createElement("div", {
      className: "ga-opsheet__leg"
    }, "Nessuna anomalia"));
  })(), /*#__PURE__*/React.createElement("div", {
    className: "ga-col__head"
  }, !op.id && /*#__PURE__*/React.createElement("div", {
    className: "ga-col__title"
  }, "Anomalie"), clonaIds && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--info"
  }, /*#__PURE__*/React.createElement("b", null, "Clona ", op.id), ": spunta le anomalie da copiare sul nuovo OP (anche le chiuse), poi \xABContinua\xBB."), /*#__PURE__*/React.createElement("div", {
    className: "ga-raggr"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-seg-ctl",
    role: "group",
    "aria-label": "Raggruppa le anomalie"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: raggruppa === "sn" ? "is-on" : "",
    "aria-pressed": raggruppa === "sn",
    onClick: () => setRaggruppa("sn")
  }, "Per S/N"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: raggruppa === "stato" ? "is-on" : "",
    "aria-pressed": raggruppa === "stato",
    onClick: () => setRaggruppa("stato")
  }, "Per stato")), pageFilter === "in_carico" && anomalie.length > 0 && /*#__PURE__*/React.createElement("label", {
    className: "ga-mostra-tutte",
    title: "In \xABIn carico a me\xBB compaiono solo le anomalie che toccano a te"
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: mostraTutte,
    onChange: e => setMostraTutte(e.target.checked)
  }), /*#__PURE__*/React.createElement("span", null, "Mostra tutte (", anomalie.length, ") \xB7 tue ", nInCarico)), raggruppa === "sn" && /*#__PURE__*/React.createElement("div", {
    className: "ga-chips"
  }, /*#__PURE__*/React.createElement(Chip, {
    active: snFilter === "tutte",
    onClick: () => setSnFilter("tutte"),
    count: anomalie.length
  }, "Tutte"), /*#__PURE__*/React.createElement(Chip, {
    active: snFilter === "da_decidere",
    onClick: () => setSnFilter("da_decidere"),
    count: nDaDecidere,
    tone: "warn"
  }, "Da decidere"))), /*#__PURE__*/React.createElement("div", {
    className: "ga-search"
  }, Ico.search, /*#__PURE__*/React.createElement("input", {
    value: searchSn,
    onChange: e => setSearchSn(e.target.value),
    placeholder: "Cerca S/N, testo, #numero\u2026"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "ga-col__body"
  }, loadingAnom ? /*#__PURE__*/React.createElement("div", {
    className: "ga-empty"
  }, "Caricamento\u2026") : !op.id ? /*#__PURE__*/React.createElement("div", {
    className: "ga-empty"
  }, "Seleziona un ordine.") : filteredSeriali.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "ga-empty"
  }, pageFilter === "in_carico" && !mostraTutte && anomalie.length ? "Nessuna anomalia di questo OP tocca a te. «Mostra tutte» per vederle." : raggruppa === "sn" && snFilter === "da_decidere" && anomalie.length ? "Nessuna anomalia da decidere: tutto gestito. ✓" : searchSn ? "Nessuna anomalia corrisponde alla ricerca." : "Nessuna anomalia registrata.", canEditCurrentOp && !anomalie.length && /*#__PURE__*/React.createElement("a", {
    className: "ga-btn ga-btn--accent ga-btn--sm",
    href: nuovaAnomaliaUrl
  }, Ico.plus, "Nuova segnalazione")) : /*#__PURE__*/React.createElement("div", {
    className: "ga-grps"
  }, gruppiAnomalie.map(renderGruppo))), clonaIds && /*#__PURE__*/React.createElement("div", {
    className: "ga-clona"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-clona__top"
  }, /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, clonaIds.length), " da copiare"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-link",
    onClick: () => toggleClona(anomalie.map(a => a.local_id), true)
  }, "Tutte"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-link",
    onClick: () => toggleClona(anomalie.filter(a => !a.chiudere).map(a => a.local_id), true)
  }, "Aperte"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-link",
    onClick: () => setClona(p => p ? {
      ...p,
      ids: []
    } : p)
  }, "Nessuna")), /*#__PURE__*/React.createElement("div", {
    className: "ga-clona__acts"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--ghost-dark ga-btn--xs",
    onClick: () => setClona(null)
  }, "Annulla"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--accent ga-btn--xs",
    disabled: !clonaIds.length,
    onClick: continuaClona
  }, "Continua ", Ico.next)))), /*#__PURE__*/React.createElement("section", {
    className: "ga-col ga-col--det",
    style: {
      display: showCol("dettaglio") ? undefined : "none"
    }
  }, coda && coda.n > 0 && (() => {
    const min = Math.max(0, Math.ceil((new Date(coda.partenza).getTime() - Date.now()) / 60000));
    return /*#__PURE__*/React.createElement("div", {
      className: "ga-coda",
      role: "status",
      title: "Il riepilogo a capocommessa, CAR e segnalanti parte dopo una pausa sull'OP; ogni salvataggio fa ripartire l'attesa"
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-coda__dot"
    }), /*#__PURE__*/React.createElement("span", {
      className: "ga-coda__txt"
    }, /*#__PURE__*/React.createElement("b", null, coda.n), " decision", coda.n === 1 ? "e" : "i", " in attesa di invio \xB7 ", min > 0 ? `il riepilogo parte fra ${min} min` : "in partenza"), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "ga-btn ga-btn--outline ga-btn--xs",
      disabled: inviando,
      onClick: inviaOra
    }, inviando ? "Invio…" : "Invia ora"));
  })(), !sn.item_id ? /*#__PURE__*/React.createElement("div", {
    className: "ga-empty ga-empty--big"
  }, op.id ? "Seleziona un'anomalia dall'elenco." : "Seleziona un ordine di produzione.") : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "ga-det__head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-det__crumb"
  }, /*#__PURE__*/React.createElement("span", null, op.id), op.pn && op.pn !== "—" && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
    className: "ga-det__sep"
  }, "\xB7"), /*#__PURE__*/React.createElement("span", null, "P/N ", /*#__PURE__*/React.createElement("b", {
    className: "ga-det__pn"
  }, op.pn))), sn.fase && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
    className: "ga-det__sep"
  }, "\u203A"), /*#__PURE__*/React.createElement("span", null, "Fase ", sn.fase)), /*#__PURE__*/React.createElement("span", {
    className: `ga-pill ${isBenestare ? "ga-pill--ben" : "ga-pill--muted"}`
  }, isBenestare ? "Collaudo di benestare" : "Altro controllo")), /*#__PURE__*/React.createElement("div", {
    className: "ga-det__titlerow"
  }, /*#__PURE__*/React.createElement("h2", {
    className: "ga-det__title"
  }, "Anomalia #", sn.local_id), /*#__PURE__*/React.createElement("span", {
    className: `ga-pill ga-pill--${statoSel.variant} ga-pill--lg`
  }, statoSel.text), /*#__PURE__*/React.createElement("div", {
    className: "ga-det__nav"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-iconbtn ga-iconbtn--light",
    disabled: posizione <= 0,
    onClick: () => vaiA(-1),
    title: "Anomalia precedente (Alt+\u2191)"
  }, Ico.prev), /*#__PURE__*/React.createElement("span", null, posizione + 1, " di ", ordineVisibile.length), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-iconbtn ga-iconbtn--light",
    disabled: posizione < 0 || posizione >= ordineVisibile.length - 1,
    onClick: () => vaiA(1),
    title: "Anomalia successiva (Alt+\u2193)"
  }, Ico.next))), /*#__PURE__*/React.createElement(PezziInteressati, {
    sn: sn
  }), /*#__PURE__*/React.createElement("div", {
    className: "ga-det__people"
  }, isMobile && /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, "Capocommessa"), " ", op.capo || "—"), isMobile && /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, "CAR"), " ", op.car || "—"), sn.controllo_operatore && /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, "Segnalata da"), " ", sn.controllo_operatore, sn.controllo_data ? ` il ${fmtData(sn.controllo_data)}` : ""))), /*#__PURE__*/React.createElement("div", {
    className: "ga-det__body"
  }, !canEditCurrentOp && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--warn"
  }, "Sola lettura: puoi consultare ma non decidere su questo OP."), isSelectedClosed && (canEditCurrentOp || sn.can_riaprire) && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--ok ga-note--row"
  }, /*#__PURE__*/React.createElement("span", null, "Anomalia chiusa: i dati restano consultabili ma non modificabili."), sn.can_riaprire && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--outline ga-btn--xs",
    onClick: riapri,
    disabled: saving
  }, saving ? "Riapertura…" : "Riapri anomalia")), /*#__PURE__*/React.createElement("div", {
    className: `ga-card${sezChiusa("ctrl") ? " is-chiusa" : ""}`
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-card__head"
  }, /*#__PURE__*/React.createElement(TitoloSezione, {
    chiusa: sezChiusa("ctrl"),
    onToggle: () => toggleSez("ctrl")
  }, "Controllore \xB7 segnalazione"), sn.stato_superficie && /*#__PURE__*/React.createElement("span", {
    className: "ga-pill ga-pill--sup"
  }, sn.stato_superficie), canEditSelected && !editDesc && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-link",
    onClick: () => setEditDesc(true)
  }, "Modifica testo"), sn.can_sposta && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-link",
    title: "Sposta su un altro S/N dello stesso OP o di un altro OP",
    onClick: apriTaglia
  }, "\u2702 Taglia"), sn.can_elimina && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-link ga-link--danger",
    title: "Solo chi l'ha inserita, finch\xE9 nessuno ci ha lavorato",
    onClick: () => setAzAnom({
      tipo: "elimina",
      busy: false,
      err: ""
    })
  }, "Elimina")), editDesc ? /*#__PURE__*/React.createElement("textarea", {
    className: "ga-input",
    rows: 4,
    value: desc,
    onChange: e => setDesc(e.target.value),
    autoFocus: true
  }) : /*#__PURE__*/React.createElement("div", {
    className: "ga-desc"
  }, sn.testo || sn.desc || "(nessuna descrizione)"), Array.isArray(sn.descrizioni) && sn.descrizioni.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "ga-multi"
  }, sn.descrizioni.map((detail, index) => /*#__PURE__*/React.createElement("div", {
    key: detail.id,
    className: "ga-multi__item"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-multi__title"
  }, "Descrizione ", index + 1, " \xB7 S/N ", (detail.seriali || []).join(", ") || "—"), /*#__PURE__*/React.createElement("div", {
    className: "ga-desc"
  }, detail.testo), /*#__PURE__*/React.createElement("textarea", {
    className: "ga-input",
    rows: 2,
    placeholder: "Risposta per questa descrizione\u2026",
    value: descrizioneAnswers[String(detail.id)] || "",
    disabled: !canEditSelected,
    onChange: e => setDescrizioneAnswers(prev => ({
      ...prev,
      [String(detail.id)]: e.target.value
    }))
  }), detail.risposta_da && /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, "Risposta di ", detail.risposta_da, detail.risposta_il ? ` · ${new Date(detail.risposta_il).toLocaleString("it-IT")}` : "")))), (sn.dove_pezzi || (sn.dettaglio_righe || []).length > 0 || sn.tipo_difetto) && /*#__PURE__*/React.createElement("div", {
    className: "ga-ctrl"
  }, sn.dove_pezzi && /*#__PURE__*/React.createElement("div", null, "\uD83D\uDCE6 Dove sono i pezzi: ", /*#__PURE__*/React.createElement("b", null, sn.dove_pezzi)), (sn.dettaglio_righe || []).map((r, ri) => /*#__PURE__*/React.createElement("div", {
    key: ri,
    className: "ga-ctrl__r"
  }, r)), sn.tipo_difetto && /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, "Tipo di difetto: ", sn.tipo_difetto)), renderRichieste("controllore"), /*#__PURE__*/React.createElement("div", {
    className: `ga-att${dropOver ? " is-over" : ""}`,
    tabIndex: canEditCurrentOp ? 0 : -1,
    onDragOver: e => {
      if (!canEditCurrentOp) return;
      e.preventDefault();
      setDropOver(true);
    },
    onDragLeave: () => setDropOver(false),
    onDrop: e => {
      e.preventDefault();
      setDropOver(false);
      if (canEditCurrentOp) uploadFiles(Array.from(e.dataTransfer.files || []));
    },
    onPaste: e => {
      const files = Array.from(e.clipboardData && e.clipboardData.items || []).filter(it => it.kind === "file").map(it => it.getAsFile()).filter(Boolean);
      if (files.length && canEditCurrentOp) {
        e.preventDefault();
        uploadFiles(nomeAppunti(files));
      }
    }
  }, /*#__PURE__*/React.createElement("input", {
    ref: fileInputRef,
    type: "file",
    multiple: true,
    hidden: true,
    accept: ALLEGATI_ACCEPT,
    onChange: e => {
      const f = Array.from(e.target.files || []);
      e.target.value = "";
      uploadFiles(f);
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "ga-att__head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ga-card__sub"
  }, Ico.clip, " Allegati ", attAnomalia.length ? `(${attAnomalia.length})` : ""), canEditCurrentOp && /*#__PURE__*/React.createElement("span", {
    className: "ga-hint"
  }, uploadingAttachments ? "Caricamento…" : /*#__PURE__*/React.createElement(React.Fragment, null, "Trascina qui, ", /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-link",
    onClick: () => fileInputRef.current && fileInputRef.current.click()
  }, "sfoglia"), " o clicca e premi Ctrl+V"))), loadingAttachments ? /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, "Caricamento allegati\u2026") : attAnomalia.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, "Nessun allegato.") : renderAttGrid(attAnomalia))), /*#__PURE__*/React.createElement("div", {
    className: `ga-card ga-card--decision${dirty ? " is-dirty" : ""}${sezChiusa("cc") ? " is-chiusa" : ""}`
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-card__head"
  }, /*#__PURE__*/React.createElement(TitoloSezione, {
    chiusa: sezChiusa("cc"),
    onToggle: () => toggleSez("cc")
  }, "Capocommessa")), /*#__PURE__*/React.createElement(PercorsoAnomalia, {
    passi: esitiInfo && esitiInfo.local_id === sn.local_id ? esitiInfo.percorso : null
  }), /*#__PURE__*/React.createElement("div", {
    className: "ga-flags"
  }, /*#__PURE__*/React.createElement(FlagToggle, {
    label: "Aprire RDC",
    checked: aprireRdc,
    disabled: !canEditSelected,
    onChange: () => setAprireRdc(!aprireRdc)
  }), /*#__PURE__*/React.createElement(FlagToggle, {
    label: "Segnalare al cliente",
    checked: segnalare,
    disabled: !canEditSelected,
    onChange: toggleSegnalare
  }), /*#__PURE__*/React.createElement(FlagToggle, {
    label: "Segnala a terzista",
    checked: terzista,
    disabled: !canEditSelected,
    onChange: toggleTerzista
  }), /*#__PURE__*/React.createElement(FlagToggle, {
    label: "Segnala a CAR",
    hint: "I CAR scelti ricevono una mail con questa anomalia",
    checked: segnalaCar,
    disabled: !canEditSelected,
    onChange: toggleSegnalaCar
  }), /*#__PURE__*/React.createElement(FlagToggle, {
    label: "Pezzi precedenti al benestare",
    checked: pezziPrec,
    disabled: !canEditSelected,
    onChange: () => setPezziPrec(!pezziPrec)
  })), (segnalare || terzista || segnalaCar) && /*#__PURE__*/React.createElement("div", {
    className: "ga-segnalati-riga"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ga-hint"
  }, "Hai gi\xE0 fatto tu la segnalazione? Spunta \xABSegnalato\xBB."), [["cliente", segnalare, "Segnalato al cliente"], ["terzista", terzista, "Segnalato al terzista"]].filter(([, on]) => on).map(([chi,, label]) => {
    const reg = sn[`segnalato_${chi}`];
    return /*#__PURE__*/React.createElement("span", {
      key: chi,
      className: "ga-segnalato-voce"
    }, /*#__PURE__*/React.createElement(FlagToggle, {
      label: label,
      checked: segnalati[chi],
      disabled: !canEditSelected || !!reg && ruoloSegnalato(sn, chi) === "qualita",
      onChange: () => toggleSegnalato(chi)
    }), reg && /*#__PURE__*/React.createElement("span", {
      className: "ga-hint"
    }, "il ", reg.il, reg.da ? ` da ${reg.da}` : "", ruoloSegnalato(sn, chi) === "qualita" ? " (qualità)" : ""));
  }), segnalaCar && /*#__PURE__*/React.createElement("span", {
    className: "ga-segnalato-voce"
  }, /*#__PURE__*/React.createElement(FlagToggle, {
    label: "Segnalato al CAR",
    checked: !!sn.segnalato_car,
    disabled: true,
    onChange: () => {}
  }), /*#__PURE__*/React.createElement("span", {
    className: "ga-hint"
  }, sn.segnalato_car ? `il ${sn.segnalato_car.il} · mail dal portale` : "si spunta da solo quando parte la mail ai CAR scelti"))), !sn.chiudere && sn.item_id && (() => {
    // Cosa succede al salvataggio della decisione del capocommessa.
    const info = normalizeChoice(avanzamento) === AVANZAMENTO_INFO_RICHIESTE;
    const attesa = STATI_RISPOSTA.includes(normalizeChoice(avanzamento).toLowerCase());
    const manca = [];
    if (aprireRdc && !String(rdcNum || "").trim()) manca.push("il numero RDC");
    if (segnalare && !segnalati.cliente) manca.push("la segnalazione al cliente");
    if (terzista && !segnalati.terzista) manca.push("la segnalazione al terzista");
    const variante = info ? "info" : chiudere ? "ok" : "aperta";
    const testo = info ? "⏸ Rimandata al capocommessa: servono ulteriori informazioni" : chiudere ? "✓ Al salvataggio l'anomalia si chiude" : attesa ? "Al salvataggio resta in attesa della risposta: la registra chi ha fatto la segnalazione" : richiestaAperta(sn) ? "In attesa dei chiarimenti chiesti dalla qualità" : aprireRdc || segnalare || terzista || segnalaCar || baseline.avanzamento !== DEFAULT_AVANZAMENTO || note.trim() ? "Al salvataggio passa alla qualità" : "";
    if (!testo) return null;
    return /*#__PURE__*/React.createElement("div", {
      className: `ga-chiusura ga-chiusura--${variante}`,
      role: "status"
    }, /*#__PURE__*/React.createElement("div", {
      className: "ga-chiusura__t"
    }, testo), !chiudere && !info && !attesa && manca.length > 0 && /*#__PURE__*/React.createElement("div", {
      className: "ga-chiusura__d"
    }, "La qualit\xE0 completa ", manca.join(", "), "; senza RDC le segnalazioni fatte chiudono l'anomalia."));
  })(), segnalaCar && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "A quale CAR?"), carOpzioni.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, "Nessun CAR sull'OP e nessun capo reparto in Configurazione.") : /*#__PURE__*/React.createElement("div", {
    className: "ga-chips"
  }, carOpzioni.map(nome => /*#__PURE__*/React.createElement(Chip, {
    key: nome,
    active: carScelti.some(n => n.toLowerCase() === nome.toLowerCase()),
    onClick: () => canEditSelected && toggleCarScelto(nome)
  }, nome, isCarDellOp(nome) ? " · CAR dell'OP" : ""))), /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, carScelti.length ? `Al salvataggio la mail «Segnala a CAR» va solo a: ${carScelti.join(", ")} (chi l'ha già ricevuta non la riceve di nuovo).` : "Scegli almeno un CAR: senza scelta la segnalazione non parte.", " ", "Il CAR dell'OP riceve comunque il riepilogo delle modifiche, come sempre.")), /*#__PURE__*/React.createElement("div", {
    className: "ga-att ga-att--dec",
    onDragOver: e => {
      if (canEditCurrentOp && sn.local_id) e.preventDefault();
    },
    onDrop: e => {
      e.preventDefault();
      if (canEditCurrentOp && sn.local_id) uploadFiles(Array.from(e.dataTransfer.files || []), "decisione");
    }
  }, /*#__PURE__*/React.createElement("input", {
    ref: fileInputDecRef,
    type: "file",
    multiple: true,
    hidden: true,
    accept: ALLEGATI_ACCEPT,
    onChange: e => {
      const f = Array.from(e.target.files || []);
      e.target.value = "";
      uploadFiles(f, "decisione");
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "ga-att__head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ga-card__sub"
  }, Ico.clip, " Allegati della decisione ", attDecisione.length ? `(${attDecisione.length})` : ""), canEditCurrentOp && sn.local_id && /*#__PURE__*/React.createElement("span", {
    className: "ga-hint"
  }, uploadingAttachments ? "Caricamento…" : /*#__PURE__*/React.createElement(React.Fragment, null, "Trascina qui o ", /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-link",
    onClick: () => fileInputDecRef.current && fileInputDecRef.current.click()
  }, "sfoglia")))), attDecisione.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, "Nessun allegato alla decisione.") : renderAttGrid(attDecisione)), /*#__PURE__*/React.createElement("div", {
    className: "ga-grid2"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "Avanzamento"), /*#__PURE__*/React.createElement("select", {
    className: `ga-input${canEditSelected && (notaSenzaStato || rispostaSenzaStato) ? " is-invalid" : ""}`,
    value: avanzamento,
    onChange: e => setAvanzamento(e.target.value),
    disabled: !canEditSelected
  }, avanzamentoOptions.map(opt => /*#__PURE__*/React.createElement("option", {
    key: opt
  }, opt))))), notaCongelata ? /*#__PURE__*/React.createElement("div", {
    className: "ga-nota-ferma"
  }, /*#__PURE__*/React.createElement(FieldLabel, null, "Note gi\xE0 inviate"), /*#__PURE__*/React.createElement("div", {
    className: "ga-nota-ferma__testo"
  }, baseline.note), /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, "Congelate mentre si aspetta la risposta: scrivi la risposta nel campo qui sotto.")) : /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "Risposta / note per il reparto"), /*#__PURE__*/React.createElement("textarea", {
    className: "ga-input",
    rows: 3,
    value: note,
    onChange: e => setNote(e.target.value),
    disabled: !canEditSelected,
    placeholder: "Decisione, istruzioni di rilavorazione, riferimenti\u2026"
  })), canEditSelected && notaSenzaStato && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--warn"
  }, NOTA_STATO_MSG), DESTINATARI.filter(d => (d.chi === "cliente" ? segnalare : terzista) && baseline.segnalati[d.chi] && segnalati[d.chi] && ruoloSegnalato(sn, d.chi) === "cc" && STATI_RISPOSTA.includes(normalizeChoice(baseline.avanzamento).toLowerCase())).map(d => {
    const gia = (esitiInfo && esitiInfo.local_id === sn.local_id && esitiInfo.esiti || []).filter(e => e.tipo === d.tipo);
    return /*#__PURE__*/React.createElement("div", {
      key: d.chi,
      className: "ga-risposta"
    }, /*#__PURE__*/React.createElement(FieldLabel, null, d.risposta), gia.map(e => /*#__PURE__*/React.createElement("div", {
      key: e.id,
      className: "ga-risposta__gia"
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-hint"
    }, e.utente, e.data ? ` · ${new Date(e.data).toLocaleString("it-IT", {
      day: "2-digit",
      month: "2-digit",
      year: "2-digit",
      hour: "2-digit",
      minute: "2-digit"
    })}` : ""), /*#__PURE__*/React.createElement("div", null, e.testo))), canEditSelected && /*#__PURE__*/React.createElement("textarea", {
      className: `ga-input${rispostaSenzaStato && (risposte[d.chi] || "").trim() ? " is-invalid" : ""}`,
      rows: 2,
      value: risposte[d.chi],
      onChange: e => setRisposte(prev => ({
        ...prev,
        [d.chi]: e.target.value
      })),
      placeholder: gia.length ? "Un'altra risposta…" : `Cosa ha risposto ${d.a} (riferimento della mail, decisione…)`
    }));
  }), canEditSelected && rispostaSenzaStato && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--warn"
  }, RISPOSTA_STATO_MSG), renderRichieste("cc"), canEditSelected && !sn.chiudere && CC_PUO_CHIUDERE && /*#__PURE__*/React.createElement("div", {
    className: "ga-chiudi"
  }, /*#__PURE__*/React.createElement(FlagToggle, {
    label: "Chiudi l'anomalia",
    checked: chiudere,
    disabled: chiudereAuto,
    onChange: () => setChiudiManuale(!chiudiManuale)
  }), /*#__PURE__*/React.createElement("span", {
    className: "ga-hint"
  }, chiudereAuto ? "Si chiude da sola con questa decisione." : "Chiude al salvataggio anche se mancano dei passi.")), canEditSelected && chiudere && !sn.chiudere && !aprireRdc && esitiInfo && esitiInfo.serve_azione && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--warn"
  }, "La prima decisione \xE8 stata \xABAzione di recupero\xBB: per chiudere registra l'azione effettuata in \xABTempi ed esiti\xBB."), canEditSelected && (altreAperte.length > 0 || giaDecise > 0) && /*#__PURE__*/React.createElement("div", {
    className: "ga-apply ga-apply--ambito"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-apply__t"
  }, "Applica la stessa decisione anche a"), /*#__PURE__*/React.createElement("div", {
    className: "ga-apply__opts",
    role: "radiogroup",
    "aria-label": "Applica la stessa decisione anche a"
  }, [["solo", "Solo questa", null], ...(sn.blocco_id ? [["blocco", "Stesso blocco di seriali", stessoBlocco.length]] : []), ["op", "Tutte le aperte dell'OP", altreAperte.length], ["mano", "Scelte a mano", null]].map(([k, label, n]) => /*#__PURE__*/React.createElement("button", {
    key: k,
    type: "button",
    role: "radio",
    "aria-checked": ambito === k,
    className: `ga-chip-opt${ambito === k ? " is-on" : ""}`,
    disabled: n === 0,
    onClick: () => setAmbito(k)
  }, label, n != null ? /*#__PURE__*/React.createElement("span", {
    className: "ga-chip-opt__n"
  }, n) : null))), ambito === "blocco" && /*#__PURE__*/React.createElement(PezziInteressati, {
    sn: sn,
    compact: true
  }), ambito === "mano" && /*#__PURE__*/React.createElement("div", {
    className: "ga-apply__mano"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-apply__mano-acts"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ga-hint"
  }, scelteMano.filter(id => altreAperte.some(x => x.item_id === id)).length, " scelte su ", altreAperte.length), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-link",
    onClick: () => setScelteMano(altreAperte.map(x => x.item_id))
  }, "Tutte"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-link",
    onClick: () => setScelteMano([])
  }, "Nessuna")), altreAperte.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, "Nessun'altra anomalia ", includiDecise ? "aperta" : "da decidere", ".") : gruppiPerSn(altreAperte).map(g => /*#__PURE__*/React.createElement("div", {
    key: g.chiave,
    className: "ga-apply__grp"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-apply__grp-t"
  }, "S/N ", g.titolo), g.righe.map(x => /*#__PURE__*/React.createElement("label", {
    key: x.item_id,
    className: "ga-apply__row"
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: scelteMano.includes(x.item_id),
    onChange: e => setScelteMano(prev => e.target.checked ? [...prev, x.item_id] : prev.filter(id => id !== x.item_id))
  }), /*#__PURE__*/React.createElement("span", {
    className: "ga-apply__txt"
  }, x.testo || x.desc || "—"), /*#__PURE__*/React.createElement("span", {
    className: "ga-hint"
  }, "#", x.local_id, isDaDecidere(x) ? "" : ` · ${x.avanzamento || "decisa"}`)))))), giaDecise > 0 && ambito !== "solo" && /*#__PURE__*/React.createElement("label", {
    className: "ga-apply__decise"
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: includiDecise,
    onChange: e => setIncludiDecise(e.target.checked)
  }), /*#__PURE__*/React.createElement("span", null, "Includi anche le ", giaDecise, " gi\xE0 decise (la loro decisione viene sostituita)")))), sn.local_id && (() => {
    const puo = CAN_QUALITA && !sn.chiudere;
    const attesaQ = chi => ruoloSegnalato(sn, chi) === "qualita" && !!sn[`segnalato_${chi}`] && normalizeChoice(sn.avanzamento).toLowerCase() === AVANZAMENTO_RISPOSTA[chi].toLowerCase();
    const chiudeQ = !sn.chiudere && shouldAutoClose(!!sn.aprire_rdc, DESTINATARI.some(d => attesaQ(d.chi) && qRisp[d.chi].trim()) ? "In attesa" : sn.avanzamento, qNum, !!sn.segnalare, qSeg.cliente, !!sn.segnala_terzista, qSeg.terzista, richiestaAperta(sn));
    const esitiQ = tipo => (esitiInfo && esitiInfo.local_id === sn.local_id && esitiInfo.esiti || []).filter(e => e.tipo === tipo);
    return /*#__PURE__*/React.createElement("div", {
      className: `ga-card ga-card--qualita${sezChiusa("qualita") ? " is-chiusa" : ""}`
    }, /*#__PURE__*/React.createElement("div", {
      className: "ga-card__head"
    }, /*#__PURE__*/React.createElement(TitoloSezione, {
      chiusa: sezChiusa("qualita"),
      onToggle: () => toggleSez("qualita")
    }, "Decisione qualit\xE0"), sezChiusa("qualita") && sn.avanzamento_qualita && /*#__PURE__*/React.createElement("span", {
      className: "ga-pill ga-pill--muted"
    }, sn.avanzamento_qualita), sn.qualita_da && /*#__PURE__*/React.createElement("span", {
      className: "ga-hint"
    }, sn.qualita_da, sn.qualita_il ? ` · ${sn.qualita_il}` : "")), !puo && !sn.avanzamento_qualita && !sn.note_qualita && !sn.numero_rdc && !attQualita.length && !(sn.richieste_info || []).length ? /*#__PURE__*/React.createElement("div", {
      className: "ga-hint"
    }, sn.chiudere ? "Nessuna decisione qualità." : "La decide la qualità (Configurazione → «Qualità»).") : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
      className: "ga-grid2"
    }, sn.aprire_rdc && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "Numero RDC"), /*#__PURE__*/React.createElement("input", {
      className: `ga-input${puo && !qNum.trim() ? " is-invalid" : ""}`,
      placeholder: "Es. RDC-2026-014",
      value: qNum,
      onChange: e => setQNum(e.target.value),
      disabled: !puo
    })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "Avanzamento qualit\xE0"), /*#__PURE__*/React.createElement("select", {
      className: "ga-input",
      value: qAv,
      onChange: e => setQAv(e.target.value),
      disabled: !puo
    }, /*#__PURE__*/React.createElement("option", {
      value: ""
    }, "\u2014 nessuno stato \u2014"), [...AVANZAMENTI_QUALITA, ...(qAv && !AVANZAMENTI_QUALITA.includes(qAv) ? [qAv] : [])].map(o => /*#__PURE__*/React.createElement("option", {
      key: o
    }, o))))), (sn.segnalare || sn.segnala_terzista) && /*#__PURE__*/React.createElement("div", {
      className: "ga-segnalati-riga"
    }, DESTINATARI.filter(d => d.chi === "cliente" ? sn.segnalare : sn.segnala_terzista).map(d => {
      const reg = sn[`segnalato_${d.chi}`];
      const delCc = !!reg && ruoloSegnalato(sn, d.chi) === "cc";
      return /*#__PURE__*/React.createElement("span", {
        key: d.chi,
        className: "ga-segnalato-voce"
      }, /*#__PURE__*/React.createElement(FlagToggle, {
        label: d.segnalato,
        checked: qSeg[d.chi],
        disabled: !puo || delCc,
        onChange: () => setQSeg(p => ({
          ...p,
          [d.chi]: !p[d.chi]
        }))
      }), /*#__PURE__*/React.createElement("span", {
        className: "ga-hint"
      }, reg ? `il ${reg.il}${reg.da ? ` da ${reg.da}` : ""}${delCc ? " (capocommessa)" : ""}` : "se il capocommessa non l'ha fatto"));
    })), DESTINATARI.filter(d => attesaQ(d.chi)).map(d => /*#__PURE__*/React.createElement("div", {
      key: d.chi,
      className: "ga-risposta"
    }, /*#__PURE__*/React.createElement(FieldLabel, null, d.risposta), esitiQ(d.tipo).map(e => /*#__PURE__*/React.createElement("div", {
      key: e.id,
      className: "ga-risposta__gia"
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-hint"
    }, e.utente), /*#__PURE__*/React.createElement("div", null, e.testo))), puo && /*#__PURE__*/React.createElement("textarea", {
      className: "ga-input",
      rows: 2,
      value: qRisp[d.chi],
      onChange: e => setQRisp(p => ({
        ...p,
        [d.chi]: e.target.value
      })),
      placeholder: `Cosa ha risposto ${d.a}`
    }))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "Note della qualit\xE0"), /*#__PURE__*/React.createElement("textarea", {
      className: "ga-input",
      rows: 3,
      value: qNote,
      onChange: e => setQNote(e.target.value),
      disabled: !puo,
      placeholder: "Valutazione, riferimenti RDC, indicazioni\u2026"
    })), /*#__PURE__*/React.createElement("div", {
      className: "ga-att ga-att--dec",
      onDragOver: e => {
        if (puo) e.preventDefault();
      },
      onDrop: e => {
        e.preventDefault();
        if (puo) uploadFiles(Array.from(e.dataTransfer.files || []), "qualita");
      }
    }, /*#__PURE__*/React.createElement("input", {
      ref: fileInputQRef,
      type: "file",
      multiple: true,
      hidden: true,
      accept: ALLEGATI_ACCEPT,
      onChange: e => {
        const f = Array.from(e.target.files || []);
        e.target.value = "";
        uploadFiles(f, "qualita");
      }
    }), /*#__PURE__*/React.createElement("div", {
      className: "ga-att__head"
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-card__sub"
    }, Ico.clip, " Allegati della qualit\xE0 ", attQualita.length ? `(${attQualita.length})` : ""), puo && /*#__PURE__*/React.createElement("span", {
      className: "ga-hint"
    }, uploadingAttachments ? "Caricamento…" : /*#__PURE__*/React.createElement(React.Fragment, null, "Trascina qui o ", /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "ga-link",
      onClick: () => fileInputQRef.current && fileInputQRef.current.click()
    }, "sfoglia")))), attQualita.length === 0 ? /*#__PURE__*/React.createElement("div", {
      className: "ga-hint"
    }, "Nessun allegato della qualit\xE0.") : renderAttGrid(attQualita)), (sn.richieste_info || []).length > 0 && /*#__PURE__*/React.createElement("div", {
      className: "ga-richieste"
    }, /*#__PURE__*/React.createElement("div", {
      className: "ga-richieste__t"
    }, "Informazioni chieste"), sn.richieste_info.map(r => /*#__PURE__*/React.createElement("div", {
      key: r.id,
      className: "ga-richiesta"
    }, /*#__PURE__*/React.createElement("div", {
      className: "ga-hint"
    }, r.il, " \xB7 a ", (r.destinatari || []).map(x => x === "cc" ? "capocommessa" : "controllore").join(" e "), r.aperta ? " · in attesa" : ""), /*#__PURE__*/React.createElement("div", {
      className: "ga-richiesta__msg"
    }, r.messaggio), !r.aperta && /*#__PURE__*/React.createElement("div", {
      className: "ga-richiesta__risp"
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-hint"
    }, r.risposta_da, " \xB7 ", r.risposta_il), /*#__PURE__*/React.createElement("div", null, r.risposta))))), puo && /*#__PURE__*/React.createElement(React.Fragment, null, chiudeQ && /*#__PURE__*/React.createElement("div", {
      className: "ga-note ga-note--ok"
    }, "Al salvataggio l'anomalia si chiude."), /*#__PURE__*/React.createElement("div", {
      className: "ga-qualita__acts"
    }, /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "ga-btn ga-btn--ghost-dark",
      disabled: qBusy,
      onClick: () => setInfoModal({
        cc: true,
        controllore: false,
        messaggio: "",
        busy: false,
        err: ""
      })
    }, "Richiedi info aggiuntive\u2026"), /*#__PURE__*/React.createElement("span", {
      className: "ga-qualita__spacer"
    }), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "ga-btn ga-btn--outline",
      disabled: qBusy,
      onClick: () => salvaQualita(false)
    }, qBusy ? "Salvataggio…" : "Salva"), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "ga-btn ga-btn--accent",
      disabled: qBusy,
      onClick: () => salvaQualita(true)
    }, "Chiudi l'anomalia")))));
  })(), sn.local_id && /*#__PURE__*/React.createElement(EsitiAnomalia, {
    localId: sn.local_id,
    avanzamento: sn.avanzamento,
    chiusa: Boolean(sn.chiudere),
    segnalare: Boolean(sn.segnalare),
    versione: versioneEsiti,
    sezChiusa: sezChiusa("esiti"),
    onToggleSez: () => toggleSez("esiti"),
    flash: flash,
    onInfo: setEsitiInfo,
    onSaved: ({
      chiusa
    }) => {
      if (chiusa) {
        setAnomalie(prev => prev.map(a => a.item_id === sn.item_id ? {
          ...a,
          chiudere: true,
          can_riaprire: true
        } : a));
        loadOrdini();
      }
      loadAttachments(sn.local_id);
    }
  }), op.id && op.id !== "—" && /*#__PURE__*/React.createElement(TimelineOp, {
    opId: op.id,
    opItemId: op.item_id
  })), canEditSelected && /*#__PURE__*/React.createElement("div", {
    className: "ga-det__foot"
  }, /*#__PURE__*/React.createElement("span", {
    className: `ga-det__state${dirty ? " is-dirty" : ""}`
  }, dirty ? "● Modifiche non salvate" : "Nessuna modifica"), dirty && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--ghost-dark",
    onClick: annullaModifiche,
    disabled: saving
  }, "Annulla"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--outline",
    onClick: () => handleSave(),
    disabled: saving,
    title: "Ctrl+S"
  }, saving ? "Salvataggio…" : "Salva"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--accent",
    onClick: salvaEProssima,
    disabled: saving
  }, "Salva e prossima ", Ico.next))))), azAnom && sn.local_id && /*#__PURE__*/React.createElement("div", {
    className: "ga-modal",
    role: "dialog",
    "aria-modal": "true",
    "aria-labelledby": "ga-az-t"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__box"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__title",
    id: "ga-az-t"
  }, azAnom.tipo === "elimina" ? `Eliminare l'anomalia #${sn.local_id}?` : `✂ Taglia l'anomalia #${sn.local_id}`), /*#__PURE__*/React.createElement("div", {
    className: "ga-hint ga-az__ctx"
  }, "S/N ", sn.sn || "—", " \xB7 ", sn.testo || sn.desc || "(nessuna descrizione)"), azAnom.tipo === "elimina" ? /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--warn"
  }, "Sparisce dall'OP con i suoi dati; gli allegati restano recuperabili dall'amministratore. Non si pu\xF2 annullare.") : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("label", {
    className: "ga-field"
  }, /*#__PURE__*/React.createElement("span", null, "OP di destinazione"), /*#__PURE__*/React.createElement("input", {
    className: "ga-input",
    list: "ga-taglia-op",
    value: azAnom.op,
    disabled: azAnom.busy,
    onChange: e => setAzAnom({
      ...azAnom,
      op: e.target.value,
      err: ""
    })
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "ga-taglia-op"
  }, ordini.slice(0, 500).map(o => /*#__PURE__*/React.createElement("option", {
    key: opKey(o),
    value: o.id
  })))), /*#__PURE__*/React.createElement("label", {
    className: "ga-field"
  }, /*#__PURE__*/React.createElement("span", null, "S/N di destinazione"), /*#__PURE__*/React.createElement("input", {
    className: "ga-input",
    list: "ga-taglia-sn",
    value: azAnom.sn,
    disabled: azAnom.busy,
    autoFocus: true,
    placeholder: "Es. LCN00012 o LCN00012-LCN00015",
    onChange: e => setAzAnom({
      ...azAnom,
      sn: e.target.value,
      err: ""
    }),
    onKeyDown: e => {
      if (e.key === "Enter") {
        e.preventDefault();
        confermaAzione();
      }
    }
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "ga-taglia-sn"
  }, (azAnom.seriali || []).slice(0, 500).map(s => /*#__PURE__*/React.createElement("option", {
    key: s,
    value: s
  })))), /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, String(azAnom.op || "").trim().toLowerCase() === String(op.id || "").toLowerCase() ? "Stesso OP: cambia solo il S/N (nel controllo va nel blocco che ha già quel S/N)." : "Altro OP: passa alla NC di quell'OP e il suo capocommessa la trova nel riepilogo delle modifiche.")), azAnom.err && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--warn"
  }, azAnom.err), /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__acts"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--ghost-dark",
    disabled: azAnom.busy,
    onClick: () => setAzAnom(null)
  }, "Annulla"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: `ga-btn ${azAnom.tipo === "elimina" ? "ga-btn--danger" : "ga-btn--accent"}`,
    disabled: azAnom.busy,
    onClick: confermaAzione
  }, azAnom.busy ? "Attendere…" : azAnom.tipo === "elimina" ? "Elimina" : "Sposta qui")))), infoModal && /*#__PURE__*/React.createElement("div", {
    className: "ga-modal",
    role: "dialog",
    "aria-modal": "true",
    "aria-labelledby": "ga-info-t"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__box"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__title",
    id: "ga-info-t"
  }, "Richiedi info aggiuntive \xB7 #", sn.local_id), /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, "Arriva una notifica e una mail con il link per rispondere; finch\xE9 non rispondono l'anomalia \xE8 in carico a loro (\xAB", AVANZAMENTO_CHIARIMENTI, "\xBB)."), /*#__PURE__*/React.createElement("div", {
    className: "ga-flags"
  }, /*#__PURE__*/React.createElement(FlagToggle, {
    label: "Capocommessa",
    checked: infoModal.cc,
    onChange: () => setInfoModal({
      ...infoModal,
      cc: !infoModal.cc
    })
  }), /*#__PURE__*/React.createElement(FlagToggle, {
    label: "Controllore",
    checked: infoModal.controllore,
    onChange: () => setInfoModal({
      ...infoModal,
      controllore: !infoModal.controllore
    })
  })), /*#__PURE__*/React.createElement("textarea", {
    className: "ga-input",
    rows: 4,
    autoFocus: true,
    value: infoModal.messaggio,
    placeholder: "Cosa ti serve sapere?",
    onChange: e => setInfoModal({
      ...infoModal,
      messaggio: e.target.value
    })
  }), infoModal.err && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--warn"
  }, infoModal.err), /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__acts"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--ghost-dark",
    disabled: infoModal.busy,
    onClick: () => setInfoModal(null)
  }, "Annulla"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--accent",
    disabled: infoModal.busy,
    onClick: inviaRichiestaInfo
  }, infoModal.busy ? "Invio…" : "Invia richiesta")))), modOp && /*#__PURE__*/React.createElement("div", {
    className: "ga-modal",
    role: "dialog",
    "aria-modal": "true",
    "aria-labelledby": "ga-modop-t"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__box"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__title",
    id: "ga-modop-t"
  }, "Modifica OP ", modOp.titolo), !modOp.dati ? /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, modOp.busy ? "Caricamento…" : "") : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "ga-modop__grid"
  }, /*#__PURE__*/React.createElement("label", {
    className: "ga-field"
  }, /*#__PURE__*/React.createElement("span", null, "P/N *"), /*#__PURE__*/React.createElement("input", {
    className: "ga-input",
    value: modOp.dati.pn,
    disabled: modOp.busy,
    autoFocus: true,
    onChange: e => campoModOp("pn", e.target.value)
  })), /*#__PURE__*/React.createElement("label", {
    className: "ga-field"
  }, /*#__PURE__*/React.createElement("span", null, "Fase"), /*#__PURE__*/React.createElement("input", {
    className: "ga-input",
    value: modOp.dati.fase,
    disabled: modOp.busy,
    onChange: e => campoModOp("fase", e.target.value)
  })), /*#__PURE__*/React.createElement("label", {
    className: "ga-field"
  }, /*#__PURE__*/React.createElement("span", null, "Capocommessa *"), /*#__PURE__*/React.createElement("input", {
    className: "ga-input",
    list: "ga-modop-capi",
    value: modOp.dati.capocommessa,
    disabled: modOp.busy,
    onChange: e => campoModOp("capocommessa", e.target.value)
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "ga-modop-capi"
  }, (Array.isArray(CONFIG_LISTS.capi_commessa) ? CONFIG_LISTS.capi_commessa : []).map(n => /*#__PURE__*/React.createElement("option", {
    key: n,
    value: n
  })))), /*#__PURE__*/React.createElement("label", {
    className: "ga-field"
  }, /*#__PURE__*/React.createElement("span", null, "CAR *"), /*#__PURE__*/React.createElement("input", {
    className: "ga-input",
    list: "ga-modop-car",
    value: modOp.dati.car,
    disabled: modOp.busy,
    onChange: e => campoModOp("car", e.target.value)
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "ga-modop-car"
  }, (Array.isArray(CONFIG_LISTS.capi_reparto) ? CONFIG_LISTS.capi_reparto : []).map(n => /*#__PURE__*/React.createElement("option", {
    key: n,
    value: n
  }))))), /*#__PURE__*/React.createElement("label", {
    className: "ga-field"
  }, /*#__PURE__*/React.createElement("span", null, "Note"), /*#__PURE__*/React.createElement("input", {
    className: "ga-input",
    value: modOp.dati.note,
    maxLength: 180,
    disabled: modOp.busy,
    onChange: e => campoModOp("note", e.target.value)
  })), modOp.dati.benestare_modificabile && /*#__PURE__*/React.createElement("label", {
    className: "ga-modop__check"
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: !!modOp.dati.benestare,
    disabled: modOp.busy,
    onChange: e => campoModOp("benestare", e.target.checked)
  }), "Collaudo di benestare"), /*#__PURE__*/React.createElement("label", {
    className: "ga-field"
  }, /*#__PURE__*/React.createElement("span", null, "Motivo della modifica *"), /*#__PURE__*/React.createElement("textarea", {
    className: "ga-input",
    rows: 2,
    value: modOp.motivo,
    maxLength: 500,
    disabled: modOp.busy,
    placeholder: "Es. P/N scritto male in apertura",
    onChange: e => setModOp({
      ...modOp,
      motivo: e.target.value,
      err: ""
    })
  })), /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, "Il numero dell'OP non si cambia: per un OP sbagliato usa \xABTaglia\xBB. La modifica resta nella cronologia dell'OP.")), modOp.err && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--warn"
  }, modOp.err), /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__acts"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--ghost-dark",
    disabled: modOp.busy && !!modOp.dati,
    onClick: () => setModOp(null)
  }, "Annulla"), modOp.dati && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--accent",
    disabled: modOp.busy || !modOpCambiato,
    onClick: salvaModificaOp
  }, modOp.busy ? "Salvataggio…" : "Salva modifica")))), riepilogo && /*#__PURE__*/React.createElement("div", {
    className: "ga-modal",
    role: "dialog",
    "aria-modal": "true",
    "aria-labelledby": "ga-riep-t"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__box ga-modal__box--wide"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__title",
    id: "ga-riep-t"
  }, "Applica la decisione a ", bersagli.length + 1, " anomalie"), /*#__PURE__*/React.createElement("div", {
    className: "ga-riep__dec"
  }, /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, "Avanzamento"), " ", avanzamento), aprireRdc && /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, "RDC"), " ", rdcNum || "da aprire"), segnalare && /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, "Segnalata al cliente")), terzista && /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, "Segnalata al terzista")), segnalaCar && carScelti.length > 0 && /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, "Segnalata al CAR"), " ", carScelti.join(", ")), note.trim() && /*#__PURE__*/React.createElement("span", {
    className: "ga-riep__nota"
  }, /*#__PURE__*/React.createElement("b", null, "Note"), " ", note.trim())), /*#__PURE__*/React.createElement("div", {
    className: "ga-riep__list"
  }, gruppiPerSn([sn, ...bersagli]).map(g => /*#__PURE__*/React.createElement("div", {
    key: g.chiave,
    className: "ga-riep__grp"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-apply__grp-t"
  }, "S/N ", g.titolo), g.righe.map(x => {
    const chiude = x.item_id === sn.item_id ? chiudereAuto : chiudeBersaglio(x);
    return /*#__PURE__*/React.createElement("div", {
      key: x.item_id,
      className: "ga-riep__row"
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-apply__txt"
    }, "#", x.local_id, " ", x.testo || x.desc || "—", x.item_id === sn.item_id ? " (questa)" : ""), /*#__PURE__*/React.createElement("span", {
      className: "ga-riep__stato"
    }, x.avanzamento || "In attesa", " \u2192 ", avanzamento), chiude ? /*#__PURE__*/React.createElement("span", {
      className: "ga-pill ga-pill--chiuso"
    }, "Si chiude") : chiudereAuto && x.serve_azione ? /*#__PURE__*/React.createElement("span", {
      className: "ga-pill ga-pill--attesa",
      title: "Prima decisione \xABAzione di recupero\xBB: serve l'azione effettuata"
    }, "Resta aperta") : null);
  })))), chiudereAuto && bersagli.some(x => x.serve_azione) && !aprireRdc && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--warn"
  }, "Le anomalie in \xABAzione di recupero\xBB ricevono la decisione ma restano aperte finch\xE9 non si registra l'azione effettuata."), /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__acts"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--ghost-dark",
    onClick: () => setRiepilogo(null)
  }, "Annulla"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--accent",
    disabled: saving,
    onClick: async () => {
      const prossima = riepilogo.prossima ? trovaProssima(bersagli.map(x => x.item_id)) : null;
      const vaiAvanti = riepilogo.prossima;
      setRiepilogo(null);
      if ((await handleSave(true)) && vaiAvanti) vaiAllaProssima(prossima);
    }
  }, "Conferma e salva ", bersagli.length + 1, " anomalie")))), pendingNav && /*#__PURE__*/React.createElement("div", {
    className: "ga-modal",
    role: "dialog",
    "aria-modal": "true"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__box"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__title"
  }, "Modifiche non salvate"), /*#__PURE__*/React.createElement("p", null, "Hai cambiato la decisione sull'anomalia #", sn.local_id, " senza salvarla."), /*#__PURE__*/React.createElement("div", {
    className: "ga-modal__acts"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--ghost-dark",
    onClick: () => setPendingNav(null)
  }, "Resta qui"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--outline",
    onClick: () => {
      const nav = pendingNav;
      setPendingNav(null);
      annullaModifiche();
      nav();
    }
  }, "Scarta"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--accent",
    onClick: async () => {
      const nav = pendingNav;
      setPendingNav(null);
      if (await handleSave()) nav();
    }
  }, "Salva e continua")))), lightbox && lightboxIdx >= 0 && /*#__PURE__*/React.createElement("div", {
    className: "ga-lightbox",
    onClick: () => setLightbox(null)
  }, /*#__PURE__*/React.createElement("img", {
    src: getAttachmentUrl(lightbox),
    alt: immagini[lightboxIdx].name,
    onClick: e => e.stopPropagation()
  }), /*#__PURE__*/React.createElement("div", {
    className: "ga-lightbox__bar",
    onClick: e => e.stopPropagation()
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    disabled: lightboxIdx <= 0,
    onClick: () => setLightbox(immagini[lightboxIdx - 1].file_id)
  }, Ico.prev), /*#__PURE__*/React.createElement("span", null, immagini[lightboxIdx].name, " \xB7 ", lightboxIdx + 1, "/", immagini.length), /*#__PURE__*/React.createElement("button", {
    type: "button",
    disabled: lightboxIdx >= immagini.length - 1,
    onClick: () => setLightbox(immagini[lightboxIdx + 1].file_id)
  }, Ico.next), /*#__PURE__*/React.createElement("a", {
    href: getAttachmentUrl(lightbox, true)
  }, "Scarica"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => setLightbox(null)
  }, "Chiudi"))), saveMsg && /*#__PURE__*/React.createElement("div", {
    className: `ga-toast${saveMsg.ok ? "" : " is-err"}`
  }, saveMsg.text), isMobile && /*#__PURE__*/React.createElement("nav", {
    className: "ga-tabs"
  }, [["ordini", "Ordini", Ico.list], ["serie", "Anomalie", Ico.rows], ["dettaglio", "Dettaglio", Ico.edit]].map(([id, label, icon]) => /*#__PURE__*/React.createElement("button", {
    key: id,
    type: "button",
    className: mobilePanel === id ? "is-on" : "",
    onClick: () => setMobilePanel(id)
  }, icon, label, id === "serie" && nDaDecidere > 0 ? /*#__PURE__*/React.createElement("span", {
    className: "ga-tabs__n"
  }, nDaDecidere) : null))));
}
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      error: null
    };
  }
  static getDerivedStateFromError(e) {
    return {
      error: e
    };
  }
  componentDidCatch(e, info) {
    console.error("React render error:", e, info);
  }
  render() {
    if (this.state.error) {
      return React.createElement("div", {
        style: {
          color: "red",
          padding: 24,
          fontFamily: "monospace",
          whiteSpace: "pre-wrap"
        }
      }, "ERRORE RENDERING: " + this.state.error.message);
    }
    return this.props.children;
  }
}
console.log("Babel script eseguito OK");
const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(React.createElement(ErrorBoundary, null, React.createElement(GestioneAnomalie, null)));
