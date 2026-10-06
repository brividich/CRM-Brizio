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
  allegati_file: "/api/anomalie/allegati/file"
};
const EDIT_NAME_WHITELIST = Array.isArray(CONFIG_LISTS.autorizzati_modifica) ? CONFIG_LISTS.autorizzati_modifica : [];
const ACCESS_CONTEXT = window.ANOMALIE_ACCESS || {};
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
const ACTIVE_FILTER = ["aperte", "in_carico"].includes(INITIAL_FILTER) ? INITIAL_FILTER : "";
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

// Regola PowerApps: la prima scelta cambia in base a "Aprire RDC?"
const buildAvanzamentoOptions = isAprireRdc => {
  const dynamicFirst = isAprireRdc ? "Apertura ORE/RIPI" : "Azione di recupero";
  const dynamicAlt = isAprireRdc ? "Azione di recupero" : "Apertura ORE/RIPI";
  const sanitizedBase = BASE_AVANZAMENTO_OPTIONS.filter(opt => normalizeChoice(opt).toLowerCase() !== dynamicAlt.toLowerCase());
  return dedupeChoices([dynamicFirst, ...sanitizedBase]);
};

// Regola PowerApps: chiusura automatica in base ad avanzamento/apertura RDC.
const shouldAutoClose = (isAprireRdc, avanzamentoValue) => {
  const avanz = normalizeChoice(avanzamentoValue).toLowerCase();
  return Boolean(isAprireRdc || avanz === "accetto lo stato" || avanz === "apertura ore/ripi");
};

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

// â"€â"€â"€ Stepper stati anomalia (#4) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
// Mostra l'avanzamento dei 3 stati fissi + lo stato "Chiusa". L'indice corrente
// deriva da `avanzamento`; se `chiuso` è true tutti gli step risultano completati.
const StatoStepper = ({
  avanzamento,
  chiuso
}) => {
  const steps = BASE_AVANZAMENTO_OPTIONS;
  const norm = String(avanzamento || "").trim().toLowerCase();
  let currentIdx = steps.findIndex(s => String(s).trim().toLowerCase() === norm);
  if (chiuso) currentIdx = steps.length; // tutti completati
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 0,
      flexWrap: "wrap"
    }
  }, steps.map((label, i) => {
    const done = i < currentIdx;
    const active = i === currentIdx && !chiuso;
    const col = snColor(label);
    const dotBg = active ? col : done ? col : "#e2e8f0";
    const dotColor = active || done ? "#fff" : "#94a3b8";
    return /*#__PURE__*/React.createElement(React.Fragment, {
      key: label
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        minWidth: 70
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: 22,
        height: 22,
        borderRadius: "50%",
        background: dotBg,
        color: dotColor,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 11,
        fontWeight: 700,
        boxShadow: active ? `0 0 0 4px ${col}33` : "none"
      }
    }, done ? "✓" : i + 1), /*#__PURE__*/React.createElement("span", {
      className: "text-2xs",
      style: {
        marginTop: 4,
        textAlign: "center",
        lineHeight: 1.15,
        color: active || done ? "var(--text)" : "#94a3b8",
        fontWeight: active ? 700 : 500
      }
    }, label)), i < steps.length - 1 && /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 16,
        height: 2,
        background: i < currentIdx ? snColor(steps[i]) : "#e2e8f0",
        marginTop: -16
      }
    }));
  }), chiuso && /*#__PURE__*/React.createElement("span", {
    className: "text-2xs font-semibold",
    style: {
      marginLeft: 10,
      padding: "2px 8px",
      borderRadius: 4,
      background: "var(--success-bg)",
      color: "var(--success)",
      border: "1px solid #c6f6d5",
      fontWeight: 600
    }
  }, "CHIUSA"));
};

// â"€â"€â"€ Pannello timeline azioni OP (#2) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
// Consuma /api/anomalie/timeline (aggregata per OP). Lazy: carica al cambio OP.
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
const fmtData = iso => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit"
  });
};
const ALLEGATI_ACCEPT = ".jpg,.jpeg,.png,.gif,.bmp,.webp,.pdf,.doc,.docx,.xls,.xlsx,.xlsm,.csv";
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
function GestioneAnomalie() {
  // ── Dati ──
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

  // ── Selezione, ricerca, filtri ──
  const [selectedOpKey, setSelectedOpKey] = useState("");
  const [selectedSnId, setSelectedSnId] = useState("");
  const [searchOp, setSearchOp] = useState("");
  const [searchSn, setSearchSn] = useState("");
  const [pageFilter, setPageFilter] = useState(ACTIVE_FILTER);
  const [snFilter, setSnFilter] = useState("tutte"); // "tutte" | "da_decidere"
  const [closedCollapsed, setClosedCollapsed] = useState(true);
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
  const [avanzamento, setAvanzamento] = useState(DEFAULT_AVANZAMENTO);
  const [rdcNum, setRdcNum] = useState("");
  const [applicaBlocco, setApplicaBlocco] = useState(false);
  const avanzamentoOptions = useMemo(() => buildAvanzamentoOptions(aprireRdc), [aprireRdc]);
  const chiudereAuto = shouldAutoClose(aprireRdc, avanzamento);
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
    setAvanzamento(DEFAULT_AVANZAMENTO);
    setRdcNum("");
    setCurrentItemId(null);
    setCurrentLocalId(null);
    setAttachments([]);
    setApplicaBlocco(false);
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
    if (pageFilter) nextUrl.searchParams.set("filter", pageFilter);else nextUrl.searchParams.delete("filter");
    window.history.replaceState({}, "", nextUrl.toString());
  }, [pageFilter]);
  const apertiDi = o => Number(o?.anomalie_aperte_count ?? o?.anomalie_count ?? 0);
  const daDecidereDi = o => Number(o?.anomalie_da_decidere_count ?? 0);
  const orderMatches = (o, filtro) => {
    if (filtro === "aperte") return apertiDi(o) > 0;
    if (filtro === "in_carico") return apertiDi(o) > 0 && canUserEditOp(o?.capo, o?.car);
    return true;
  };
  const ordiniCercati = useMemo(() => {
    const q = searchOp.trim().toLowerCase();
    if (!q) return ordini;
    return ordini.filter(o => [o.id, o.pn, o.capo, o.car].some(v => String(v || "").toLowerCase().includes(q)));
  }, [ordini, searchOp]);
  const contatoriFiltro = useMemo(() => ({
    "": ordiniCercati.length,
    aperte: ordiniCercati.filter(o => orderMatches(o, "aperte")).length,
    in_carico: ordiniCercati.filter(o => orderMatches(o, "in_carico")).length
  }), [ordiniCercati]);
  const filteredOrdini = useMemo(() => {
    const list = ordiniCercati.filter(o => orderMatches(o, pageFilter));
    // Nei filtri operativi prima gli OP con decisioni in sospeso.
    if (pageFilter) return [...list].sort((a, b) => daDecidereDi(b) - daDecidereDi(a));
    return list;
  }, [ordiniCercati, pageFilter]);

  // L'OP resta selezionato anche se una ricerca lo nasconde dall'elenco.
  const op = useMemo(() => ordini.find(o => opKey(o) === selectedOpKey) || filteredOrdini[0] || {}, [ordini, filteredOrdini, selectedOpKey]);
  const canEditCurrentOp = useMemo(() => canUserEditOp(op.capo, op.car), [op.capo, op.car]);
  const nuovaAnomaliaUrl = op.id && op.id !== "—" ? `/gestione-anomalie/nuova-segnalazione?op_id=${encodeURIComponent(op.id)}` : "/gestione-anomalie/nuova-segnalazione";

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
      if (snFilter === "da_decidere" && !isDaDecidere(a)) return false;
      if (!q) return true;
      return [a.sn, a.blocco_label, a.testo, a.desc, a.fase, a.local_id && `#${a.local_id}`].some(v => String(v || "").toLowerCase().includes(q));
    });
  }, [anomalie, searchSn, snFilter]);
  const openSeriali = useMemo(() => filteredSeriali.filter(a => !a.chiudere), [filteredSeriali]);
  const closedSeriali = useMemo(() => filteredSeriali.filter(a => a.chiudere), [filteredSeriali]);
  const ordineVisibile = useMemo(() => [...openSeriali, ...closedSeriali], [openSeriali, closedSeriali]);
  const nDaDecidere = useMemo(() => anomalie.filter(isDaDecidere).length, [anomalie]);
  const nAperte = useMemo(() => anomalie.filter(a => !a.chiudere).length, [anomalie]);
  const sn = useMemo(() => anomalie.find(a => a.item_id === selectedSnId) || {}, [anomalie, selectedSnId]);
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
      const first = list.find(isDaDecidere) || list.find(a => !a.chiudere) || list[0];
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
    const opts = buildAvanzamentoOptions(!!sn.aprire_rdc);
    const av = sn.avanzamento || DEFAULT_AVANZAMENTO;
    return {
      desc: sn.desc || "",
      note: sn.note || "",
      pezziPrec: !!sn.pezzi_prec,
      aprireRdc: !!sn.aprire_rdc,
      rdcNum: sn.numero_rdc || "",
      segnalare: !!sn.segnalare,
      avanzamento: opts.some(o => o.toLowerCase() === av.toLowerCase()) ? av : opts[0] || DEFAULT_AVANZAMENTO,
      risposte: Object.fromEntries((sn.descrizioni || []).map(d => [String(d.id), d.risposta || ""]))
    };
  }, [sn.item_id, sn.desc, sn.note, sn.pezzi_prec, sn.aprire_rdc, sn.numero_rdc, sn.segnalare, sn.avanzamento, sn.descrizioni]);
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
    setAvanzamento(baseline.avanzamento);
    setApplicaBlocco(false);
    setEditDesc(false);
  }, [sn.item_id]);
  const dirty = !!sn.item_id && canEditSelected && (desc !== baseline.desc || note !== baseline.note || pezziPrec !== baseline.pezziPrec || aprireRdc !== baseline.aprireRdc || segnalare !== baseline.segnalare || aprireRdc && rdcNum !== baseline.rdcNum || normalizeChoice(avanzamento).toLowerCase() !== normalizeChoice(baseline.avanzamento).toLowerCase() || Object.keys(descrizioneAnswers).some(k => (descrizioneAnswers[k] || "") !== (baseline.risposte[k] || "")));

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
  const vaiA = delta => {
    if (posizione < 0) return;
    const target = ordineVisibile[posizione + delta];
    if (target) selectSn(target);
  };

  // Altre anomalie aperte dello stesso blocco di seriali.
  const fratelliBlocco = useMemo(() => sn && sn.blocco_id ? anomalie.filter(x => x.blocco_id === sn.blocco_id && x.item_id !== sn.item_id && !x.chiudere) : [], [anomalie, sn && sn.blocco_id, sn && sn.item_id]);

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
  const uploadFiles = async files => {
    if (!files.length) return;
    if (!canEditCurrentOp) {
      flash({
        ok: false,
        text: "Permesso negato: non puoi caricare allegati su questo OP"
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
  const lightboxIdx = immagini.findIndex(f => f.file_id === lightbox);

  // ── Salvataggio ──
  const handleSave = async () => {
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
          numero_rdc: aprireRdc ? rdcNum : "",
          segnalare,
          chiudere: chiudereAuto,
          avanzamento
        }),
        credentials: "same-origin"
      });
      const data = await readJsonOrThrow(r, "Salvataggio anomalia");
      if (!data.success) throw new Error(data.error || "risposta non valida");
      ok = true;
      const aggiornato = {
        desc,
        note,
        pezzi_prec: pezziPrec,
        aprire_rdc: aprireRdc,
        numero_rdc: aprireRdc ? rdcNum : "",
        segnalare,
        chiudere: chiudereAuto,
        avanzamento,
        descrizioni: (sn.descrizioni || []).map(d => ({
          ...d,
          risposta: descrizioneAnswers[String(d.id)] || ""
        }))
      };
      setAnomalie(prev => prev.map(a => a.item_id === currentItemId ? {
        ...a,
        ...aggiornato
      } : a));
      let testo = chiudereAuto ? "Decisione salvata · anomalia chiusa" : "Decisione salvata";
      if (applicaBlocco && fratelliBlocco.length) {
        let n = 0;
        const errori = [];
        for (const f of fratelliBlocco) {
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
                numero_rdc: aprireRdc ? rdcNum : "",
                segnalare,
                chiudere: chiudereAuto,
                avanzamento
              }),
              credentials: "same-origin"
            });
            const df = await readJsonOrThrow(rf, "Salvataggio anomalia del blocco");
            if (!df.success) throw new Error(df.error || "errore");
            n += 1;
            setAnomalie(prev => prev.map(a => a.item_id === f.item_id ? {
              ...a,
              note,
              aprire_rdc: aprireRdc,
              numero_rdc: aprireRdc ? rdcNum : "",
              segnalare,
              chiudere: chiudereAuto,
              avanzamento
            } : a));
          } catch (err) {
            errori.push(`#${f.local_id}: ${err.message}`);
          }
        }
        setApplicaBlocco(false);
        if (errori.length) {
          flash({
            ok: false,
            text: `Salvata; sul blocco ${n} aggiornate e ${errori.length} no (${errori.join("; ")})`
          }, 8000);
          testo = "";
        } else {
          testo += ` · applicata anche ad altre ${n}`;
        }
      }
      if (testo) flash({
        ok: true,
        text: data.protocollo ? `${testo} · ${data.protocollo}` : testo
      });
      loadOrdini();
    } catch (e) {
      flash({
        ok: false,
        text: "Errore: " + e.message
      }, 7000);
    }
    setSaving(false);
    return ok;
  };
  const salvaEProssima = async () => {
    // La prossima è la successiva in elenco ancora da decidere (o la successiva aperta).
    const dopo = ordineVisibile.slice(posizione + 1);
    const prossima = dopo.find(a => isDaDecidere(a) && a.item_id !== sn.item_id) || ordineVisibile.find(a => isDaDecidere(a) && a.item_id !== sn.item_id) || dopo.find(a => !a.chiudere);
    if (!(await handleSave())) return;
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
    setAvanzamento(baseline.avanzamento);
    setDescrizioneAnswers(baseline.risposte);
    setEditDesc(false);
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
    return /*#__PURE__*/React.createElement("button", {
      type: "button",
      key: a.item_id,
      className: `ga-an${selected ? " is-sel" : ""}${a.chiudere ? " is-closed" : ""}`,
      onClick: () => selectSn(a)
    }, /*#__PURE__*/React.createElement("span", {
      className: `ga-an__dot ga-an__dot--${st.variant}`
    }), /*#__PURE__*/React.createElement("span", {
      className: "ga-an__main"
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-an__txt"
    }, a.blocco_id ? a.testo || a.desc || "(nessuna descrizione)" : a.sn ? `S/N ${a.sn}` : a.testo || a.desc || "—"), /*#__PURE__*/React.createElement("span", {
      className: "ga-an__meta"
    }, /*#__PURE__*/React.createElement("span", {
      className: `ga-pill ga-pill--${st.variant}`
    }, st.text), a.aprire_rdc && /*#__PURE__*/React.createElement("span", {
      className: "ga-pill ga-pill--rdc"
    }, "RDC", a.numero_rdc ? ` ${a.numero_rdc}` : ""), a.segnalare && /*#__PURE__*/React.createElement("span", {
      className: "ga-pill ga-pill--cli"
    }, "Cliente"), !a.blocco_id && (a.testo || a.desc) && /*#__PURE__*/React.createElement("span", {
      className: "ga-an__sub"
    }, a.testo || a.desc), /*#__PURE__*/React.createElement("span", {
      className: "ga-an__id"
    }, "#", a.local_id))));
  };
  const renderGrouped = list => list.map((a, idx) => {
    const prev = idx > 0 ? list[idx - 1] : null;
    if (!a.blocco_id || prev && prev.blocco_id === a.blocco_id) return renderAnomalia(a);
    const delBlocco = list.filter(y => y.blocco_id === a.blocco_id);
    const daDec = delBlocco.filter(isDaDecidere).length;
    return /*#__PURE__*/React.createElement(React.Fragment, {
      key: `blk-${a.blocco_id}-${a.item_id}`
    }, /*#__PURE__*/React.createElement("div", {
      className: "ga-blk"
    }, /*#__PURE__*/React.createElement("div", {
      className: "ga-blk__sn"
    }, a.blocco_label || a.sn || "—"), /*#__PURE__*/React.createElement("div", {
      className: "ga-blk__meta"
    }, [a.fase ? `Fase ${a.fase}` : "", a.controllo_operatore, fmtData(a.controllo_data)].filter(Boolean).join(" · "), daDec > 0 && /*#__PURE__*/React.createElement("span", {
      className: "ga-blk__todo"
    }, daDec, " da decidere"))), renderAnomalia(a));
  });
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
  }, [["", "Tutti"], ["aperte", "Con aperte"], ["in_carico", "In carico a me"]].map(([v, l]) => /*#__PURE__*/React.createElement(Chip, {
    key: v || "all",
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
    const sel = opKey(o) === opKey(op);
    const tot = Number(o.anomalie_count || 0);
    const aperte = apertiDi(o);
    const daDec = daDecidereDi(o);
    const chiuse = Math.max(0, tot - aperte);
    return /*#__PURE__*/React.createElement("button", {
      type: "button",
      key: opKey(o),
      className: `ga-op${sel ? " is-sel" : ""}`,
      onClick: () => selectOp(o)
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-op__row"
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-op__id"
    }, o.id), String(o.stato || "").toLowerCase() === "benestare" && /*#__PURE__*/React.createElement("span", {
      className: "ga-pill ga-pill--ben"
    }, "Benestare"), daDec > 0 && /*#__PURE__*/React.createElement("span", {
      className: "ga-op__todo",
      title: "Anomalie in attesa di decisione"
    }, daDec)), /*#__PURE__*/React.createElement("span", {
      className: "ga-op__pn"
    }, "P/N ", o.pn), /*#__PURE__*/React.createElement("span", {
      className: "ga-op__people"
    }, Ico.user, o.capo, o.car && o.car !== "—" ? ` · CAR ${o.car}` : ""), tot > 0 ? /*#__PURE__*/React.createElement("span", {
      className: "ga-op__bar",
      title: `${chiuse} chiuse su ${tot}`
    }, /*#__PURE__*/React.createElement("span", {
      className: "ga-op__bar-fill",
      style: {
        width: `${Math.round(chiuse / tot * 100)}%`
      }
    }), /*#__PURE__*/React.createElement("span", {
      className: "ga-op__bar-txt"
    }, aperte, " apert", aperte === 1 ? "a" : "e", " \xB7 ", tot, " total", tot === 1 ? "e" : "i")) : /*#__PURE__*/React.createElement("span", {
      className: "ga-op__none"
    }, "Nessuna anomalia"));
  }))), /*#__PURE__*/React.createElement("section", {
    className: "ga-col ga-col--sn",
    style: {
      display: showCol("serie") ? undefined : "none"
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-col__head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-col__title"
  }, "Anomalie ", op.id ? /*#__PURE__*/React.createElement("span", {
    className: "ga-col__sub"
  }, nAperte, " apert", nAperte === 1 ? "a" : "e", " su ", anomalie.length) : null), /*#__PURE__*/React.createElement("div", {
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
  }, "Da decidere")), /*#__PURE__*/React.createElement("div", {
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
  }, snFilter === "da_decidere" && anomalie.length ? "Nessuna anomalia da decidere: tutto gestito. ✓" : searchSn ? "Nessuna anomalia corrisponde alla ricerca." : "Nessuna anomalia registrata.", canEditCurrentOp && !anomalie.length && /*#__PURE__*/React.createElement("a", {
    className: "ga-btn ga-btn--accent ga-btn--sm",
    href: nuovaAnomaliaUrl
  }, Ico.plus, "Nuova segnalazione")) : /*#__PURE__*/React.createElement(React.Fragment, null, renderGrouped(openSeriali), closedSeriali.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "ga-closed"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-closed__toggle",
    onClick: () => setClosedCollapsed(v => !v)
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      transform: closedCollapsed ? "rotate(-90deg)" : "none"
    }
  }, "\u25BE"), " Chiuse (", closedSeriali.length, ")"), !closedCollapsed && renderGrouped(closedSeriali))))), /*#__PURE__*/React.createElement("section", {
    className: "ga-col ga-col--det",
    style: {
      display: showCol("dettaglio") ? undefined : "none"
    }
  }, !sn.item_id ? /*#__PURE__*/React.createElement("div", {
    className: "ga-empty ga-empty--big"
  }, op.id ? "Seleziona un'anomalia dall'elenco." : "Seleziona un ordine di produzione.") : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "ga-det__head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-det__crumb"
  }, /*#__PURE__*/React.createElement("span", null, op.id), /*#__PURE__*/React.createElement("span", {
    className: "ga-det__sep"
  }, "\u203A"), /*#__PURE__*/React.createElement("span", {
    className: "ga-mono"
  }, "S/N ", sn.blocco_label || sn.sn || "—"), sn.fase && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
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
  }, Ico.next))), /*#__PURE__*/React.createElement("div", {
    className: "ga-det__people"
  }, /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, "Capocommessa"), " ", op.capo || "—"), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, "CAR"), " ", op.car || "—"), sn.controllo_operatore && /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, "Segnalata da"), " ", sn.controllo_operatore, sn.controllo_data ? ` il ${fmtData(sn.controllo_data)}` : ""))), /*#__PURE__*/React.createElement("div", {
    className: "ga-det__body"
  }, !canEditCurrentOp && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--warn"
  }, "Sola lettura: puoi consultare ma non decidere su questo OP."), canEditCurrentOp && isSelectedClosed && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--ok"
  }, "Anomalia chiusa: i dati restano consultabili ma non modificabili."), /*#__PURE__*/React.createElement("div", {
    className: "ga-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-card__head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ga-card__title"
  }, "Segnalazione"), sn.stato_superficie && /*#__PURE__*/React.createElement("span", {
    className: "ga-pill ga-pill--sup"
  }, sn.stato_superficie), canEditSelected && !editDesc && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-link",
    onClick: () => setEditDesc(true)
  }, "Modifica testo")), editDesc ? /*#__PURE__*/React.createElement("textarea", {
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
  }, "Risposta di ", detail.risposta_da, detail.risposta_il ? ` · ${new Date(detail.risposta_il).toLocaleString("it-IT")}` : "")))), /*#__PURE__*/React.createElement("div", {
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
  }, Ico.clip, " Allegati ", attachments.length ? `(${attachments.length})` : ""), canEditCurrentOp && /*#__PURE__*/React.createElement("span", {
    className: "ga-hint"
  }, uploadingAttachments ? "Caricamento…" : /*#__PURE__*/React.createElement(React.Fragment, null, "Trascina qui, ", /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-link",
    onClick: () => fileInputRef.current && fileInputRef.current.click()
  }, "sfoglia"), " o clicca e premi Ctrl+V"))), loadingAttachments ? /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, "Caricamento allegati\u2026") : attachments.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, "Nessun allegato.") : /*#__PURE__*/React.createElement("div", {
    className: "ga-att__grid"
  }, attachments.map(file => /*#__PURE__*/React.createElement("div", {
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
  }, "Elimina")))))))), /*#__PURE__*/React.createElement("div", {
    className: `ga-card ga-card--decision${dirty ? " is-dirty" : ""}`
  }, /*#__PURE__*/React.createElement("div", {
    className: "ga-card__head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ga-card__title"
  }, "Decisione del capocommessa")), /*#__PURE__*/React.createElement(StatoStepper, {
    avanzamento: sn.avanzamento,
    chiuso: Boolean(sn.chiudere)
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
    onChange: () => setSegnalare(!segnalare)
  }), /*#__PURE__*/React.createElement(FlagToggle, {
    label: "Pezzi precedenti al benestare",
    checked: pezziPrec,
    disabled: !canEditSelected,
    onChange: () => setPezziPrec(!pezziPrec)
  })), /*#__PURE__*/React.createElement("div", {
    className: "ga-grid2"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "Avanzamento"), /*#__PURE__*/React.createElement("select", {
    className: "ga-input",
    value: avanzamento,
    onChange: e => setAvanzamento(e.target.value),
    disabled: segnalare || !canEditSelected
  }, avanzamentoOptions.map(opt => /*#__PURE__*/React.createElement("option", {
    key: opt
  }, opt))), segnalare && /*#__PURE__*/React.createElement("div", {
    className: "ga-hint"
  }, "Con \xABSegnalare al cliente\xBB l'avanzamento resta quello attuale.")), aprireRdc && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "Numero RDC"), /*#__PURE__*/React.createElement("input", {
    className: "ga-input",
    placeholder: "Es. RDC-2026-014",
    value: rdcNum,
    onChange: e => setRdcNum(e.target.value),
    disabled: !canEditSelected
  }))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(FieldLabel, null, "Risposta / note per il reparto"), /*#__PURE__*/React.createElement("textarea", {
    className: "ga-input",
    rows: 3,
    value: note,
    onChange: e => setNote(e.target.value),
    disabled: !canEditSelected,
    placeholder: "Decisione, istruzioni di rilavorazione, riferimenti\u2026"
  })), canEditSelected && chiudereAuto && !sn.chiudere && /*#__PURE__*/React.createElement("div", {
    className: "ga-note ga-note--ok"
  }, "Con questa decisione l'anomalia verr\xE0 ", /*#__PURE__*/React.createElement("b", null, "chiusa"), " al salvataggio."), canEditSelected && fratelliBlocco.length > 0 && /*#__PURE__*/React.createElement("label", {
    className: "ga-apply"
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: applicaBlocco,
    onChange: e => setApplicaBlocco(e.target.checked)
  }), /*#__PURE__*/React.createElement("span", null, "Applica la stessa decisione anche alle altre ", /*#__PURE__*/React.createElement("b", null, fratelliBlocco.length), " anomali", fratelliBlocco.length === 1 ? "a" : "e", " aperte di questi seriali"))), op.id && op.id !== "—" && /*#__PURE__*/React.createElement(TimelineOp, {
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
    onClick: handleSave,
    disabled: saving,
    title: "Ctrl+S"
  }, saving ? "Salvataggio…" : "Salva"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "ga-btn ga-btn--accent",
    onClick: salvaEProssima,
    disabled: saving
  }, "Salva e prossima ", Ico.next))))), pendingNav && /*#__PURE__*/React.createElement("div", {
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
