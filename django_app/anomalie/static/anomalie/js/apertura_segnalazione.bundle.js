function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* eslint-disable */
/* SORGENTE del bundle UI «Controllo anomalie» (apertura_segnalazione).
   Estratto dallo <script type="text/babel"> inline (prima Babel nel browser a ogni apertura)
   e transpilato offline (solo JSX) con tools/build_anomalie_ui.ps1 in
   anomalie/static/anomalie/js/apertura_segnalazione.bundle.js. Modificare QUI, poi ricompilare. */
const {
  useState,
  useEffect,
  useRef
} = React;
// Codice dell'anomalia («AN-00123»), stesso di mail e link (anomalie/codice.py).
const codiceAnomalia = id => {
  const n = parseInt(String(id || "").split(":").pop(), 10);
  return n > 0 ? `AN-${String(n).padStart(5, "0")}` : "";
};
const API = window._AP_API || {
  db_ordini: '/api/anomalie/db/ordini',
  db_ordini_crea: '/api/anomalie/db/ordini/crea',
  salva: '/api/anomalie/salva',
  notifica_op: '/api/anomalie/notifica-op',
  seriali_op: '/api/anomalie/seriali-op',
  allegati_upload: '/api/anomalie/allegati/upload',
  copilota: '/api/anomalie/copilota',
  controlli: '/api/anomalie/controlli',
  controllo_apri: '/api/anomalie/controlli/apri',
  controlli_sospesi: '/api/anomalie/controlli/sospesi',
  controllo_prendi: '/api/anomalie/controlli/0/prendi',
  controllo_dettaglio: '/api/anomalie/controlli/0',
  controllo_impostazioni: '/api/anomalie/controlli/0/impostazioni',
  controllo_blocco: '/api/anomalie/controlli/0/blocco',
  controllo_termina: '/api/anomalie/controlli/0/termina',
  controllo_cambia_op: '/api/anomalie/controlli/0/cambia-op',
  controllo_bozza: '/api/anomalie/controlli/0/bozza',
  controllo_destinatari: '/api/anomalie/controlli/destinatari',
  controllo_persone: '/api/anomalie/controlli/persone',
  clona: '/api/anomalie/clona',
  allegati_copia: '/api/anomalie/allegati/copia',
  report_cmm: '/api/anomalie/report-cmm/leggi',
  elimina: '/api/anomalie/elimina',
  sposta: '/api/anomalie/sposta'
};

/* Clonazione da Gestione anomalie: ?clona_da=<OP>&anomalie=<id,id,…> */
const CLONA_PARAMS = (() => {
  const q = new URLSearchParams(window.location.search);
  const da = (q.get('clona_da') || '').trim();
  const ids = (q.get('anomalie') || '').split(',').map(x => x.trim()).filter(x => /^\d+$/.test(x));
  return da && ids.length ? {
    da,
    ids
  } : null;
})();
const contaClona = c => c ? c.blocchi.reduce((n, b) => n + b.anomalie.length, 0) : 0;
const cfgLists = window._AP_CONFIG_LISTS || {};
const CFG_CAPI_REPARTO = Array.isArray(cfgLists.capi_reparto) ? cfgLists.capi_reparto : [];
const CFG_CAPI_COMMESSA = Array.isArray(cfgLists.capi_commessa) ? cfgLists.capi_commessa : [];
const CFG_CAUSALI_DOC = Array.isArray(cfgLists.causali_doc) && cfgLists.causali_doc.length ? cfgLists.causali_doc : ['OP', 'OG'];
const CFG_STATI_SUPERFICIE = Array.isArray(cfgLists.stati_superficie) && cfgLists.stati_superficie.length ? cfgLists.stati_superficie : ['Finito macchinato', 'Con sovrametallo', 'Finito trattato'];

/* ── CSRF ── */
const getCsrf = () => (document.cookie.split(';').find(c => c.trim().startsWith('csrftoken=')) || '').split('=')[1] || '';
const parseJsonSafe = async (resp, fallback = null) => {
  try {
    return await resp.json();
  } catch (_) {
    return fallback;
  }
};
const parseJsonStrict = async (resp, context) => {
  const ct = String(resp.headers.get('content-type') || '').toLowerCase();
  if (!ct.includes('application/json')) {
    const txt = await resp.text();
    if (/<!doctype html/i.test(txt || '')) {
      throw new Error(`${context}: risposta HTML (login/sessione/404)`);
    }
    throw new Error(`${context}: risposta non JSON (HTTP ${resp.status})`);
  }
  try {
    return await resp.json();
  } catch (_) {
    throw new Error(`${context}: JSON non valido`);
  }
};
const formatBytes = value => {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let idx = 0;
  let n = bytes;
  while (n >= 1024 && idx < units.length - 1) {
    n /= 1024;
    idx += 1;
  }
  return `${n.toFixed(n >= 10 || idx === 0 ? 0 : 1)} ${units[idx]}`;
};
const ALLEGATI_ALLOWED_EXT = new Set(['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.xlsm', '.csv']);
const ALLEGATI_MAX_MB = window._AP_UPLOAD_MAX_MB || 100;
const ALLEGATI_MAX_SIZE = ALLEGATI_MAX_MB * 1024 * 1024;

/* ── Step 1: Selezione OP ── */
const makeNewOpDraft = () => ({
  causale_doc: CFG_CAUSALI_DOC[0] || 'OP',
  anno: String(new Date().getFullYear()),
  numero: '',
  fase: '',
  pn: '',
  capocommessa: '',
  car: '',
  collaudo_benestare: false,
  note: ''
});

/* Bozza del nuovo OP dai dati dell'OP clonato: resta da scrivere il numero. */
const newOpDaClona = c => {
  const base = makeNewOpDraft();
  if (!c) return base;
  const parti = String(c.op.id || '').split('/');
  return {
    ...base,
    causale_doc: parti.length === 3 && parti[0] ? parti[0] : base.causale_doc,
    pn: c.op.pn || '',
    capocommessa: c.op.capo || '',
    car: c.op.car || '',
    collaudo_benestare: String(c.op.stato || '').toLowerCase().includes('benestare')
  };
};
const ClonaBanner = ({
  clona,
  children
}) => /*#__PURE__*/React.createElement("div", {
  className: "clona-banner"
}, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Copia da ", clona.op.id), clona.op.pn ? ` · P/N ${clona.op.pn}` : '', ": ", contaClona(clona), " anomali", contaClona(clona) === 1 ? 'a' : 'e', " in ", clona.blocchi.length, " blocch", clona.blocchi.length === 1 ? 'o' : 'i', "."), children && /*#__PURE__*/React.createElement("div", {
  className: "field-hint"
}, children));
const Step1SelectOP = ({
  onSelect,
  clona
}) => {
  const [ordini, setOrdini] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(!!clona);
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState('');
  const [newOp, setNewOp] = useState(() => newOpDaClona(clona));
  const loadOrdini = () => {
    setLoading(true);
    setErr('');
    fetch(API.db_ordini, {
      credentials: 'same-origin'
    }).then(async r => {
      const data = await parseJsonSafe(r, []);
      if (!r.ok) throw new Error(data && data.error || 'HTTP ' + r.status);
      return data;
    }).then(data => {
      setOrdini(Array.isArray(data) ? data : []);
      setLoading(false);
    }).catch(e => {
      setErr(e.message || 'Errore caricamento ordini');
      setLoading(false);
    });
  };
  useEffect(() => {
    loadOrdini();
  }, []);
  const filtered = ordini.filter(op => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (op.id || '').toLowerCase().includes(q) || (op.pn || '').toLowerCase().includes(q) || (op.capo || '').toLowerCase().includes(q) || (op.car || '').toLowerCase().includes(q);
  });
  const capocommessaOptions = Array.from(new Set([...CFG_CAPI_COMMESSA, ...ordini.map(op => String(op.capo || '').trim()).filter(v => v && v !== '—')]));
  const carOptions = Array.from(new Set([...CFG_CAPI_REPARTO, ...ordini.map(op => String(op.car || '').trim()).filter(v => v && v !== '—')]));
  const updateNewOp = (field, value) => {
    setNewOp(prev => ({
      ...prev,
      [field]: value
    }));
  };

  // Sblocco progressivo: P/N -> dati OP (anno/numero/fase) -> Capocommessa/CAR.
  const opUnlocked = !!newOp.pn.trim();
  const ccCarUnlocked = opUnlocked && !!newOp.anno.trim() && !!newOp.numero.trim();
  const newOpValid = ccCarUnlocked && !!newOp.capocommessa.trim() && !!newOp.car.trim();
  const validateNewOp = () => {
    if (!newOp.pn.trim()) return 'P/N obbligatorio.';
    if (!newOp.anno.trim()) return 'Anno obbligatorio.';
    if (!newOp.numero.trim()) return 'Numero obbligatorio.';
    if (!newOp.capocommessa.trim()) return 'Capocommessa obbligatorio.';
    if (!newOp.car.trim()) return 'CAR obbligatorio.';
    return '';
  };
  const handleCreateOp = async () => {
    const vErr = validateNewOp();
    if (vErr) {
      setCreateErr(vErr);
      return;
    }
    setCreateErr('');
    setCreating(true);
    try {
      const csrf = getCsrf();
      // Solo verifica: l'OP si crea davvero al primo «Salva blocco» (Step 2).
      const r = await fetch(API.db_ordini_crea, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrf
        },
        body: JSON.stringify({
          ...newOp,
          verifica: true
        }),
        credentials: 'same-origin'
      });
      const j = await parseJsonSafe(r, {});
      if (!r.ok || !j.success) {
        throw new Error(j.error || 'Errore verifica OP (HTTP ' + r.status + ')');
      }
      if (!j.op || !j.op.id) throw new Error('Risposta verifica OP non valida.');
      setShowCreate(false);
      setNewOp(newOpDaClona(clona));
      onSelect({
        ...j.op,
        item_id: null,
        daCreare: {
          ...newOp
        }
      });
    } catch (e) {
      setCreateErr(e.message || 'Errore creazione OP');
    } finally {
      setCreating(false);
    }
  };
  const handleCancelCreate = () => {
    if (creating) return;
    setShowCreate(false);
    setCreateErr('');
    setNewOp(newOpDaClona(clona));
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "step-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "step-header"
  }, /*#__PURE__*/React.createElement("div", {
    className: "step-num"
  }, "1"), /*#__PURE__*/React.createElement("h2", null, "Seleziona Ordine di Produzione")), !window._AP_HAS_ORDINI && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '24px 28px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "error-msg"
  }, "Tabella ", /*#__PURE__*/React.createElement("code", null, "ordini_produzione"), " non disponibile nel database.")), clona && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '16px 28px 0'
    }
  }, /*#__PURE__*/React.createElement(ClonaBanner, {
    clona: clona
  }, "P/N, capocommessa e CAR sono gi\xE0 copiati: scrivi il ", /*#__PURE__*/React.createElement("strong", null, "numero"), " del nuovo OP e premi \xABContinua\xBB (l\u2019OP si crea solo quando salvi il primo blocco). Se il nuovo OP esiste gi\xE0, sceglilo dall\u2019elenco sotto. Le anomalie arriveranno gi\xE0 divise in blocchi, da controllare prima di salvarle.")), window._AP_HAS_ORDINI && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "create-op-wrap"
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn-primary create-op-btn",
    onClick: () => {
      setShowCreate(v => !v);
      setCreateErr('');
    },
    disabled: creating
  }, showCreate ? 'Chiudi inserimento nuovo OP' : '+ Nuovo OP'), /*#__PURE__*/React.createElement("div", {
    className: "create-op-hint"
  }, "Prima scelta: puoi inserire un nuovo OP e passare direttamente alla segnalazione; l\u2019OP si crea solo quando salvi il primo blocco di anomalie. Compila prima il ", /*#__PURE__*/React.createElement("strong", null, "P/N"), ", poi i dati dell'OP (anno e numero), infine Capocommessa e CAR: i campi si sbloccano in ordine."), showCreate && /*#__PURE__*/React.createElement("div", {
    className: "create-op-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "create-grid"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "P/N ", /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    placeholder: "Part number",
    value: newOp.pn,
    onChange: e => updateNewOp('pn', e.target.value),
    autoFocus: !clona
  })), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "Causale doc."), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    value: newOp.causale_doc,
    onChange: e => updateNewOp('causale_doc', e.target.value),
    list: "causale-doc-options",
    disabled: !opUnlocked
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "causale-doc-options"
  }, CFG_CAUSALI_DOC.map(v => /*#__PURE__*/React.createElement("option", {
    key: v,
    value: v
  })))), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "Anno ", /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    inputMode: "numeric",
    placeholder: "2026",
    value: newOp.anno,
    onChange: e => updateNewOp('anno', e.target.value),
    disabled: !opUnlocked
  })), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "Numero ", /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    placeholder: "123",
    value: newOp.numero,
    onChange: e => updateNewOp('numero', e.target.value),
    disabled: !opUnlocked
  })), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "Fase"), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    placeholder: "Opzionale",
    value: newOp.fase,
    onChange: e => updateNewOp('fase', e.target.value),
    disabled: !opUnlocked
  })), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "Capocommessa ", /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    value: newOp.capocommessa,
    onChange: e => updateNewOp('capocommessa', e.target.value),
    list: "capocommessa-options",
    disabled: !ccCarUnlocked
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "capocommessa-options"
  }, capocommessaOptions.map(v => /*#__PURE__*/React.createElement("option", {
    key: v,
    value: v
  })))), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "CAR ", /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    value: newOp.car,
    onChange: e => updateNewOp('car', e.target.value),
    list: "car-options",
    disabled: !ccCarUnlocked
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "car-options"
  }, carOptions.map(v => /*#__PURE__*/React.createElement("option", {
    key: v,
    value: v
  })))), /*#__PURE__*/React.createElement("div", {
    className: "field-group full"
  }, /*#__PURE__*/React.createElement("label", {
    className: "create-op-checkbox"
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: newOp.collaudo_benestare,
    onChange: e => updateNewOp('collaudo_benestare', e.target.checked),
    disabled: !ccCarUnlocked
  }), /*#__PURE__*/React.createElement("span", null, "Collaudo di benestare"))), /*#__PURE__*/React.createElement("div", {
    className: "field-group full"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "Note"), /*#__PURE__*/React.createElement("textarea", {
    className: "textarea-input",
    rows: 2,
    placeholder: "Note opzionali OP",
    value: newOp.note,
    onChange: e => updateNewOp('note', e.target.value),
    disabled: !ccCarUnlocked
  }))), createErr && /*#__PURE__*/React.createElement("div", {
    className: "error-msg"
  }, createErr), /*#__PURE__*/React.createElement("div", {
    className: "create-actions"
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn-secondary",
    onClick: handleCancelCreate,
    disabled: creating
  }, "Annulla"), /*#__PURE__*/React.createElement("button", {
    className: "btn-primary",
    onClick: handleCreateOp,
    disabled: creating || !newOpValid
  }, creating ? 'Verifica OP...' : 'Continua')))), /*#__PURE__*/React.createElement("div", {
    className: "search-wrap"
  }, /*#__PURE__*/React.createElement("input", {
    className: "search-input",
    type: "text",
    placeholder: "Cerca per titolo OP, P/N, capocommessa, CAR...",
    value: search,
    onChange: e => setSearch(e.target.value),
    autoFocus: true
  })), loading && /*#__PURE__*/React.createElement("div", {
    className: "loading-msg"
  }, "Caricamento ordini in corso..."), err && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '12px 28px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "error-msg"
  }, err)), !loading && !err && filtered.length === 0 && /*#__PURE__*/React.createElement("div", {
    className: "empty-msg"
  }, "Nessun ordine trovato."), !loading && !err && filtered.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "op-list"
  }, filtered.map((op, idx) => /*#__PURE__*/React.createElement("div", {
    key: op.item_id ?? idx,
    className: "op-row",
    onClick: () => onSelect(op)
  }, /*#__PURE__*/React.createElement("div", {
    className: "op-row-title"
  }, op.id || '—'), /*#__PURE__*/React.createElement("div", {
    className: "op-row-meta"
  }, op.pn && /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("span", {
    className: "meta-label"
  }, "P/N"), op.pn), op.capo && /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("span", {
    className: "meta-label"
  }, "Capo"), op.capo), op.car && /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("span", {
    className: "meta-label"
  }, "CAR"), op.car), op.anomalie_count > 0 && /*#__PURE__*/React.createElement("span", {
    className: "badge"
  }, op.anomalie_count, " anomali", op.anomalie_count === 1 ? 'a' : 'e')))))));
};

/* ── Step 2: controllo dell'OP a blocchi di seriali ──
   Un blocco = un gruppo di seriali (singoli, liste, range) con una o più anomalie.
   Ogni anomalia diventa una riga a sé: il capocommessa decide su ciascuna. */
const STATI_SUPERFICIE = CFG_STATI_SUPERFICIE;
const MSG_SUP = 'Indica lo stato superficie del blocco.';
const MSG_SN_ANOM = 'Scegli su quali seriali è presente l’anomalia';
const SN_PATTERN = /^[A-Za-z]{3}\d{5}$/;
const MAX_RANGE = 1000;
// La mail al capocommessa parte solo con «Termina controllo»; dopo 15 minuti dall'ultimo
// salvataggio senza invio arriva un promemoria al controllore, dopo 4 ore parte da sola.
// I due tempi si impostano in Configurazione → Notifiche.
const TEMPI = window._AP_TEMPI || {
  promemoria: 15,
  invio_auto: 60
};
const durata = min => {
  const h = Math.floor(min / 60),
    m = min % 60;
  const parti = [];
  if (h) parti.push(`${h} or${h === 1 ? 'a' : 'e'}`);
  if (m || !h) parti.push(`${m} minut${m === 1 ? 'o' : 'i'}`);
  return parti.join(' e ');
};
const MAIL_FINE_HINT = `La mail parte quando premi «Termina controllo». Se ${durata(TEMPI.promemoria)} dopo l’ultimo salvataggio non è ancora partita ricevi un promemoria per inviarla; dopo ${durata(TEMPI.invio_auto)} parte da sola.`;
const urlFor = (tpl, id) => String(tpl).replace('/controlli/0', `/controlli/${id}`);
const postJson = async (url, body, context) => {
  const r = await fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrf()
    },
    body: JSON.stringify(body || {})
  });
  const j = await parseJsonStrict(r, context);
  if (!r.ok && r.status !== 207) {
    const err = new Error(j.error || `${context}: HTTP ${r.status}`);
    err.data = j;
    throw err;
  }
  return j;
};
const getJson = async (url, context) => {
  const r = await fetch(url, {
    credentials: 'same-origin'
  });
  const j = await parseJsonStrict(r, context);
  if (!r.ok) throw new Error(j.error || `${context}: HTTP ${r.status}`);
  return j;
};

/* Seriali: stessa logica di anomalie/seriali.py */
const parseVoce = raw => {
  const voce = String(raw || '').trim().replace(/\s*-\s*/g, '-');
  if (!voce) return null;
  const m = voce.match(/^(.*?)(\d+)-(.*?)(\d+)$/);
  if (m && (!m[3] || m[3].toLowerCase() === m[1].toLowerCase())) {
    const a = parseInt(m[2], 10),
      b = parseInt(m[4], 10);
    if (a <= b && b - a <= MAX_RANGE) {
      const tokens = [];
      for (let i = a; i <= b; i += 1) tokens.push(`${m[1]}${String(i).padStart(m[2].length, '0')}`);
      return {
        voce,
        range: true,
        da: tokens[0],
        a: tokens[tokens.length - 1],
        tokens
      };
    }
  }
  return {
    voce,
    range: false,
    tokens: [voce]
  };
};
const splitSerialText = text => String(text || '').replace(/\s*-\s*/g, '-').split(/[\s,;]+/).map(v => v.trim()).filter(Boolean);
const tokensOf = voci => {
  const seen = new Set();
  const out = [];
  (voci || []).forEach(v => {
    const p = parseVoce(v);
    (p ? p.tokens : []).forEach(t => {
      const k = t.toLowerCase();
      if (!seen.has(k)) {
        seen.add(k);
        out.push(t);
      }
    });
  });
  return out;
};
const labelVoci = voci => {
  const n = tokensOf(voci).length;
  const txt = (voci || []).join(', ');
  return n > 1 ? `${txt} (${n} pezzi)` : txt;
};
const fileExt = name => {
  const dot = String(name || '').lastIndexOf('.');
  return dot >= 0 ? String(name).slice(dot).toLowerCase() : '';
};
const isImageFile = f => /^image\//.test(String(f.type || '')) || ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'].includes(fileExt(f.name));
const stamp = () => {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
};
/* Le immagini incollate dagli appunti arrivano come "image.png": nome leggibile e univoco. */
const nameClipboardFiles = files => files.map((f, i) => {
  const ext = fileExt(f.name) || (String(f.type || '').split('/')[1] ? `.${String(f.type).split('/')[1]}` : '.png');
  if (f.name && !/^image\.\w+$/i.test(f.name)) return f;
  try {
    return new File([f], `appunti-${stamp()}-${i + 1}${ext === '.jpeg' ? '.jpg' : ext}`, {
      type: f.type || 'image/png'
    });
  } catch (_) {
    return f;
  }
});
const validateFiles = files => {
  const ok = [];
  const errors = [];
  files.forEach(f => {
    if (!ALLEGATI_ALLOWED_EXT.has(fileExt(f.name))) errors.push(`${f.name || 'file'}: formato non supportato`);else if (Number(f.size || 0) <= 0) errors.push(`${f.name || 'file'}: file vuoto`);else if (Number(f.size || 0) > ALLEGATI_MAX_SIZE) errors.push(`${f.name || 'file'}: supera ${ALLEGATI_MAX_MB} MB`);else ok.push(f);
  });
  return {
    ok,
    errors
  };
};
let _uid = 0;
const uid = () => `n${Date.now()}_${_uid += 1}`;

/* Dati strutturati facoltativi dell'anomalia: stessa logica di anomalie/dettaglio_controllo.py. */
const DETT = window._AP_DETTAGLIO || {};
const CARATT = DETT.caratteristiche || [];
const CARATT_BY = Object.fromEntries(CARATT.map(c => [c.codice, c]));
const GENERI = DETT.generi || [];
const GENERI_BY = Object.fromEntries(GENERI.map(g => [g.codice, g]));
const DOC_LIST = DETT.documenti || [];
const TIPI_DIFETTO = DETT.tipi_difetto || [];
// Parti accese da Configurazione → «Campi del blocco del controllore» (di serie tutte).
// Regole «Visibile se» (Configurazione → «Campi del blocco del controllore»): persone e ruoli
// li valuta il server; fase del controllo e tipo di difetto dell'anomalia si valutano qui.
const CAMPI = window._AP_CAMPI || {};
const campoVisibile = (chiave, ctx = {}) => {
  const r = CAMPI[chiave];
  if (!r) return true;
  if (!r.visibile) return false;
  const fase = String(ctx.fase || '').toLowerCase();
  if ((r.fasi || []).length && !r.fasi.some(f => fase.includes(String(f).toLowerCase()))) return false;
  if ((r.tipi || []).length && !r.tipi.includes(ctx.tipo || '')) return false;
  return true;
};
const TUTTI_I_CASI = [['misura', 'Misura fuori tolleranza'], ['difetto', 'Difetto sul pezzo'], ['documenti', 'Marcatura / documenti']];
const casiVisibili = ctx => campoVisibile('caso', ctx) ? TUTTI_I_CASI.filter(([k]) => campoVisibile(`caso_${k}`, ctx)) : [];
// Tipo di difetto dell'anomalia per le regole: quello scelto, altrimenti quello proposto.
const codiceTipoAnomalia = (d, testo) => {
  const scelto = d && d.tipoDifettoId ? TIPI_DIFETTO.find(t => t.id === d.tipoDifettoId) : null;
  return scelto ? scelto.codice : codiceSuggerito(d, testo);
};
const SIMBOLI = ['Ø', '±', '°', '⊥', '∥', '◎', '⌖', '⌯', '⏥', '○', '⌒', '↗', '≤', '≥', 'µm', 'Ra'];
const emptyMisura = () => ({
  key: uid(),
  car: 'diametro',
  nome: '',
  modo: 'minmax',
  nom: '',
  a: '',
  b: '',
  ril: '',
  dove: ''
});
const emptyDett = () => ({
  tipo: '',
  misure: [],
  difetto: {},
  documenti: {
    docs: []
  },
  rif: {},
  rifAperto: false,
  tipoDifettoId: null
});
const dettDaServer = (d, tipoDifettoId) => {
  const x = d && typeof d === 'object' ? d : {};
  const rif = x.rif || {};
  return {
    tipo: x.tipo || '',
    misure: (x.misure || []).map(m => ({
      ...emptyMisura(),
      ...m,
      key: uid()
    })),
    difetto: x.difetto || {},
    documenti: {
      docs: [],
      ...(x.documenti || {})
    },
    rif,
    rifAperto: !!(rif.disegno || rif.sezione || rif.fase),
    tipoDifettoId: tipoDifettoId || null
  };
};
const dettPayload = d => {
  if (!d) return {};
  const out = {};
  if (d.tipo) out.tipo = d.tipo;
  if (d.tipo === 'misura') out.misure = (d.misure || []).map(({
    key,
    ...m
  }) => m);
  if (d.tipo === 'difetto') out.difetto = d.difetto || {};
  if (d.tipo === 'documenti') out.documenti = d.documenti || {};
  if (d.rif && (d.rif.disegno || d.rif.sezione || d.rif.fase)) out.rif = d.rif;
  return out;
};
const numero = v => {
  const t = String(v == null ? '' : v).trim().replace(',', '.').replace('−', '-').replace('±', '');
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
};
const fmtNum = v => {
  const t = (Math.round(v * 10000) / 10000).toString();
  return t === '-0' ? '0' : t;
};
const esitoMisura = m => {
  const ril = numero(m.ril),
    nom = numero(m.nom),
    a = numero(m.a),
    b = numero(m.b);
  let lo = null,
    hi = null;
  if (m.modo === 'minmax') {
    lo = a;
    hi = b;
    if (lo != null && hi != null && lo > hi) [lo, hi] = [hi, lo];
  } else if (m.modo === 'pm' && nom != null && a != null) {
    lo = nom - Math.abs(a);
    hi = nom + Math.abs(b != null ? b : a);
  } else if (m.modo === 'max') {
    hi = a;
  }
  if (ril == null || lo == null && hi == null) return {
    fuori: null,
    scarto: null
  };
  if (hi != null && ril > hi) return {
    fuori: true,
    scarto: Math.round((ril - hi) * 10000) / 10000
  };
  if (lo != null && ril < lo) return {
    fuori: true,
    scarto: Math.round((ril - lo) * 10000) / 10000
  };
  return {
    fuori: false,
    scarto: 0
  };
};
const fraseMisura = m => {
  const c = CARATT_BY[m.car] || {
    simbolo: '',
    nome: 'Misura'
  };
  const nome = m.nome || c.nome;
  const testa = (c.simbolo === 'Ø' || c.simbolo === 'R') && !m.nome ? c.simbolo : `${c.simbolo || ''} ${nome}`.trim();
  let tol;
  if (m.modo === 'minmax') tol = `${m.a || '?'}/${m.b || '?'}`;else if (m.modo === 'pm') tol = !m.b || m.b === m.a ? `${m.nom || '?'} ±${m.a || '?'}` : `${m.nom || '?'} −${m.a}/+${m.b}`;else tol = `max ${m.a || '?'}`;
  const parti = [`${testa} ${tol}`.trim()];
  if (m.ril) parti.push(`rilevato ${m.ril}`);
  const e = esitoMisura(m);
  if (e.fuori) parti.push(`(${e.scarto > 0 ? '+' : '−'}${fmtNum(Math.abs(e.scarto))})`);
  return parti.join(' ') + (m.dove ? ` · ${m.dove}` : '');
};
const misuraUtile = m => !!(m.nom || m.a || m.b || m.ril || m.dove || m.nome);
const frasiDett = d => {
  if (!d) return [];
  const out = [];
  if (d.tipo === 'misura') (d.misure || []).filter(misuraUtile).forEach(m => out.push(fraseMisura(m)));else if (d.tipo === 'difetto') {
    const x = d.difetto || {};
    if (x.genere || x.dove || x.lung || x.larg || x.prof || x.est) {
      const dim = [['lung', 'lunghezza'], ['larg', 'larghezza/altezza'], ['prof', 'profondità'], ['est', 'estensione']].filter(([k]) => x[k]).map(([k, l]) => `${l} ${x[k]}`);
      out.push(((GENERI_BY[x.genere] || {}).nome || 'Difetto') + (x.dove ? ` · ${x.dove}` : '') + (dim.length ? ` · ${dim.join(', ')}` : ''));
    }
  } else if (d.tipo === 'documenti') {
    const x = d.documenti || {};
    const parti = [];
    if (x.trovato) parti.push(`sul pezzo ${x.trovato}`);
    if (x.atteso) parti.push(`atteso ${x.atteso}`);
    if ((x.docs || []).length) parti.push(`documenti: ${x.docs.join(', ')}`);
    if (parti.length) out.push('Marcatura/documenti non coincidenti · ' + parti.join(' · '));
  }
  const r = d.rif || {};
  const pezzi = [r.disegno, r.sezione ? `sez. ${r.sezione}` : '', r.fase].filter(Boolean);
  if (pezzi.length) out.push('Rif.: ' + pezzi.join(' · '));
  return out;
};
const PAROLE = [[/\bbav[ae]\b|spigol/i, 'bave-spigoli'], [/marcat|ddt|cartellino/i, 'marcatura-documenti'], [/concentricit|simmetri|posizione|planarit|perpendicolar|parallelis|circolarit|oscillazion/i, 'geometria'], [/filett/i, 'filettatura'], [/rugosit|\bRa\b/i, 'rugosita'], [/testimone|porosit|fusione|graff|ammacc|impront/i, 'difetto-superficiale'], [/Ø|diametr|quota|lunghezz|smusso|\bOT\b|fuori toll|rilevat|risulta/i, 'fuori-tolleranza']];
const codiceSuggerito = (d, testo) => {
  if (d && d.tipo === 'misura') {
    const m = (d.misure || [])[0];
    return m ? (CARATT_BY[m.car] || {}).famiglia || 'fuori-tolleranza' : 'fuori-tolleranza';
  }
  if (d && d.tipo === 'difetto') return (GENERI_BY[(d.difetto || {}).genere] || {}).famiglia || 'difetto-superficiale';
  if (d && d.tipo === 'documenti') return 'marcatura-documenti';
  const hit = PAROLE.find(([re]) => re.test(testo || ''));
  return hit ? hit[1] : '';
};
/* Testo effettivo dell'anomalia: la descrizione o, se vuota, le frasi dei dati strutturati. */
const testoAnomalia = a => (a.testo || '').trim() || frasiDett(a.dett).join('\n');
/* Inserisce un simbolo nel campo di testo attivo (React: setter nativo + evento input). */
const inserisciNelCampo = (el, testo) => {
  if (!el || !('value' in el) || el.disabled || el.readOnly) return false;
  const start = el.selectionStart != null ? el.selectionStart : el.value.length;
  const end = el.selectionEnd != null ? el.selectionEnd : el.value.length;
  const nuovo = el.value.slice(0, start) + testo + el.value.slice(end);
  const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, nuovo);
  el.dispatchEvent(new Event('input', {
    bubbles: true
  }));
  const pos = start + testo.length;
  try {
    el.setSelectionRange(pos, pos);
  } catch (e) {/* input number */}
  return true;
};

/* Pulsanti dei simboli: scrivono nel campo dove si trova il cursore (di serie la descrizione). */
const BarraSimboli = ({
  disabled,
  fallbackRef
}) => /*#__PURE__*/React.createElement("div", {
  className: "sym-bar",
  role: "group",
  "aria-label": "Simboli"
}, /*#__PURE__*/React.createElement("span", {
  className: "sym-bar__lbl"
}, "Simboli:"), SIMBOLI.map(sym => /*#__PURE__*/React.createElement("button", {
  key: sym,
  type: "button",
  className: "sym-btn",
  disabled: disabled,
  title: `Inserisci ${sym}`,
  onMouseDown: e => e.preventDefault(),
  onClick: () => {
    const el = document.activeElement;
    const card = fallbackRef.current && fallbackRef.current.closest('.anom-card');
    const target = el && card && card.contains(el) && ['TEXTAREA', 'INPUT'].includes(el.tagName) && el.type !== 'checkbox' ? el : fallbackRef.current;
    if (target) {
      target.focus();
      inserisciNelCampo(target, sym);
    }
  }
}, sym)));

/* «Incolla dal report ZEISS»: screenshot di righe del protocollo -> misure proposte da confermare.
   L'immagine va solo alla lettura (OCR sul server) e non diventa un allegato. */
const LetturaReport = ({
  opId,
  disabled,
  onAggiungi
}) => {
  const [stato, setStato] = useState(''); // '' | 'lettura' | errore
  const [proposte, setProposte] = useState(null);
  const [testoLetto, setTestoLetto] = useState([]);
  const [scelte, setScelte] = useState({});
  const [over, setOver] = useState(false);
  const fileRef = useRef(null);
  const leggi = async file => {
    if (!file || disabled) return;
    if (!/^image\//.test(file.type || '')) {
      setStato('Serve un\'immagine: cattura le righe del report e incollale qui.');
      return;
    }
    setStato('lettura');
    setProposte(null);
    try {
      const form = new FormData();
      form.append('op_id', opId || '');
      form.append('immagine', file, file.name || 'report.png');
      const r = await fetch(API.report_cmm, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCsrf()
        },
        body: form,
        credentials: 'same-origin'
      });
      const j = await parseJsonStrict(r, 'Lettura del report');
      if (!r.ok || !j.success) throw new Error(j.error || `HTTP ${r.status}`);
      const righe = j.righe || [];
      setTestoLetto(j.testo || []);
      if (!righe.length) {
        setStato('Nessuna riga di misura riconosciuta: cattura le righe con valori (Actual, Nominal, tolleranze) e riprova, magari ingrandendo il PDF.');
        return;
      }
      setProposte(righe);
      setScelte(Object.fromEntries(righe.map((x, i) => [i, !!x.fuori])));
      setStato('');
    } catch (e) {
      setStato(e.message);
    }
  };
  const onPaste = e => {
    const items = Array.from(e.clipboardData && e.clipboardData.items || []);
    const file = items.filter(it => it.kind === 'file').map(it => it.getAsFile()).find(Boolean);
    if (!file) return;
    e.preventDefault();
    e.stopPropagation();
    leggi(file);
  };
  const nScelte = proposte ? proposte.filter((_, i) => scelte[i]).length : 0;
  return /*#__PURE__*/React.createElement("div", {
    className: "dett"
  }, /*#__PURE__*/React.createElement("div", {
    className: `cmm-box${over ? ' is-over' : ''}`,
    tabIndex: disabled ? -1 : 0,
    onPaste: onPaste,
    onDragOver: e => {
      e.preventDefault();
      setOver(true);
    },
    onDragLeave: () => setOver(false),
    onDrop: e => {
      e.preventDefault();
      e.stopPropagation();
      setOver(false);
      leggi((e.dataTransfer.files || [])[0]);
    },
    onClick: e => e.currentTarget.focus(),
    "aria-label": "Incolla qui lo screenshot del report ZEISS"
  }, /*#__PURE__*/React.createElement("input", {
    ref: fileRef,
    type: "file",
    accept: "image/*",
    hidden: true,
    onChange: e => {
      const f = (e.target.files || [])[0];
      e.target.value = '';
      leggi(f);
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "cmm-box__hint"
  }, "\uD83D\uDCCB ", /*#__PURE__*/React.createElement("strong", null, "Dal report ZEISS:"), " cattura le righe del protocollo (Win+Maiusc+S), clicca qui e premi ", /*#__PURE__*/React.createElement("kbd", null, "Ctrl"), "+", /*#__PURE__*/React.createElement("kbd", null, "V"), ' ', "oppure ", /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    disabled: disabled,
    onClick: e => {
      e.stopPropagation();
      fileRef.current && fileRef.current.click();
    }
  }, "scegli l\u2019immagine"), ".", /*#__PURE__*/React.createElement("span", null, "L\u2019immagine non viene allegata: serve solo a proporre le misure.")), stato === 'lettura' && /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, "Lettura del report in corso\u2026"), stato && stato !== 'lettura' && /*#__PURE__*/React.createElement("div", {
    className: "error-msg"
  }, stato)), proposte && /*#__PURE__*/React.createElement("div", {
    className: "dett-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dett-panel__head"
  }, "Righe lette dal report ", /*#__PURE__*/React.createElement("small", null, "\u2014 spunta quelle da aggiungere (gi\xE0 spuntate le fuori tolleranza)")), /*#__PURE__*/React.createElement("div", {
    className: "cmm-prop"
  }, proposte.map((p, i) => {
    const e = esitoMisura(p);
    return /*#__PURE__*/React.createElement("label", {
      key: i
    }, /*#__PURE__*/React.createElement("input", {
      type: "checkbox",
      checked: !!scelte[i],
      onChange: ev => setScelte(prev => ({
        ...prev,
        [i]: ev.target.checked
      }))
    }), e.fuori === true ? /*#__PURE__*/React.createElement("span", {
      className: "mis-esito is-ko"
    }, "Fuori ", e.scarto > 0 ? '+' : '−', fmtNum(Math.abs(e.scarto))) : e.fuori === false ? /*#__PURE__*/React.createElement("span", {
      className: "mis-esito is-ok"
    }, "Dentro") : null, /*#__PURE__*/React.createElement("span", {
      className: "mis-frase"
    }, fraseMisura(p)), p.da_verificare && /*#__PURE__*/React.createElement("span", {
      className: "pill-verifica",
      title: "Lo scostamento letto non tornava con misurato \u2212 nominale: controlla i valori"
    }, "da verificare"));
  })), /*#__PURE__*/React.createElement("details", {
    className: "field-hint"
  }, /*#__PURE__*/React.createElement("summary", null, "Lette ", proposte.length, " righe. Ne manca qualcuna? Testo letto dall\u2019immagine"), /*#__PURE__*/React.createElement("pre", {
    style: {
      whiteSpace: 'pre-wrap',
      margin: '6px 0 0',
      fontSize: 11
    }
  }, testoLetto.join('\n')), /*#__PURE__*/React.createElement("div", null, "Se mancano righe o i valori sono sbagliati: ingrandisci il PDF (almeno 125%) e cattura di nuovo, anche a pezzi.")), /*#__PURE__*/React.createElement("div", {
    className: "dett-actions"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-outline",
    disabled: !nScelte,
    onClick: () => {
      onAggiungi(proposte.filter((_, i) => scelte[i]));
      setProposte(null);
    }
  }, "Aggiungi ", nScelte, " misur", nScelte === 1 ? 'a' : 'e'), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    onClick: () => setProposte(null)
  }, "Annulla"), /*#__PURE__*/React.createElement("span", {
    className: "field-hint"
  }, "I valori restano modificabili nelle righe qui sopra: controllali sul report."))));
};

/* «Che cosa hai trovato?»: una scelta facoltativa apre solo i campi di quel caso. */
const DettaglioAnomalia = ({
  dett,
  testo,
  disabled,
  onChange,
  onCopiaNelTesto,
  opId,
  fase
}) => {
  const d = dett || emptyDett();
  const upd = patch => onChange({
    ...d,
    ...patch
  });
  const scegli = tipo => {
    if (d.tipo === tipo) {
      upd({
        tipo: ''
      });
      return;
    }
    const patch = {
      tipo
    };
    if (tipo === 'misura' && !(d.misure || []).length) patch.misure = [emptyMisura()];
    upd(patch);
  };
  const updMisura = (k, patch) => upd({
    misure: d.misure.map(m => m.key === k ? {
      ...m,
      ...patch
    } : m)
  });
  const dif = d.difetto || {};
  const doc = d.documenti || {
    docs: []
  };
  const rif = d.rif || {};
  const frasi = frasiDett(d);
  const ctx = {
    fase,
    tipo: codiceTipoAnomalia(d, testo)
  };
  const DETT_TIPI = casiVisibili(ctx);
  const casoAcceso = tipo => DETT_TIPI.some(([k]) => k === tipo);
  const vede = chiave => campoVisibile(chiave, ctx);
  const suggerito = codiceSuggerito(d, testo);
  const tipoSugg = TIPI_DIFETTO.find(t => t.codice === suggerito);
  const tipoSel = d.tipoDifettoId ? TIPI_DIFETTO.find(t => t.id === d.tipoDifettoId) : null;
  const f = (label, value, onCh, extra = {}) => /*#__PURE__*/React.createElement("label", {
    className: "dett-f"
  }, /*#__PURE__*/React.createElement("span", null, label), /*#__PURE__*/React.createElement("input", _extends({
    className: "text-input",
    value: value || '',
    disabled: disabled,
    spellCheck: true,
    lang: "it",
    onChange: e => onCh(e.target.value)
  }, extra)));
  return /*#__PURE__*/React.createElement("div", {
    className: "dett"
  }, DETT_TIPI.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "dett-ask"
  }, /*#__PURE__*/React.createElement("strong", null, "Che cosa hai trovato?"), /*#__PURE__*/React.createElement("span", null, "(facoltativo: apre i campi giusti)"), /*#__PURE__*/React.createElement("div", {
    className: "sup-chips"
  }, DETT_TIPI.map(([k, l]) => /*#__PURE__*/React.createElement("button", {
    key: k,
    type: "button",
    className: `sup-chip${d.tipo === k ? ' is-on' : ''}`,
    "aria-pressed": d.tipo === k,
    disabled: disabled,
    onClick: () => scegli(k)
  }, d.tipo === k ? '✓ ' : '', l)))), d.tipo === 'misura' && casoAcceso('misura') && /*#__PURE__*/React.createElement("div", {
    className: "dett-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dett-panel__head"
  }, "\uD83D\uDCCF Misure fuori tolleranza ", /*#__PURE__*/React.createElement("small", null, "\u2014 una riga per misura")), (d.misure || []).map((m, mi) => {
    const e = esitoMisura(m);
    return /*#__PURE__*/React.createElement(React.Fragment, {
      key: m.key
    }, mi > 0 && /*#__PURE__*/React.createElement("hr", {
      className: "mis-sep"
    }), /*#__PURE__*/React.createElement("div", {
      className: "dett-grid dett-grid--mis"
    }, /*#__PURE__*/React.createElement("label", {
      className: "dett-f"
    }, /*#__PURE__*/React.createElement("span", null, "Caratteristica"), /*#__PURE__*/React.createElement("select", {
      className: "text-input",
      value: m.car,
      disabled: disabled,
      onChange: ev => updMisura(m.key, {
        car: ev.target.value,
        modo: (CARATT_BY[ev.target.value] || {}).famiglia === 'geometria' || ev.target.value === 'rugosita' ? 'max' : m.modo === 'max' ? 'minmax' : m.modo
      })
    }, CARATT.map(c => /*#__PURE__*/React.createElement("option", {
      key: c.codice,
      value: c.codice
    }, c.simbolo ? `${c.simbolo} ` : '', c.nome))), m.car === 'altro' && /*#__PURE__*/React.createElement("input", {
      className: "text-input",
      value: m.nome || '',
      disabled: disabled,
      placeholder: "Che misura?",
      "aria-label": "Che misura",
      onChange: ev => updMisura(m.key, {
        nome: ev.target.value
      })
    })), /*#__PURE__*/React.createElement("label", {
      className: "dett-f"
    }, /*#__PURE__*/React.createElement("span", null, "Tolleranza", /*#__PURE__*/React.createElement("span", {
      className: "seg-mini"
    }, [['minmax', 'min/max'], ['pm', '±'], ['max', 'max']].map(([k, l]) => /*#__PURE__*/React.createElement("button", {
      key: k,
      type: "button",
      className: m.modo === k ? 'is-on' : '',
      disabled: disabled,
      onClick: () => updMisura(m.key, {
        modo: k
      })
    }, l)))), /*#__PURE__*/React.createElement("div", {
      className: "dett-tol"
    }, m.modo === 'pm' && /*#__PURE__*/React.createElement("input", {
      className: "text-input",
      inputMode: "decimal",
      disabled: disabled,
      value: m.nom || '',
      placeholder: "nominale",
      "aria-label": "Nominale",
      onChange: ev => updMisura(m.key, {
        nom: ev.target.value
      })
    }), /*#__PURE__*/React.createElement("input", {
      className: "text-input",
      inputMode: "decimal",
      disabled: disabled,
      value: m.a || '',
      placeholder: m.modo === 'minmax' ? 'min' : m.modo === 'pm' ? '±' : 'max',
      "aria-label": "Tolleranza",
      onChange: ev => updMisura(m.key, {
        a: ev.target.value
      })
    }), m.modo !== 'max' && /*#__PURE__*/React.createElement("input", {
      className: "text-input",
      inputMode: "decimal",
      disabled: disabled,
      value: m.b || '',
      placeholder: m.modo === 'minmax' ? 'max' : '+ (se diverso)',
      "aria-label": "Tolleranza superiore",
      onChange: ev => updMisura(m.key, {
        b: ev.target.value
      })
    }))), f('Rilevato', m.ril, v => updMisura(m.key, {
      ril: v
    }), {
      inputMode: 'decimal'
    }), f('Dove (quota / zona)', m.dove, v => updMisura(m.key, {
      dove: v
    }), {
      placeholder: 'Es. sez. H-H, lato piano M'
    }), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "dett-x",
      title: "Togli misura",
      disabled: disabled,
      onClick: () => upd({
        misure: d.misure.filter(x => x.key !== m.key)
      })
    }, "\xD7")), misuraUtile(m) && /*#__PURE__*/React.createElement("div", {
      className: "mis-out"
    }, e.fuori === true && /*#__PURE__*/React.createElement("span", {
      className: "mis-esito is-ko"
    }, "Fuori tolleranza ", e.scarto > 0 ? '+' : '−', fmtNum(Math.abs(e.scarto))), e.fuori === false && /*#__PURE__*/React.createElement("span", {
      className: "mis-esito is-ok"
    }, "Dentro la tolleranza"), /*#__PURE__*/React.createElement("span", {
      className: "mis-frase"
    }, fraseMisura(m))));
  }), /*#__PURE__*/React.createElement("div", {
    className: "dett-actions"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    disabled: disabled,
    onClick: () => upd({
      misure: [...(d.misure || []), emptyMisura()]
    })
  }, "+ Aggiungi misura")), !disabled && vede('report_zeiss') && /*#__PURE__*/React.createElement(LetturaReport, {
    opId: opId,
    disabled: disabled,
    onAggiungi: righe => {
      const nuove = righe.map(({
        car,
        nome,
        modo,
        nom,
        a,
        b,
        ril,
        dove
      }) => ({
        ...emptyMisura(),
        car,
        nome,
        modo,
        nom,
        a,
        b,
        ril,
        dove
      }));
      const tenute = (d.misure || []).filter(misuraUtile);
      upd({
        misure: [...tenute, ...nuove]
      });
    }
  })), d.tipo === 'difetto' && casoAcceso('difetto') && /*#__PURE__*/React.createElement("div", {
    className: "dett-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dett-panel__head"
  }, "\uD83D\uDD0E Difetto sul pezzo"), /*#__PURE__*/React.createElement("div", {
    className: "dett-grid dett-grid--dif"
  }, /*#__PURE__*/React.createElement("label", {
    className: "dett-f"
  }, /*#__PURE__*/React.createElement("span", null, "Che difetto"), /*#__PURE__*/React.createElement("select", {
    className: "text-input",
    value: dif.genere || '',
    disabled: disabled,
    onChange: ev => upd({
      difetto: {
        ...dif,
        genere: ev.target.value
      }
    })
  }, /*#__PURE__*/React.createElement("option", {
    value: ""
  }, "\u2014 scegli \u2014"), GENERI.map(g => /*#__PURE__*/React.createElement("option", {
    key: g.codice,
    value: g.codice
  }, g.nome)))), f('Dove sul pezzo', dif.dove, v => upd({
    difetto: {
      ...dif,
      dove: v
    }
  }), {
    placeholder: 'Es. smusso adiacente piano B, diametro AY sez. S17'
  })), /*#__PURE__*/React.createElement("div", {
    className: "dett-grid dett-grid--dim"
  }, f('Lunghezza', dif.lung, v => upd({
    difetto: {
      ...dif,
      lung: v
    }
  })), f('Larghezza / altezza', dif.larg, v => upd({
    difetto: {
      ...dif,
      larg: v
    }
  })), f('Profondità', dif.prof, v => upd({
    difetto: {
      ...dif,
      prof: v
    }
  })), f('Estensione', dif.est, v => upd({
    difetto: {
      ...dif,
      est: v
    }
  }), {
    placeholder: 'Es. 45°'
  }))), d.tipo === 'documenti' && casoAcceso('documenti') && /*#__PURE__*/React.createElement("div", {
    className: "dett-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dett-panel__head"
  }, "\uD83C\uDFF7\uFE0F Marcatura / documenti che non coincidono"), /*#__PURE__*/React.createElement("div", {
    className: "dett-grid dett-grid--doc"
  }, f('Sul pezzo c’è', doc.trovato, v => upd({
    documenti: {
      ...doc,
      trovato: v
    }
  }), {
    placeholder: 'Es. marcato AW340'
  }), f('Atteso (documenti)', doc.atteso, v => upd({
    documenti: {
      ...doc,
      atteso: v
    }
  }), {
    placeholder: 'Es. AW341'
  })), /*#__PURE__*/React.createElement("div", {
    className: "dett-ask"
  }, /*#__PURE__*/React.createElement("span", null, "Documenti coinvolti:"), /*#__PURE__*/React.createElement("div", {
    className: "doc-chips"
  }, DOC_LIST.map(x => {
    const on = (doc.docs || []).includes(x);
    return /*#__PURE__*/React.createElement("button", {
      key: x,
      type: "button",
      className: `anom-sn__chip${on ? ' is-on' : ''}`,
      disabled: disabled,
      onClick: () => upd({
        documenti: {
          ...doc,
          docs: on ? doc.docs.filter(y => y !== x) : [...(doc.docs || []), x]
        }
      })
    }, x);
  })))), !vede('riferimento') ? null : d.rifAperto || rif.disegno || rif.sezione || rif.fase ? /*#__PURE__*/React.createElement("div", {
    className: "dett-grid dett-grid--rif"
  }, f('Disegno / revisione', rif.disegno, v => upd({
    rif: {
      ...rif,
      disegno: v
    }
  })), f('Sezione / vista', rif.sezione, v => upd({
    rif: {
      ...rif,
      sezione: v
    }
  })), f('Fase del ciclo / F.OP', rif.fase, v => upd({
    rif: {
      ...rif,
      fase: v
    }
  }), {
    placeholder: 'Es. Fase 80, pag. 1/1'
  })) : !disabled && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    onClick: () => upd({
      rifAperto: true
    })
  }, "+ Riferimento (disegno, sezione, fase del ciclo)")), vede('tipo_difetto') && d.tipo && casoAcceso(d.tipo) && TIPI_DIFETTO.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "dett-tipo"
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-label"
  }, "Tipo di difetto"), /*#__PURE__*/React.createElement("select", {
    className: "text-input",
    disabled: disabled,
    value: d.tipoDifettoId || (tipoSugg ? tipoSugg.id : ''),
    onChange: ev => upd({
      tipoDifettoId: ev.target.value ? Number(ev.target.value) : null
    })
  }, /*#__PURE__*/React.createElement("option", {
    value: ""
  }, "\u2014 non indicato \u2014"), TIPI_DIFETTO.map(t => /*#__PURE__*/React.createElement("option", {
    key: t.id,
    value: t.id
  }, t.nome))), !tipoSel && tipoSugg && /*#__PURE__*/React.createElement("span", {
    className: "pill-auto"
  }, "proposto")), vede('copia_testo') && frasi.length > 0 && !disabled && /*#__PURE__*/React.createElement("div", {
    className: "dett-actions"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    onClick: () => onCopiaNelTesto(frasi)
  }, "\u2193 Copia nella descrizione"), /*#__PURE__*/React.createElement("span", {
    className: "field-hint"
  }, "Se lasci vuota la descrizione, al salvataggio si usano queste righe.")));
};

// tutti: l'anomalia vale per tutti i seriali del blocco (default); altrimenti sel = S/N scelti.
const newAnomalia = () => ({
  key: uid(),
  localId: null,
  testo: '',
  files: [],
  existing: [],
  gestita: false,
  avanzamento: '',
  tutti: true,
  sel: [],
  dett: emptyDett()
});
// confermaScoperti: S/N senza anomalia già confermati dall'operatore (chiave = elenco), vale solo se l'elenco non cambia.
const newEditor = () => ({
  bloccoId: null,
  voci: [],
  stati: [],
  dovePezzi: '',
  anomalie: [newAnomalia()],
  attiva: 0,
  bloccato: false,
  confermaRipetuti: false,
  confermaScoperti: ''
});
const editorFromBlocco = b => ({
  bloccoId: b.id,
  voci: [...(b.seriali || [])],
  stati: [...(b.stato_superficie || [])],
  dovePezzi: b.dove_pezzi || '',
  anomalie: (b.anomalie || []).map(a => ({
    key: `s${a.local_id}`,
    localId: a.local_id,
    testo: a.testo || '',
    files: [],
    existing: a.allegati || [],
    gestita: !!a.gestita,
    avanzamento: a.avanzamento || '',
    autoreId: a.autore_id || null,
    modificabile: a.modificabile !== false,
    tutti: a.tutti !== false,
    sel: a.tutti === false ? tokensOf(a.seriali) : [],
    dett: dettDaServer(a.dettaglio, a.tipo_difetto_id)
  })),
  attiva: -1,
  bloccato: !!b.bloccato,
  confermaRipetuti: false,
  confermaScoperti: ''
});
/* Bozza del blocco in scrittura, salvata in automatico sul server (senza gli allegati). */
const bozzaDa = ed => ({
  bloccoId: ed.bloccoId,
  voci: ed.voci,
  stati: ed.stati,
  dovePezzi: ed.dovePezzi || '',
  anomalie: ed.anomalie.filter(a => a.localId || testoAnomalia(a) || a.files.length || a.dett && a.dett.tipo).map(a => ({
    localId: a.localId,
    testo: a.testo,
    tutti: a.tutti,
    sel: a.sel,
    allegati: a.files.length,
    dett: a.dett ? {
      ...dettPayload(a.dett),
      tipoDifettoId: a.dett.tipoDifettoId || null
    } : null,
    origineId: a.origineId || null,
    allegatiOrigine: a.allegatiOrigine || 0,
    copiaAllegati: !!a.copiaAllegati
  })),
  daClona: !!ed.daClona
});
const bozzaPiena = bz => !!bz && ((bz.voci || []).length > 0 || (bz.stati || []).length > 0 || (bz.anomalie || []).length > 0 || !!bz.bloccoId);
const editorDaBozza = (bz, blocchi) => {
  const blocco = bz.bloccoId ? (blocchi || []).find(b => b.id === bz.bloccoId) : null;
  if (bz.bloccoId && !blocco) return newEditor();
  const base = blocco ? editorFromBlocco(blocco) : newEditor();
  const daBozza = bz.anomalie || [];
  const perId = {};
  daBozza.forEach(a => {
    if (a.localId) perId[a.localId] = a;
  });
  const esistenti = blocco ? base.anomalie.map(a => {
    const b = perId[a.localId];
    return b && !a.gestita ? {
      ...a,
      testo: b.testo || '',
      tutti: b.tutti !== false,
      sel: b.sel || [],
      dett: b.dett ? dettDaServer(b.dett, b.dett.tipoDifettoId) : a.dett
    } : a;
  }) : [];
  const nuove = daBozza.filter(a => !a.localId).map(a => ({
    ...newAnomalia(),
    testo: a.testo || '',
    tutti: a.tutti !== false,
    sel: a.sel || [],
    dett: a.dett ? dettDaServer(a.dett, a.dett.tipoDifettoId) : emptyDett(),
    ...(a.origineId ? {
      origineId: a.origineId,
      allegatiOrigine: a.allegatiOrigine || 0,
      copiaAllegati: !!a.copiaAllegati
    } : {})
  }));
  const anomalie = [...esistenti, ...nuove];
  return {
    ...base,
    voci: base.bloccato ? base.voci : [...(bz.voci || [])],
    stati: [...(bz.stati || base.stati)],
    dovePezzi: bz.dovePezzi != null ? bz.dovePezzi : base.dovePezzi || '',
    anomalie: anomalie.length ? anomalie : [newAnomalia()],
    attiva: anomalie.length ? anomalie.length - 1 : 0,
    daClona: !!bz.daClona
  };
};
/* S/N del blocco senza nessuna anomalia (stessa regola di controllo_service.seriali_senza_anomalia). */
const serialiScoperti = (tokens, anomalie) => {
  const piene = (anomalie || []).filter(a => a.localId || a.testo.trim() || a.files.length);
  if (tokens.length <= 1 || !piene.length || piene.some(a => a.tutti)) return [];
  const coperti = new Set();
  piene.forEach(a => a.sel.forEach(t => coperti.add(t.toLowerCase())));
  return tokens.filter(t => !coperti.has(t.toLowerCase()));
};
/* Singoli S/N -> voci, con i consecutivi in range (come seriali.comprimi_seriali). */
const comprimiTokens = tokens => {
  const out = [];
  let run = null;
  const chiudi = () => {
    if (!run) return;
    const da = `${run.p}${String(run.a).padStart(run.w, '0')}`;
    out.push(run.a === run.b ? da : `${da}-${run.p}${String(run.b).padStart(run.w, '0')}`);
    run = null;
  };
  tokens.forEach(t => {
    const m = String(t).match(/^(.*?)(\d+)$/);
    if (!m) {
      chiudi();
      out.push(t);
      return;
    }
    const n = parseInt(m[2], 10);
    if (run && run.p.toLowerCase() === m[1].toLowerCase() && run.w === m[2].length && n === run.b + 1) {
      run.b = n;
      return;
    }
    chiudi();
    run = {
      p: m[1],
      w: m[2].length,
      a: n,
      b: n
    };
  });
  chiudi();
  return out;
};
const editorDirty = ed => !!ed && (ed.bloccoId !== null || ed.voci.length > 0 || ed.stati.length > 0 || ed.anomalie.some(a => a.testo.trim() || a.files.length));
const StatoPill = ({
  a
}) => {
  if (a.chiusa) return /*#__PURE__*/React.createElement("span", {
    className: "pill pill-ok"
  }, "Chiusa");
  if (a.gestita) return /*#__PURE__*/React.createElement("span", {
    className: "pill pill-info"
  }, a.avanzamento || 'Gestita');
  return /*#__PURE__*/React.createElement("span", {
    className: "pill pill-wait"
  }, "In attesa del capocommessa");
};

/* Campo seriali a «chip»: Invio, virgola o spazio confermano; si incollano anche elenchi. */
const SerialInput = ({
  voci,
  onChange,
  disabled,
  inputRef
}) => {
  const [text, setText] = useState('');
  const add = parts => {
    if (!parts.length) return;
    const next = [...voci];
    parts.forEach(p => {
      const v = p.replace(/\s*-\s*/g, '-');
      if (!next.some(x => x.toLowerCase() === v.toLowerCase())) next.push(v);
    });
    onChange(next);
  };
  const commit = () => {
    const parts = splitSerialText(text);
    setText('');
    add(parts);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: `sn-field${disabled ? ' is-disabled' : ''}`,
    onClick: () => inputRef && inputRef.current && inputRef.current.focus()
  }, voci.map(v => {
    const p = parseVoce(v);
    return /*#__PURE__*/React.createElement("span", {
      key: v,
      className: `sn-chip${p && p.range ? ' is-range' : ''}`
    }, p && p.range ? /*#__PURE__*/React.createElement(React.Fragment, null, p.da, /*#__PURE__*/React.createElement("span", {
      className: "sn-chip__arrow"
    }, "\u2192"), p.a, /*#__PURE__*/React.createElement("span", {
      className: "sn-chip__n"
    }, p.tokens.length, " pz")) : v, !disabled && /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "sn-chip__x",
      "aria-label": `Rimuovi ${v}`,
      onClick: e => {
        e.stopPropagation();
        onChange(voci.filter(x => x !== v));
      }
    }, "\xD7"));
  }), !disabled && /*#__PURE__*/React.createElement("input", {
    ref: inputRef,
    className: "sn-field__input",
    type: "text",
    value: text,
    placeholder: voci.length ? 'Aggiungi altri seriali…' : 'Es. LCN00001 · LCN00005-LCN00010 · più seriali separati da virgola',
    onChange: e => setText(e.target.value),
    onKeyDown: e => {
      if (e.key === 'Enter' || e.key === ',' || e.key === ';' || e.key === ' ' && !/-\s*$/.test(text)) {
        if (text.trim()) {
          e.preventDefault();
          commit();
        } else if (e.key === 'Enter') e.preventDefault();
      } else if (e.key === 'Backspace' && !text && voci.length) {
        onChange(voci.slice(0, -1));
      }
    },
    onBlur: commit,
    onPaste: e => {
      const t = e.clipboardData ? e.clipboardData.getData('text') : '';
      if (t && /[\s,;]/.test(t.trim())) {
        e.preventDefault();
        add(splitSerialText(t));
      }
    }
  }));
};
let ORDINI_CACHE = null;
/* Cambio OP dalla pagina di inserimento: si clicca su OP o P/N in alto. */
const CambiaOpPanel = ({
  opAttuale,
  nSalvate,
  busy,
  err,
  onScegli,
  onCancel
}) => {
  const [ordini, setOrdini] = useState(ORDINI_CACHE || []);
  const [q, setQ] = useState('');
  const [sel, setSel] = useState(null);
  useEffect(() => {
    if (ORDINI_CACHE) return;
    getJson(API.db_ordini, 'Elenco OP').then(d => {
      ORDINI_CACHE = Array.isArray(d) ? d : [];
      setOrdini(ORDINI_CACHE);
    }).catch(() => {});
  }, []);
  const t = q.trim().toLowerCase();
  const lista = ordini.filter(o => String(o.id || '') !== String(opAttuale || '')).filter(o => !t || [o.id, o.pn, o.capo, o.car].some(v => String(v || '').toLowerCase().includes(t))).slice(0, 30);
  return /*#__PURE__*/React.createElement("div", {
    className: "cambia-op"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dett-panel__head"
  }, "Cambia OP / P/N ", /*#__PURE__*/React.createElement("small", null, "(ora: ", opAttuale, ")")), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    autoFocus: true,
    value: q,
    disabled: busy,
    placeholder: "Cerca per OP, P/N, capocommessa o CAR\u2026",
    onChange: e => {
      setQ(e.target.value);
      setSel(null);
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "cambia-op__list"
  }, !ordini.length && /*#__PURE__*/React.createElement("small", null, "Caricamento degli OP\u2026"), ordini.length > 0 && !lista.length && /*#__PURE__*/React.createElement("small", null, "Nessun OP trovato."), lista.map(o => /*#__PURE__*/React.createElement("button", {
    type: "button",
    key: o.item_id ?? o.id,
    className: `cambia-op__row${sel && sel.id === o.id ? ' is-sel' : ''}`,
    disabled: busy,
    onClick: () => setSel(o)
  }, /*#__PURE__*/React.createElement("strong", null, o.id), /*#__PURE__*/React.createElement("span", null, "P/N ", o.pn || '—'), /*#__PURE__*/React.createElement("small", null, [o.capo, o.car].filter(v => v && v !== '—').join(' · '))))), err && /*#__PURE__*/React.createElement("div", {
    className: "error-msg"
  }, err), /*#__PURE__*/React.createElement("div", {
    className: "cambia-op__foot"
  }, /*#__PURE__*/React.createElement("span", null, nSalvate ? `${nSalvate === 1 ? "L'anomalia già salvata passa" : `Le ${nSalvate} anomalie già salvate passano`} all'OP scelto (solo se nessuna è stata ancora gestita); il blocco che stai scrivendo resta com'è.` : 'Il controllo prosegue sull’OP scelto; quello che stai scrivendo resta com’è.'), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    disabled: busy,
    onClick: onCancel
  }, "Annulla"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-primary",
    disabled: busy || !sel,
    onClick: () => onScegli(sel)
  }, busy ? 'Sposto…' : sel ? `Passa a ${sel.id}` : 'Scegli un OP')));
};

/* «Taglia»: sposta un'anomalia salvata su un altro S/N (stesso OP o un altro OP). */
const TagliaPanel = ({
  anomalia,
  opCorrente,
  onDone,
  onCancel
}) => {
  const [opId, setOpId] = useState(opCorrente || '');
  const [sn, setSn] = useState('');
  const [ordini, setOrdini] = useState(ORDINI_CACHE || []);
  const [seriali, setSeriali] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => {
    if (ORDINI_CACHE) return;
    getJson(API.db_ordini, 'Elenco OP').then(d => {
      ORDINI_CACHE = Array.isArray(d) ? d : [];
      setOrdini(ORDINI_CACHE);
    }).catch(() => {});
  }, []);
  useEffect(() => {
    const op = opId.trim();
    setSeriali([]);
    if (!op) return undefined;
    const t = setTimeout(() => {
      getJson(`${API.seriali_op}?op_id=${encodeURIComponent(op)}`, 'Seriali OP').then(d => setSeriali(Array.isArray(d.seriali) ? d.seriali : [])).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [opId]);
  const altroOp = opId.trim().toLowerCase() !== String(opCorrente || '').toLowerCase();
  const conferma = async () => {
    if (!opId.trim()) {
      setErr('Indica l’OP.');
      return;
    }
    if (!sn.trim()) {
      setErr('Indica il S/N di destinazione.');
      return;
    }
    const sel = ordini.find(o => String(o.id || '').toLowerCase() === opId.trim().toLowerCase());
    setBusy(true);
    setErr('');
    try {
      const j = await postJson(API.sposta, {
        local_id: anomalia.localId,
        op_id: opId.trim(),
        op_item_id: sel ? sel.item_id : null,
        seriali: splitSerialText(sn)
      }, 'Taglia');
      onDone(j);
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "anom-taglia"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dett-panel__head"
  }, "\u2702 Taglia: sposta l\u2019anomalia ", codiceAnomalia(anomalia.localId), " su un altro S/N"), /*#__PURE__*/React.createElement("div", {
    className: "anom-taglia__row"
  }, /*#__PURE__*/React.createElement("label", null, "OP", /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    list: "taglia-op",
    value: opId,
    disabled: busy,
    onChange: e => setOpId(e.target.value),
    placeholder: "Stesso OP o un altro"
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "taglia-op"
  }, ordini.slice(0, 500).map(o => /*#__PURE__*/React.createElement("option", {
    key: o.item_id ?? o.id,
    value: o.id
  })))), /*#__PURE__*/React.createElement("label", null, "S/N di destinazione", /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    list: "taglia-sn",
    value: sn,
    disabled: busy,
    autoFocus: true,
    onChange: e => setSn(e.target.value),
    placeholder: "Es. LCN00012 o LCN00012-LCN00015",
    onKeyDown: e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        conferma();
      }
    }
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "taglia-sn"
  }, seriali.slice(0, 500).map(s => /*#__PURE__*/React.createElement("option", {
    key: s,
    value: s
  }))))), err && /*#__PURE__*/React.createElement("div", {
    className: "error-msg",
    role: "alert"
  }, err), /*#__PURE__*/React.createElement("div", {
    className: "anom-taglia__foot"
  }, /*#__PURE__*/React.createElement("small", null, altroOp ? 'Esce da questo controllo e passa all’OP indicato: il suo capocommessa la trova nel riepilogo delle modifiche.' : 'Resta in questo controllo: va nel blocco che ha già quel S/N, altrimenti in un blocco nuovo.'), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    disabled: busy,
    onClick: onCancel
  }, "Annulla"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-primary",
    disabled: busy,
    onClick: conferma
  }, busy ? 'Sposto…' : 'Sposta qui')));
};

/* Allegati di una anomalia: trascina, sfoglia o incolla (Ctrl+V) dagli appunti. */
const AttachmentZone = ({
  files,
  existing,
  onAdd,
  onRemove,
  disabled
}) => {
  const [over, setOver] = useState(false);
  const inputRef = useRef(null);
  const previews = React.useMemo(() => files.map(f => isImageFile(f) ? URL.createObjectURL(f) : ''), [files]);
  useEffect(() => () => previews.forEach(u => u && URL.revokeObjectURL(u)), [previews]);
  return /*#__PURE__*/React.createElement("div", {
    className: `drop-zone${over ? ' is-over' : ''}${disabled ? ' is-disabled' : ''}`,
    onDragOver: e => {
      if (disabled) return;
      e.preventDefault();
      setOver(true);
    },
    onDragLeave: () => setOver(false),
    onDrop: e => {
      if (disabled) return;
      e.preventDefault();
      setOver(false);
      onAdd(Array.from(e.dataTransfer.files || []));
    }
  }, /*#__PURE__*/React.createElement("input", {
    ref: inputRef,
    type: "file",
    multiple: true,
    hidden: true,
    accept: ".jpg,.jpeg,.png,.gif,.bmp,.webp,.pdf,.doc,.docx,.xls,.xlsx,.xlsm,.csv",
    onChange: e => {
      const sel = Array.from(e.target.files || []);
      e.target.value = '';
      onAdd(sel);
    }
  }), !disabled && /*#__PURE__*/React.createElement("div", {
    className: "drop-zone__hint"
  }, /*#__PURE__*/React.createElement("svg", {
    width: "18",
    height: "18",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"
  }), /*#__PURE__*/React.createElement("polyline", {
    points: "17 8 12 3 7 8"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "12",
    y1: "3",
    x2: "12",
    y2: "15"
  })), /*#__PURE__*/React.createElement("span", null, "Trascina qui foto e documenti, ", /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    onClick: () => inputRef.current && inputRef.current.click()
  }, "sfoglia"), " oppure incolla con ", /*#__PURE__*/React.createElement("kbd", null, "Ctrl"), "+", /*#__PURE__*/React.createElement("kbd", null, "V"))), (existing.length > 0 || files.length > 0) && /*#__PURE__*/React.createElement("div", {
    className: "thumbs"
  }, existing.map(f => /*#__PURE__*/React.createElement("div", {
    key: f.file_id,
    className: "thumb is-saved",
    title: `${f.name} · già caricato`
  }, /*#__PURE__*/React.createElement("span", {
    className: "thumb__ext"
  }, fileExt(f.name).replace('.', '').toUpperCase() || 'FILE'), /*#__PURE__*/React.createElement("span", {
    className: "thumb__name"
  }, f.name))), files.map((f, i) => /*#__PURE__*/React.createElement("div", {
    key: `${f.name}-${f.size}-${i}`,
    className: "thumb",
    title: `${f.name} · ${formatBytes(f.size)}`
  }, previews[i] ? /*#__PURE__*/React.createElement("img", {
    src: previews[i],
    alt: ""
  }) : /*#__PURE__*/React.createElement("span", {
    className: "thumb__ext"
  }, fileExt(f.name).replace('.', '').toUpperCase() || 'FILE'), /*#__PURE__*/React.createElement("span", {
    className: "thumb__name"
  }, f.name), !disabled && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "thumb__x",
    "aria-label": `Rimuovi ${f.name}`,
    onClick: () => onRemove(i)
  }, "\xD7")))));
};

/* Blocco già salvato: sola lettura, compatto. */
const BloccoCongelato = ({
  b,
  index,
  onEdit,
  canEdit
}) => {
  const [open, setOpen] = useState(false);
  return /*#__PURE__*/React.createElement("div", {
    className: "blk is-frozen"
  }, /*#__PURE__*/React.createElement("div", {
    className: "blk-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "blk-num"
  }, index + 1), /*#__PURE__*/React.createElement("div", {
    className: "blk-head__main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "blk-sn"
  }, b.seriale_label), /*#__PURE__*/React.createElement("div", {
    className: "blk-meta"
  }, "Fase ", b.fase, " \xB7 ", tokensOf(b.seriali).length, " pezz", tokensOf(b.seriali).length === 1 ? 'o' : 'i', " \xB7 ", b.anomalie.length, " anomali", b.anomalie.length === 1 ? 'a' : 'e', b.stato_superficie.map(s => /*#__PURE__*/React.createElement("span", {
    key: s,
    className: "pill pill-sup",
    style: {
      marginLeft: 6
    }
  }, s)))), /*#__PURE__*/React.createElement("span", {
    className: "blk-lock",
    title: "Blocco salvato"
  }, /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2.4",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "3",
    y: "11",
    width: "18",
    height: "11",
    rx: "2"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M7 11V7a5 5 0 0 1 10 0v4"
  })), "Salvato")), /*#__PURE__*/React.createElement("ol", {
    className: "blk-list"
  }, b.anomalie.map((a, i) => /*#__PURE__*/React.createElement("li", {
    key: a.local_id,
    className: "blk-item"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "blk-item__btn",
    onClick: () => setOpen(open === a.local_id ? false : a.local_id),
    "aria-expanded": open === a.local_id
  }, /*#__PURE__*/React.createElement("span", {
    className: "blk-item__n"
  }, i + 1), /*#__PURE__*/React.createElement("span", {
    className: `blk-item__txt${open === a.local_id ? ' is-open' : ''}`
  }, a.testo), a.tutti === false && /*#__PURE__*/React.createElement("span", {
    className: "pill pill-parz",
    title: `Solo sui S/N: ${a.seriale_label}`
  }, "Solo ", a.seriale_label), a.allegati.length > 0 && /*#__PURE__*/React.createElement("span", {
    className: "blk-item__att"
  }, "\uD83D\uDCCE ", a.allegati.length), /*#__PURE__*/React.createElement(StatoPill, {
    a: a
  })), open === a.local_id && a.note_capocommessa && /*#__PURE__*/React.createElement("div", {
    className: "blk-item__note"
  }, /*#__PURE__*/React.createElement("strong", null, "Capocommessa:"), " ", a.note_capocommessa)))), (b.seriali_scoperti || []).length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "sn-warn"
  }, "\u26A0 S/N senza anomalia: ", comprimiTokens(b.seriali_scoperti).join(', ')), canEdit && /*#__PURE__*/React.createElement("div", {
    className: "blk-foot"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary btn-sm",
    onClick: onEdit
  }, "Modifica o aggiungi anomalie")));
};

/* S/N presenti in più blocchi dello stesso controllo. */
const serialiMultiBlocco = blocchi => {
  const map = {};
  (blocchi || []).forEach((b, i) => tokensOf(b.seriali).forEach(t => {
    const k = t.toLowerCase();
    (map[k] = map[k] || {
      token: t,
      blocchi: []
    }).blocchi.push(i + 1);
  }));
  return Object.values(map).filter(x => x.blocchi.length > 1);
};

/* Riepilogo del controllo: prima di terminare (da confermare) e dopo (da stampare). */
/* Destinatari della mail: capocommessa/CAR risolti dall'OP + persone aggiunte in copia.
   Si aggiungono solo persone dell'anagrafica (ricerca per nome o email): il server
   rifiuta gli indirizzi non collegati a nessuno, perché la mail porta il link di decisione. */
const DestinatariMail = ({
  destinatari,
  extra,
  onChange,
  disabled,
  compact
}) => {
  const [aperto, setAperto] = useState(false); // false | 'persona' | 'capo'
  const [capi, setCapi] = useState(null);
  const [q, setQ] = useState('');
  const [sug, setSug] = useState([]);
  const [hi, setHi] = useState(0);
  const [msg, setMsg] = useState('');
  const lista = extra || [];
  const gia = new Set([destinatari && destinatari.to_email, destinatari && destinatari.cc_email, ...lista.map(d => d.email)].filter(Boolean).map(e => e.toLowerCase()));
  useEffect(() => {
    if (aperto !== 'capo' || capi) return undefined;
    let alive = true;
    getJson(`${API.controllo_persone}?ruolo=capocommessa`, 'Capicommessa').then(j => alive && setCapi(j.results || [])).catch(e => {
      if (alive) {
        setCapi([]);
        setMsg(e.message);
      }
    });
    return () => {
      alive = false;
    };
  }, [aperto]);
  useEffect(() => {
    if (aperto !== 'capo') return;
    const t = q.trim().toLowerCase();
    setSug((capi || []).filter(p => !gia.has(p.email.toLowerCase()) && (!t || p.nome.toLowerCase().includes(t) || p.email.toLowerCase().includes(t))));
    setHi(0);
  }, [aperto, capi, q, extra]);
  useEffect(() => {
    if (aperto !== 'persona') return undefined;
    const testo = q.trim();
    if (testo.length < 2) {
      setSug([]);
      return undefined;
    }
    let alive = true;
    const t = setTimeout(() => {
      getJson(`${API.controllo_persone}?q=${encodeURIComponent(testo)}`, 'Ricerca persone').then(j => {
        if (!alive) return;
        setSug((j.results || []).filter(p => !gia.has(p.email.toLowerCase())));
        setHi(0);
        setMsg('');
      }).catch(e => alive && setMsg(e.message));
    }, 220);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [q, aperto]);
  const chiudi = () => {
    setAperto(false);
    setQ('');
    setSug([]);
    setMsg('');
  };
  const aggiungi = p => {
    if (!p || gia.has(p.email.toLowerCase())) return;
    onChange([...lista, {
      email: p.email,
      nome: p.nome
    }]);
    chiudi();
  };
  const onKey = e => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHi(h => Math.min(h + 1, sug.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHi(h => Math.max(h - 1, 0));
    } else if (e.key === 'Escape') chiudi();else if (e.key === 'Enter') {
      e.preventDefault();
      if (sug[hi]) aggiungi(sug[hi]);else if (aperto === 'persona' && q.includes('@')) setMsg('Nessuna persona in anagrafica con questo indirizzo: si possono aggiungere solo persone collegate a un utente.');
    }
  };
  const chip = (nome, email, key) => /*#__PURE__*/React.createElement("span", {
    key: key,
    className: "dest-chip",
    title: email
  }, nome);
  return /*#__PURE__*/React.createElement("div", {
    className: `dest-mail${compact ? ' dest-mail--compact' : ''}`,
    "aria-label": "Destinatari della mail"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dest-mail__row"
  }, /*#__PURE__*/React.createElement("span", {
    className: "dest-mail__lbl"
  }, "A"), destinatari && destinatari.to ? chip(destinatari.to, destinatari.to_email) : /*#__PURE__*/React.createElement("span", {
    className: "copilot-err"
  }, destinatari ? 'Capocommessa e CAR dell’OP senza indirizzo email: la mail non potrà partire, avvisa l’ufficio.' : 'Lettura destinatari…')), /*#__PURE__*/React.createElement("div", {
    className: "dest-mail__row"
  }, /*#__PURE__*/React.createElement("span", {
    className: "dest-mail__lbl"
  }, "In copia"), destinatari && destinatari.cc && chip(destinatari.cc, destinatari.cc_email), lista.map(d => /*#__PURE__*/React.createElement("span", {
    key: d.email,
    className: "dest-chip is-extra",
    title: d.email
  }, d.nome || d.email, /*#__PURE__*/React.createElement("small", null, d.email), !disabled && /*#__PURE__*/React.createElement("button", {
    type: "button",
    "aria-label": `Togli ${d.nome || d.email}`,
    onClick: () => onChange(lista.filter(x => x.email !== d.email))
  }, "\xD7"))), !(destinatari && destinatari.cc) && !lista.length && /*#__PURE__*/React.createElement("span", {
    className: "field-hint"
  }, "nessuno"), !disabled && !aperto && lista.length < 10 && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    onClick: () => setAperto('capo')
  }, "+ Aggiungi altro capocommessa"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    onClick: () => setAperto('persona')
  }, "+ Aggiungi persona"))), destinatari && (destinatari.riepilogo || []).length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "dest-mail__row",
    title: "Lista \xABRiepilogo modifiche\xBB di Configurazione \u2192 Notifiche"
  }, /*#__PURE__*/React.createElement("span", {
    className: "dest-mail__lbl"
  }, "Riepilogo"), destinatari.riepilogo.map(d => chip(d.nome || d.email, d.email, d.email)), /*#__PURE__*/React.createElement("span", {
    className: "dest-mail__note"
  }, "riepilogo senza link, da Configurazione")), destinatari && (destinatari.riepilogo_rdc || []).length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "dest-mail__row",
    title: "Lista \xABRDC / segnalazione cliente\xBB di Configurazione \u2192 Notifiche"
  }, /*#__PURE__*/React.createElement("span", {
    className: "dest-mail__lbl"
  }, "Se RDC"), destinatari.riepilogo_rdc.map(d => chip(d.nome || d.email, d.email, d.email)), /*#__PURE__*/React.createElement("span", {
    className: "dest-mail__note"
  }, "solo se un\u2019anomalia \xE8 da aprire RDC o da segnalare al cliente")), aperto && !disabled && /*#__PURE__*/React.createElement("div", {
    className: "dest-add"
  }, /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    autoFocus: true,
    value: q,
    placeholder: aperto === 'capo' ? 'Filtra i capicommessa…' : 'Nome, cognome o email…',
    onFocus: () => aperto === 'capo' && setHi(0),
    onChange: e => setQ(e.target.value),
    onKeyDown: onKey,
    "aria-label": aperto === 'capo' ? 'Scegli il capocommessa da aggiungere in copia' : 'Cerca persona da aggiungere in copia'
  }), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary btn-sm",
    onClick: chiudi
  }, "Chiudi"), sug.length > 0 && /*#__PURE__*/React.createElement("ul", {
    className: "dest-sug",
    role: "listbox"
  }, sug.map((p, i) => /*#__PURE__*/React.createElement("li", {
    key: p.email
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: i === hi ? 'is-hi' : '',
    onMouseDown: e => {
      e.preventDefault();
      aggiungi(p);
    }
  }, /*#__PURE__*/React.createElement("strong", null, p.nome), /*#__PURE__*/React.createElement("small", null, p.email))))), aperto === 'capo' && capi === null && /*#__PURE__*/React.createElement("span", {
    className: "field-hint"
  }, "Carico i capicommessa\u2026"), aperto === 'capo' && capi !== null && !sug.length && !msg && /*#__PURE__*/React.createElement("span", {
    className: "field-hint"
  }, "Nessun altro capocommessa con email disponibile."), aperto === 'persona' && q.trim().length >= 2 && !sug.length && !msg && /*#__PURE__*/React.createElement("span", {
    className: "field-hint"
  }, "Nessuna persona trovata.")), msg && /*#__PURE__*/React.createElement("div", {
    className: "copilot-err"
  }, msg));
};
const RiepilogoControllo = ({
  op,
  controllo,
  destinatari,
  onChangeExtra
}) => {
  const blocchi = controllo.blocchi || [];
  const pezzi = new Set();
  blocchi.forEach(b => tokensOf(b.seriali).forEach(t => pezzi.add(t.toLowerCase())));
  const nAnom = blocchi.reduce((n, b) => n + b.anomalie.length, 0);
  const nAll = blocchi.reduce((n, b) => n + b.anomalie.reduce((m, a) => m + (a.allegati || []).length, 0), 0);
  const ripetuti = serialiMultiBlocco(blocchi);
  const senzaSup = STATI_SUPERFICIE.length ? blocchi.filter(b => !(b.stato_superficie || []).length).map((b, i) => b.ordine || i + 1) : [];
  const scoperti = blocchi.map((b, i) => ({
    n: i + 1,
    sn: b.seriali_scoperti || []
  })).filter(x => x.sn.length);
  return /*#__PURE__*/React.createElement("div", {
    className: "riep"
  }, /*#__PURE__*/React.createElement("div", {
    className: "riep-kpi"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, blocchi.length), /*#__PURE__*/React.createElement("span", null, "Blocchi")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, pezzi.size), /*#__PURE__*/React.createElement("span", null, "Pezzi")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, nAnom), /*#__PURE__*/React.createElement("span", null, "Anomalie")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, nAll), /*#__PURE__*/React.createElement("span", null, "Allegati"))), /*#__PURE__*/React.createElement("div", {
    className: "riep-mail"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "OP ", op.id), " \xB7 fase ", /*#__PURE__*/React.createElement("strong", null, controllo.fase), controllo.operatore ? /*#__PURE__*/React.createElement(React.Fragment, null, " \xB7 operatore ", controllo.operatore) : null)), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-label"
  }, "Mail al capocommessa con il link di decisione"), /*#__PURE__*/React.createElement(DestinatariMail, {
    destinatari: destinatari,
    extra: controllo.destinatari_extra || [],
    onChange: onChangeExtra || (() => {}),
    disabled: !onChangeExtra
  })), ripetuti.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "riep-warn"
  }, "S/N in pi\xF9 blocchi (confermato in inserimento): ", ripetuti.slice(0, 10).map(r => `${r.token} → blocchi ${r.blocchi.join(', ')}`).join(' · '), ripetuti.length > 10 ? '…' : ''), senzaSup.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "riep-warn"
  }, "Stato superficie non indicato nei blocchi ", senzaSup.join(', '), "."), scoperti.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "riep-warn"
  }, "S/N senza nessuna anomalia (confermato in inserimento): ", scoperti.map(x => `blocco ${x.n} → ${comprimiTokens(x.sn).join(', ')}`).join(' · ')), blocchi.map((b, i) => /*#__PURE__*/React.createElement("div", {
    className: "riep-blk",
    key: b.id
  }, /*#__PURE__*/React.createElement("div", {
    className: "riep-blk__head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "blk-num"
  }, i + 1), /*#__PURE__*/React.createElement("div", {
    className: "blk-sn"
  }, b.seriale_label), (b.stato_superficie || []).map(s => /*#__PURE__*/React.createElement("span", {
    key: s,
    className: "pill pill-sup"
  }, s)), /*#__PURE__*/React.createElement("span", {
    className: "blk-meta"
  }, "Fase ", b.fase)), /*#__PURE__*/React.createElement("ol", {
    className: "riep-list"
  }, b.anomalie.map((a, j) => /*#__PURE__*/React.createElement("li", {
    key: a.local_id
  }, /*#__PURE__*/React.createElement("span", {
    className: "blk-item__n"
  }, j + 1), /*#__PURE__*/React.createElement("span", {
    className: "riep-list__txt"
  }, a.testo), /*#__PURE__*/React.createElement("span", {
    className: "riep-list__side"
  }, a.tutti === false && /*#__PURE__*/React.createElement("span", {
    className: "pill pill-parz",
    title: `Solo sui S/N: ${a.seriale_label}`
  }, "Solo ", a.seriale_label), /*#__PURE__*/React.createElement("span", {
    className: "blk-meta"
  }, codiceAnomalia(a.local_id)), (a.allegati || []).length > 0 && /*#__PURE__*/React.createElement("span", {
    className: "blk-item__att"
  }, "\uD83D\uDCCE ", a.allegati.length), /*#__PURE__*/React.createElement(StatoPill, {
    a: a
  }))))))));
};

/* Blocco copiato da un altro OP -> editor: stessi S/N, stato superficie e testi. */
const editorDaClona = b => ({
  ...newEditor(),
  voci: [...(b.seriali || [])],
  stati: (b.stato_superficie || []).filter(st => STATI_SUPERFICIE.includes(st)),
  anomalie: (b.anomalie || []).map(a => ({
    ...newAnomalia(),
    testo: a.testo || '',
    tutti: a.tutti !== false,
    sel: a.tutti === false ? tokensOf(a.seriali || []) : [],
    origineId: a.origine_id,
    allegatiOrigine: a.allegati || 0,
    copiaAllegati: false,
    dett: dettDaServer(a.dettaglio, a.tipo_difetto_id)
  })),
  attiva: -1,
  daClona: true
});
const editorCorrenteBlocco = ed => ({
  seriali: ed.voci,
  stato_superficie: ed.stati,
  anomalie: ed.anomalie.filter(a => a.testo.trim() || a.origineId).map(a => ({
    origine_id: a.origineId,
    testo: a.testo,
    tutti: a.tutti,
    seriali: a.sel,
    allegati: a.allegatiOrigine || 0,
    dettaglio: dettPayload(a.dett),
    tipo_difetto_id: a.dett ? a.dett.tipoDifettoId : null
  }))
});

/* Controlli aperti con qualcosa in sospeso: i propri e, per il gruppo qualità
   (Controllo qualità / Qualità), quelli dei colleghi. Un controllo lungo iniziato a
   fine turno lo prosegue il collega dopo con «Prendi in carico». */
const ControlliSospesi = () => {
  const [righe, setRighe] = useState([]);
  const [gruppo, setGruppo] = useState(false);
  useEffect(() => {
    getJson(API.controlli_sospesi, 'Controlli in sospeso').then(j => {
      setRighe(j.controlli || []);
      setGruppo(!!j.gruppo);
    }).catch(() => {});
  }, []);
  if (!righe.length) return null;
  const quando = iso => iso ? new Date(iso).toLocaleString('it-IT', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }) : '';
  const cosa = r => [r.anomalie_in_bozza ? `${r.anomalie_in_bozza} anomali${r.anomalie_in_bozza === 1 ? 'a' : 'e'} scritt${r.anomalie_in_bozza === 1 ? 'a' : 'e'} da salvare` : '', r.blocchi_da_copiare ? `${r.blocchi_da_copiare} blocch${r.blocchi_da_copiare === 1 ? 'o' : 'i'} da copiare` : '', r.da_notificare ? `${r.da_notificare} anomali${r.da_notificare === 1 ? 'a' : 'e'} non ancora comunicat${r.da_notificare === 1 ? 'a' : 'e'}` : ''].filter(Boolean).join(' · ') || 'blocco in scrittura';
  return /*#__PURE__*/React.createElement("div", {
    className: "step-card sospesi-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "resume-box"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-label"
  }, gruppo ? 'Controlli in sospeso del gruppo qualità' : 'I tuoi controlli in sospeso'), gruppo && /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, "Li vedono tutti i colleghi con ruolo Controllo qualit\xE0 o Qualit\xE0: chi riprende il controllo di un altro lo prende in carico e lo porta a termine."), righe.map(r => /*#__PURE__*/React.createElement("div", {
    key: r.id,
    className: "resume-row"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "OP ", r.op_id), r.op_nuovo ? ' (nuovo, non ancora creato)' : '', " \xB7 fase ", r.fase, /*#__PURE__*/React.createElement("div", {
    className: "sospesi-meta"
  }, /*#__PURE__*/React.createElement("span", {
    className: "sospesi-chi"
  }, r.mio ? 'Tuo' : r.operatore), " \xB7 ", cosa(r), " \xB7 ultimo aggiornamento ", quando(r.ultimo_at), r.passaggi && r.passaggi.length > 0 && ` · iniziato da ${r.passaggi[0].da}`)), /*#__PURE__*/React.createElement("a", {
    className: "btn-outline",
    href: `${window.location.pathname}?controllo=${r.id}`
  }, r.mio ? 'Riprendi' : 'Apri')))));
};
const Step2Controllo = ({
  op,
  onBack,
  onDone,
  clona,
  onOpCreato,
  riprendiId,
  onCambiaOp
}) => {
  // OP nuovo non ancora creato: nasce con il primo «Salva blocco»; uscendo prima non resta niente.
  const opRef = useRef(op);
  const daCreare = !!op.daCreare;
  const [loading, setLoading] = useState(true);
  const [controllo, setControllo] = useState(null);
  const [riprendibili, setRiprendibili] = useState([]);
  // Controllo di un collega del gruppo qualità aperto in lettura: si prosegue solo
  // dopo «Prendi in carico» (mai in automatico: il link del promemoria non lo ruba).
  const [daPrendere, setDaPrendere] = useState(null);
  const [fasiNote, setFasiNote] = useState([]);
  const [fase, setFase] = useState(clona ? clona.fase || '' : '');
  // Blocchi copiati non ancora caricati nell'editor (in ordine).
  const [coda, setCoda] = useState(clona ? clona.blocchi : []);
  const editorDopo = codaAttuale => {
    if (!codaAttuale.length) return newEditor();
    setCoda(codaAttuale.slice(1));
    return editorDaClona(codaAttuale[0]);
  };
  const [editingFase, setEditingFase] = useState(false);
  const [editor, setEditor] = useState(newEditor());
  const [saving, setSaving] = useState(false);
  // Cambio OP dalla barra in alto: null | { busy, err }.
  const [cambioOp, setCambioOp] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [attachErr, setAttachErr] = useState('');
  const [confirmTermina, setConfirmTermina] = useState(false);
  const [esito, setEsito] = useState(null);
  const [riepilogo, setRiepilogo] = useState(false);
  const [destinatari, setDestinatari] = useState(null);
  const [extraAvvio, setExtraAvvio] = useState([]);
  const [bozzaAt, setBozzaAt] = useState('');
  const bozzaRef = useRef({
    salvata: false,
    pending: null
  });
  const [confirmRipetuti, setConfirmRipetuti] = useState(null);
  const [serialiAperti, setSerialiAperti] = useState({
    seriali: [],
    dettagli: {}
  });
  const [copilot, setCopilot] = useState({
    key: '',
    loading: false,
    sug: null,
    err: ''
  });
  const snRef = useRef(null);
  // Selezione dei S/N di un'anomalia trascinando sui chip: { anomalia, mode, last }.
  const snDragRef = useRef(null);
  useEffect(() => {
    const fine = () => {
      snDragRef.current = null;
    };
    window.addEventListener('pointerup', fine);
    window.addEventListener('pointercancel', fine);
    return () => {
      window.removeEventListener('pointerup', fine);
      window.removeEventListener('pointercancel', fine);
    };
  }, []);
  const impostaSeriali = (i, lista, accendi) => setEditor(prev => ({
    ...prev,
    anomalie: prev.anomalie.map((x, idx) => {
      if (idx !== i) return x;
      const chiavi = new Set(lista.map(t => t.toLowerCase()));
      const resto = x.sel.filter(s => !chiavi.has(s.toLowerCase()));
      return {
        ...x,
        sel: accendi ? [...resto, ...lista] : resto
      };
    })
  }));
  const isBenestare = String(op.stato || '').toLowerCase().includes('benestare');
  const loadSerialiAperti = () => {
    if (!op || !op.id || opRef.current.daCreare) return;
    fetch(`${API.seriali_op}?op_id=${encodeURIComponent(op.id)}`, {
      credentials: 'same-origin'
    }).then(r => r.ok ? r.json() : {
      seriali: [],
      dettagli: {}
    }).then(d => setSerialiAperti({
      seriali: Array.isArray(d.seriali) ? d.seriali : [],
      dettagli: d.dettagli || {}
    })).catch(() => {});
  };
  useEffect(() => {
    if (riprendiId) riprendi({
      id: riprendiId
    });
    if (opRef.current.daCreare) {
      // OP non ancora creato: destinatari dai nomi scritti, e i controlli lasciati in
      // bozza sullo stesso OP nuovo (per «Riprendi»).
      const benestare = !!opRef.current.daCreare.collaudo_benestare;
      setDestinatari({
        to: benestare ? op.car : op.capo,
        cc: benestare ? op.capo : op.car
      });
      let vivo = true;
      getJson(`${API.controlli}?op_id=${encodeURIComponent(op.id)}`, 'Controlli in corso').then(j => vivo && setRiprendibili(j.controlli || [])).catch(() => {}).finally(() => vivo && setLoading(false));
      return () => {
        vivo = false;
      };
    }
    let alive = true;
    getJson(`${API.controlli}?op_id=${encodeURIComponent(op.id)}`, 'Controlli in corso').then(j => {
      if (!alive) return;
      setRiprendibili(j.controlli || []);
      setFasiNote(j.fasi || []);
    }).catch(e => alive && setError(e.message)).finally(() => alive && setLoading(false));
    getJson(`${API.controllo_destinatari}?op_id=${encodeURIComponent(op.id)}`, 'Destinatari mail').then(j => alive && setDestinatari(j.destinatari || {
      to: '',
      cc: ''
    })).catch(() => alive && setDestinatari({
      to: '',
      cc: ''
    }));
    loadSerialiAperti();
    return () => {
      alive = false;
    };
  }, [op.id]);

  // Avviso se si chiude la pagina con un blocco non salvato o una mail «a fine controllo» in sospeso.
  useEffect(() => {
    const handler = e => {
      const pendingMail = controllo && controllo.mail_mode === 'fine' && controllo.da_notificare > 0 && !controllo.terminato;
      if (editorDirty(editor) || pendingMail) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [editor, controllo]);
  const addFiles = (index, rawFiles, fromClipboard) => {
    const named = fromClipboard ? nameClipboardFiles(rawFiles) : rawFiles;
    const {
      ok,
      errors
    } = validateFiles(named);
    setAttachErr(errors.join(' · '));
    if (!ok.length) return;
    setEditor(prev => {
      // Incolla senza un'anomalia aperta: va all'ultima ancora modificabile.
      let idx = index === null ? prev.attiva : index;
      if (idx < 0) idx = prev.anomalie.map(a => !a.gestita).lastIndexOf(true);
      if (idx < 0 || !prev.anomalie[idx] || prev.anomalie[idx].gestita) return prev;
      return {
        ...prev,
        attiva: idx,
        anomalie: prev.anomalie.map((a, i) => {
          if (i !== idx) return a;
          const next = [...a.files];
          ok.forEach(f => {
            if (!next.some(x => x.name === f.name && x.size === f.size && x.lastModified === f.lastModified)) next.push(f);
          });
          return {
            ...a,
            files: next
          };
        })
      };
    });
  };

  // Ctrl+V di immagini (screenshot, foto copiate) ovunque nella pagina: va all'anomalia aperta.
  useEffect(() => {
    if (!controllo) return undefined;
    const onPaste = e => {
      if (e.defaultPrevented) return; // già gestito (es. riquadro «Incolla dal report»)
      const items = Array.from(e.clipboardData && e.clipboardData.items || []);
      const files = items.filter(it => it.kind === 'file').map(it => it.getAsFile()).filter(Boolean);
      if (!files.length) return;
      // Testo copiato da Word/Outlook porta con sé anche un'immagine: in un campo di
      // testo vince il testo.
      const inText = e.target && /^(TEXTAREA|INPUT)$/.test(e.target.tagName);
      if (inText && items.some(it => it.kind === 'string' && it.type === 'text/plain')) return;
      e.preventDefault();
      addFiles(null, files, true);
    };
    document.addEventListener('paste', onPaste);
    return () => document.removeEventListener('paste', onPaste);
  }, [controllo]);
  const apriControllo = async () => {
    if (!fase.trim()) {
      setError('Indica la fase del controllo.');
      return;
    }
    setError('');
    setSaving(true);
    try {
      // OP da creare: il controllo nasce subito (bozza e promemoria funzionano), l'OP
      // vero lo crea il server al primo «Salva blocco».
      const j = await postJson(API.controllo_apri, opRef.current.daCreare ? {
        op_id: op.id,
        op_nuovo: opRef.current.daCreare,
        fase: fase.trim(),
        mail_mode: 'fine',
        destinatari_extra: extraAvvio
      } : {
        op_id: op.id,
        op_item_id: op.item_id,
        fase: fase.trim(),
        mail_mode: 'fine',
        destinatari_extra: extraAvvio
      }, 'Avvio controllo');
      setControllo(j.controllo);
      setEditor(editorDopo(coda));
      if (coda.length) setNotice(`Caricato il primo dei ${coda.length} blocchi copiati: controlla S/N e testi, poi «Salva blocco».`);
      setTimeout(() => snRef.current && snRef.current.focus(), 50);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };
  const riprendi = async c => {
    setSaving(true);
    setError('');
    try {
      const j = await getJson(urlFor(API.controllo_dettaglio, c.id), 'Ripresa controllo');
      if (j.mio === false) {
        setDaPrendere(j.controllo);
        return;
      }
      applicaRipresa(j);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };
  const prendiInCarico = async () => {
    if (!daPrendere) return;
    setSaving(true);
    setError('');
    try {
      const j = await postJson(urlFor(API.controllo_prendi, daPrendere.id), {}, 'Presa in carico');
      setDaPrendere(null);
      applicaRipresa(j);
      setNotice(prev => `Hai preso in carico il controllo di ${daPrendere.operatore}: da qui in avanti è tuo. ${prev || ''}`.trim());
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };
  const applicaRipresa = j => {
    {
      setControllo(j.controllo);
      setDestinatari(j.destinatari || null);
      setFase(j.controllo.fase);
      const bz = j.controllo.bozza;
      // Blocchi copiati ancora da caricare: tornano in coda come erano.
      const codaBozza = bz && Array.isArray(bz.coda) ? bz.coda : null;
      if (codaBozza) setCoda(codaBozza);
      if (bozzaPiena(bz)) {
        setEditor(editorDaBozza(bz, j.controllo.blocchi));
        bozzaRef.current.salvata = true;
        setBozzaAt(j.controllo.bozza_at || '');
        const allegati = (bz.anomalie || []).reduce((n, a) => n + (a.allegati || 0), 0);
        setNotice('Ripristinato il blocco in scrittura (salvato in automatico).' + (allegati ? ` Gli allegati non si salvano in bozza: ricarica ${allegati === 1 ? 'il file' : `i ${allegati} file`}.` : ''));
      } else {
        setEditor(editorDopo(codaBozza || coda));
        if (codaBozza && codaBozza.length) setNotice(`Ripresi i blocchi copiati: ${codaBozza.length === 1 ? 'ne resta 1' : `ne restano ${codaBozza.length}`} da caricare.`);
      }
    }
  };

  // Salvataggio automatico del blocco in scrittura: 1,5 s dopo l'ultima modifica.
  // Un blocco vuoto cancella la bozza; il salvataggio del blocco la svuota lato server.
  const inviaBozza = (body, keepalive) => fetch(urlFor(API.controllo_bozza, controllo.id), {
    method: 'POST',
    credentials: 'same-origin',
    keepalive: !!keepalive,
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrf()
    },
    body: JSON.stringify(body)
  });
  useEffect(() => {
    if (!controllo || !controllo.id || controllo.terminato || riepilogo || saving) return undefined;
    const dirty = editorDirty(editor) || coda.length > 0;
    if (!dirty && !bozzaRef.current.salvata) {
      bozzaRef.current.pending = null;
      return undefined;
    }
    const body = {
      bozza: dirty ? {
        ...(editorDirty(editor) ? bozzaDa(editor) : {}),
        ...(coda.length ? {
          coda
        } : {})
      } : {}
    };
    bozzaRef.current.pending = body;
    const t = setTimeout(() => {
      inviaBozza(body).then(r => r.ok ? r.json() : null).then(j => {
        if (!j) return;
        bozzaRef.current.salvata = dirty;
        if (bozzaRef.current.pending === body) bozzaRef.current.pending = null;
        setBozzaAt(dirty ? j.bozza_at || '' : '');
      }).catch(() => {});
    }, 1500);
    return () => clearTimeout(t);
  }, [editor, coda, controllo && controllo.id, riepilogo, saving]);
  // Chiudendo la pagina prima dei 1,5 s parte comunque l'ultima bozza.
  useEffect(() => {
    if (!controllo) return undefined;
    const flush = () => {
      const b = bozzaRef.current.pending;
      if (b) {
        bozzaRef.current.pending = null;
        inviaBozza(b, true).catch(() => {});
      }
    };
    window.addEventListener('pagehide', flush);
    return () => window.removeEventListener('pagehide', flush);
  }, [controllo && controllo.id]);
  const salvaImpostazioni = async patch => {
    setError('');
    try {
      const j = await postJson(urlFor(API.controllo_impostazioni, controllo.id), patch, 'Impostazioni controllo');
      setControllo(prev => ({
        ...prev,
        fase: j.controllo.fase,
        mail_mode: j.controllo.mail_mode,
        destinatari_extra: j.controllo.destinatari_extra || []
      }));
      if (patch.fase) setEditingFase(false);
    } catch (e) {
      setError(e.message);
    }
  };

  // Descrizione dell'anomalia aperta: i simboli finiscono qui se nessun altro campo ha il cursore.
  const testoRef = useRef(null);
  const updAnomalia = (i, patch) => setEditor(prev => ({
    ...prev,
    anomalie: prev.anomalie.map((a, idx) => idx === i ? {
      ...a,
      ...patch
    } : a)
  }));
  const nuovaAnomalia = () => setEditor(prev => {
    // L'ultima anomalia vuota si riusa invece di aggiungerne un'altra.
    const last = prev.anomalie[prev.anomalie.length - 1];
    if (last && !last.localId && !last.testo.trim() && !last.files.length) return {
      ...prev,
      attiva: prev.anomalie.length - 1
    };
    return {
      ...prev,
      anomalie: [...prev.anomalie, newAnomalia()],
      attiva: prev.anomalie.length
    };
  });

  // Elimina / Taglia su un'anomalia già salvata: {key, tipo: 'elimina'|'taglia', busy, err}.
  const [azAnom, setAzAnom] = useState(null);
  const puoAgireSu = a => !!(a.localId && !a.gestita && a.modificabile && window._AP_ME && a.autoreId === window._AP_ME);
  const dopoAzioneAnom = async (a, messaggio) => {
    const fresh = await getJson(urlFor(API.controllo_dettaglio, controllo.id), 'Aggiornamento controllo');
    setControllo(fresh.controllo);
    const fb = (fresh.controllo.blocchi || []).find(b => b.id === editor.bloccoId);
    setEditor(prev => {
      if (!fb) return newEditor();
      const fa = (fb.anomalie || []).find(x => x.local_id === a.localId);
      const anomalie = fa ? prev.anomalie.map(x => x.key === a.key ? {
        ...x,
        tutti: fa.tutti !== false,
        sel: fa.tutti === false ? tokensOf(fa.seriali) : []
      } : x) : prev.anomalie.filter(x => x.key !== a.key);
      return {
        ...prev,
        anomalie: anomalie.length ? anomalie : [newAnomalia()],
        attiva: -1
      };
    });
    setAzAnom(null);
    setNotice(messaggio);
  };
  const eliminaAnomalia = async a => {
    setAzAnom({
      key: a.key,
      tipo: 'elimina',
      busy: true,
      err: ''
    });
    try {
      await postJson(API.elimina, {
        local_id: a.localId
      }, 'Elimina anomalia');
      await dopoAzioneAnom(a, `Anomalia ${codiceAnomalia(a.localId)} eliminata.`);
    } catch (e) {
      setAzAnom({
        key: a.key,
        tipo: 'elimina',
        busy: false,
        err: e.message
      });
    }
  };
  const tagliaFatta = async (a, j) => {
    try {
      await dopoAzioneAnom(a, `Anomalia ${codiceAnomalia(a.localId)}: ${j.nota || 'spostata'}.`);
    } catch (e) {
      setAzAnom(null);
      setError(e.message);
    }
  };
  const rimuoviAnomalia = i => setEditor(prev => {
    const anomalie = prev.anomalie.filter((_, idx) => idx !== i);
    return {
      ...prev,
      anomalie: anomalie.length ? anomalie : [newAnomalia()],
      attiva: Math.max(0, Math.min(prev.attiva, anomalie.length - 1))
    };
  });
  const uploadFiles = async (localId, files) => {
    const form = new FormData();
    form.append('local_id', String(localId));
    files.forEach(f => form.append('files', f));
    const r = await fetch(API.allegati_upload, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCsrf()
      },
      body: form,
      credentials: 'same-origin'
    });
    const j = await parseJsonStrict(r, 'Caricamento allegati');
    if (Array.isArray(j.errors) && j.errors.length) throw new Error(j.errors.join(' · '));
    if (!r.ok) throw new Error(j.error || `Caricamento allegati: HTTP ${r.status}`);
  };
  const opNuovoAperto = !!(controllo && controllo.op_nuovo && Object.keys(controllo.op_nuovo).length);
  const salvaBlocco = async () => {
    const ed = editor;
    const anomalie = ed.anomalie.filter(a => a.localId || testoAnomalia(a) || a.files.length);
    if (!ed.voci.length) {
      setError('Inserisci almeno un seriale (premi Invio dopo averlo scritto).');
      snRef.current && snRef.current.focus();
      return false;
    }
    if (!anomalie.length) {
      setError('Descrivi almeno un’anomalia.');
      return false;
    }
    if (STATI_SUPERFICIE.length && !ed.stati.length && !ed.bloccato) {
      setError(MSG_SUP);
      return false;
    }
    if (ripetutiEditor.length && !ed.confermaRipetuti) {
      setError('');
      setConfirmRipetuti(ripetutiEditor.map(r => ({
        seriale: r.token,
        blocco: r.blocco
      })));
      return false;
    }
    const vuota = ed.anomalie.findIndex(a => (a.files.length || a.localId) && !testoAnomalia(a));
    if (vuota >= 0) {
      setError(`L’anomalia ${vuota + 1} ha allegati ma nessuna descrizione.`);
      setEditor(prev => ({
        ...prev,
        attiva: vuota
      }));
      return false;
    }
    const edTokens = tokensOf(ed.voci);
    const selDi = a => {
      const k = new Set(a.sel.map(t => t.toLowerCase()));
      return edTokens.filter(t => k.has(t.toLowerCase()));
    };
    const parzialeVuota = ed.anomalie.findIndex(a => !a.gestita && (a.localId || a.testo.trim() || a.files.length) && !a.tutti && edTokens.length > 1 && !selDi(a).length);
    if (parzialeVuota >= 0) {
      setError(`${MSG_SN_ANOM} (anomalia ${parzialeVuota + 1}).`);
      setEditor(prev => ({
        ...prev,
        attiva: parzialeVuota
      }));
      return false;
    }
    const scoperti = serialiScoperti(edTokens, ed.anomalie);
    const scopertiOk = !scoperti.length || ed.confermaScoperti === scoperti.join('|');
    if (!scopertiOk) {
      setError('');
      setConfirmScoperti(scoperti);
      return false;
    }
    setError('');
    setNotice('');
    setSaving(true);
    try {
      const opNuovo = opNuovoAperto;
      const cid = controllo.id;
      const j = await postJson(urlFor(API.controllo_blocco, cid), {
        blocco_id: ed.bloccoId,
        seriali: ed.voci,
        stato_superficie: ed.stati,
        ...(campoVisibile('dove_pezzi', {
          fase: controllo && controllo.fase
        }) ? {
          dove_pezzi: (ed.dovePezzi || '').trim()
        } : {}),
        conferma_seriali_ripetuti: !!ed.confermaRipetuti,
        conferma_seriali_scoperti: scoperti.length > 0 && scopertiOk,
        anomalie: anomalie.map(a => {
          const tutti = a.tutti || edTokens.length <= 1;
          return {
            local_id: a.localId,
            testo: testoAnomalia(a),
            tutti,
            seriali: tutti ? [] : selDi(a),
            dettaglio: dettPayload(a.dett),
            tipo_difetto_id: a.dett ? a.dett.tipoDifettoId : null
          };
        })
      }, 'Salvataggio blocco');
      // Primo blocco su un OP nuovo: il server ha creato l'OP.
      if (j.op_creato) {
        opRef.current = j.op_creato;
        if (onOpCreato) onOpCreato(j.op_creato);
      }
      const risultati = j.risultati || [];
      const uploadErrors = [];
      for (let i = 0; i < anomalie.length; i += 1) {
        const res = risultati[i];
        if (res && res.ok && res.local_id && anomalie[i].files.length) {
          try {
            await uploadFiles(res.local_id, anomalie[i].files);
          } catch (e) {
            uploadErrors.push(`anomalia ${i + 1}: ${e.message}`);
          }
        }
      }
      // Allegati dell'anomalia di origine, se scelto di copiarli.
      for (let i = 0; i < anomalie.length; i += 1) {
        const res = risultati[i];
        if (res && res.ok && res.local_id && anomalie[i].origineId && anomalie[i].copiaAllegati) {
          try {
            await postJson(API.allegati_copia, {
              da: anomalie[i].origineId,
              a: res.local_id
            }, 'Copia allegati');
          } catch (e) {
            uploadErrors.push(`anomalia ${i + 1}: ${e.message}`);
          }
        }
      }
      if (!j.success) {
        // Salvataggio parziale: le anomalie riuscite tengono il loro id, così un nuovo
        // tentativo le aggiorna invece di duplicarle.
        const byKey = {};
        anomalie.forEach((a, i) => {
          if (risultati[i] && risultati[i].ok) byKey[a.key] = risultati[i].local_id;
        });
        setEditor(prev => ({
          ...prev,
          bloccoId: j.blocco_id || prev.bloccoId,
          anomalie: prev.anomalie.map(a => byKey[a.key] ? {
            ...a,
            localId: byKey[a.key],
            files: []
          } : a)
        }));
        setControllo(j.controllo);
        setError(`Blocco salvato solo in parte: ${j.error}`);
        return false;
      }
      const fresh = await getJson(urlFor(API.controllo_dettaglio, cid), 'Aggiornamento controllo');
      setControllo(fresh.controllo);
      setDestinatari(fresh.destinatari || null);
      setEditor(ed.bloccoId === null ? editorDopo(coda) : newEditor());
      setConfirmRipetuti(null);
      setConfirmScoperti(null);
      loadSerialiAperti();
      const n = anomalie.length;
      const restanti = ed.bloccoId === null ? coda.length : 0;
      setNotice((opNuovo ? `Creato l’OP ${opRef.current.id}. ` : '') + `Salvato: ${n} anomali${n === 1 ? 'a' : 'e'} su ${labelVoci(ed.voci)}.` + (ed.daClona ? restanti ? ` Caricato il prossimo blocco copiato (${restanti === 1 ? 'ne resta 1' : `ne restano ${restanti}`}).` : ' Copiati tutti i blocchi: controlla e premi «Termina controllo».' : '') + (uploadErrors.length ? ` Attenzione, allegati non caricati (${uploadErrors.join('; ')}): riapri il blocco con «Modifica» e riallegali.` : ''));
      setTimeout(() => snRef.current && snRef.current.focus(), 50);
      return true;
    } catch (e) {
      if (e.data && e.data.code === 'seriali_ripetuti') {
        setConfirmRipetuti(e.data.seriali_ripetuti || []);
        setError('');
      } else if (e.data && e.data.code === 'seriali_scoperti') {
        setConfirmScoperti(e.data.seriali_scoperti || []);
        setError('');
      } else setError(e.message);
      return false;
    } finally {
      setSaving(false);
    }
  };

  // Stesso S/N in un altro blocco: ammesso (es. altra fase o altro stato superficie),
  // ma va confermato esplicitamente; poi si risalva con la conferma.
  const [salvaDopoConferma, setSalvaDopoConferma] = useState(false);
  const confermaESalva = () => {
    setEditor(prev => ({
      ...prev,
      confermaRipetuti: true
    }));
    setConfirmRipetuti(null);
    setSalvaDopoConferma(true);
  };
  useEffect(() => {
    if (salvaDopoConferma && editor.confermaRipetuti) {
      setSalvaDopoConferma(false);
      salvaBlocco();
    }
  }, [salvaDopoConferma, editor.confermaRipetuti]);

  // S/N del blocco senza nessuna anomalia: si salva solo dopo conferma, oppure
  // togliendoli dal blocco (non se il capocommessa ha già deciso: i seriali sono fermi).
  const [confirmScoperti, setConfirmScoperti] = useState(null);
  const [salvaDopoScoperti, setSalvaDopoScoperti] = useState(false);
  const confermaScopertiESalva = () => {
    const chiave = (confirmScoperti || []).join('|');
    setEditor(prev => ({
      ...prev,
      confermaScoperti: chiave
    }));
    setConfirmScoperti(null);
    setSalvaDopoScoperti(true);
  };
  const togliScopertiESalva = () => {
    const via = new Set((confirmScoperti || []).map(t => t.toLowerCase()));
    setEditor(prev => ({
      ...prev,
      voci: comprimiTokens(tokensOf(prev.voci).filter(t => !via.has(t.toLowerCase()))),
      confermaScoperti: ''
    }));
    setConfirmScoperti(null);
    setSalvaDopoScoperti(true);
  };
  useEffect(() => {
    if (salvaDopoScoperti) {
      setSalvaDopoScoperti(false);
      salvaBlocco();
    }
  }, [salvaDopoScoperti]);

  // «Termina controllo» passa sempre dal riepilogo: l'operatore vede tutto prima della mail.
  const apriRiepilogo = async salvaPrima => {
    if (salvaPrima && !(await salvaBlocco())) {
      setConfirmTermina(false);
      return;
    }
    if (!salvaPrima && opNuovoAperto && !(controllo && controllo.blocchi || []).length) {
      // Nessun blocco salvato su un OP nuovo: non c'è niente da comunicare né da creare.
      setConfirmTermina(false);
      setEditor(newEditor());
      setNotice('Blocco scartato: l’OP non è stato creato.');
      return;
    }
    setConfirmTermina(false);
    setSaving(true);
    setError('');
    try {
      const fresh = await getJson(urlFor(API.controllo_dettaglio, controllo.id), 'Riepilogo controllo');
      setControllo(fresh.controllo);
      setDestinatari(fresh.destinatari || null);
      setEditor(newEditor());
      setRiepilogo(true);
      window.scrollTo(0, 0);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };
  const termina = async () => {
    setConfirmTermina(false);
    setSaving(true);
    setError('');
    try {
      const j = await postJson(urlFor(API.controllo_termina, controllo.id), {}, 'Termina controllo');
      setControllo(j.controllo);
      setEditor(newEditor());
      setRiepilogo(false);
      setEsito(j.mail || {});
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };
  const proponiCopilota = async a => {
    if (!a.testo.trim()) {
      setCopilot({
        key: a.key,
        loading: false,
        sug: null,
        err: 'Scrivi prima la descrizione.'
      });
      return;
    }
    setCopilot({
      key: a.key,
      loading: true,
      sug: null,
      err: ''
    });
    try {
      const r = await fetch(API.copilota, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrf()
        },
        body: JSON.stringify({
          descrizione: a.testo
        })
      });
      const d = await parseJsonSafe(r, {});
      if (!r.ok || !d.success) setCopilot({
        key: a.key,
        loading: false,
        sug: null,
        err: d && d.error || 'Suggerimento non disponibile.'
      });else if (!d.proposta || !d.proposta.ai_disponibile) setCopilot({
        key: a.key,
        loading: false,
        sug: null,
        err: 'AI non disponibile al momento.'
      });else setCopilot({
        key: a.key,
        loading: false,
        sug: d.proposta,
        err: ''
      });
    } catch (_) {
      setCopilot({
        key: a.key,
        loading: false,
        sug: null,
        err: 'Errore di rete.'
      });
    }
  };

  /* Avvisi sui seriali digitati: formato, prefisso diverso, anomalie già aperte. */
  // Token dei blocchi già salvati (escluso quello riaperto) → numero del blocco.
  const controlloTokens = React.useMemo(() => {
    const own = new Map();
    (controllo && controllo.blocchi || []).forEach((b, i) => {
      if (b.id === editor.bloccoId) return;
      tokensOf(b.seriali).forEach(t => {
        if (!own.has(t.toLowerCase())) own.set(t.toLowerCase(), i + 1);
      });
    });
    return own;
  }, [controllo, editor.bloccoId]);
  const tokens = tokensOf(editor.voci);
  const fuoriFormato = tokens.filter(t => !SN_PATTERN.test(t));
  const primo = tokens.find(t => SN_PATTERN.test(t));
  const prefissoDiverso = primo ? tokens.filter(t => SN_PATTERN.test(t) && t.slice(0, 3).toUpperCase() !== primo.slice(0, 3).toUpperCase()) : [];
  const ripetutiEditor = tokens.filter(t => controlloTokens.has(t.toLowerCase())).map(t => ({
    token: t,
    blocco: controlloTokens.get(t.toLowerCase())
  }));
  const scopertiEditor = serialiScoperti(tokens, editor.anomalie);
  const duplicati = (() => {
    const exist = new Set((serialiAperti.seriali || []).map(x => x.toLowerCase()));
    const out = [];
    tokens.forEach(t => {
      const k = t.toLowerCase();
      if (!exist.has(k) || controlloTokens.has(k)) return;
      const info = serialiAperti.dettagli[k] || {};
      out.push({
        token: t,
        ...info
      });
    });
    return out.slice(0, 6);
  })();
  const blocchi = controllo && controllo.blocchi || [];
  const dirty = editorDirty(editor);
  const nPezzi = (() => {
    const set = new Set();
    blocchi.forEach(b => tokensOf(b.seriali).forEach(t => set.add(t.toLowerCase())));
    return set.size;
  })();
  const nAnomalie = blocchi.reduce((n, b) => n + b.anomalie.length, 0);
  if (loading) return /*#__PURE__*/React.createElement("div", {
    className: "step-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "loading-msg"
  }, "Caricamento\u2026"));
  const cambiaOp = async nuovo => {
    if (!nuovo || !onCambiaOp) return;
    if (!controllo || !controllo.id) {
      onCambiaOp(nuovo, null);
      return;
    }
    setCambioOp({
      busy: true,
      err: ''
    });
    try {
      // L'ultima bozza va sul server prima: il controllo si riapre sul nuovo OP.
      const b = bozzaRef.current.pending;
      if (b) {
        bozzaRef.current.pending = null;
        await inviaBozza(b);
      }
      await postJson(urlFor(API.controllo_cambia_op, controllo.id), {
        op_id: nuovo.id,
        op_item_id: nuovo.item_id
      }, 'Cambio OP');
      onCambiaOp(nuovo, controllo.id);
    } catch (e) {
      setCambioOp({
        busy: false,
        err: e.message
      });
    }
  };
  const puoCambiareOp = !!onCambiaOp && !saving && !riepilogo && !(controllo && controllo.terminato);
  const apriCambioOp = () => {
    if (puoCambiareOp) setCambioOp({
      busy: false,
      err: ''
    });
  };
  const titoloCambio = puoCambiareOp ? 'Clicca per cambiare OP / P/N' : '';
  const opBar = /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "op-info-bar"
  }, /*#__PURE__*/React.createElement("button", {
    className: "op-info-back",
    onClick: onBack,
    disabled: saving || dirty && !!controllo,
    title: dirty ? 'Salva o svuota il blocco in corso prima di cambiare OP' : ''
  }, "\u2190 Cambio OP"), /*#__PURE__*/React.createElement("div", {
    className: "op-info-items"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "op-info-chip",
    disabled: !puoCambiareOp,
    title: titoloCambio,
    onClick: apriCambioOp
  }, /*#__PURE__*/React.createElement("strong", null, op.id), puoCambiareOp && /*#__PURE__*/React.createElement("span", {
    className: "op-info-chip__edit"
  }, "\u270E")), daCreare && /*#__PURE__*/React.createElement("div", {
    className: "op-info-chip is-nuovo",
    title: "L\u2019OP si crea quando salvi il primo blocco: uscendo prima non resta niente"
  }, "Nuovo \xB7 si crea al primo salvataggio"), op.pn && op.pn !== '—' && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "op-info-chip",
    disabled: !puoCambiareOp,
    title: titoloCambio,
    onClick: apriCambioOp
  }, /*#__PURE__*/React.createElement("strong", null, "P/N"), " ", op.pn, puoCambiareOp && /*#__PURE__*/React.createElement("span", {
    className: "op-info-chip__edit"
  }, "\u270E")), op.capo && op.capo !== '—' && /*#__PURE__*/React.createElement("div", {
    className: "op-info-chip"
  }, /*#__PURE__*/React.createElement("strong", null, "Capocommessa"), " ", op.capo), op.car && op.car !== '—' && /*#__PURE__*/React.createElement("div", {
    className: "op-info-chip"
  }, /*#__PURE__*/React.createElement("strong", null, "CAR"), " ", op.car), /*#__PURE__*/React.createElement("div", {
    className: `op-info-chip ${isBenestare ? 'is-benestare' : ''}`
  }, isBenestare ? 'Collaudo di benestare' : 'Altro controllo'))), cambioOp && /*#__PURE__*/React.createElement(CambiaOpPanel, {
    opAttuale: op.id,
    nSalvate: nAnomalie,
    busy: cambioOp.busy,
    err: cambioOp.err,
    onScegli: cambiaOp,
    onCancel: () => setCambioOp(null)
  }));

  /* Esito di fine controllo */
  if (esito) {
    return /*#__PURE__*/React.createElement("div", {
      className: "step-card"
    }, opBar, /*#__PURE__*/React.createElement("div", {
      className: "form-body"
    }, /*#__PURE__*/React.createElement("div", {
      className: "esito-card"
    }, /*#__PURE__*/React.createElement("div", {
      className: "esito-card__icon"
    }, "\u2713"), /*#__PURE__*/React.createElement("h2", null, "Controllo terminato"), /*#__PURE__*/React.createElement("p", null, blocchi.length, " blocch", blocchi.length === 1 ? 'o' : 'i', " di seriali, ", blocchi.reduce((n, b) => n + b.anomalie.length, 0), " anomalie registrate sull\u2019OP ", op.id, "."), esito.sent && /*#__PURE__*/React.createElement("p", {
      className: "esito-ok"
    }, "Mail con il link di decisione inviata a ", /*#__PURE__*/React.createElement("strong", null, esito.to), [esito.cc, ...(esito.extra || [])].filter(Boolean).length ? /*#__PURE__*/React.createElement(React.Fragment, null, " (in copia ", [esito.cc, ...(esito.extra || [])].filter(Boolean).join(', '), ")") : null, "."), !esito.sent && esito.reason === 'nessuna_anomalia' && /*#__PURE__*/React.createElement("p", {
      className: "esito-muted"
    }, "Nessuna mail da inviare ora: le anomalie erano gi\xE0 state comunicate al capocommessa."), !esito.sent && esito.reason === 'errore' && /*#__PURE__*/React.createElement("p", {
      className: "error-msg"
    }, "Mail al capocommessa non inviata: ", esito.error, ". Il sistema riprover\xE0 in automatico.")), blocchi.length > 0 && /*#__PURE__*/React.createElement(RiepilogoControllo, {
      op: op,
      controllo: controllo,
      destinatari: destinatari
    }), /*#__PURE__*/React.createElement("div", {
      className: "esito-card no-print"
    }, /*#__PURE__*/React.createElement("div", {
      className: "action-bar"
    }, blocchi.length > 0 && /*#__PURE__*/React.createElement("button", {
      className: "btn-outline",
      onClick: () => window.print()
    }, "Stampa riepilogo"), /*#__PURE__*/React.createElement("button", {
      className: "btn-secondary",
      onClick: () => onDone('menu')
    }, "Torna al menu"), /*#__PURE__*/React.createElement("button", {
      className: "btn-outline",
      onClick: () => onDone('altro_op')
    }, "Controlla un altro OP"), /*#__PURE__*/React.createElement("button", {
      className: "btn-primary",
      onClick: () => onDone('stesso_op')
    }, "Nuovo controllo su questo OP")))));
  }

  /* Riepilogo prima di terminare: l'operatore controlla tutto e conferma */
  if (riepilogo && controllo) {
    return /*#__PURE__*/React.createElement("div", {
      className: "step-card step-card--wide"
    }, opBar, /*#__PURE__*/React.createElement("div", {
      className: "step-header"
    }, /*#__PURE__*/React.createElement("div", {
      className: "step-num"
    }, "\u2713"), /*#__PURE__*/React.createElement("h2", null, "Riepilogo del controllo")), /*#__PURE__*/React.createElement("div", {
      className: "form-body"
    }, /*#__PURE__*/React.createElement("div", {
      className: "field-hint"
    }, "Controlla blocchi, stato superficie e anomalie. Con \xABConferma e termina\xBB il controllo si chiude", controllo.da_notificare ? ' e parte la mail al capocommessa' : '', "."), blocchi.length === 0 && /*#__PURE__*/React.createElement("div", {
      className: "info-msg"
    }, "Nessun blocco salvato: il controllo si chiude senza anomalie."), /*#__PURE__*/React.createElement(RiepilogoControllo, {
      op: op,
      controllo: controllo,
      destinatari: destinatari,
      onChangeExtra: saving ? null : lista => salvaImpostazioni({
        destinatari_extra: lista
      })
    }), error && /*#__PURE__*/React.createElement("div", {
      className: "error-msg"
    }, error), /*#__PURE__*/React.createElement("div", {
      className: "riep-actions"
    }, /*#__PURE__*/React.createElement("button", {
      className: "btn-secondary",
      onClick: () => setRiepilogo(false),
      disabled: saving
    }, "\u2190 Torna al controllo"), /*#__PURE__*/React.createElement("button", {
      className: "btn-primary",
      onClick: termina,
      disabled: saving
    }, saving ? 'Chiusura…' : 'Conferma e termina'))));
  }

  /* Avvio: fase + modalità mail, oppure ripresa di un controllo lasciato aperto */
  if (!controllo) {
    return /*#__PURE__*/React.createElement("div", {
      className: "step-card"
    }, opBar, /*#__PURE__*/React.createElement("div", {
      className: "step-header"
    }, /*#__PURE__*/React.createElement("div", {
      className: "step-num"
    }, "2"), /*#__PURE__*/React.createElement("h2", null, "Nuovo controllo")), /*#__PURE__*/React.createElement("div", {
      className: "form-body"
    }, clona && coda.length > 0 && /*#__PURE__*/React.createElement(ClonaBanner, {
      clona: clona
    }, "Conferma la fase", clona.fasi && clona.fasi.length > 1 ? ` (sull’OP di origine: ${clona.fasi.join(', ')})` : '', " e premi \xABInizia controllo\xBB: i blocchi copiati si caricano uno alla volta, pronti da salvare."), daPrendere && /*#__PURE__*/React.createElement("div", {
      className: "prendi-box",
      role: "alert"
    }, /*#__PURE__*/React.createElement("div", {
      className: "field-label"
    }, "Controllo in carico a ", daPrendere.operatore), /*#__PURE__*/React.createElement("div", null, "Fase ", daPrendere.fase, " \xB7 ", daPrendere.blocchi.length, " blocch", daPrendere.blocchi.length === 1 ? 'o' : 'i', " salvat", daPrendere.blocchi.length === 1 ? 'o' : 'i', bozzaPiena(daPrendere.bozza) ? ` · ${(daPrendere.bozza.anomalie || []).length} anomalie scritte da salvare` : '', daPrendere.da_notificare ? ` · ${daPrendere.da_notificare} non ancora comunicate` : ''), /*#__PURE__*/React.createElement("div", {
      className: "field-hint"
    }, "Prendendolo in carico prosegui tu da dove \xE8 rimasto: blocco in scrittura, salvataggi, mail e \xABTermina controllo\xBB diventano tuoi. ", daPrendere.operatore, " riceve un avviso nel portale e il passaggio resta registrato."), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 8,
        flexWrap: 'wrap'
      }
    }, /*#__PURE__*/React.createElement("button", {
      className: "btn-primary",
      onClick: prendiInCarico,
      disabled: saving
    }, saving ? 'Presa in carico…' : 'Prendi in carico e prosegui'), /*#__PURE__*/React.createElement("button", {
      className: "btn-secondary",
      onClick: () => setDaPrendere(null),
      disabled: saving
    }, "Annulla"))), riprendibili.length > 0 && /*#__PURE__*/React.createElement("div", {
      className: "resume-box"
    }, /*#__PURE__*/React.createElement("div", {
      className: "field-label"
    }, riprendibili.some(c => c.mio === false) ? 'Controlli ancora aperti su questo OP' : 'Hai un controllo ancora aperto su questo OP'), riprendibili.map(c => /*#__PURE__*/React.createElement("div", {
      key: c.id,
      className: "resume-row"
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Fase ", c.fase), c.mio === false ? ` · di ${c.operatore}` : '', " \xB7 ", new Date(c.created_at).toLocaleString('it-IT', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    }), /*#__PURE__*/React.createElement("div", {
      className: "field-hint"
    }, c.blocchi.length, " blocch", c.blocchi.length === 1 ? 'o' : 'i', " salvat", c.blocchi.length === 1 ? 'o' : 'i', c.da_notificare ? ` · ${c.da_notificare} anomalie non ancora comunicate` : '')), /*#__PURE__*/React.createElement("button", {
      className: "btn-outline",
      onClick: () => riprendi(c),
      disabled: saving
    }, c.mio === false ? 'Prendi in carico' : 'Riprendi'))), /*#__PURE__*/React.createElement("div", {
      className: "field-hint"
    }, "Riprendi quello aperto invece di aprirne un altro; per un controllo nuovo scrivi la fase qui sotto. I controlli rimasti vuoti si chiudono da soli dopo 24 ore.")), /*#__PURE__*/React.createElement("div", {
      className: "field-group"
    }, /*#__PURE__*/React.createElement("label", {
      className: "field-label",
      htmlFor: "controllo-fase"
    }, "Fase del controllo ", /*#__PURE__*/React.createElement("span", {
      className: "req"
    }, "*")), /*#__PURE__*/React.createElement("input", {
      id: "controllo-fase",
      className: "text-input",
      type: "text",
      list: "fasi-op",
      maxLength: 100,
      autoFocus: true,
      placeholder: "Es. accettazione materiale, lavorazione, collaudo finale\u2026",
      value: fase,
      onChange: e => setFase(e.target.value),
      onKeyDown: e => {
        if (e.key === 'Enter') apriControllo();
      }
    }), /*#__PURE__*/React.createElement("datalist", {
      id: "fasi-op"
    }, fasiNote.map(f => /*#__PURE__*/React.createElement("option", {
      key: f,
      value: f
    }))), /*#__PURE__*/React.createElement("div", {
      className: "field-hint"
    }, "Vale per tutti i blocchi che salverai; la puoi cambiare durante il controllo.")), /*#__PURE__*/React.createElement("div", {
      className: "field-group"
    }, /*#__PURE__*/React.createElement("span", {
      className: "field-label"
    }, "Mail al capocommessa: una sola, a fine controllo"), /*#__PURE__*/React.createElement(DestinatariMail, {
      destinatari: destinatari,
      extra: extraAvvio,
      onChange: setExtraAvvio,
      disabled: saving
    }), /*#__PURE__*/React.createElement("div", {
      className: "field-hint"
    }, MAIL_FINE_HINT, " Capocommessa e CAR arrivano dall\u2019OP; con \xABAggiungi altro capocommessa\xBB o \xABAggiungi persona\xBB metti in copia altri colleghi, che ricevono la stessa mail con il link di decisione.")), error && /*#__PURE__*/React.createElement("div", {
      className: "error-msg"
    }, error), /*#__PURE__*/React.createElement("div", {
      className: "action-bar"
    }, /*#__PURE__*/React.createElement("button", {
      className: "btn-secondary",
      onClick: () => onDone('menu'),
      disabled: saving
    }, "Esci"), /*#__PURE__*/React.createElement("button", {
      className: "btn-primary",
      onClick: apriControllo,
      disabled: saving || !fase.trim()
    }, saving ? 'Avvio…' : 'Inizia controllo'))));
  }
  const editorCard = /*#__PURE__*/React.createElement("div", {
    className: `blk is-editing${editor.bloccoId ? ' is-reopened' : ''}`,
    key: "editor"
  }, /*#__PURE__*/React.createElement("div", {
    className: "blk-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "blk-num is-active"
  }, editor.bloccoId ? blocchi.findIndex(b => b.id === editor.bloccoId) + 1 : blocchi.length + 1), /*#__PURE__*/React.createElement("div", {
    className: "blk-head__main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "blk-title"
  }, editor.bloccoId ? 'Modifica blocco' : editor.daClona ? `Blocco copiato da ${clona ? clona.op.id : 'altro OP'}` : 'Nuovo blocco di seriali'), /*#__PURE__*/React.createElement("div", {
    className: "blk-meta"
  }, "Fase ", controllo.fase, bozzaAt ? ` · salvato in automatico alle ${new Date(bozzaAt).toLocaleTimeString('it-IT', {
    hour: '2-digit',
    minute: '2-digit'
  })}` : ''))), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "Seriali ", /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement(SerialInput, {
    voci: editor.voci,
    disabled: editor.bloccato,
    inputRef: snRef,
    onChange: voci => setEditor(prev => ({
      ...prev,
      voci
    }))
  }), editor.bloccato ? /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, "Il capocommessa ha gi\xE0 deciso su almeno un\u2019anomalia: i seriali non si possono pi\xF9 cambiare. Puoi aggiungere nuove anomalie.") : /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, "Un seriale, un range (", /*#__PURE__*/React.createElement("code", null, "LCN00005-LCN00010"), ") o pi\xF9 seriali separati da virgola; Invio per confermare.", tokens.length > 1 && /*#__PURE__*/React.createElement(React.Fragment, null, " Totale: ", /*#__PURE__*/React.createElement("strong", null, tokens.length, " pezzi"), ".")), (fuoriFormato.length > 0 || prefissoDiverso.length > 0 || ripetutiEditor.length > 0) && /*#__PURE__*/React.createElement("div", {
    className: "sn-warn"
  }, fuoriFormato.length > 0 && /*#__PURE__*/React.createElement("div", null, "\u26A0 Formato atteso \xABAAA00000\xBB: ", fuoriFormato.slice(0, 8).join(', '), fuoriFormato.length > 8 ? '…' : ''), prefissoDiverso.length > 0 && /*#__PURE__*/React.createElement("div", null, "\u26A0 Prefisso diverso da \xAB", primo.slice(0, 3).toUpperCase(), "\xBB: ", prefissoDiverso.slice(0, 8).join(', ')), ripetutiEditor.length > 0 && /*#__PURE__*/React.createElement("div", null, "\u26A0 Gi\xE0 in un altro blocco di questo controllo: ", ripetutiEditor.slice(0, 8).map(r => `${r.token} (blocco ${r.blocco})`).join(', '), ripetutiEditor.length > 8 ? '…' : '', ".", editor.confermaRipetuti ? ' Confermato: è voluto.' : ' Se è voluto (altra fase o altro stato superficie) puoi salvare: ti chiederò conferma. Altrimenti usa «Modifica» sul blocco esistente.')), duplicati.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "sn-dup-pop",
    role: "status",
    "aria-live": "polite"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sn-dup-pop__head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "sn-dup-pop__icon"
  }, "!"), duplicati.length === 1 ? 'Questo S/N ha già un’anomalia aperta' : 'Questi S/N hanno già anomalie aperte'), duplicati.map(d => /*#__PURE__*/React.createElement("div", {
    className: "sn-dup-card",
    key: d.token
  }, /*#__PURE__*/React.createElement("div", {
    className: "sn-dup-card__top"
  }, /*#__PURE__*/React.createElement("span", {
    className: "sn-dup-card__sn"
  }, d.token), d.avanzamento && /*#__PURE__*/React.createElement("span", {
    className: "sn-dup-card__stato"
  }, d.avanzamento)), /*#__PURE__*/React.createElement("div", {
    className: "sn-dup-card__desc"
  }, d.descrizione || /*#__PURE__*/React.createElement("em", null, "(nessuna descrizione registrata)")), d.autore && /*#__PURE__*/React.createElement("div", {
    className: "sn-dup-card__meta"
  }, "Inserita da ", /*#__PURE__*/React.createElement("strong", null, d.autore)))))), STATI_SUPERFICIE.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-label",
    id: "sup-label"
  }, "Stato superficie del blocco ", !editor.bloccato && /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement("div", {
    className: `sup-chips${!editor.bloccato && !editor.stati.length && error === MSG_SUP ? ' is-missing' : ''}`,
    role: "group",
    "aria-labelledby": "sup-label"
  }, STATI_SUPERFICIE.map(s => {
    const on = editor.stati.includes(s);
    return /*#__PURE__*/React.createElement("button", {
      key: s,
      type: "button",
      className: `sup-chip${on ? ' is-on' : ''}`,
      "aria-pressed": on,
      disabled: editor.bloccato,
      onClick: () => {
        if (error === MSG_SUP) setError('');
        setEditor(prev => ({
          ...prev,
          stati: prev.stati.includes(s) ? prev.stati.filter(x => x !== s) : [...prev.stati, s]
        }));
      }
    }, on ? '✓ ' : '', s);
  })), /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, editor.bloccato ? 'Il capocommessa ha già deciso: lo stato superficie non si può più cambiare.' : 'Vale per tutti i pezzi del blocco. Pezzi in stati diversi? Mettili in blocchi separati.')), campoVisibile('dove_pezzi', {
    fase: controllo && controllo.fase
  }) && /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label",
    htmlFor: "dove-pezzi"
  }, "Dove sono i pezzi?"), /*#__PURE__*/React.createElement("input", {
    id: "dove-pezzi",
    className: "text-input",
    maxLength: 200,
    spellCheck: true,
    lang: "it",
    value: editor.dovePezzi || '',
    placeholder: "Es. area pezzi non conformi, reparto rettifica, carrello del collaudo\u2026",
    onChange: e => {
      const v = e.target.value;
      setEditor(prev => ({
        ...prev,
        dovePezzi: v
      }));
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, "Vale per tutti i pezzi del blocco; il capocommessa lo trova nella mail e in Gestione anomalie.")), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-label"
  }, "Anomalie su questi seriali ", /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement("div", {
    className: "anom-list"
  }, editor.anomalie.map((a, i) => {
    const attiva = editor.attiva === i;
    const nAll = a.files.length + a.existing.length;
    if (!attiva) {
      return /*#__PURE__*/React.createElement("button", {
        type: "button",
        key: a.key,
        className: `anom-card is-collapsed${a.gestita ? ' is-gestita' : ''}`,
        onClick: () => setEditor(prev => ({
          ...prev,
          attiva: i
        }))
      }, /*#__PURE__*/React.createElement("span", {
        className: "anom-card__n"
      }, i + 1), /*#__PURE__*/React.createElement("span", {
        className: "anom-card__txt"
      }, a.testo.trim() || /*#__PURE__*/React.createElement("em", null, "Anomalia senza descrizione")), !a.tutti && tokens.length > 1 && /*#__PURE__*/React.createElement("span", {
        className: "pill pill-parz"
      }, "Su ", tokens.filter(t => a.sel.some(x => x.toLowerCase() === t.toLowerCase())).length, " di ", tokens.length, " S/N"), nAll > 0 && /*#__PURE__*/React.createElement("span", {
        className: "anom-card__att"
      }, "\uD83D\uDCCE ", nAll), a.origineId && /*#__PURE__*/React.createElement("span", {
        className: "pill pill-info"
      }, "da #", a.origineId, a.copiaAllegati && a.allegatiOrigine ? ` · 📎 ${a.allegatiOrigine}` : ''), a.gestita && /*#__PURE__*/React.createElement("span", {
        className: "pill pill-info"
      }, a.avanzamento || 'Gestita'), /*#__PURE__*/React.createElement("span", {
        className: "anom-card__edit"
      }, a.gestita ? 'Vedi' : 'Apri'));
    }
    return /*#__PURE__*/React.createElement("div", {
      key: a.key,
      className: `anom-card is-active${a.gestita ? ' is-gestita' : ''}`
    }, /*#__PURE__*/React.createElement("div", {
      className: "anom-card__head"
    }, /*#__PURE__*/React.createElement("span", {
      className: "anom-card__n"
    }, i + 1), /*#__PURE__*/React.createElement("span", {
      className: "anom-card__title"
    }, "Anomalia ", i + 1, a.localId ? ` · ${codiceAnomalia(a.localId)}` : ''), a.gestita && /*#__PURE__*/React.createElement("span", {
      className: "pill pill-info"
    }, "Gestita dal capocommessa: ", a.avanzamento || 'decisione presa'), a.origineId && /*#__PURE__*/React.createElement("span", {
      className: "pill pill-info"
    }, "Copiata da #", a.origineId), !a.localId && editor.anomalie.length > 1 && /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "link-btn link-btn--danger",
      onClick: () => rimuoviAnomalia(i)
    }, "Rimuovi"), puoAgireSu(a) && !azAnom && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "link-btn",
      title: "Sposta su un altro S/N dello stesso OP o di un altro OP",
      onClick: () => setAzAnom({
        key: a.key,
        tipo: 'taglia',
        busy: false,
        err: ''
      })
    }, "\u2702 Taglia"), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "link-btn link-btn--danger",
      onClick: () => setAzAnom({
        key: a.key,
        tipo: 'elimina',
        busy: false,
        err: ''
      })
    }, "Elimina")), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "link-btn",
      onClick: () => setEditor(prev => ({
        ...prev,
        attiva: -1
      }))
    }, "Comprimi")), azAnom && azAnom.key === a.key && azAnom.tipo === 'elimina' && /*#__PURE__*/React.createElement("div", {
      className: "error-msg",
      role: "alert"
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Eliminare l\u2019anomalia ", codiceAnomalia(a.localId), "?"), " Sparisce dall\u2019OP con i suoi dati; gli allegati restano recuperabili dall\u2019amministratore. Non si pu\xF2 annullare."), azAnom.err && /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 6
      }
    }, azAnom.err), /*#__PURE__*/React.createElement("div", {
      className: "anom-taglia__foot",
      style: {
        marginTop: 8
      }
    }, /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "btn-secondary",
      disabled: azAnom.busy,
      onClick: () => setAzAnom(null)
    }, "Annulla"), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "btn-primary",
      style: {
        background: 'var(--danger)'
      },
      disabled: azAnom.busy,
      onClick: () => eliminaAnomalia(a)
    }, azAnom.busy ? 'Elimino…' : 'Elimina'))), azAnom && azAnom.key === a.key && azAnom.tipo === 'taglia' && /*#__PURE__*/React.createElement(TagliaPanel, {
      anomalia: a,
      opCorrente: controllo ? controllo.op_id : '',
      onCancel: () => setAzAnom(null),
      onDone: j => tagliaFatta(a, j)
    }), campoVisibile('simboli', {
      fase: controllo && controllo.fase,
      tipo: codiceTipoAnomalia(a.dett, a.testo)
    }) && /*#__PURE__*/React.createElement(BarraSimboli, {
      disabled: a.gestita,
      fallbackRef: testoRef
    }), /*#__PURE__*/React.createElement("textarea", {
      ref: testoRef,
      className: "textarea-input",
      rows: 4,
      autoFocus: !a.gestita,
      disabled: a.gestita,
      spellCheck: true,
      lang: "it",
      "aria-label": `Descrizione anomalia ${i + 1}`,
      placeholder: "Cosa hai rilevato, dove si trova sul pezzo, misura rilevata e tolleranza\u2026",
      value: a.testo,
      onChange: e => updAnomalia(i, {
        testo: e.target.value
      })
    }), /*#__PURE__*/React.createElement(DettaglioAnomalia, {
      dett: a.dett,
      testo: a.testo,
      disabled: a.gestita,
      opId: controllo ? controllo.op_id : '',
      fase: controllo ? controllo.fase : '',
      onChange: dett => updAnomalia(i, {
        dett
      }),
      onCopiaNelTesto: righe => updAnomalia(i, {
        testo: [a.testo.trim(), ...righe].filter(Boolean).join('\n')
      })
    }), tokens.length > 1 && (() => {
      const selSet = new Set(a.sel.map(t => t.toLowerCase()));
      const nSel = tokens.filter(t => selSet.has(t.toLowerCase())).length;
      const missing = !a.tutti && !nSel && error.startsWith(MSG_SN_ANOM);
      return /*#__PURE__*/React.createElement("div", {
        className: `anom-sn${a.tutti ? '' : ' is-parziale'}${missing ? ' is-missing' : ''}`
      }, /*#__PURE__*/React.createElement("label", {
        className: `anom-sn__toggle${a.gestita ? ' is-disabled' : ''}`
      }, /*#__PURE__*/React.createElement("input", {
        type: "checkbox",
        checked: a.tutti,
        disabled: a.gestita,
        onChange: e => {
          if (error.startsWith(MSG_SN_ANOM)) setError('');
          updAnomalia(i, {
            tutti: e.target.checked
          });
        }
      }), /*#__PURE__*/React.createElement("span", null, "Presente su tutti i ", tokens.length, " seriali del blocco")), !a.tutti && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
        className: "anom-sn__chips",
        role: "group",
        "aria-label": `Seriali con l’anomalia ${i + 1}`,
        onPointerMove: e => {
          const d = snDragRef.current;
          if (!d || d.anomalia !== i) return;
          const el = document.elementFromPoint(e.clientX, e.clientY);
          const chip = el && el.closest ? el.closest('[data-sn-idx]') : null;
          if (!chip || !e.currentTarget.contains(chip)) return;
          const idx = Number(chip.getAttribute('data-sn-idx'));
          if (idx === d.last) return;
          // Anche i chip saltati con un movimento veloce: tutto il tratto fra l'ultimo e questo.
          const [da, a2] = idx > d.last ? [d.last, idx] : [idx, d.last];
          impostaSeriali(i, tokens.slice(da, a2 + 1), d.mode);
          d.last = idx;
        }
      }, tokens.map((t, ti) => {
        const on = selSet.has(t.toLowerCase());
        return /*#__PURE__*/React.createElement("button", {
          key: t,
          type: "button",
          className: `anom-sn__chip${on ? ' is-on' : ''}`,
          "aria-pressed": on,
          disabled: a.gestita,
          "data-sn-idx": ti,
          onPointerDown: e => {
            if (e.button !== 0 || a.gestita) return;
            e.preventDefault();
            // Il primo chip decide: spento → si accende tutto il tratto, acceso → si spegne.
            snDragRef.current = {
              anomalia: i,
              mode: !on,
              last: ti
            };
            if (error.startsWith(MSG_SN_ANOM)) setError('');
            impostaSeriali(i, [t], !on);
          },
          onClick: e => {
            // Mouse e tocco passano da onPointerDown; qui solo la tastiera (Invio/Spazio).
            if (e.detail !== 0) return;
            if (error.startsWith(MSG_SN_ANOM)) setError('');
            impostaSeriali(i, [t], !on);
          }
        }, /*#__PURE__*/React.createElement("span", {
          className: "anom-sn__ck",
          "aria-hidden": "true"
        }, "\u2713"), t);
      })), /*#__PURE__*/React.createElement("div", {
        className: "anom-sn__foot"
      }, /*#__PURE__*/React.createElement("span", null, nSel ? /*#__PURE__*/React.createElement(React.Fragment, null, "Selezionati ", /*#__PURE__*/React.createElement("strong", null, nSel), " di ", tokens.length) : 'Tocca i seriali su cui hai trovato questa anomalia, oppure trascina per sceglierne più di fila.'), !a.gestita && nSel < tokens.length && /*#__PURE__*/React.createElement("button", {
        type: "button",
        className: "link-btn",
        onClick: () => updAnomalia(i, {
          sel: [...tokens]
        })
      }, "Seleziona tutti"), !a.gestita && nSel > 0 && /*#__PURE__*/React.createElement("button", {
        type: "button",
        className: "link-btn",
        onClick: () => updAnomalia(i, {
          sel: []
        })
      }, "Nessuno"))));
    })(), a.origineId && a.allegatiOrigine > 0 && !a.localId && /*#__PURE__*/React.createElement("label", {
      className: "clona-att"
    }, /*#__PURE__*/React.createElement("input", {
      type: "checkbox",
      checked: !!a.copiaAllegati,
      onChange: e => updAnomalia(i, {
        copiaAllegati: e.target.checked
      })
    }), /*#__PURE__*/React.createElement("span", null, "Copia anche ", a.allegatiOrigine === 1 ? 'l’allegato' : `i ${a.allegatiOrigine} allegati`, " dell\u2019anomalia #", a.origineId)), /*#__PURE__*/React.createElement(AttachmentZone, {
      files: a.files,
      existing: a.existing,
      disabled: a.gestita,
      onAdd: files => addFiles(i, files, false),
      onRemove: fi => updAnomalia(i, {
        files: a.files.filter((_, idx) => idx !== fi)
      })
    }), !a.gestita && /*#__PURE__*/React.createElement("div", {
      className: "copilot-inline"
    }, /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "link-btn",
      onClick: () => proponiCopilota(a),
      disabled: copilot.loading
    }, copilot.loading && copilot.key === a.key ? 'Analisi…' : 'Suggerimento AI sul triage'), copilot.key === a.key && copilot.err && /*#__PURE__*/React.createElement("span", {
      className: "copilot-err"
    }, copilot.err), copilot.key === a.key && copilot.sug && /*#__PURE__*/React.createElement("div", {
      className: "copilot-sug"
    }, copilot.sug.stato_superficie && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Stato superficie:"), " ", copilot.sug.stato_superficie), copilot.sug.avanzamento && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Avanzamento:"), " ", copilot.sug.avanzamento), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Serve RDC/cliente:"), " ", copilot.sug.serve_rdc ? 'sì' : 'no'), copilot.sug.bozza_descrizione && /*#__PURE__*/React.createElement("div", {
      className: "copilot-sug__row"
    }, /*#__PURE__*/React.createElement("strong", null, "Bozza:"), " ", copilot.sug.bozza_descrizione), copilot.sug.motivazione && /*#__PURE__*/React.createElement("div", {
      className: "copilot-sug__row copilot-sug__why"
    }, /*#__PURE__*/React.createElement("em", null, copilot.sug.motivazione)))));
  })), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-outline anom-add",
    onClick: nuovaAnomalia,
    disabled: saving
  }, "+ Nuova anomalia su questi seriali"), scopertiEditor.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "sn-warn",
    role: "status"
  }, "\u26A0 ", scopertiEditor.length, " di ", tokens.length, " S/N senza nessuna anomalia: ", comprimiTokens(scopertiEditor).slice(0, 8).join(', '), comprimiTokens(scopertiEditor).length > 8 ? '…' : '', ".", ' ', "Assegnali a un\u2019anomalia", editor.bloccato ? '' : ' o toglili dal blocco', "."), attachErr && /*#__PURE__*/React.createElement("div", {
    className: "sn-warn"
  }, "\u26A0 ", attachErr)), confirmScoperti && /*#__PURE__*/React.createElement("div", {
    className: "confirm-box",
    role: "alertdialog",
    "aria-label": "Seriali senza anomalia"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, confirmScoperti.length === 1 ? 'Questo seriale del blocco non ha' : `Questi ${confirmScoperti.length} seriali del blocco non hanno`, " nessuna anomalia:"), " ", comprimiTokens(confirmScoperti).slice(0, 10).join(', '), comprimiTokens(confirmScoperti).length > 10 ? '…' : '', "."), /*#__PURE__*/React.createElement("div", null, "Ogni S/N del blocco dovrebbe avere almeno un\u2019anomalia. Hai dimenticato di selezionarli in un\u2019anomalia, oppure sono pezzi buoni da togliere dal blocco?"), /*#__PURE__*/React.createElement("div", {
    className: "action-bar"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    onClick: () => setConfirmScoperti(null)
  }, "Annulla, correggo"), !editor.bloccato && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    onClick: togliScopertiESalva,
    disabled: saving
  }, "Togli dal blocco e salva"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-primary",
    onClick: confermaScopertiESalva,
    disabled: saving
  }, "Salva comunque"))), confirmRipetuti && /*#__PURE__*/React.createElement("div", {
    className: "confirm-box",
    role: "alertdialog",
    "aria-label": "Seriali gi\xE0 in un altro blocco"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Questi seriali sono gi\xE0 in un altro blocco del controllo:"), " ", confirmRipetuti.slice(0, 10).map(r => `${r.seriale} (blocco ${r.blocco})`).join(', '), confirmRipetuti.length > 10 ? '…' : '', "."), /*#__PURE__*/React.createElement("div", null, "\xC8 voluto? Per esempio lo stesso pezzo in un\u2019altra fase o con un altro stato superficie. Se invece vuoi aggiungere anomalie a quei pezzi, annulla e usa \xABModifica\xBB sul blocco esistente."), /*#__PURE__*/React.createElement("div", {
    className: "action-bar"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    onClick: () => setConfirmRipetuti(null)
  }, "Annulla, correggo"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-primary",
    onClick: confermaESalva,
    disabled: saving
  }, "S\xEC, \xE8 voluto: salva"))), /*#__PURE__*/React.createElement("div", {
    className: "blk-actions"
  }, editor.bloccoId !== null && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    onClick: () => {
      setEditor(newEditor());
      setError('');
    },
    disabled: saving
  }, "Annulla modifiche"), editor.bloccoId === null && editor.daClona && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    onClick: () => {
      setEditor(editorDopo(coda));
      setError('');
      setNotice('');
    },
    disabled: saving
  }, "Salta questo blocco"), editor.bloccoId === null && dirty && !editor.daClona && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    onClick: () => {
      setEditor(newEditor());
      setError('');
    },
    disabled: saving
  }, "Svuota"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-primary",
    onClick: () => salvaBlocco(),
    disabled: saving
  }, saving ? 'Salvataggio…' : editor.bloccoId ? 'Salva modifiche' : 'Salva blocco')));
  return /*#__PURE__*/React.createElement("div", {
    className: "step-card step-card--wide"
  }, opBar, /*#__PURE__*/React.createElement("div", {
    className: "ctl-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ctl-head__fase"
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-label"
  }, "Fase"), editingFase ? /*#__PURE__*/React.createElement("span", {
    className: "ctl-head__edit"
  }, /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    list: "fasi-op",
    maxLength: 100,
    value: fase,
    autoFocus: true,
    onChange: e => setFase(e.target.value),
    onKeyDown: e => {
      if (e.key === 'Enter') salvaImpostazioni({
        fase: fase.trim()
      });
    }
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "fasi-op"
  }, fasiNote.map(f => /*#__PURE__*/React.createElement("option", {
    key: f,
    value: f
  }))), /*#__PURE__*/React.createElement("button", {
    className: "btn-primary btn-sm",
    onClick: () => salvaImpostazioni({
      fase: fase.trim()
    }),
    disabled: !fase.trim()
  }, "OK"), /*#__PURE__*/React.createElement("button", {
    className: "btn-secondary btn-sm",
    onClick: () => {
      setFase(controllo.fase);
      setEditingFase(false);
    }
  }, "Annulla")) : /*#__PURE__*/React.createElement("span", {
    className: "ctl-head__val"
  }, controllo.fase, " ", /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    onClick: () => setEditingFase(true)
  }, "Cambia"))), blocchi.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "ctl-stats",
    "aria-label": "Avanzamento del controllo"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ctl-stat"
  }, /*#__PURE__*/React.createElement("strong", null, blocchi.length), " blocch", blocchi.length === 1 ? 'o' : 'i'), /*#__PURE__*/React.createElement("span", {
    className: "ctl-stat"
  }, /*#__PURE__*/React.createElement("strong", null, nPezzi), " pezz", nPezzi === 1 ? 'o' : 'i'), /*#__PURE__*/React.createElement("span", {
    className: "ctl-stat"
  }, /*#__PURE__*/React.createElement("strong", null, nAnomalie), " anomali", nAnomalie === 1 ? 'a' : 'e')), /*#__PURE__*/React.createElement("div", {
    className: "ctl-head__mail"
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-label"
  }, "Mail al capocommessa"), /*#__PURE__*/React.createElement("span", {
    className: "ctl-head__val",
    title: MAIL_FINE_HINT
  }, controllo.mail_mode === 'subito' ? 'a ogni blocco' : 'a fine controllo')), /*#__PURE__*/React.createElement(DestinatariMail, {
    compact: true,
    destinatari: destinatari,
    extra: controllo.destinatari_extra || [],
    disabled: saving,
    onChange: lista => salvaImpostazioni({
      destinatari_extra: lista
    })
  })), /*#__PURE__*/React.createElement("div", {
    className: "form-body"
  }, blocchi.map((b, i) => editor.bloccoId === b.id ? /*#__PURE__*/React.createElement(React.Fragment, {
    key: b.id
  }, editorCard) : /*#__PURE__*/React.createElement(BloccoCongelato, {
    key: b.id,
    b: b,
    index: i,
    canEdit: !dirty && !saving,
    onEdit: () => {
      setEditor(editorFromBlocco(b));
      setError('');
      setNotice('');
    }
  })), editor.bloccoId === null && editorCard, coda.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "clona-coda"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-label"
  }, "Da copiare ancora (", coda.length, ")"), coda.map((b, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: "clona-coda__row"
  }, /*#__PURE__*/React.createElement("span", {
    className: "clona-coda__sn"
  }, labelVoci(b.seriali)), /*#__PURE__*/React.createElement("span", {
    className: "clona-coda__txt"
  }, b.anomalie.length, " anomali", b.anomalie.length === 1 ? 'a' : 'e', " \xB7 ", b.anomalie.map(a => a.testo).filter(Boolean).join(' · ')), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    disabled: saving || dirty && !editor.daClona || editor.bloccoId !== null,
    title: "Carica ora questo blocco (quello in scrittura torna in coda)",
    onClick: () => {
      const resto = coda.filter((_, idx) => idx !== i);
      setCoda(editor.daClona && editorCorrenteBlocco(editor) ? [editorCorrenteBlocco(editor), ...resto] : resto);
      setEditor(editorDaClona(b));
      setError('');
    }
  }, "Carica ora")))), notice && /*#__PURE__*/React.createElement("div", {
    className: "info-msg"
  }, notice), error && /*#__PURE__*/React.createElement("div", {
    className: "error-msg"
  }, error), confirmTermina && /*#__PURE__*/React.createElement("div", {
    className: "confirm-box"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Il blocco in corso non \xE8 salvato."), " Vuoi salvarlo prima di vedere il riepilogo?"), /*#__PURE__*/React.createElement("div", {
    className: "action-bar"
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn-secondary",
    onClick: () => setConfirmTermina(false)
  }, "Annulla"), /*#__PURE__*/React.createElement("button", {
    className: "btn-outline",
    onClick: () => apriRiepilogo(false)
  }, "Scarta il blocco"), /*#__PURE__*/React.createElement("button", {
    className: "btn-primary",
    onClick: () => apriRiepilogo(true)
  }, "Salva e vai al riepilogo"))), /*#__PURE__*/React.createElement("div", {
    className: "ctl-footer"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, controllo.mail_mode === 'fine' ? controllo.da_notificare ? `${controllo.da_notificare === 1 ? '1 anomalia in attesa: partirà' : `${controllo.da_notificare} anomalie in attesa: partiranno`} in un’unica mail con «Termina controllo». Se ti fermi, fra ${durata(TEMPI.promemoria)} ricevi un promemoria.` : 'La mail partirà con «Termina controllo».' : controllo.da_notificare ? `${controllo.da_notificare} anomalie in coda: la mail parte pochi minuti dopo l’ultimo salvataggio.` : 'Ogni blocco salvato viene comunicato al capocommessa.', controllo.mail_errore && /*#__PURE__*/React.createElement("div", {
    className: "copilot-err"
  }, "Ultimo invio non riuscito: ", controllo.mail_errore)), /*#__PURE__*/React.createElement("button", {
    className: "btn-primary btn-termina",
    onClick: () => dirty ? setConfirmTermina(true) : apriRiepilogo(false),
    disabled: saving || !blocchi.length && !dirty
  }, "Termina controllo\u2026"))));
};

/* ── App Root ── */
const AperturaSegnalazione = () => {
  const [step, setStep] = useState(1);
  const [selectedOp, setSelectedOp] = useState(null);
  const [formKey, setFormKey] = useState(0);
  const [clona, setClona] = useState(null);
  const [clonaStato, setClonaStato] = useState(CLONA_PARAMS ? 'loading' : '');
  useEffect(() => {
    if (!CLONA_PARAMS) return;
    getJson(`${API.clona}?op_id=${encodeURIComponent(CLONA_PARAMS.da)}&anomalie=${CLONA_PARAMS.ids.join(',')}`, 'Anomalie da copiare').then(j => {
      if (!j.blocchi || !j.blocchi.length) {
        setClonaStato('Nessuna delle anomalie scelte è stata trovata su questo OP.');
        return;
      }
      setClona(j);
      setClonaStato('');
      // Un ricaricamento non deve ricopiare tutto da capo (OP e blocchi doppi).
      window.history.replaceState(null, '', window.location.pathname);
    }).catch(e => setClonaStato(e.message || 'Errore nel caricare le anomalie da copiare'));
  }, []);
  const handleSelectOp = op => {
    setSelectedOp(op);
    setStep(2);
    setFormKey(k => k + 1);
  };
  // OP nuovo creato al primo salvataggio: da qui in poi si lavora sull'OP vero.
  const handleOpCreato = op => setSelectedOp(op);
  // Cambio OP dalla barra in alto: il controllo (se c'è) è già stato spostato dal server e si riapre.
  const handleCambiaOp = (op, controlloId) => {
    setSelectedOp(op);
    setRiprendiId(controlloId || null);
    setFormKey(k => k + 1);
    if (window.location.search) window.history.replaceState(null, '', window.location.pathname);
  };
  const handleBack = () => {
    setStep(1);
    setSelectedOp(null);
    setRiprendiId(null);
  };

  // Link del promemoria (?controllo=<id>): riapre quel controllo; per un OP nuovo
  // non ancora creato l'OP si ricostruisce dai dati salvati nel controllo.
  const [riprendiId, setRiprendiId] = useState(null);
  useEffect(() => {
    const cid = new URLSearchParams(window.location.search).get('controllo');
    if (!cid || !/^\d+$/.test(cid)) return;
    getJson(urlFor(API.controllo_dettaglio, cid), 'Ripresa controllo').then(async j => {
      const c = j.controllo || {};
      const nuovo = c.op_nuovo && Object.keys(c.op_nuovo).length ? c.op_nuovo : null;
      let opSel = null;
      if (nuovo) {
        opSel = {
          id: c.op_id,
          item_id: null,
          pn: nuovo.pn || '—',
          capo: nuovo.capocommessa || '—',
          car: nuovo.car || '—',
          stato: nuovo.collaudo_benestare ? 'Benestare' : 'Aperto',
          daCreare: nuovo
        };
      } else {
        const list = await getJson(API.db_ordini, 'Ordini').catch(() => []);
        opSel = (Array.isArray(list) ? list : []).find(o => String(o.id) === String(c.op_id)) || null;
      }
      if (!opSel) return;
      window.history.replaceState(null, '', window.location.pathname);
      setRiprendiId(Number(cid));
      setSelectedOp(opSel);
      setStep(2);
      setFormKey(k => k + 1);
    }).catch(() => {});
  }, []);

  // Preselezione OP da query string (?op_id=...): salta direttamente allo Step 2.
  useEffect(() => {
    const qs = new URLSearchParams(window.location.search);
    const preId = qs.get('op_id');
    if (!preId || qs.get('controllo')) return;
    let alive = true;
    fetch(API.db_ordini, {
      credentials: 'same-origin'
    }).then(r => r.ok ? r.json() : []).then(list => {
      if (!alive) return;
      const arr = Array.isArray(list) ? list : [];
      const found = arr.find(o => String(o.id) === String(preId));
      if (found) {
        setSelectedOp(found);
        setStep(2);
      }
    }).catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  const handleDone = action => {
    if (action === 'menu') {
      window.location.href = '/anomalie-menu';
      return;
    }
    setClona(null);
    if (action === 'altro_op') {
      handleBack();
      return;
    }
    setFormKey(k => k + 1);
  };
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "topbar"
  }, /*#__PURE__*/React.createElement("a", {
    href: "/anomalie-menu",
    className: "topbar-back"
  }, "\u2190 Menu Anomalie"), /*#__PURE__*/React.createElement("div", {
    className: "topbar-sep"
  }), /*#__PURE__*/React.createElement("div", {
    className: "topbar-title"
  }, "Controllo e segnalazione anomalie"), window._AP_CAN_MANAGE_CONFIG && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("a", {
    href: "/gestione-anomalie/configurazione",
    className: "topbar-back"
  }, "Config Liste"), /*#__PURE__*/React.createElement("div", {
    className: "topbar-sep"
  })), /*#__PURE__*/React.createElement("div", {
    className: "topbar-user"
  }, window._AP_USERNAME)), /*#__PURE__*/React.createElement("div", {
    className: "content"
  }, clonaStato === 'loading' ? /*#__PURE__*/React.createElement("div", {
    className: "step-card"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '24px 28px'
    }
  }, "Caricamento delle anomalie da copiare\u2026")) : step === 1 ? /*#__PURE__*/React.createElement(React.Fragment, null, clonaStato && /*#__PURE__*/React.createElement("div", {
    className: "error-msg",
    style: {
      marginBottom: 16
    }
  }, clonaStato), !clona && /*#__PURE__*/React.createElement(ControlliSospesi, null), /*#__PURE__*/React.createElement(Step1SelectOP, {
    onSelect: handleSelectOp,
    clona: clona
  })) : /*#__PURE__*/React.createElement(Step2Controllo, {
    key: formKey,
    op: selectedOp,
    onBack: handleBack,
    onDone: handleDone,
    clona: clona,
    onOpCreato: handleOpCreato,
    riprendiId: riprendiId,
    onCambiaOp: clona ? null : handleCambiaOp
  })));
};
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(React.createElement(AperturaSegnalazione));
