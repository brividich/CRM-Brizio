/* eslint-disable */
/* SORGENTE del bundle UI Gestione Anomalie.
   Estratto dallo <script type="text/babel"> inline e transpilato offline
   con @babel/preset-react in ../gestione_anomalie.bundle.js (committato).
   Per rigenerare: vedi tools/build_anomalie_ui.ps1. NON modificare il bundle a mano. */
    const { useState, useEffect, useMemo, useRef } = React;
    const IS_ADMIN = window.IS_ADMIN;
    const ADMIN_URL = window.ADMIN_URL || "";
    const CONFIG_LISTS = window.ANOMALIE_CONFIG_LISTS || {};
    const CURRENT_USER_NAME = String(window.CURRENT_USER_NAME || "").trim();
    const CURRENT_USER_EMAIL = String(window.CURRENT_USER_EMAIL || "").trim();
    const CURRENT_USER_NAME_NORMS = Array.isArray(window.CURRENT_USER_NAME_NORMS)
      ? window.CURRENT_USER_NAME_NORMS
      : [];
    const API = window.ANOMALIE_API || {
      ordini: "/api/anomalie/ordini",
      anomalie: "/api/anomalie/anomalie",
      salva: "/api/anomalie/salva",
      allegati_list: "/api/anomalie/allegati",
      allegati_upload: "/api/anomalie/allegati/upload",
      allegati_delete: "/api/anomalie/allegati/delete",
      allegati_file: "/api/anomalie/allegati/file",
    };
    const EDIT_NAME_WHITELIST = Array.isArray(CONFIG_LISTS.autorizzati_modifica)
      ? CONFIG_LISTS.autorizzati_modifica
      : [];
    const ACCESS_CONTEXT = window.ANOMALIE_ACCESS || {};
    const ROLE_ACCESS = ACCESS_CONTEXT.role_access || {};
    const ACCESS_ORDER = { NONE: 0, READ_ALL: 1, EDIT_ASSIGNED: 2, EDIT_ALL: 3 };
    const BASE_AVANZAMENTO_OPTIONS =
      Array.isArray(CONFIG_LISTS.avanzamenti) && CONFIG_LISTS.avanzamenti.length
        ? CONFIG_LISTS.avanzamenti
        : ["Accetto lo stato", "In attesa", "Finito trattato"];
    const DEFAULT_AVANZAMENTO = BASE_AVANZAMENTO_OPTIONS[0] || "Accetto lo stato";

    const normalizeChoice = (value) => String(value || "").trim();
    const dedupeChoices = (values) => {
      const out = [];
      const seen = new Set();
      values.forEach((value) => {
        const clean = normalizeChoice(value);
        if (!clean) return;
        const key = clean.toLowerCase();
        if (seen.has(key)) return;
        seen.add(key);
        out.push(clean);
      });
      return out;
    };

    const normalizeIdentity = (value) => String(value || "").trim().replace(/\s+/g, " ").toLowerCase();
    const splitPeopleTokens = (rawValue) =>
      String(rawValue || "")
        .split(/[,\n;|]+/)
        .map((part) => String(part || "").trim().replace(/^["'\[\]()]+|["'\[\]()]+$/g, ""))
        .filter(Boolean);

    const USER_NAME_NORM = normalizeIdentity(CURRENT_USER_NAME);
    const USER_NAME_NORMS = new Set([USER_NAME_NORM, ...CURRENT_USER_NAME_NORMS].filter(Boolean));
    const EDIT_NAME_WHITELIST_SET = new Set(EDIT_NAME_WHITELIST.map((name) => normalizeIdentity(name)));
    const accessAtLeast = (level, minimum) =>
      (ACCESS_ORDER[String(level || "NONE")] || 0) >= (ACCESS_ORDER[String(minimum || "NONE")] || 0);
    const peopleMatchCurrentUser = (rawPeople) => {
      const tokens = splitPeopleTokens(rawPeople);
      if (!tokens.length || !USER_NAME_NORMS.size) return false;
      return tokens.some((token) => USER_NAME_NORMS.has(normalizeIdentity(token)));
    };
    const QUERY_PARAMS = new URLSearchParams(window.location.search || "");
    const INITIAL_FILTER = normalizeChoice(QUERY_PARAMS.get("filter")).toLowerCase();
    const ACTIVE_FILTER = ["aperte", "in_carico"].includes(INITIAL_FILTER) ? INITIAL_FILTER : "";

    const canUserEditOp = (opCapocommessa, opCar) => {
      if (IS_ADMIN) return true;
      if (ACCESS_CONTEXT.can_edit_all) return true;
      if (USER_NAME_NORM && EDIT_NAME_WHITELIST_SET.has(USER_NAME_NORM)) return true;

      const roleChecks = [
        ["CC", opCapocommessa],
        ["CAR", opCar],
      ];
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
    const buildAvanzamentoOptions = (isAprireRdc) => {
      const dynamicFirst = isAprireRdc ? "Apertura ORE/RIPI" : "Azione di recupero";
      const dynamicAlt = isAprireRdc ? "Azione di recupero" : "Apertura ORE/RIPI";
      const sanitizedBase = BASE_AVANZAMENTO_OPTIONS.filter(
        (opt) => normalizeChoice(opt).toLowerCase() !== dynamicAlt.toLowerCase()
      );
      return dedupeChoices([dynamicFirst, ...sanitizedBase]);
    };

    // Regola PowerApps: chiusura automatica in base ad avanzamento/apertura RDC.
    const shouldAutoClose = (isAprireRdc, avanzamentoValue) => {
      const avanz = normalizeChoice(avanzamentoValue).toLowerCase();
      return Boolean(
        isAprireRdc ||
        avanz === "accetto lo stato" ||
        avanz === "apertura ore/ripi"
      );
    };

    // --- CSRF helper ---
    const getCsrfToken = () =>
      (document.cookie.split(';').find(c => c.trim().startsWith('csrftoken=')) || '').split('=')[1] || '';

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

    const formatBytes = (value) => {
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

    const fileExt = (name) => {
      const idx = String(name || "").lastIndexOf(".");
      return idx >= 0 ? String(name).slice(idx).toLowerCase() : "";
    };

    //â"€â"€â"€ Utility: colore per avanzamento â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    const snColor = (avanz) => {
      if (avanz === "Accetto lo stato") return "#10b981";
      if (avanz === "In attesa")        return "#f59e0b";
      if (avanz === "Finito trattato")  return "#6366f1";
      return "#94a3b8";
    };

    // â"€â"€â"€ Componenti UI riutilizzabili â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    const StatusBadge = ({ text, variant }) => {
      const colors = {
        benestare: { bg: "#dcfce7", text: "#166534", border: "#86efac" },
        aperto:    { bg: "#dbeafe", text: "#1e40af", border: "#93c5fd" },
        attesa:    { bg: "#fef3c7", text: "#92400e", border: "#fcd34d" },
        accettato: { bg: "#d1fae5", text: "#065f46", border: "#6ee7b7" },
        chiuso:    { bg: "#f3f4f6", text: "#374151", border: "#d1d5db" },
      };
      const c = colors[variant] || colors.aperto;
      return (
        <span className="text-xs font-semibold" style={{
          display: "inline-block", padding: "2px 10px", borderRadius: "99px",
          fontWeight: 600, letterSpacing: "0.03em",
          background: c.bg, color: c.text, border: `1px solid ${c.border}`,
          textTransform: "uppercase", whiteSpace: "nowrap",
        }}>{text}</span>
      );
    };

    const IconBtn = ({ children, onClick, title, accent, disabled }) => (
      <button className="text-sm font-medium" onClick={onClick} title={title} disabled={disabled} style={{
        background: accent ? "var(--accent)" : "transparent",
        border: accent ? "none" : "1px solid var(--border)",
        borderRadius: 8, padding: accent ? "6px 14px" : "6px 8px", cursor: disabled ? "not-allowed" : "pointer",
        display: "inline-flex", alignItems: "center", gap: 6,
        color: accent ? "#fff" : "var(--text-mid)", fontWeight: 500,
        transition: "all 0.15s ease", opacity: disabled ? 0.6 : 1,
      }}>{children}</button>
    );

    const FieldLabel = ({ children, required }) => (
      <label className="text-xs font-semibold" style={{
        display: "block", fontWeight: 600, color: "var(--text-light)",
        textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6,
      }}>
        {children}
        {required && <span style={{ color: "#ef4444", marginLeft: 2 }}>*</span>}
      </label>
    );

    // â"€â"€â"€ Stepper stati anomalia (#4) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    // Mostra l'avanzamento dei 3 stati fissi + lo stato "Chiusa". L'indice corrente
    // deriva da `avanzamento`; se `chiuso` è true tutti gli step risultano completati.
    const StatoStepper = ({ avanzamento, chiuso }) => {
      const steps = BASE_AVANZAMENTO_OPTIONS;
      const norm = String(avanzamento || "").trim().toLowerCase();
      let currentIdx = steps.findIndex((s) => String(s).trim().toLowerCase() === norm);
      if (chiuso) currentIdx = steps.length;  // tutti completati
      return (
        <div style={{ display: "flex", alignItems: "center", gap: 0, flexWrap: "wrap" }}>
          {steps.map((label, i) => {
            const done = i < currentIdx;
            const active = i === currentIdx && !chiuso;
            const col = snColor(label);
            const dotBg = active ? col : (done ? col : "#e2e8f0");
            const dotColor = (active || done) ? "#fff" : "#94a3b8";
            return (
              <React.Fragment key={label}>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", minWidth: 70 }}>
                  <div style={{
                    width: 22, height: 22, borderRadius: "50%", background: dotBg, color: dotColor,
                    display: "inline-flex", alignItems: "center", justifyContent: "center",
                    fontSize: 11, fontWeight: 700,
                    boxShadow: active ? `0 0 0 4px ${col}33` : "none",
                  }}>{done ? "✓" : i + 1}</div>
                  <span className="text-2xs" style={{
                    marginTop: 4, textAlign: "center", lineHeight: 1.15,
                    color: (active || done) ? "var(--text)" : "#94a3b8",
                    fontWeight: active ? 700 : 500,
                  }}>{label}</span>
                </div>
                {i < steps.length - 1 && (
                  <div style={{ flex: 1, minWidth: 16, height: 2, background: i < currentIdx ? snColor(steps[i]) : "#e2e8f0", marginTop: -16 }} />
                )}
              </React.Fragment>
            );
          })}
          {chiuso && (
            <span className="text-2xs font-semibold" style={{
              marginLeft: 10, padding: "2px 8px", borderRadius: 4,
              background: "var(--success-bg)", color: "var(--success)",
              border: "1px solid #c6f6d5", fontWeight: 600,
            }}>CHIUSA</span>
          )}
        </div>
      );
    };

    // â"€â"€â"€ Pannello timeline azioni OP (#2) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    // Consuma /api/anomalie/timeline (aggregata per OP). Lazy: carica al cambio OP.
    const TimelineOp = ({ opId, opItemId }) => {
      const [items, setItems] = useState([]);
      const [loading, setLoading] = useState(false);
      const [open, setOpen] = useState(false);

      useEffect(() => {
        if (!open) return;
        if (!opId && !opItemId) { setItems([]); return; }
        if (!API.timeline) return;
        setLoading(true);
        const qs = new URLSearchParams();
        if (opId) qs.set("op_id", opId);
        if (opItemId) qs.set("op_item_id", opItemId);
        fetch(`${API.timeline}?${qs.toString()}`, { credentials: "same-origin" })
          .then((r) => r.json())
          .then((d) => { setItems(Array.isArray(d.items) ? d.items : []); setLoading(false); })
          .catch(() => { setItems([]); setLoading(false); });
      }, [open, opId, opItemId]);

      const sourceColor = (s) => s === "mail_action" ? "#6366f1" : (s === "system" ? "#64748b" : "#0ea5e9");

      return (
        <div style={{ marginTop: 20, border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden" }}>
          <button type="button" onClick={() => setOpen((v) => !v)} style={{
            display: "flex", alignItems: "center", gap: 8, width: "100%",
            padding: "10px 14px", background: "var(--bg)", border: "none",
            cursor: "pointer", color: "var(--text-mid)",
          }}>
            <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24"
                 style={{ transform: open ? "none" : "rotate(-90deg)", transition: "transform .15s" }}>
              <path d="M6 9l6 6 6-6"/>
            </svg>
            <span className="text-sm font-semibold" style={{ fontWeight: 600 }}>
              Cronologia azioni{items.length ? ` (${items.length})` : ""}
            </span>
          </button>
          {open && (
            <div style={{ padding: "8px 14px 12px", maxHeight: 320, overflowY: "auto" }}>
              {loading ? (
                <div className="text-sm" style={{ padding: 12, textAlign: "center", color: "#94a3b8" }}>Caricamento…</div>
              ) : items.length === 0 ? (
                <div className="text-sm" style={{ padding: 12, textAlign: "center", color: "#94a3b8" }}>Nessuna azione registrata per questo OP.</div>
              ) : (
                items.map((it) => (
                  <div key={it.id} style={{ display: "flex", gap: 10, padding: "8px 0", borderBottom: "1px solid #f1f5f9" }}>
                    <div style={{ width: 8, height: 8, borderRadius: "50%", marginTop: 6, flexShrink: 0, background: sourceColor(it.source) }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                        <span className="text-sm font-semibold" style={{ fontWeight: 600, color: "var(--text)" }}>{it.action_label}</span>
                        {it.previous_status && it.new_status && it.previous_status !== it.new_status && (
                          <span className="text-2xs" style={{ color: "var(--text-mid)" }}>{it.previous_status} → {it.new_status}</span>
                        )}
                        <span className="text-2xs" style={{ marginLeft: "auto", color: "#94a3b8" }}>{it.created_at}</span>
                      </div>
                      <div className="text-2xs" style={{ color: "#94a3b8", marginTop: 2 }}>
                        {it.user}{it.source_label ? ` · ${it.source_label}` : ""}{it.anomalia_id ? ` · #${it.anomalia_id}` : ""}
                      </div>
                      {it.note && <div className="text-2xs" style={{ color: "var(--text-mid)", marginTop: 2 }}>{it.note}</div>}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      );
    };

    const Toggle = ({ label, checked, onChange, disabled = false }) => (
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div onClick={disabled ? undefined : onChange} style={{
          width: 40, height: 22, borderRadius: 11, cursor: disabled ? "not-allowed" : "pointer",
          background: checked ? "var(--accent)" : "var(--border)", transition: "background 0.2s",
          position: "relative", flexShrink: 0,
          opacity: disabled ? 0.7 : 1,
        }}>
          <div style={{
            width: 18, height: 18, borderRadius: "50%", background: "#fff",
            position: "absolute", top: 2, left: checked ? 20 : 2,
            transition: "left 0.2s", boxShadow: "0 1px 3px rgba(0,0,0,0.15)",
          }} />
        </div>
        <span className="text-base font-medium" style={{ color: "var(--text-mid)", fontWeight: 500 }}>{label}</span>
      </div>
    );

    // â"€â"€â"€ Componente principale â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    function GestioneAnomalie() {
      // â"€â"€ Dati dalla API â"€â"€
      const [ordini,        setOrdini]        = useState([]);
      const [anomalie,      setAnomalie]       = useState([]);   // record anomalie per l'OP selezionato

      // â"€â"€ Stato caricamento / salvataggio â"€â"€
      const [loadingOrdini, setLoadingOrdini]  = useState(true);
      const [loadingAnom,   setLoadingAnom]    = useState(false);
      const [saving,        setSaving]         = useState(false);
      const [saveMsg,       setSaveMsg]        = useState(null);  // { ok, text }
      const [currentItemId, setCurrentItemId]  = useState(null);
      const [currentLocalId, setCurrentLocalId] = useState(null);
      const [attachments, setAttachments] = useState([]);
      const [loadingAttachments, setLoadingAttachments] = useState(false);
      const [uploadingAttachments, setUploadingAttachments] = useState(false);
      const [selectedAttachmentId, setSelectedAttachmentId] = useState(null);
      const fileInputRef = useRef(null);

      // â"€â"€ Selezione e ricerca â"€â"€
      const [selectedOp,  setSelectedOp]  = useState(0);
      const [selectedSn,  setSelectedSn]  = useState(0);
      const [searchOp,    setSearchOp]    = useState("");
      const [searchSn,    setSearchSn]    = useState("");
      const [pageFilter, setPageFilter] = useState(ACTIVE_FILTER);
      const [closedCollapsed, setClosedCollapsed] = useState(true);

      // ── Mobile / tablet navigation ──
      const [isMobile, setIsMobile] = useState(window.innerWidth < 768);
      const [isTablet, setIsTablet] = useState(window.innerWidth >= 768 && window.innerWidth < 1100);
      const [mobilePanel, setMobilePanel] = useState("ordini"); // "ordini" | "serie" | "dettaglio"
      useEffect(() => {
        const onResize = () => {
          setIsMobile(window.innerWidth < 768);
          setIsTablet(window.innerWidth >= 768 && window.innerWidth < 1100);
        };
        window.addEventListener("resize", onResize);
        return () => window.removeEventListener("resize", onResize);
      }, []);

      // â"€â"€ Campi form â"€â"€
      const [desc,        setDesc]        = useState("");
      const [note,        setNote]        = useState("");
      const [pezziPrec,   setPezziPrec]   = useState(false);
      const [aprireRdc,   setAprireRdc]   = useState(false);
      const [segnalare,   setSegnalare]   = useState(false);
      const [avanzamento, setAvanzamento] = useState(DEFAULT_AVANZAMENTO);
      const [rdcNum,      setRdcNum]      = useState("");
      const filterButtons = [
        { value: "", label: "Tutte" },
        { value: "aperte", label: "Aperte" },
        { value: "in_carico", label: "In carico" },
      ];

      const avanzamentoOptions = useMemo(() => buildAvanzamentoOptions(aprireRdc), [aprireRdc]);
      const chiudereAuto = shouldAutoClose(aprireRdc, avanzamento);

      const clearForm = () => {
        setDesc(""); setNote("");
        setPezziPrec(false); setAprireRdc(false);
        setSegnalare(false);
        setAvanzamento(DEFAULT_AVANZAMENTO); setRdcNum("");
        setCurrentItemId(null);
        setCurrentLocalId(null);
        setAttachments([]);
        setSelectedAttachmentId(null);
      };

      useEffect(() => {
        const current = normalizeChoice(avanzamento).toLowerCase();
        const exists = avanzamentoOptions.some((opt) => normalizeChoice(opt).toLowerCase() === current);
        if (!exists) {
          setAvanzamento(avanzamentoOptions[0] || DEFAULT_AVANZAMENTO);
        }
      }, [avanzamento, avanzamentoOptions]);

      // Carica ordini dal DB locale.
      const loadOrdini = () => {
        setLoadingOrdini(true);
        fetch(API.ordini, { credentials: "same-origin" })
          .then(r => readJsonOrThrow(r, "Caricamento ordini"))
          .then(data => {
            setOrdini(Array.isArray(data) ? data : []);
            setLoadingOrdini(false);
          })
          .catch(e => {
            console.error("Errore caricamento ordini:", e);
            setLoadingOrdini(false);
          });
      };

      useEffect(() => { loadOrdini(); }, []);

      useEffect(() => {
        const nextUrl = new URL(window.location.href);
        if (pageFilter) {
          nextUrl.searchParams.set("filter", pageFilter);
        } else {
          nextUrl.searchParams.delete("filter");
        }
        window.history.replaceState({}, "", nextUrl.toString());
      }, [pageFilter]);

      const orderMatchesPageFilter = (order) => {
        const openCount = Number(order?.anomalie_aperte_count ?? order?.anomalie_count ?? 0);
        if (pageFilter === "aperte") return openCount > 0;
        if (pageFilter === "in_carico") return openCount > 0 && canUserEditOp(order?.capo, order?.car);
        return true;
      };

      // NB: nel filtro "aperte"/"in_carico" le anomalie chiuse NON vengono piu'
      // escluse: restano consultabili in una sezione collassata "Chiuse (N)" in
      // fondo alla lista (vedi rendering). Qui si filtra solo per la ricerca S/N.
      const anomalyMatchesPageFilter = () => true;

      const filteredOrdini = useMemo(() => {
        const search = searchOp.toLowerCase();
        return ordini.filter((o) => {
          const matchesSearch =
            (o.id || "").toLowerCase().includes(search) ||
            (o.pn || "").toLowerCase().includes(search) ||
            (o.capo || "").toLowerCase().includes(search);
          return matchesSearch && orderMatchesPageFilter(o);
        });
      }, [ordini, searchOp, pageFilter]);

      const op = filteredOrdini[selectedOp] || {};
      const canEditCurrentOp = useMemo(() => canUserEditOp(op.capo, op.car), [op.capo, op.car]);

      // URL "Nuova anomalia" → pagina Apertura Segnalazione, preselezionando l'OP corrente se presente.
      const nuovaAnomaliaUrl = (op.id && op.id !== '—')
        ? `/gestione-anomalie/nuova-segnalazione?op_id=${encodeURIComponent(op.id)}`
        : "/gestione-anomalie/nuova-segnalazione";

      const filteredSeriali = useMemo(() => {
        const search = searchSn.toLowerCase();
        return anomalie.filter((a) => {
          const matchesSearch = (a.sn || "").toLowerCase().includes(search);
          return matchesSearch && anomalyMatchesPageFilter(a);
        });
      }, [anomalie, searchSn, pageFilter]);

      // Separa le anomalie in aperte e chiuse conservando l'indice originale in
      // filteredSeriali (selectedSn indicizza quell'array): le chiuse vanno in
      // fondo, in una sezione collassata e in sola lettura.
      const openSeriali = useMemo(
        () => filteredSeriali.map((a, i) => ({ a, i })).filter((x) => !Boolean(x.a.chiudere)),
        [filteredSeriali]
      );
      const closedSeriali = useMemo(
        () => filteredSeriali.map((a, i) => ({ a, i })).filter((x) => Boolean(x.a.chiudere)),
        [filteredSeriali]
      );

      const sn = filteredSeriali[selectedSn] || {};
      // Anomalia selezionata chiusa => form in sola lettura (congelata):
      // consultabile ma non modificabile, anche se l'utente avrebbe i permessi sull'OP.
      const isSelectedClosed = Boolean(sn.chiudere);
      // Editabilita' effettiva dei campi del dettaglio: serve il permesso sull'OP
      // E che l'anomalia selezionata non sia chiusa.
      const canEditSelected = canEditCurrentOp && !isSelectedClosed;

      useEffect(() => {
        if (selectedOp < filteredOrdini.length) return;
        setSelectedOp(0);
      }, [filteredOrdini.length, selectedOp]);

      useEffect(() => {
        if (selectedSn < filteredSeriali.length) return;
        setSelectedSn(0);
      }, [filteredSeriali.length, selectedSn]);

      // Carica anomalie dal DB locale quando cambia OP.
      useEffect(() => {
        setSelectedSn(0);
        clearForm();
        if (!op || !op.item_id) {
          setAnomalie([]);
          return;
        }
        setLoadingAnom(true);
        fetch(`${API.anomalie}?op_item_id=${encodeURIComponent(op.item_id)}&op_id=${encodeURIComponent(op.id || "")}`, { credentials: "same-origin" })
          .then(r => readJsonOrThrow(r, "Caricamento anomalie"))
          .then(data => {
            setAnomalie(Array.isArray(data) ? data : []);
            setLoadingAnom(false);
          })
          .catch(e => {
            console.error("Errore caricamento anomalie:", e);
            setLoadingAnom(false);
          });
      }, [op.item_id]);

      // â"€â"€ Popola form quando cambia S/N â"€â"€
      useEffect(() => {
        const a = filteredSeriali[selectedSn];
        if (a) {
          setCurrentItemId(a.item_id || null);
          setCurrentLocalId(a.local_id || null);
          setDesc(a.desc || "");
          setNote(a.note || "");
          setPezziPrec(!!a.pezzi_prec);
          setAprireRdc(!!a.aprire_rdc);
          setRdcNum(a.numero_rdc || "");
          setSegnalare(!!a.segnalare);
          setAvanzamento(a.avanzamento || DEFAULT_AVANZAMENTO);
        } else {
          clearForm();
        }
      }, [selectedSn, filteredSeriali]);

      const loadAttachments = async (localId) => {
        if (!localId) {
          setAttachments([]);
          return;
        }
        setLoadingAttachments(true);
        try {
          const r = await fetch(`${API.allegati_list}?local_id=${encodeURIComponent(localId)}`, {
            credentials: "same-origin",
          });
          const d = await readJsonOrThrow(r, "Allegati");
          if (!r.ok || !d.success) throw new Error(d.error || "Errore caricamento allegati");
          setAttachments(Array.isArray(d.attachments) ? d.attachments : []);
        } catch (e) {
          setAttachments([]);
          setSaveMsg({ ok: false, text: "Errore allegati: " + e.message });
          setTimeout(() => setSaveMsg(null), 4000);
        }
        setLoadingAttachments(false);
      };

      useEffect(() => {
        if (!currentLocalId) {
          setAttachments([]);
          return;
        }
        loadAttachments(currentLocalId);
      }, [currentLocalId]);

      const getStatoBadge = (s) => {
        if (!s || !s.avanzamento) return { text: "Aperto", variant: "aperto" };
        if (s.avanzamento === "Accetto lo stato") return { text: "Accettato", variant: "accettato" };
        if (s.avanzamento === "In attesa")        return { text: "In Attesa", variant: "attesa" };
        return { text: s.avanzamento, variant: "aperto" };
      };
      const statoBadge = getStatoBadge(sn);

      // â"€â"€ Salva anomalia â"€â"€
      const handleSave = async (notifyUpdate) => {
        if (!op.id || op.id === '\u2014') {
          setSaveMsg({ ok: false, text: "Seleziona un ordine prima di salvare" });
          setTimeout(() => setSaveMsg(null), 3000);
          return;
        }
        if (!canEditCurrentOp) {
          setSaveMsg({ ok: false, text: "Permesso negato: non puoi modificare questo OP" });
          setTimeout(() => setSaveMsg(null), 3000);
          return;
        }
        if (isSelectedClosed) {
          setSaveMsg({ ok: false, text: "Anomalia chiusa: in sola lettura, non modificabile" });
          setTimeout(() => setSaveMsg(null), 3000);
          return;
        }
        setSaving(true);
        setSaveMsg(null);
        try {
          const body = {
            item_id:    currentItemId,
            op_id:      op.id,
            sn:         sn.sn || "",
            desc,
            note,
            pezzi_prec: pezziPrec,
            aprire_rdc: aprireRdc,
            numero_rdc: rdcNum,
            segnalare,
            chiudere: chiudereAuto,
            avanzamento,
            notify_update: !!notifyUpdate,
          };
          const r = await fetch(API.salva, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
            body: JSON.stringify(body),
            credentials: "same-origin",
          });
          const data = await readJsonOrThrow(r, "Salvataggio anomalia");
          if (data.success) {
            const newItemId = data.item_id || currentItemId;
            const newLocalId = data.local_id || currentLocalId;
            setCurrentItemId(newItemId);
            setCurrentLocalId(newLocalId || null);
            setSaveMsg({ ok: true, text: "Salvato" });
            if (newLocalId) {
              loadAttachments(newLocalId);
            }
            // Optimistic update: aggiorna lo stato locale senza re-fetch
            const updatedRecord = {
              item_id:    newItemId,
              local_id:   newLocalId || null,
              op_id:      op.id,
              sn:         sn.sn || "",
              desc, note,
              pezzi_prec: pezziPrec,
              aprire_rdc: aprireRdc,
              numero_rdc: rdcNum,
              segnalare,
              chiudere: chiudereAuto,
              avanzamento,
            };
            setAnomalie(prev => {
              const idx = prev.findIndex(a => a.item_id === currentItemId);
              if (idx >= 0) {
                const next = [...prev];
                next[idx] = updatedRecord;
                return next;
              }
              return [...prev, updatedRecord];
            });
          } else {
            setSaveMsg({ ok: false, text: "Errore: " + (data.error || "risposta non valida") });
          }
        } catch (e) {
          setSaveMsg({ ok: false, text: "Errore di rete: " + e.message });
        }
        setSaving(false);
        setTimeout(() => setSaveMsg(null), 5000);
      };

      const openAttachmentPicker = () => {
        if (!canEditCurrentOp) {
          setSaveMsg({ ok: false, text: "Permesso negato: non puoi caricare allegati su questo OP" });
          setTimeout(() => setSaveMsg(null), 3000);
          return;
        }
        if (!currentLocalId) {
          setSaveMsg({ ok: false, text: "Salva prima l'anomalia, poi puoi caricare allegati." });
          setTimeout(() => setSaveMsg(null), 3000);
          return;
        }
        if (fileInputRef.current) fileInputRef.current.click();
      };

      const handleAttachmentInput = async (event) => {
        const files = Array.from((event.target && event.target.files) || []);
        event.target.value = "";
        if (!files.length) return;
        if (!currentLocalId) {
          setSaveMsg({ ok: false, text: "Salva prima l'anomalia, poi puoi caricare allegati." });
          setTimeout(() => setSaveMsg(null), 3000);
          return;
        }
        setUploadingAttachments(true);
        try {
          const form = new FormData();
          form.append("local_id", String(currentLocalId));
          files.forEach((f) => form.append("files", f));
          const r = await fetch(API.allegati_upload, {
            method: "POST",
            headers: { "X-CSRFToken": getCsrfToken() },
            body: form,
            credentials: "same-origin",
          });
          const d = await readJsonOrThrow(r, "Upload allegati");
          if (!r.ok) throw new Error(d.error || "Upload non riuscito");
          setAttachments(Array.isArray(d.attachments) ? d.attachments : []);
          if (Array.isArray(d.errors) && d.errors.length) {
            setSaveMsg({ ok: false, text: "Upload parziale: " + d.errors.join(" | ") });
          } else {
            setSaveMsg({ ok: true, text: "Allegati caricati correttamente." });
          }
        } catch (e) {
          setSaveMsg({ ok: false, text: "Errore upload allegati: " + e.message });
        }
        setUploadingAttachments(false);
        setTimeout(() => setSaveMsg(null), 5000);
      };

      const handleDeleteAttachment = async (fileId) => {
        if (!currentLocalId || !fileId) return;
        try {
          const r = await fetch(API.allegati_delete, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": getCsrfToken(),
            },
            body: JSON.stringify({ local_id: currentLocalId, file_id: fileId }),
            credentials: "same-origin",
          });
          const d = await readJsonOrThrow(r, "Elimina allegato");
          if (!r.ok || !d.success) throw new Error(d.error || "Eliminazione non riuscita");
          setAttachments(Array.isArray(d.attachments) ? d.attachments : []);
        } catch (e) {
          setSaveMsg({ ok: false, text: "Errore eliminazione allegato: " + e.message });
          setTimeout(() => setSaveMsg(null), 4000);
        }
      };

      const openAttachment = (fileId, forceDownload = false) => {
        if (!currentLocalId || !fileId) return;
        const q = `local_id=${encodeURIComponent(currentLocalId)}&file_id=${encodeURIComponent(fileId)}${forceDownload ? "&download=1" : ""}`;
        window.open(`${API.allegati_file}?${q}`, "_blank", "noopener");
      };

      const getAttachmentUrl = (fileId, forceDownload = false) =>
        `${API.allegati_file}?local_id=${encodeURIComponent(currentLocalId)}&file_id=${encodeURIComponent(fileId)}${forceDownload ? "&download=1" : ""}`;

      useEffect(() => {
        if (!attachments.length) {
          setSelectedAttachmentId(null);
          return;
        }
        const exists = attachments.some((f) => f.file_id === selectedAttachmentId);
        if (!exists) {
          const preferred = attachments.find((f) => f.is_image) || attachments[0];
          setSelectedAttachmentId(preferred.file_id);
        }
      }, [attachments, selectedAttachmentId]);

      const selectedAttachment = useMemo(
        () => attachments.find((f) => f.file_id === selectedAttachmentId) || null,
        [attachments, selectedAttachmentId]
      );

      const handleOpenReport = (format) => {
        const params = new URLSearchParams();
        if (op.item_id) {
          params.set("op_item_id", op.item_id);
        } else if (op.id) {
          params.set("op_id", op.id);
        } else if (currentLocalId) {
          params.set("id", currentLocalId);
        } else {
          return;
        }
        if (format === "pdf") params.set("format", "pdf");
        window.open(`${API.report}?${params.toString()}`, "_blank", "noopener");
      };

      // â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
      return (
        <div style={{
          fontFamily: "inherit",
          background: "var(--bg)", minHeight: "100vh", display: "flex", flexDirection: "column",
        }}>
          {/* â"€â"€ Top Bar â"€â"€ */}
          <header style={{
            background: "var(--primary)",
            padding: isMobile ? "0 12px" : "0 28px", height: 56, display: "flex", alignItems: "center",
            justifyContent: "space-between", boxShadow: "0 2px 12px rgba(0,0,0,.15)",
            position: "sticky", top: 0, zIndex: 100,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: isMobile ? 8 : 16 }}>
              <a href="/anomalie-menu" title="Torna al menu anomalie" style={{
                display: "flex", alignItems: "center", justifyContent: "center",
                width: 32, height: 32, borderRadius: 8,
                background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.12)",
                color: "#94a3b8", textDecoration: "none",
              }}>
                <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" viewBox="0 0 24 24">
                  <path d="M15 18l-6-6 6-6"/>
                </svg>
              </a>
              {!isMobile && <h1 className="text-lg font-bold" style={{ margin: 0, fontWeight: 700, color: "#fff", letterSpacing: "-0.01em" }}>
                Gestione Anomalie
              </h1>}
              {isMobile && mobilePanel === "dettaglio" && sn.sn && (
                <span className="text-base font-semibold" style={{ fontWeight: 600, color: "#e2e8f0" }}>
                  {op.id ? `${op.id} / ${sn.sn}` : sn.sn}
                </span>
              )}
              {isMobile && mobilePanel === "serie" && op.id && (
                <span className="text-base font-semibold" style={{ fontWeight: 600, color: "#e2e8f0" }}>{op.id}</span>
              )}
              {isMobile && mobilePanel === "ordini" && (
                <span className="text-base font-bold" style={{ fontWeight: 700, color: "#fff" }}>Gestione Anomalie</span>
              )}
              {!isMobile && op.id && (
                <span className="text-sm font-medium" style={{
                  background: "rgba(255,255,255,.1)", padding: "3px 12px",
                  borderRadius: 99, color: "#94a3b8", fontWeight: 500,
                }}>{op.id}</span>
              )}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: isMobile ? 8 : 12 }}>
              {!isMobile && IS_ADMIN && ADMIN_URL && (
                <a className="text-base font-bold" href={ADMIN_URL} style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  background: "var(--accent)", color: "#fff", borderRadius: 8,
                  padding: "6px 12px", fontWeight: 700,
                  textDecoration: "none", boxShadow: "0 2px 8px rgba(249,115,22,.25)",
                  whiteSpace: "nowrap",
                }}>
                  &#9881; Gestione Admin
                </a>
              )}
              {isMobile && IS_ADMIN && ADMIN_URL && (
                <a href={ADMIN_URL} title="Gestione Admin" style={{
                  display: "flex", alignItems: "center", justifyContent: "center",
                  width: 32, height: 32, borderRadius: 8,
                  background: "var(--accent)", color: "#fff", textDecoration: "none",
                  fontSize: 16,
                }}>&#9881;</a>
              )}
              {/* Nuova anomalia / segnalazione (apre il form completo di apertura segnalazione, preselezionando l'OP se presente) */}
              {!isMobile && (
                <a className="text-base font-semibold" href={nuovaAnomaliaUrl} title="Inserisci una nuova anomalia / segnalazione" style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  background: "rgba(255,255,255,.08)", border: "1px solid rgba(255,255,255,.12)",
                  borderRadius: 8, padding: "7px 16px", color: "#e2e8f0",
                  fontWeight: 600, textDecoration: "none", whiteSpace: "nowrap",
                }}>
                  <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.4" viewBox="0 0 24 24"><path d="M12 5v14m-7-7h14"/></svg>
                  Nuova anomalia
                </a>
              )}
              {isMobile && (
                <a href={nuovaAnomaliaUrl} title="Nuova anomalia / segnalazione" style={{
                  display: "flex", alignItems: "center", justifyContent: "center",
                  width: 32, height: 32, borderRadius: 8,
                  background: "rgba(255,255,255,.08)", border: "1px solid rgba(255,255,255,.12)",
                  color: "#e2e8f0", textDecoration: "none",
                }}>
                  <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.4" viewBox="0 0 24 24"><path d="M12 5v14m-7-7h14"/></svg>
                </a>
              )}
              {/* Messaggio di salvataggio / sync */}
              {saveMsg && !isMobile && (
                <span className="text-base font-medium" style={{
                  fontWeight: 500,
                  color: saveMsg.ok ? "#86efac" : "#fca5a5",
                  background: "rgba(255,255,255,.07)",
                  padding: "5px 12px", borderRadius: 6,
                }}>
                  {saveMsg.text}
                </span>
              )}
              {!isMobile && <button style={{
                background: "rgba(255,255,255,.08)", border: "1px solid rgba(255,255,255,.12)",
                borderRadius: 8, padding: "7px 16px", color: "#e2e8f0",
                fontWeight: 500, cursor: "pointer", display: "flex", alignItems: "center", gap: 6,
              }}>
                <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
                </svg>
                Cartella file
              </button>}
              {!isMobile && currentItemId && (
                <button onClick={() => {
                  setCurrentItemId(null);
                  setSaveMsg({ ok: true, text: "Dati copiati - modifica e salva come nuovo record" });
                  setTimeout(() => setSaveMsg(null), 4000);
                }} style={{
                  background: "rgba(255,255,255,.08)", border: "1px solid rgba(255,255,255,.12)",
                  borderRadius: 8, padding: "7px 16px", color: "#e2e8f0",
                  fontWeight: 500, cursor: "pointer", display: "flex", alignItems: "center", gap: 6,
                }}>
                  <svg width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                  Duplica
                </button>
              )}
              {!isMobile && (op.item_id || op.id || currentLocalId) && (
                <button onClick={() => handleOpenReport()} title="Apri il report riepilogativo dell'OP (HTML)" style={{
                  background: "rgba(255,255,255,.08)", border: "1px solid rgba(255,255,255,.12)",
                  borderRadius: 8, padding: "7px 16px", color: "#e2e8f0",
                  fontWeight: 500, cursor: "pointer", display: "flex", alignItems: "center", gap: 6,
                }}>
                  <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>
                  </svg>
                  Report OP
                </button>
              )}
              {!isMobile && (op.item_id || op.id || currentLocalId) && (
                <button onClick={() => handleOpenReport("pdf")} title="Scarica il report riepilogativo dell'OP in PDF" style={{
                  background: "rgba(255,255,255,.08)", border: "1px solid rgba(255,255,255,.12)",
                  borderRadius: 8, padding: "7px 16px", color: "#e2e8f0",
                  fontWeight: 500, cursor: "pointer", display: "flex", alignItems: "center", gap: 6,
                }}>
                  <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><polyline points="14 2 14 8 20 8"/><path d="M9 15h1.5a1.5 1.5 0 000-3H9v6"/><path d="M15 18v-6h1.8M15 15h1.6"/>
                  </svg>
                  PDF
                </button>
              )}
              {/* Pulsante unico "Salva": salva e accoda SEMPRE la notifica (debounce
                  ~5 min, 1 mail riepilogativa per OP). Niente più "Salva e notifica":
                  la mail parte da sola a ogni salvataggio. */}
              <button className={isMobile ? "text-md font-semibold" : "text-base font-semibold"} onClick={() => handleSave(false)} disabled={saving || !canEditSelected}
                title={isSelectedClosed ? "Anomalia chiusa: sola lettura" : "Salva l'anomalia: la mail di conferma a segnalante, CC e CAR parte automaticamente"} style={{
                background: saving ? "var(--primary-mid)" : "var(--accent)", border: "none", borderRadius: 8,
                padding: isMobile ? "8px 16px" : "7px 18px", color: "#fff",
                fontWeight: 600,
                cursor: saving || !canEditSelected ? "not-allowed" : "pointer",
                display: "flex", alignItems: "center", gap: 6,
                boxShadow: "0 2px 8px rgba(249,115,22,.3)",
                opacity: saving || !canEditSelected ? 0.8 : 1,
              }}>
                {saving ? (
                  <>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
                      style={{ animation: "spin 1s linear infinite" }}>
                      <path d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" strokeOpacity=".3"/>
                      <path d="M21 12a9 9 0 00-9-9"/>
                    </svg>
                    {isMobile ? "…" : "Salvataggio…"}
                  </>
                ) : (
                  <>
                    <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                      <path d="M5 13l4 4L19 7"/>
                    </svg>
                    Salva
                  </>
                )}
              </button>
            </div>
          </header>

          <style>{`
      @keyframes spin { to { transform: rotate(360deg); } }
      @keyframes fadeInUp { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
    `}</style>

          {/* â"€â"€ Layout 3 colonne â"€â"€ */}
          <div style={{
            flex: 1, display: "grid",
            gridTemplateColumns: isMobile ? "1fr" : isTablet ? "260px 220px 1fr" : "340px 280px 1fr",
            height: isMobile ? "auto" : "calc(100vh - 56px)",
            overflow: isMobile ? "visible" : "hidden",
          }}>

            {/* â"€â"€ SINISTRA: Ordini di Produzione â"€â"€ */}
            <div style={{
              borderRight: isMobile ? "none" : "1px solid #e2e8f0", background: "var(--surface)",
              display: isMobile && mobilePanel !== "ordini" ? "none" : "flex",
              flexDirection: "column", overflow: "hidden",
              minHeight: isMobile ? "calc(100dvh - 112px)" : undefined,
            }}>
              <div style={{ padding: "16px 16px 12px", borderBottom: "1px solid var(--border)" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                  <h2 className="text-base font-bold" style={{ margin: 0, fontWeight: 700, color: "var(--text)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Ordini di Produzione
                  </h2>
                  <span className="text-xs font-semibold" style={{ background: "var(--bg)", padding: "2px 8px", borderRadius: 99, fontWeight: 600, color: "var(--text-mid)" }}>
                    {loadingOrdini ? "…" : filteredOrdini.length}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
                  {filterButtons.map((filterOpt) => {
                    const active = pageFilter === filterOpt.value;
                    return (
                      <button
                        key={filterOpt.value || "all"}
                        onClick={() => {
                          setPageFilter(filterOpt.value);
                          setSelectedOp(0);
                          setSelectedSn(0);
                        }}
                        style={{
                          border: active ? "1px solid var(--accent)" : "1px solid var(--border)",
                          background: active ? "var(--accent-light)" : "var(--surface)",
                          color: active ? "var(--accent)" : "var(--text-mid)",
                          borderRadius: 999,
                          padding: "6px 10px",
                          fontWeight: 700,
                          letterSpacing: "0.02em",
                          cursor: "pointer",
                        }}
                        className="text-xs font-bold"
                      >
                        {filterOpt.label}
                      </button>
                    );
                  })}
                </div>
                <div style={{ position: "relative" }}>
                  <svg width="15" height="15" fill="none" stroke="#94a3b8" strokeWidth="2" viewBox="0 0 24 24"
                    style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)" }}>
                    <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
                  </svg>
                  <input value={searchOp} onChange={e => setSearchOp(e.target.value)}
                    placeholder="Cerca OP, P/N, capocommessa..."
                    style={{
                      width: "100%", padding: "9px 12px 9px 32px",
                      border: "1px solid #e2e8f0", borderRadius: 8,
                      outline: "none", background: "#f8fafc", color: "#334155",
                    }}
                    onFocus={e => e.target.style.borderColor="rgba(249,115,22,.5)"}
                    onBlur={e  => e.target.style.borderColor="var(--border)"}
                  />
                </div>
              </div>

              <div style={{ flex: 1, overflowY: "auto", padding: "8px" }}>
                {loadingOrdini ? (
                  <div className="text-base" style={{ padding: 24, textAlign: "center", color: "#94a3b8" }}>
                    Caricamento ordini…
                  </div>
                ) : filteredOrdini.length === 0 ? (
                  <div className="text-base" style={{ padding: 24, textAlign: "center", color: "#94a3b8" }}>
                    {pageFilter === "in_carico"
                      ? "Nessuna anomalia in carico per l'utente corrente"
                      : pageFilter === "aperte"
                        ? "Nessun ordine con anomalie aperte"
                        : "Nessun ordine trovato"}
                  </div>
                ) : (
                  filteredOrdini.map((o, i) => (
                    <div key={o.item_id || i} onClick={() => { setSelectedOp(i); if (isMobile) setMobilePanel("serie"); }} style={{
                      padding: "12px 14px", borderRadius: 10, cursor: "pointer", marginBottom: 4,
                      background: selectedOp === i ? "var(--accent-light)" : "transparent",
                      border: selectedOp === i ? "1px solid rgba(249,115,22,.25)" : "1px solid transparent",
                      transition: "all 0.15s ease",
                    }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                        <span className="text-md font-bold" style={{ fontWeight: 700, color: "#0f172a" }}>{o.id}</span>
                        {o.stato && <StatusBadge text={o.stato} variant="benestare" />}
                      </div>
                      <div className="text-sm" style={{ color: "var(--text-mid)", marginBottom: 4, fontFamily: "ui-monospace,monospace", letterSpacing: "-0.02em" }}>
                        P/N: {o.pn}
                      </div>
                      <div className="text-sm" style={{ display: "flex", alignItems: "center", gap: 12, color: "#94a3b8" }}>
                        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                            <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/>
                          </svg>
                          {o.capo}
                        </span>
                      </div>
                      {selectedOp === i && (
                        <div style={{ display: "flex", gap: 6, marginTop: 10, paddingTop: 10, borderTop: "1px solid #e2e8f0" }}>
                          <IconBtn accent title="Inserisci una nuova anomalia su questo OP" onClick={() => {
                            window.location.href = o.id
                              ? `/gestione-anomalie/nuova-segnalazione?op_id=${encodeURIComponent(o.id)}`
                              : "/gestione-anomalie/nuova-segnalazione";
                          }}>
                            <svg width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24"><path d="M12 5v14m-7-7h14"/></svg>
                            Anomalia
                          </IconBtn>
                          <IconBtn title="Duplica - copia i dati nel form come nuovo record" onClick={() => { setCurrentItemId(null); setSaveMsg({ ok: true, text: "Dati copiati - modifica e salva come nuovo record" }); setTimeout(() => setSaveMsg(null), 4000); }}>
                            <svg width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                            Duplica
                          </IconBtn>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>

              <div style={{ padding: "12px 16px", borderTop: "1px solid #e2e8f0", display: "flex", gap: 8 }}>
                <button className="text-base font-semibold" onClick={() => history.back()} style={{
                  flex: 1, padding: "9px", border: "1px solid rgba(229,62,62,.3)", borderRadius: 8,
                  background: "var(--danger-bg)", color: "var(--danger)", fontWeight: 600, cursor: "pointer",
                }}>Indietro</button>
                <button className="text-base font-medium" onClick={loadOrdini} style={{
                  flex: 1, padding: "9px", border: "1px solid #e2e8f0", borderRadius: 8,
                  background: "#fff", color: "var(--text-mid)", fontWeight: 500, cursor: "pointer",
                }}>Aggiorna</button>
              </div>
            </div>

            {/* â"€â"€ CENTRO: Numeri di Serie â"€â"€ */}
            <div style={{
              borderRight: isMobile ? "none" : "1px solid var(--border)", background: "var(--bg)",
              display: isMobile && mobilePanel !== "serie" ? "none" : "flex",
              flexDirection: "column", overflow: "hidden",
              minHeight: isMobile ? "calc(100dvh - 112px)" : undefined,
            }}>
              {isMobile && (
                <button className="text-base font-semibold" onClick={() => setMobilePanel("ordini")} style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "10px 14px",
                  background: "none", border: "none", borderBottom: "1px solid #f1f5f9",
                  color: "var(--primary-mid)", fontWeight: 600, cursor: "pointer", width: "100%",
                }}>
                  <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>
                  Ordini di Produzione
                </button>
              )}
              <div style={{ padding: "16px 14px 12px", borderBottom: "1px solid var(--border)" }}>
                <h2 className="text-base font-bold" style={{ margin: "0 0 12px", fontWeight: 700, color: "var(--text)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  {isMobile && op.id ? `S/N — ${op.id}` : "Numeri di Serie"}
                </h2>
                <div style={{ position: "relative" }}>
                  <svg width="15" height="15" fill="none" stroke="#94a3b8" strokeWidth="2" viewBox="0 0 24 24"
                    style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)" }}>
                    <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
                  </svg>
                  <input value={searchSn} onChange={e => setSearchSn(e.target.value)}
                    placeholder="Cerca S/N..."
                    style={{
                      width: "100%", padding: "9px 12px 9px 32px",
                      border: "1px solid #e2e8f0", borderRadius: 8,
                      outline: "none", background: "#fff", color: "#334155",
                    }}
                    onFocus={e => e.target.style.borderColor="rgba(249,115,22,.5)"}
                    onBlur={e  => e.target.style.borderColor="var(--border)"}
                  />
                </div>
              </div>

              <div style={{ flex: 1, overflowY: "auto", padding: "8px" }}>
                {loadingAnom ? (
                  <div className="text-base" style={{ padding: 20, textAlign: "center", color: "#94a3b8" }}>
                    Caricamento…
                  </div>
                ) : filteredSeriali.length === 0 ? (
                  <div className="text-base" style={{ padding: 20, textAlign: "center", color: "#94a3b8" }}>
                    {op.id && op.id !== '\u2014'
                      ? (pageFilter === "aperte" || pageFilter === "in_carico"
                          ? "Nessuna anomalia aperta per questo ordine"
                          : "Nessuna anomalia registrata")
                      : "Seleziona un ordine"}
                  </div>
                ) : (
                  (() => {
                    const renderSnCard = ({ a, i }) => {
                      const col = snColor(a.avanzamento);
                      const closed = Boolean(a.chiudere);
                      return (
                        <div key={a.item_id || i} onClick={() => { setSelectedSn(i); if (isMobile) setMobilePanel("dettaglio"); }} style={{
                          padding: "10px 12px", borderRadius: 10, cursor: "pointer", marginBottom: 4,
                          background: selectedSn === i ? "var(--surface)" : "transparent",
                          border: selectedSn === i ? "1px solid var(--border)" : "1px solid transparent",
                          boxShadow: selectedSn === i ? "0 1px 4px rgba(0,0,0,.06)" : "none",
                          opacity: closed ? 0.7 : 1,
                          transition: "all 0.15s",
                        }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                            <div style={{ width: 10, height: 10, borderRadius: "50%", background: col, boxShadow: `0 0 0 3px ${col}22` }} />
                            <span className="text-base font-semibold" style={{ fontWeight: 600, color: "var(--text)", fontFamily: "ui-monospace,monospace" }}>
                              S/N: {a.sn || '\u2014'}
                            </span>
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, paddingLeft: 18 }}>
                            <span className="text-sm" style={{ color: "var(--text-mid)" }}>{a.avanzamento || "Aperto"}</span>
                            {a.modified && (
                              <span className="text-2xs" style={{ color: "#94a3b8" }}>
                                {new Date(a.modified).toLocaleDateString("it-IT", { day:"2-digit", month:"2-digit", year:"2-digit" })}
                              </span>
                            )}
                            {a.pezzi_prec && (
                              <span className="text-2xs font-medium" style={{ padding: "1px 6px", borderRadius: 4, background: "var(--bg)", color: "var(--primary-mid)", border: "1px solid var(--border)", fontWeight: 500 }}>
                                prec. benestare
                              </span>
                            )}
                            {closed && (
                              <span className="text-2xs font-medium" style={{ padding: "1px 6px", borderRadius: 4, background: "var(--success-bg)", color: "var(--success)", border: "1px solid #c6f6d5", fontWeight: 500 }}>
                                chiusa
                              </span>
                            )}
                          </div>
                          {selectedSn === i && !closed && (
                            <div style={{ marginTop: 8, paddingLeft: 18, display: "flex", gap: 6 }}>
                              <IconBtn title="Duplica - copia i dati nel form come nuovo record" onClick={() => {
                                setCurrentItemId(null);
                                setSaveMsg({ ok: true, text: "Dati copiati - modifica e salva come nuovo record" });
                                setTimeout(() => setSaveMsg(null), 4000);
                              }}>
                                <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                                Duplica
                              </IconBtn>
                            </div>
                          )}
                        </div>
                      );
                    };
                    return (
                      <React.Fragment>
                        {openSeriali.map(renderSnCard)}
                        {closedSeriali.length > 0 && (
                          <div style={{ marginTop: openSeriali.length ? 10 : 0 }}>
                            <button type="button" onClick={() => setClosedCollapsed((v) => !v)} style={{
                              display: "flex", alignItems: "center", gap: 6, width: "100%",
                              padding: "8px 12px", background: "var(--bg)", border: "1px solid var(--border)",
                              borderRadius: 8, cursor: "pointer", color: "var(--text-mid)", marginBottom: 4,
                            }}>
                              <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24"
                                   style={{ transform: closedCollapsed ? "rotate(-90deg)" : "none", transition: "transform .15s" }}>
                                <path d="M6 9l6 6 6-6"/>
                              </svg>
                              <span className="text-sm font-semibold" style={{ fontWeight: 600 }}>
                                Chiuse ({closedSeriali.length})
                              </span>
                            </button>
                            {!closedCollapsed && closedSeriali.map(renderSnCard)}
                          </div>
                        )}
                      </React.Fragment>
                    );
                  })()
                )}
              </div>
            </div>

            {/* â"€â"€ DESTRA: Pannello dettaglio â"€â"€ */}
            <div style={{
              background: "var(--surface)", overflowY: "auto",
              display: isMobile && mobilePanel !== "dettaglio" ? "none" : "flex",
              flexDirection: "column",
            }}>
              {isMobile && (
                <button className="text-base font-semibold" onClick={() => setMobilePanel("serie")} style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "10px 14px",
                  background: "none", border: "none", borderBottom: "1px solid #f1f5f9",
                  color: "var(--primary-mid)", fontWeight: 600, cursor: "pointer", width: "100%",
                }}>
                  <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>
                  S/N — {sn.sn || "lista"}
                </button>
              )}
              {/* Header dettaglio */}
              <div style={{
                padding: isMobile ? "12px 16px" : "20px 24px 16px", borderBottom: "1px solid #f1f5f9",
                background: "var(--surface)",
              }}>
                <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr 1fr" : "1fr 1fr 1fr auto", gap: isMobile ? 12 : 16, alignItems: "start" }}>
                  <div>
                    <FieldLabel>Capocommessa</FieldLabel>
                    <div className="text-md font-semibold" style={{ fontWeight: 600, color: "#0f172a" }}>{op.capo || '\u2014'}</div>
                  </div>
                  <div>
                    <FieldLabel>CAR</FieldLabel>
                    <div className="text-md font-medium" style={{ fontWeight: 500, color: "#334155" }}>{op.car || '\u2014'}</div>
                  </div>
                  <div>
                    <FieldLabel>S/N selezionato</FieldLabel>
                    <div className="text-md font-medium" style={{ fontWeight: 500, color: "var(--text-mid)", fontFamily: "ui-monospace,monospace" }}>
                      {sn.sn || '\u2014'}
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <FieldLabel>Identificativo</FieldLabel>
                    <span className="text-base font-bold" style={{
                      display: "inline-block", padding: "4px 12px", borderRadius: 6,
                      background: "#f1f5f9", fontWeight: 700,
                      color: "var(--text)", fontFamily: "ui-monospace,monospace",
                    }}>{op.id || '\u2014'}</span>
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 12, paddingTop: 12, borderTop: "1px solid #f1f5f9" }}>
                  <div>
                    <FieldLabel>P/N</FieldLabel>
                    <span className="text-base" style={{ fontFamily: "'JetBrains Mono',monospace", color: "var(--text-mid)" }}>
                      {op.pn || '\u2014'}
                    </span>
                  </div>
                  <div style={{ marginLeft: "auto" }}>
                    <FieldLabel>Stato</FieldLabel>
                    <StatusBadge text={statoBadge.text} variant={statoBadge.variant} />
                  </div>
                </div>
                {sn.sn && (
                  <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid #f1f5f9" }}>
                    <FieldLabel>Avanzamento</FieldLabel>
                    <StatoStepper avanzamento={sn.avanzamento} chiuso={Boolean(sn.chiudere)} />
                  </div>
                )}
                {!canEditCurrentOp && op.id && op.id !== '\u2014' && (
                  <div className="text-sm font-semibold" style={{
                    marginTop: 12,
                    padding: "10px 12px",
                    borderRadius: 8,
                    border: "1px solid var(--warning)",
                    background: "var(--warning-bg)",
                    color: "var(--warning)",
                    fontWeight: 600,
                  }}>
                    Modalità sola lettura: puoi visualizzare i dati ma non modificare questo OP.
                  </div>
                )}
                {canEditCurrentOp && isSelectedClosed && (
                  <div className="text-sm font-semibold" style={{
                    marginTop: 12,
                    padding: "10px 12px",
                    borderRadius: 8,
                    border: "1px solid #c6f6d5",
                    background: "var(--success-bg)",
                    color: "var(--success)",
                    fontWeight: 600,
                  }}>
                    Anomalia chiusa: in sola lettura. I dati restano consultabili ma non modificabili.
                  </div>
                )}
              </div>

              {/* Body form */}
              <div style={{ padding: isMobile ? "16px" : "20px 24px", flex: 1, paddingBottom: isMobile ? 72 : 24 }}>
                <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: isMobile ? 16 : 24 }}>
                  {/* Colonna sinistra */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                    <div>
                      <FieldLabel required>Descrizione anomalia</FieldLabel>
                      <textarea value={desc} onChange={e => setDesc(e.target.value)} rows={4} disabled={!canEditSelected}
                        style={{
                          width: "100%", padding: "10px 14px",
                          border: "1px solid var(--border)", borderRadius: 10,
                          fontFamily: "inherit", resize: "vertical", outline: "none",
                          lineHeight: 1.5, color: "var(--text)", background: canEditSelected ? "var(--bg)" : "var(--border)",
                        }}
                        onFocus={e => e.target.style.borderColor="rgba(249,115,22,.5)"}
                        onBlur={e  => e.target.style.borderColor="var(--border)"}
                      />
                    </div>

                    <div style={{ background: "var(--bg)", borderRadius: 12, padding: "16px 18px", display: "flex", flexDirection: "column", gap: 14, border: "1px solid var(--border)" }}>
                      <Toggle label="Pezzi precedenti al benestare" checked={pezziPrec} disabled={!canEditSelected} onChange={() => setPezziPrec(!pezziPrec)} />
                      <div style={{ height: 1, background: "var(--border)" }} />
                      <Toggle label="Aprire RDC?" checked={aprireRdc} disabled={!canEditSelected} onChange={() => setAprireRdc(!aprireRdc)} />
                      <div style={{ height: 1, background: "var(--border)" }} />
                      <Toggle label="Segnalare a cliente?" checked={segnalare} disabled={!canEditSelected} onChange={() => setSegnalare(!segnalare)} />
                      <div style={{ height: 1, background: "var(--border)" }} />
                      <Toggle label="Chiudere? (automatico)" checked={chiudereAuto} disabled={true} />
                    </div>

                    <div>
                      <FieldLabel>Avanzamento</FieldLabel>
                      <select value={avanzamento} onChange={e => setAvanzamento(e.target.value)} disabled={segnalare || !canEditSelected}
                        style={{
                          width: "100%", padding: "9px 14px", border: "1px solid var(--border)",
                          borderRadius: 8, color: "var(--text)",
                          background: segnalare || !canEditSelected ? "var(--bg)" : "var(--surface)", outline: "none",
                          cursor: segnalare || !canEditSelected ? "not-allowed" : "pointer",
                          opacity: segnalare || !canEditSelected ? 0.75 : 1,
                        }}>
                        {avanzamentoOptions.map((opt) => (
                          <option key={opt}>{opt}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* Colonna destra */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                    <div>
                      <FieldLabel required>Note capocommessa</FieldLabel>
                      <textarea value={note} onChange={e => setNote(e.target.value)} rows={3} disabled={!canEditSelected}
                        style={{
                          width: "100%", padding: "10px 14px",
                          border: "1px solid var(--border)", borderRadius: 10,
                          fontFamily: "inherit", resize: "vertical", outline: "none",
                          lineHeight: 1.5, color: "var(--text)", background: canEditSelected ? "var(--bg)" : "var(--border)",
                        }}
                        onFocus={e => e.target.style.borderColor="rgba(249,115,22,.5)"}
                        onBlur={e  => e.target.style.borderColor="var(--border)"}
                      />
                    </div>

                    {/* Allegati */}
                    <div>
                      <FieldLabel>Allegati anomalia</FieldLabel>
                      <input
                        ref={fileInputRef}
                        type="file"
                        multiple
                        accept=".jpg,.jpeg,.png,.gif,.bmp,.webp,.pdf,.doc,.docx,.xls,.xlsx,.xlsm,.csv"
                        onChange={handleAttachmentInput}
                        style={{ display: "none" }}
                      />
                      <div style={{ borderRadius: 12, border: "1px solid var(--border)", background: "var(--surface)", padding: 12 }}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 10 }}>
                          <div className="text-sm" style={{ color: "var(--text-mid)" }}>
                            {currentLocalId
                              ? `Record locale #${currentLocalId}`
                              : "Salva prima la segnalazione per abilitare gli allegati"}
                          </div>
                          <IconBtn
                            onClick={openAttachmentPicker}
                            disabled={!canEditCurrentOp || !currentLocalId || uploadingAttachments}
                            accent
                            title="Carica allegati"
                          >
                            {uploadingAttachments ? "Caricamento..." : "Carica file"}
                          </IconBtn>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                          {loadingAttachments ? (
                            <div className="text-sm" style={{ color: "var(--text-mid)" }}>Caricamento allegati...</div>
                          ) : attachments.length === 0 ? (
                            <div className="text-sm" style={{ color: "#94a3b8" }}>
                              Nessun allegato. Formati ammessi: immagini, PDF, Word, Excel.
                            </div>
                          ) : (
                            <>
                              {/* Preview allegato selezionato */}
                              <div style={{
                                border: "1px solid #e2e8f0",
                                borderRadius: 10,
                                background: "var(--primary)",
                                overflow: "hidden",
                                position: "relative",
                                aspectRatio: "16/9",
                              }}>
                                {selectedAttachment && selectedAttachment.is_image ? (
                                  <img
                                    src={getAttachmentUrl(selectedAttachment.file_id)}
                                    alt={selectedAttachment.name}
                                    style={{ width: "100%", height: "100%", objectFit: "contain", background: "var(--primary)", cursor: "pointer" }}
                                    onClick={() => openAttachment(selectedAttachment.file_id, false)}
                                  />
                                ) : selectedAttachment ? (
                                  <div style={{
                                    width: "100%",
                                    height: "100%",
                                    display: "flex",
                                    flexDirection: "column",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    gap: 10,
                                    color: "rgba(255,255,255,.85)",
                                    padding: 16,
                                    textAlign: "center",
                                  }}>
                                    <div style={{
                                      width: 64,
                                      height: 64,
                                      borderRadius: 12,
                                      border: "1px solid rgba(255,255,255,.2)",
                                      background: "rgba(255,255,255,.1)",
                                      display: "flex",
                                      alignItems: "center",
                                      justifyContent: "center",
                                      fontWeight: 700,
                                      color: "#fff",
                                    }}>
                                      {(fileExt(selectedAttachment.name).replace(".", "").toUpperCase() || "FILE").slice(0, 4)}
                                    </div>
                                    <div className="text-base font-semibold" style={{ fontWeight: 600 }}>{selectedAttachment.name}</div>
                                    <div style={{ display: "flex", gap: 8 }}>
                                      <IconBtn onClick={() => openAttachment(selectedAttachment.file_id, false)} accent title="Apri allegato">
                                        Apri
                                      </IconBtn>
                                      <IconBtn onClick={() => openAttachment(selectedAttachment.file_id, true)} title="Scarica allegato">
                                        Scarica
                                      </IconBtn>
                                    </div>
                                  </div>
                                ) : null}
                              </div>

                              {/* Lista allegati */}
                              <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 220, overflowY: "auto", paddingRight: 4 }}>
                                {attachments.map((file) => {
                                  const inlineUrl = getAttachmentUrl(file.file_id);
                                  const ext = fileExt(file.name).replace(".", "").toUpperCase() || "FILE";
                                  const selected = file.file_id === selectedAttachmentId;
                                  return (
                                    <div
                                      key={file.file_id}
                                      onClick={() => setSelectedAttachmentId(file.file_id)}
                                      style={{
                                        border: selected ? "1px solid var(--accent)" : "1px solid var(--border)",
                                        borderRadius: 10,
                                        padding: 8,
                                        display: "grid",
                                        gridTemplateColumns: "54px 1fr auto",
                                        gap: 10,
                                        alignItems: "center",
                                        background: selected ? "var(--accent-light)" : "var(--surface)",
                                        cursor: "pointer",
                                      }}>
                                      {file.is_image ? (
                                        <img
                                          src={inlineUrl}
                                          alt={file.name}
                                          style={{
                                            width: 54,
                                            height: 54,
                                            borderRadius: 8,
                                            objectFit: "cover",
                                            border: "1px solid #e2e8f0",
                                          }}
                                        />
                                      ) : (
                                        <div className="text-xs font-bold" style={{
                                          width: 54,
                                          height: 54,
                                          borderRadius: 8,
                                          border: "1px solid #e2e8f0",
                                          background: "#f8fafc",
                                          display: "flex",
                                          alignItems: "center",
                                          justifyContent: "center",
                                          fontWeight: 700,
                                          color: "var(--text-mid)",
                                        }}>
                                          {ext}
                                        </div>
                                      )}
                                      <div style={{ minWidth: 0 }}>
                                        <div className="text-base font-semibold" title={file.name} style={{
                                          color: "#0f172a",
                                          fontWeight: 600,
                                          overflow: "hidden",
                                          textOverflow: "ellipsis",
                                          whiteSpace: "nowrap",
                                        }}>
                                          {file.name}
                                        </div>
                                        <div className="text-xs" style={{ color: "#64748b", marginTop: 2 }}>
                                          {formatBytes(file.size)} • {file.mime_type || "file"}
                                        </div>
                                      </div>
                                      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                                        <IconBtn onClick={(e) => { e.stopPropagation(); openAttachment(file.file_id, false); }} title="Apri">
                                          Apri
                                        </IconBtn>
                                        <IconBtn onClick={(e) => { e.stopPropagation(); openAttachment(file.file_id, true); }} title="Scarica">
                                          Scarica
                                        </IconBtn>
                                        <IconBtn
                                          onClick={(e) => { e.stopPropagation(); handleDeleteAttachment(file.file_id); }}
                                          disabled={!canEditCurrentOp}
                                          title="Elimina allegato"
                                        >
                                          Elimina
                                        </IconBtn>
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            </>
                          )}
                        </div>
                      </div>
                    </div>

                    {aprireRdc && (
                      <div>
                        <FieldLabel>Numero RDC</FieldLabel>
                        <input
                          placeholder="Inserisci numero RDC..."
                          value={rdcNum}
                          onChange={e => setRdcNum(e.target.value)}
                          disabled={!canEditCurrentOp}
                          style={{
                            width: "100%", padding: "9px 14px",
                            border: "1px solid #e2e8f0", borderRadius: 8,
                            outline: "none", color: "#334155", background: canEditCurrentOp ? "#fff" : "#f1f5f9",
                          }}
                          onFocus={e => e.target.style.borderColor="#93c5fd"}
                          onBlur={e  => e.target.style.borderColor="#e2e8f0"}
                        />
                      </div>
                    )}
                  </div>
                </div>
                {op.id && op.id !== '—' && (
                  <TimelineOp opId={op.id} opItemId={op.item_id} />
                )}
              </div>
            </div>

          </div>

          {/* ── Toast mobile per saveMsg ── */}
          {isMobile && saveMsg && (
            <div style={{
              position: "fixed", bottom: 64, left: 12, right: 12, zIndex: 200,
              background: saveMsg.ok ? "#059669" : "#dc2626",
              color: "#fff", padding: "12px 16px", borderRadius: 10,
              fontWeight: 600, fontSize: 14, lineHeight: 1.4,
              boxShadow: "0 4px 16px rgba(0,0,0,.25)",
              animation: "fadeInUp 0.2s ease",
            }}>
              {saveMsg.text}
            </div>
          )}

          {/* ── Bottom tab bar mobile ── */}
          {isMobile && (
            <nav style={{
              position: "fixed", bottom: 0, left: 0, right: 0, height: 56,
              background: "#1e293b", borderTop: "1px solid rgba(255,255,255,.12)",
              display: "flex", zIndex: 150,
            }}>
              {[
                { id: "ordini", label: "Ordini", icon: (
                  <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"/>
                    <rect x="9" y="3" width="6" height="4" rx="1"/>
                    <line x1="9" y1="12" x2="15" y2="12"/><line x1="9" y1="16" x2="13" y2="16"/>
                  </svg>
                )},
                { id: "serie", label: "S/N", icon: (
                  <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <path d="M4 6h16M4 10h16M4 14h16M4 18h16"/>
                  </svg>
                )},
                { id: "dettaglio", label: "Dettaglio", icon: (
                  <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
                  </svg>
                )},
              ].map(tab => {
                const active = mobilePanel === tab.id;
                return (
                  <button key={tab.id} onClick={() => setMobilePanel(tab.id)} style={{
                    flex: 1, background: "none", border: "none",
                    color: active ? "#60a5fa" : "#64748b",
                    cursor: "pointer",
                    display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 3,
                    borderTop: active ? "2px solid #60a5fa" : "2px solid transparent",
                    fontSize: 10, fontWeight: active ? 700 : 500,
                    letterSpacing: "0.04em", transition: "color 0.15s, border-color 0.15s",
                    WebkitTapHighlightColor: "transparent",
                  }}>
                    {tab.icon}
                    {tab.label}
                  </button>
                );
              })}
            </nav>
          )}

        </div>
      );
    }

    class ErrorBoundary extends React.Component {
      constructor(props) { super(props); this.state = { error: null }; }
      static getDerivedStateFromError(e) { return { error: e }; }
      componentDidCatch(e, info) { console.error("React render error:", e, info); }
      render() {
        if (this.state.error) {
          return React.createElement("div", {
            style: { color: "red", padding: 24, fontFamily: "monospace", whiteSpace: "pre-wrap" }
          }, "ERRORE RENDERING: " + this.state.error.message);
        }
        return this.props.children;
      }
    }

    console.log("Babel script eseguito OK");
    const root = ReactDOM.createRoot(document.getElementById("root"));
    root.render(
      React.createElement(ErrorBoundary, null,
        React.createElement(GestioneAnomalie, null)
      )
    );
  