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
      segnalato: "/api/anomalie/segnalato",
      elimina: "/api/anomalie/elimina",
      sposta: "/api/anomalie/sposta",
      seriali_op: "/api/anomalie/seriali-op",
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
    // Di default solo gli OP con anomalie aperte: le chiuse restano sotto «Tutti».
    const ACTIVE_FILTER = ["tutti", "aperte", "in_carico"].includes(INITIAL_FILTER) ? INITIAL_FILTER : "aperte";
    // ?op=<titolo OP>: arrivo da un promemoria in dashboard o da una mail -> preseleziona l'OP.
    const INITIAL_OP = normalizeChoice(QUERY_PARAMS.get("op")).toLowerCase();

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

    // «Segnalare al cliente» porta l'anomalia in attesa della risposta del cliente
    // (resta aperta; il capocommessa cambia stato quando il cliente risponde).
    const AVANZAMENTO_RISPOSTA_CLIENTE = "In attesa risposta cliente";

    // Regola PowerApps: la prima scelta cambia in base a "Aprire RDC?"
    const buildAvanzamentoOptions = (isAprireRdc) => {
      const dynamicFirst = isAprireRdc ? "Apertura ORE/RIPI" : "Azione di recupero";
      const dynamicAlt = isAprireRdc ? "Azione di recupero" : "Apertura ORE/RIPI";
      const sanitizedBase = BASE_AVANZAMENTO_OPTIONS.filter(
        (opt) => normalizeChoice(opt).toLowerCase() !== dynamicAlt.toLowerCase()
      );
      return dedupeChoices([dynamicFirst, ...sanitizedBase, AVANZAMENTO_RISPOSTA_CLIENTE]);
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

    const NOTA_STATO_MSG = "Hai scritto una nota: scegli anche lo stato di avanzamento, l'anomalia non può restare «In attesa».";

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
      if (avanz === "In attesa risposta cliente") return "#0ea5e9";
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

    // ─── Percorso dell'anomalia: eventi veri con le date (api/anomalie/esiti) ───
    // Segnalata → Decisa → (cliente) → (azione effettuata) → Chiusa; i passi che non
    // riguardano l'anomalia non compaiono. Il primo passo senza data è quello in corso.
    const PercorsoAnomalia = ({ passi }) => {
      if (!Array.isArray(passi) || !passi.length) return null;
      const quando = (iso) => (iso ? new Date(iso).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "");
      return (
        <ol className="ga-percorso" aria-label="Percorso dell'anomalia">
          {passi.map((p, i) => (
            <li key={p.chiave} className={`ga-percorso__passo is-${p.stato}`}>
              <span className="ga-percorso__dot">{p.stato === "fatto" ? Ico.check : i + 1}</span>
              <span className="ga-percorso__label">{p.label}</span>
              {p.dettaglio ? <span className="ga-percorso__det">{p.dettaglio}</span> : null}
              <span className="ga-percorso__data">{p.data ? quando(p.data) : (p.stato === "attuale" ? "in corso" : "")}</span>
            </li>
          ))}
        </ol>
      );
    };

    // â"€â"€â"€ Pannello timeline azioni OP (#2) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    // Consuma /api/anomalie/timeline (aggregata per OP). Lazy: carica al cambio OP.
    // ─── Tempi ed esiti dell'anomalia: risposta del cliente, azione effettuata ───
    // Tempi in giorni lavorativi (anomalie/tempi_service.py); gli allegati degli esiti
    // finiscono nella cartella dell'anomalia, insieme agli altri.
    const AZIONI_EFFETTUATE = Array.isArray(CONFIG_LISTS.azioni_effettuate) && CONFIG_LISTS.azioni_effettuate.length
      ? CONFIG_LISTS.azioni_effettuate
      : ["Rilavorato", "Riparato", "Scartato", "Reso al fornitore", "Accettato in deroga"];
    const ESITI_ACCEPT = ".jpg,.jpeg,.png,.gif,.bmp,.webp,.pdf,.doc,.docx,.xls,.xlsx,.xlsm,.csv,.msg,.eml,.txt";
    const chiedeRiverifica = (azione) => /rilavor|ripar/i.test(String(azione || ""));

    const FileEsito = ({ files, setFiles, disabled }) => {
      const ref = useRef(null);
      const [over, setOver] = useState(false);
      const aggiungi = (lista) => setFiles((prev) => {
        const next = [...prev];
        lista.forEach((f) => { if (!next.some((x) => x.name === f.name && x.size === f.size)) next.push(f); });
        return next;
      });
      return (
        <div className={`ga-att ga-att--esito${over ? " is-over" : ""}`} tabIndex={disabled ? -1 : 0}
          onDragOver={(e) => { if (disabled) return; e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); if (!disabled) aggiungi(Array.from(e.dataTransfer.files || [])); }}
          onPaste={(e) => {
            const fs = Array.from((e.clipboardData && e.clipboardData.items) || []).filter((it) => it.kind === "file").map((it) => it.getAsFile()).filter(Boolean);
            if (fs.length && !disabled) { e.preventDefault(); aggiungi(nomeAppunti(fs)); }
          }}>
          <input ref={ref} type="file" multiple hidden accept={ESITI_ACCEPT}
            onChange={(e) => { const f = Array.from(e.target.files || []); e.target.value = ""; aggiungi(f); }} />
          <div className="ga-att__head">
            <span className="ga-card__sub">{Ico.clip} Allegati {files.length ? `(${files.length})` : ""}</span>
            <span className="ga-hint">Mail (.msg, .eml), foto, PDF: trascina, <button type="button" className="ga-link" disabled={disabled} onClick={() => ref.current && ref.current.click()}>sfoglia</button> o clicca e premi Ctrl+V</span>
          </div>
          {files.length > 0 && (
            <div className="ga-esito__files">
              {files.map((f, i) => (
                <span key={f.name + i} className="ga-esito__file">
                  {f.name} <span className="ga-hint">{formatBytes(f.size)}</span>
                  <button type="button" aria-label={`Togli ${f.name}`} onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}>×</button>
                </span>
              ))}
            </div>
          )}
        </div>
      );
    };

    const EsitiAnomalia = ({ localId, avanzamento, chiusa, segnalare, onSaved, onInfo, flash }) => {
      const [data, setData] = useState(null);
      const [saving, setSaving] = useState(false);
      const [risposta, setRisposta] = useState("");
      const [filesRisposta, setFilesRisposta] = useState([]);
      const [azioneAperta, setAzioneAperta] = useState(false);
      const [azione, setAzione] = useState("");
      const [notaAzione, setNotaAzione] = useState("");
      const [filesAzione, setFilesAzione] = useState([]);
      const [riverificato, setRiverificato] = useState(false);
      const [chiudi, setChiudi] = useState(true);

      const carica = () => {
        if (!localId || !API.esiti) { setData(null); if (onInfo) onInfo(null); return; }
        fetch(`${API.esiti}?local_id=${encodeURIComponent(localId)}`, { credentials: "same-origin" })
          .then((r) => (r.ok ? r.json() : null))
          .then((d) => { setData(d && d.success ? d : null); if (onInfo) onInfo(d && d.success ? d : null); })
          .catch(() => setData(null));
      };
      useEffect(() => {
        setRisposta(""); setFilesRisposta([]); setAzione(""); setNotaAzione(""); setFilesAzione([]);
        setRiverificato(false); setChiudi(true); setAzioneAperta(false);
        carica();
      }, [localId, avanzamento, chiusa, segnalare]);

      if (!data) return null;
      const urlFile = (fileId) => `${API.allegati_file}?local_id=${encodeURIComponent(localId)}&file_id=${encodeURIComponent(fileId)}`;
      const soglia = (k) => (data.soglie || {})[k];
      const oltre = (t) => t.in_corso && soglia(t.chiave) && t.giorni > soglia(t.chiave);
      const puoi = data.can_registrare && !data.chiusa;
      const mostraRisposta = puoi && (data.in_attesa_cliente || data.segnalata_cliente);
      const mostraAzione = puoi && (data.recupero || azioneAperta);
      const serveRiverifica = chiudi && chiedeRiverifica(azione) && !riverificato;

      const invia = async (tipo) => {
        const form = new FormData();
        form.append("local_id", String(localId));
        form.append("tipo", tipo);
        if (tipo === "RISPOSTA_CLIENTE") {
          form.append("testo", risposta);
          filesRisposta.forEach((f) => form.append("files", f));
        } else {
          form.append("azione", azione);
          form.append("testo", notaAzione);
          form.append("riverificato", riverificato ? "1" : "");
          form.append("chiudi", chiudi ? "1" : "");
          filesAzione.forEach((f) => form.append("files", f));
        }
        setSaving(true);
        try {
          const r = await fetch(API.esito, { method: "POST", headers: { "X-CSRFToken": getCsrfToken() }, body: form, credentials: "same-origin" });
          const d = await readJsonOrThrow(r, "Registrazione esito");
          if (!r.ok || !d.success) throw new Error(d.error || `HTTP ${r.status}`);
          const avvisi = (d.errors || []).length ? ` · file non salvati: ${d.errors.join("; ")}` : "";
          flash({ ok: !avvisi, text: (tipo === "RISPOSTA_CLIENTE" ? "Risposta del cliente registrata: ora scegli lo stato definitivo" : (d.chiusa ? "Azione effettuata registrata · anomalia chiusa" : "Azione effettuata registrata")) + avvisi }, avvisi ? 8000 : 4500);
          if (onSaved) onSaved({ chiusa: !!d.chiusa });
          carica();
          if (tipo === "RISPOSTA_CLIENTE") { setRisposta(""); setFilesRisposta([]); }
          else { setAzione(""); setNotaAzione(""); setFilesAzione([]); setRiverificato(false); setAzioneAperta(false); }
        } catch (e) {
          flash({ ok: false, text: "Errore: " + e.message }, 7000);
        }
        setSaving(false);
      };

      return (
        <div className="ga-card ga-card--esiti">
          <div className="ga-card__head">
            <span className="ga-card__title">Tempi ed esiti</span>
            <span className="ga-hint">{data.unita || "ore lavorate, giorni lavorativi"}</span>
          </div>
          {data.tempi && data.tempi.length > 0 && (
            <div className="ga-tempi">
              {data.tempi.map((t) => (
                <span key={t.chiave} className={`ga-tempo${t.in_corso ? " is-corso" : ""}${oltre(t) ? " is-oltre" : ""}`}
                  title={oltre(t) ? `Oltre l'obiettivo di ${soglia(t.chiave)} giorni lavorativi` : ""}>
                  <span className="ga-tempo__l">{t.label}</span>
                  <b>{t.testo}</b>{t.in_corso ? <span className="ga-tempo__c">in corso</span> : null}
                </span>
              ))}
            </div>
          )}

          {data.esiti && data.esiti.length > 0 && (
            <ol className="ga-esiti">
              {data.esiti.map((e) => (
                <li key={e.id} className="ga-esito">
                  <div className="ga-esito__head">
                    <b>{e.tipo === "AZIONE" ? `Azione effettuata: ${e.azione}` : "Risposta del cliente"}</b>
                    {e.riverificato && <span className="ga-pill ga-pill--chiuso">Riverificato conforme</span>}
                    {e.chiusa && <span className="ga-pill ga-pill--muted">Ha chiuso l'anomalia</span>}
                    <span className="ga-hint ga-esito__chi">{e.utente} · {e.data ? new Date(e.data).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }) : ""}</span>
                  </div>
                  {e.testo && <div className="ga-esito__testo">{e.testo}</div>}
                  {e.allegati.length > 0 && (
                    <div className="ga-esito__files">
                      {e.allegati.map((f) => <a key={f.file_id} className="ga-esito__file" href={urlFile(f.file_id)} target="_blank" rel="noopener">{Ico.clip} {f.name}</a>)}
                    </div>
                  )}
                </li>
              ))}
            </ol>
          )}

          {mostraRisposta && (
            <div className="ga-esito-form">
              <FieldLabel>Risposta del cliente</FieldLabel>
              <textarea className="ga-input" rows={2} value={risposta} onChange={(e) => setRisposta(e.target.value)} disabled={saving}
                placeholder="Cosa ha risposto il cliente (riferimento della mail, decisione…)" />
              <FileEsito files={filesRisposta} setFiles={setFilesRisposta} disabled={saving} />
              <div className="ga-esito-form__acts">
                <button type="button" className="ga-btn ga-btn--outline" disabled={saving || (!risposta.trim() && !filesRisposta.length)} onClick={() => invia("RISPOSTA_CLIENTE")}>
                  {saving ? "Salvataggio…" : "Registra risposta"}
                </button>
              </div>
            </div>
          )}

          {puoi && !mostraAzione && (
            <button type="button" className="ga-link ga-esito-apri" onClick={() => setAzioneAperta(true)}>+ Registra un'azione effettuata</button>
          )}
          {mostraAzione && (
            <div className="ga-esito-form">
              {data.serve_azione && <div className="ga-note ga-note--info">Decisione «Azione di recupero»: l'anomalia si chiude registrando qui l'azione effettuata.</div>}
              <div className="ga-grid2">
                <div>
                  <FieldLabel required>Azione effettuata</FieldLabel>
                  <select className="ga-input" value={azione} onChange={(e) => setAzione(e.target.value)} disabled={saving}>
                    <option value="">Scegli…</option>
                    {AZIONI_EFFETTUATE.map((a) => <option key={a}>{a}</option>)}
                  </select>
                </div>
                <div className="ga-esito-form__flags">
                  <FlagToggle label="Pezzo riverificato conforme" checked={riverificato} disabled={saving} onChange={() => setRiverificato(!riverificato)} />
                  <FlagToggle label="Chiudi l'anomalia" checked={chiudi} disabled={saving} onChange={() => setChiudi(!chiudi)} />
                </div>
              </div>
              <textarea className="ga-input" rows={2} value={notaAzione} onChange={(e) => setNotaAzione(e.target.value)} disabled={saving}
                placeholder="Note: cosa è stato fatto, da chi, riferimenti…" />
              <FileEsito files={filesAzione} setFiles={setFilesAzione} disabled={saving} />
              {serveRiverifica && <div className="ga-note ga-note--warn">Dopo una rilavorazione o riparazione, per chiudere spunta «Pezzo riverificato conforme».</div>}
              <div className="ga-esito-form__acts">
                {!data.recupero && <button type="button" className="ga-btn ga-btn--ghost" disabled={saving} onClick={() => setAzioneAperta(false)}>Annulla</button>}
                <button type="button" className="ga-btn ga-btn--outline" disabled={saving || !azione || serveRiverifica} onClick={() => invia("AZIONE")}>
                  {saving ? "Salvataggio…" : (chiudi ? "Registra e chiudi" : "Registra azione")}
                </button>
              </div>
            </div>
          )}
        </div>
      );
    };

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
                  <div key={it.id} style={{ display: "flex", gap: 10, padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
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

    // --- Scheda qualita' della singola anomalia (classificazione, NC dell'OP, proposta AI) ---
    // Consuma /api/anomalie/qualita (GET crea la scheda al primo accesso) e
    // /api/anomalie/qualita/copilota (proposta AI, non salva nulla).
    const GRAVITA_COLORS = {
      MINORE:   { bg: "var(--success-bg)", fg: "var(--success)" },
      MAGGIORE: { bg: "var(--warning-bg)", fg: "var(--warning)" },
      CRITICA:  { bg: "var(--danger-bg)",  fg: "var(--danger)" },
    };
    const qInputStyle = (enabled) => ({
      width: "100%", padding: "8px 12px", border: "1px solid var(--border)", borderRadius: 8,
      color: "var(--text)", background: enabled ? "var(--surface)" : "var(--bg)", outline: "none",
      cursor: enabled ? "auto" : "not-allowed", opacity: enabled ? 1 : 0.8,
    });
    const SCHEDA_FIELDS = ["origine", "tipo_difetto", "gravita", "reparto", "quantita_nc", "quantita_scartata", "disposizione"];

    const SchedaQualita = ({ localId, canEdit, reloadKey, isMobile }) => {
      const [scheda, setScheda] = useState(null);
      const [scelte, setScelte] = useState(null);
      const [draft, setDraft] = useState({});
      const [loading, setLoading] = useState(false);
      const [saving, setSaving] = useState(false);
      const [msg, setMsg] = useState(null);
      const [ai, setAi] = useState(null);
      const [aiLoading, setAiLoading] = useState(false);
      const [serverCanEdit, setServerCanEdit] = useState(false);

      const toDraft = (s) => {
        const d = {};
        SCHEDA_FIELDS.forEach((k) => { d[k] = s && s[k] != null ? String(s[k]) : ""; });
        return d;
      };

      useEffect(() => {
        setAi(null); setMsg(null);
        if (!localId || !API.qualita) { setScheda(null); return; }
        let alive = true;
        setLoading(true);
        fetch(`${API.qualita}?local_id=${encodeURIComponent(localId)}`, { credentials: "same-origin" })
          .then((r) => readJsonOrThrow(r, "Scheda qualità"))
          .then((d) => {
            if (!alive) return;
            if (!d.success) throw new Error(d.error || "Scheda non disponibile");
            setScheda(d.scheda); setScelte(d.scelte); setDraft(toDraft(d.scheda));
            setServerCanEdit(!!d.can_edit);
          })
          .catch((e) => { if (alive) { setScheda(null); setMsg({ ok: false, text: e.message }); } })
          .finally(() => { if (alive) setLoading(false); });
        return () => { alive = false; };
      }, [localId, reloadKey]);

      // Tipi difetto raggruppati per famiglia (optgroup). Hook PRIMA di ogni return.
      const famiglie = useMemo(() => {
        const out = [];
        ((scelte && scelte.tipi_difetto) || []).forEach((t) => {
          const fam = t.famiglia || "Altro";
          let g = out.find((x) => x.fam === fam);
          if (!g) { g = { fam, items: [] }; out.push(g); }
          g.items.push(t);
        });
        return out;
      }, [scelte]);

      if (!localId) {
        return (
          <div className="text-sm" style={{ marginTop: 20, padding: "12px 14px", border: "1px dashed var(--border)", borderRadius: 10, color: "var(--text-light)" }}>
            Scheda qualità: disponibile dopo il primo salvataggio della segnalazione.
          </div>
        );
      }

      const editable = canEdit && serverCanEdit && !!scheda;
      const dirty = scheda && SCHEDA_FIELDS.some((k) => (draft[k] || "") !== (scheda[k] != null ? String(scheda[k]) : ""));
      const set = (k) => (e) => setDraft((prev) => ({ ...prev, [k]: e.target.value }));
      const flash = (m) => { setMsg(m); setTimeout(() => setMsg(null), 4000); };

      const save = async () => {
        setSaving(true);
        try {
          const body = { local_id: localId };
          SCHEDA_FIELDS.forEach((k) => { body[k] = draft[k] === "" ? null : draft[k]; });
          const r = await fetch(API.qualita, {
            method: "POST", credentials: "same-origin",
            headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
            body: JSON.stringify(body),
          });
          const d = await readJsonOrThrow(r, "Salvataggio scheda qualità");
          if (!d.success) throw new Error(d.error || "Salvataggio non riuscito");
          setScheda(d.scheda); setDraft(toDraft(d.scheda));
          flash({ ok: true, text: "Scheda salvata" });
        } catch (e) {
          flash({ ok: false, text: e.message });
        }
        setSaving(false);
      };

      const askAi = async () => {
        setAiLoading(true); setAi(null);
        try {
          const r = await fetch(API.qualita_copilota, {
            method: "POST", credentials: "same-origin",
            headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
            body: JSON.stringify({ local_id: localId }),
          });
          const d = await readJsonOrThrow(r, "Proposta AI");
          if (!r.ok || !d.success) throw new Error(d.error || "Proposta non disponibile");
          setAi(d.proposta);
        } catch (e) {
          flash({ ok: false, text: e.message });
        }
        setAiLoading(false);
      };

      const applyAi = () => {
        if (!ai) return;
        setDraft((prev) => ({
          ...prev,
          tipo_difetto: ai.tipo_difetto != null ? String(ai.tipo_difetto) : prev.tipo_difetto,
          gravita: ai.gravita || prev.gravita,
        }));
      };

      const label = (list, value) => {
        const hit = (list || []).find((o) => String(o.value) === String(value));
        return hit ? hit.label : "";
      };
      const nc = scheda && scheda.nc;
      const grav = GRAVITA_COLORS[draft.gravita] || null;

      return (
        <div style={{ marginTop: 20, border: "1px solid var(--border)", borderRadius: 12, background: "var(--surface)", overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", padding: "12px 16px", background: "var(--bg)", borderBottom: "1px solid var(--border)" }}>
            <span className="text-sm font-semibold" style={{ fontWeight: 700, color: "var(--text)" }}>Scheda qualità</span>
            {grav && (
              <span className="text-2xs font-semibold" style={{ padding: "2px 8px", borderRadius: 99, background: grav.bg, color: grav.fg, fontWeight: 700, textTransform: "uppercase" }}>
                {label(scelte && scelte.gravita, draft.gravita)}
              </span>
            )}
            <span style={{ marginLeft: "auto" }} />
            {nc && (
              <a href={nc.url || "#"} target="_blank" rel="noopener" className="text-xs font-semibold" style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "3px 10px", borderRadius: 99, textDecoration: "none", fontWeight: 700,
                background: nc.chiusa ? "var(--success-bg)" : "var(--warning-bg)", color: nc.chiusa ? "var(--success)" : "var(--warning)",
              }} title="Non conformità dell'OP: contenimento, analisi, azioni e verifica">
                <span style={{ fontFamily: "ui-monospace,monospace" }}>{nc.protocollo}</span> · {nc.stato_label}
              </a>
            )}
          </div>

          <div style={{ padding: "14px 16px" }}>
            {loading ? (
              <div className="text-sm" style={{ color: "var(--text-light)" }}>Caricamento scheda…</div>
            ) : !scheda ? (
              <div className="text-sm" style={{ color: "var(--danger)" }}>{(msg && msg.text) || "Scheda non disponibile."}</div>
            ) : (
              <>
                {scheda.part_number && (
                  <div className="text-xs" style={{ color: "var(--text-light)", marginBottom: 10 }}>
                    P/N registrato: <span style={{ fontFamily: "ui-monospace,monospace", color: "var(--text-mid)" }}>{scheda.part_number}</span>
                  </div>
                )}
                <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(3, minmax(0,1fr))", gap: 12 }}>
                  <div style={{ gridColumn: isMobile ? "auto" : "span 2" }}>
                    <FieldLabel>Tipo difetto</FieldLabel>
                    <select value={draft.tipo_difetto || ""} onChange={set("tipo_difetto")} disabled={!editable} style={qInputStyle(editable)}>
                      <option value="">— da classificare —</option>
                      {famiglie.map((g) => (
                        <optgroup key={g.fam} label={g.fam}>
                          {g.items.map((t) => <option key={t.value} value={String(t.value)}>{t.label}</option>)}
                        </optgroup>
                      ))}
                      {draft.tipo_difetto && !((scelte && scelte.tipi_difetto) || []).some((t) => String(t.value) === draft.tipo_difetto) && (
                        <option value={draft.tipo_difetto}>{scheda.tipo_difetto_label || "Tipo disattivato"}</option>
                      )}
                    </select>
                  </div>
                  <div>
                    <FieldLabel>Gravità</FieldLabel>
                    <select value={draft.gravita || ""} onChange={set("gravita")} disabled={!editable} style={qInputStyle(editable)}>
                      <option value="">— da valutare —</option>
                      {((scelte && scelte.gravita) || []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <FieldLabel>Origine</FieldLabel>
                    <select value={draft.origine || ""} onChange={set("origine")} disabled={!editable} style={qInputStyle(editable)}>
                      <option value="">—</option>
                      {((scelte && scelte.origini) || []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <FieldLabel>Reparto</FieldLabel>
                    <select value={draft.reparto || ""} onChange={set("reparto")} disabled={!editable} style={qInputStyle(editable)}>
                      <option value="">—</option>
                      {((scelte && scelte.reparti) || []).map((o) => <option key={o.value} value={String(o.value)}>{o.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <FieldLabel>Decisione sul materiale</FieldLabel>
                    <select value={draft.disposizione || ""} onChange={set("disposizione")} disabled={!editable} style={qInputStyle(editable)}>
                      {((scelte && scelte.disposizioni) || []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                    {scheda.disposizione_auto && !dirty && (
                      <div className="text-2xs" style={{ color: "var(--text-light)", marginTop: 4 }}>Dedotta da RDC/avanzamento: cambiala se serve.</div>
                    )}
                  </div>
                  <div>
                    <FieldLabel>Q.tà non conforme</FieldLabel>
                    <input type="number" min="0" value={draft.quantita_nc || ""} onChange={set("quantita_nc")} disabled={!editable} style={qInputStyle(editable)} />
                  </div>
                  <div>
                    <FieldLabel>Q.tà scartata</FieldLabel>
                    <input type="number" min="0" value={draft.quantita_scartata || ""} onChange={set("quantita_scartata")} disabled={!editable} style={qInputStyle(editable)} />
                  </div>
                </div>

                {ai && (
                  <div style={{ marginTop: 14, padding: "12px 14px", borderRadius: 10, border: "1px solid var(--border)", background: "var(--bg)" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
                      <span className="text-xs font-semibold" style={{ fontWeight: 700, color: "var(--text)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                        Proposta {ai.fonte === "simili" ? "dai casi simili" : "AI"}
                      </span>
                      {!ai.ai_disponibile && <span className="text-2xs" style={{ color: "var(--text-light)" }}>AI non raggiungibile</span>}
                      <span style={{ marginLeft: "auto" }} />
                      {editable && (ai.tipo_difetto != null || ai.gravita) && (
                        <IconBtn onClick={applyAi} title="Copia tipo difetto e gravità nel form (poi salva)">Applica al form</IconBtn>
                      )}
                    </div>
                    <div className="text-sm" style={{ color: "var(--text-mid)", display: "grid", gap: 4 }}>
                      <div>Tipo difetto: <strong style={{ color: "var(--text)" }}>{label(scelte && scelte.tipi_difetto, ai.tipo_difetto) || "—"}</strong>
                        {" · "}Gravità: <strong style={{ color: "var(--text)" }}>{label(scelte && scelte.gravita, ai.gravita) || "—"}</strong></div>
                      {ai.causa_probabile && <div>Causa probabile (da verificare): {ai.causa_probabile}</div>}
                      {ai.motivazione && <div style={{ color: "var(--text-light)" }}>{ai.motivazione}</div>}
                    </div>
                    {Array.isArray(ai.simili) && ai.simili.length > 0 && (
                      <div style={{ marginTop: 8 }}>
                        <div className="text-2xs font-semibold" style={{ color: "var(--text-light)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Casi simili</div>
                        {ai.simili.map((c) => (
                          <div key={c.anomalia_id || c.protocollo} className="text-xs" style={{ color: "var(--text-mid)", padding: "3px 0", borderTop: "1px solid var(--border)" }}>
                            <span style={{ fontFamily: "ui-monospace,monospace", color: "var(--text)" }}>{c.protocollo}</span>
                            {" · "}{c.tipo_difetto_label}{c.part_number ? ` · P/N ${c.part_number}` : ""} — {c.descrizione}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
                  {msg && (
                    <span className="text-sm font-semibold" style={{ color: msg.ok ? "var(--success)" : "var(--danger)", fontWeight: 600 }}>{msg.text}</span>
                  )}
                  {!msg && aiLoading && (
                    <span className="text-sm" style={{ color: "var(--text-light)" }}>L'AI sta analizzando la segnalazione: può servire anche un minuto.</span>
                  )}
                  <span style={{ marginLeft: "auto" }} />
                  {editable && API.qualita_copilota && (
                    <IconBtn onClick={askAi} disabled={aiLoading} title="Proposta di tipo difetto, gravità e causa probabile (non salva nulla)">
                      {aiLoading ? "Analisi…" : "Proponi con AI"}
                    </IconBtn>
                  )}
                  {editable && (
                    <IconBtn onClick={save} disabled={saving || !dirty} accent title="Salva la scheda qualità">
                      {saving ? "Salvataggio…" : "Salva scheda"}
                    </IconBtn>
                  )}
                </div>
              </>
            )}
          </div>
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

    // ─── Componente principale ───────────────────────────────────────────────
    // Tre colonne: Ordini di produzione → anomalie dell'OP (raggruppate per blocco
    // di seriali) → dettaglio con «Segnalazione» (cosa ha trovato il reparto) e
    // «Decisione del capocommessa» (stato, RDC, cliente, note). Le selezioni sono
    // per id, così ricerche e filtri non cambiano l'anomalia aperta né perdono le
    // modifiche; le modifiche non salvate chiedono conferma prima di cambiare.
    const opKey = (o) => String((o && (o.item_id ?? o.id)) ?? "");
    const isDaDecidere = (a) => (
      !a.chiudere && !a.aprire_rdc && !a.segnalare && !String(a.note || "").trim()
      && ["", "in attesa"].includes(String(a.avanzamento || "").trim().toLowerCase())
    );
    const statoAnomalia = (a) => {
      if (!a || !a.item_id) return { text: "—", variant: "chiuso" };
      if (a.chiudere) return { text: "Chiusa", variant: "chiuso" };
      if (isDaDecidere(a)) return { text: "Da decidere", variant: "attesa" };
      return { text: a.avanzamento || "In lavorazione", variant: "aperto" };
    };
    const fmtData = (iso) => {
      if (!iso) return "";
      const d = new Date(iso);
      return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit", year: "2-digit" });
    };
    const ALLEGATI_ACCEPT = ".jpg,.jpeg,.png,.gif,.bmp,.webp,.pdf,.doc,.docx,.xls,.xlsx,.xlsm,.csv";
    const nomeAppunti = (files) => files.map((f, i) => {
      if (f.name && !/^image\.\w+$/i.test(f.name)) return f;
      const d = new Date();
      const p = (n) => String(n).padStart(2, "0");
      const ext = fileExt(f.name) || ".png";
      try {
        return new File([f], `appunti-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}-${i + 1}${ext}`, { type: f.type || "image/png" });
      } catch (_) { return f; }
    });

    const Ico = {
      back: <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>,
      plus: <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.4" viewBox="0 0 24 24"><path d="M12 5v14m-7-7h14"/></svg>,
      search: <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>,
      more: <svg width="16" height="16" fill="currentColor" viewBox="0 0 24 24"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>,
      prev: <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.4" viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>,
      next: <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.4" viewBox="0 0 24 24"><path d="M9 18l6-6-6-6"/></svg>,
      user: <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>,
      clip: <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>,
      upload: <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>,
      check: <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.6" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>,
      list: <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/></svg>,
      rows: <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M4 6h16M4 10h16M4 14h16M4 18h16"/></svg>,
      copy: <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>,
      edit: <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>,
    };

    const Chip = ({ active, onClick, children, count, tone }) => (
      <button type="button" className={`ga-chip${active ? " is-on" : ""}${tone ? ` ga-chip--${tone}` : ""}`} onClick={onClick}>
        {children}{count !== undefined && <span className="ga-chip__n">{count}</span>}
      </button>
    );

    const FlagToggle = ({ label, hint, checked, onChange, disabled }) => (
      <label className={`ga-flag${checked ? " is-on" : ""}${disabled ? " is-disabled" : ""}`} title={hint || ""}>
        <input type="checkbox" checked={!!checked} disabled={disabled} onChange={onChange} />
        <span className="ga-flag__box">{checked ? Ico.check : null}</span>
        <span>{label}</span>
      </label>
    );

    // Chip dei seriali: un range «LCN00060-LCN00065» diventa «LCN00060 → LCN00065».
    const RANGE_SN_RE = /^([A-Za-z]*\d+)-([A-Za-z]*\d+)$/;
    const SnChip = ({ voce, muted }) => {
      const m = RANGE_SN_RE.exec(String(voce || "").trim());
      return (
        <span className={`ga-snchip${muted ? " is-muted" : ""}${m ? " is-range" : ""}`}
          title={muted ? "Nello stesso controllo, ma non interessato da questa anomalia" : ""}>
          {m ? <>{m[1]}<span className="ga-snchip__arrow">→</span>{m[2]}</> : voce}
        </span>
      );
    };

    const PezziInteressati = ({ sn, compact }) => {
      const coinvolti = Array.isArray(sn.seriali_coinvolti) && sn.seriali_coinvolti.length
        ? sn.seriali_coinvolti : [sn.blocco_label || sn.sn].filter(Boolean);
      const esclusi = Array.isArray(sn.seriali_esclusi) ? sn.seriali_esclusi : [];
      const pezzi = sn.pezzi_coinvolti || coinvolti.length;
      if (!coinvolti.length) return null;
      return (
        <div className={`ga-sn${compact ? " ga-sn--compact" : ""}`}>
          {!compact && (
            <span className="ga-sn__label">
              Pezzi interessati <b className="ga-sn__count">{pezzi} pezz{pezzi === 1 ? "o" : "i"}</b>
              {esclusi.length > 0 && <span className="ga-sn__of">su {sn.pezzi_blocco} del controllo</span>}
            </span>
          )}
          <div className="ga-sn__chips">
            {coinvolti.map((v) => <SnChip key={`c-${v}`} voce={v} />)}
            {!compact && esclusi.map((v) => <SnChip key={`e-${v}`} voce={v} muted />)}
          </div>
        </div>
      );
    };

    function GestioneAnomalie() {
      // ── Dati ──
      const [ordini, setOrdini] = useState([]);
      const [anomalie, setAnomalie] = useState([]);
      const [loadingOrdini, setLoadingOrdini] = useState(true);
      const [loadingAnom, setLoadingAnom] = useState(false);
      const [saving, setSaving] = useState(false);
      const [saveMsg, setSaveMsg] = useState(null);  // { ok, text }
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
      const [snFilter, setSnFilter] = useState("tutte");   // "tutte" | "da_decidere"
      const [closedCollapsed, setClosedCollapsed] = useState(true);
      // Clonazione dell'OP: anomalie scelte da copiare su un nuovo OP ({ opKey, ids }).
      const [clona, setClona] = useState(null);
      const [pendingNav, setPendingNav] = useState(null);  // azione rinviata per modifiche non salvate
      const [menuOpen, setMenuOpen] = useState(false);
      const [editDesc, setEditDesc] = useState(false);
      const [lightbox, setLightbox] = useState(null);      // file_id immagine ingrandita
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
      // «Applica la stessa decisione anche a…»: perimetro (solo questa, stesso blocco,
      // tutte le aperte dell'OP, scelte a mano), già decise escluse di serie, riepilogo
      // in un popup prima di salvare.
      const [ambito, setAmbito] = useState("solo");
      const [scelteMano, setScelteMano] = useState([]);
      const [includiDecise, setIncludiDecise] = useState(false);
      const [riepilogo, setRiepilogo] = useState(null);  // null | { prossima: bool }
      // «Elimina» / «Taglia» dell'anomalia aperta: { tipo, op, sn, seriali, busy, err }.
      const [azAnom, setAzAnom] = useState(null);
      // «Modifica OP»: popup del controllore che ha creato l'OP dal portale.
      const [modOp, setModOp] = useState(null);  // null | { titolo, dati, iniz, motivo, busy, err }
      // Decisioni salvate su questo OP e non ancora partite nel riepilogo (parte dopo
      // la pausa configurata; «Invia ora» lo anticipa).
      const [coda, setCoda] = useState(null);  // null | { n, partenza }
      const [adesso, setAdesso] = useState(Date.now());
      const [inviando, setInviando] = useState(false);
      const caricaCoda = () => {
        if (!op.id || op.id === "—" || !API.decisioni_coda || !canEditCurrentOp) { setCoda(null); return; }
        fetch(`${API.decisioni_coda}?op_id=${encodeURIComponent(op.id)}`, { credentials: "same-origin" })
          .then((r) => (r.ok ? r.json() : null))
          .then((d) => setCoda(d && d.success && d.coda ? d.coda : null))
          .catch(() => {});
      };
      const inviaOra = async () => {
        setInviando(true);
        try {
          const r = await fetch(API.decisioni_coda, {
            method: "POST", credentials: "same-origin",
            headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
            body: JSON.stringify({ op_id: op.id }),
          });
          const d = await readJsonOrThrow(r, "Invio riepilogo");
          if (!r.ok || !d.success) throw new Error(d.error || `HTTP ${r.status}`);
          setCoda(null);
          flash({ ok: true, text: d.inviate ? `Riepilogo inviato: ${d.inviate} decision${d.inviate === 1 ? "e" : "i"}` : "Nessuna decisione da inviare" });
        } catch (e) {
          flash({ ok: false, text: "Errore: " + e.message }, 7000);
          caricaCoda();
        }
        setInviando(false);
      };
      const resetAmbito = () => { setAmbito("solo"); setScelteMano([]); setIncludiDecise(false); };

      const avanzamentoOptions = useMemo(() => buildAvanzamentoOptions(aprireRdc), [aprireRdc]);
      const chiudereAuto = shouldAutoClose(aprireRdc, avanzamento);
      // Tempi ed esiti dell'anomalia aperta: «serve_azione» blocca la chiusura senza azione effettuata.
      const [esitiInfo, setEsitiInfo] = useState(null);
      // Una risposta scritta nelle note non può lasciare l'anomalia «In attesa».
      const notaSenzaStato = !!note.trim() && ["", "in attesa"].includes(normalizeChoice(avanzamento).toLowerCase());

      // Spuntare «Segnalare al cliente» porta lo stato su «In attesa risposta cliente»
      // e spunta anche «Aprire RDC» (si può togliere); togliere la spunta riporta lo
      // stato di partenza e lascia «Aprire RDC» com'è. Con «Aprire RDC» la segnalazione
      // al cliente resta facoltativa.
      const toggleSegnalare = () => {
        const on = !segnalare;
        setSegnalare(on);
        if (on) { setAvanzamento(AVANZAMENTO_RISPOSTA_CLIENTE); setAprireRdc(true); }
        else if (avanzamento === AVANZAMENTO_RISPOSTA_CLIENTE) {
          const base = baseline.avanzamento;  // dichiarato più sotto: letto solo al clic
          setAvanzamento(base && base !== AVANZAMENTO_RISPOSTA_CLIENTE ? base : "In attesa");
        }
      };

      const flash = (msg, ms = 4500) => {
        setSaveMsg(msg);
        if (ms) setTimeout(() => setSaveMsg((cur) => (cur === msg ? null : cur)), ms);
      };

      const clearForm = () => {
        setDesc(""); setNote("");
        setDescrizioneAnswers({});
        setPezziPrec(false); setAprireRdc(false);
        setSegnalare(false); setTerzista(false); setDovePezzi("");
        setSegnalaCar(false); setCarScelti([]);
        setAvanzamento(DEFAULT_AVANZAMENTO); setRdcNum("");
        setCurrentItemId(null);
        setCurrentLocalId(null);
        setAttachments([]);
        resetAmbito();
        setEditDesc(false);
      };

      useEffect(() => {
        const current = normalizeChoice(avanzamento).toLowerCase();
        const exists = avanzamentoOptions.some((opt) => normalizeChoice(opt).toLowerCase() === current);
        if (!exists) setAvanzamento(avanzamentoOptions[0] || DEFAULT_AVANZAMENTO);
      }, [avanzamento, avanzamentoOptions]);

      // ── Ordini ──
      const loadOrdini = () => {
        setLoadingOrdini(true);
        fetch(API.ordini, { credentials: "same-origin" })
          .then(r => readJsonOrThrow(r, "Caricamento ordini"))
          .then(data => { setOrdini(Array.isArray(data) ? data : []); setLoadingOrdini(false); })
          .catch(e => { console.error("Errore caricamento ordini:", e); setLoadingOrdini(false); });
      };
      useEffect(() => { loadOrdini(); }, []);

      useEffect(() => {
        const nextUrl = new URL(window.location.href);
        if (pageFilter && pageFilter !== "aperte") nextUrl.searchParams.set("filter", pageFilter);
        else nextUrl.searchParams.delete("filter");
        window.history.replaceState({}, "", nextUrl.toString());
      }, [pageFilter]);

      const apertiDi = (o) => Number(o?.anomalie_aperte_count ?? o?.anomalie_count ?? 0);
      const daDecidereDi = (o) => Number(o?.anomalie_da_decidere_count ?? 0);
      const orderMatches = (o, filtro) => {
        if (filtro === "aperte") return apertiDi(o) > 0;
        // «In carico a me» = sono capocommessa o CAR dell'OP, oppure referente RDC e
        // l'OP ha anomalie aperte RDC / da segnalare al cliente (lo dice il server);
        // poter modificare l'OP non basta.
        if (filtro === "in_carico") return apertiDi(o) > 0 && (o?.in_carico !== undefined
          ? Boolean(o.in_carico) : (peopleMatchCurrentUser(o?.capo) || peopleMatchCurrentUser(o?.car)));
        return true;
      };
      const ordiniCercati = useMemo(() => {
        const q = searchOp.trim().toLowerCase();
        if (!q) return ordini;
        return ordini.filter((o) => [o.id, o.pn, o.capo, o.car].some((v) => String(v || "").toLowerCase().includes(q)));
      }, [ordini, searchOp]);
      const contatoriFiltro = useMemo(() => ({
        tutti: ordiniCercati.length,
        aperte: ordiniCercati.filter((o) => orderMatches(o, "aperte")).length,
        in_carico: ordiniCercati.filter((o) => orderMatches(o, "in_carico")).length,
      }), [ordiniCercati]);
      const filteredOrdini = useMemo(() => {
        const list = ordiniCercati.filter((o) => orderMatches(o, pageFilter));
        // Nei filtri operativi prima gli OP con decisioni in sospeso.
        if (pageFilter !== "tutti") return [...list].sort((a, b) => daDecidereDi(b) - daDecidereDi(a));
        return list;
      }, [ordiniCercati, pageFilter]);

      // L'OP resta selezionato anche se una ricerca lo nasconde dall'elenco.
      const op = useMemo(() => (
        ordini.find((o) => opKey(o) === selectedOpKey) || filteredOrdini[0] || {}
      ), [ordini, filteredOrdini, selectedOpKey]);
      // Con il sistema dei ruoli il server dice OP per OP se si può modificare.
      const canEditCurrentOp = useMemo(() => (
        op.can_edit !== undefined ? Boolean(op.can_edit) : canUserEditOp(op.capo, op.car)
      ), [op.can_edit, op.capo, op.car]);
      useEffect(() => { caricaCoda(); }, [op.id, canEditCurrentOp]);
      useEffect(() => {
        const t = setInterval(() => setAdesso(Date.now()), 20000);
        return () => clearInterval(t);
      }, []);
      // Passata l'ora prevista, si ricontrolla: il riepilogo sarà partito (o in partenza).
      useEffect(() => {
        if (coda && new Date(coda.partenza).getTime() + 70000 < adesso) caricaCoda();
      }, [adesso]);
      const nuovaAnomaliaUrl = (op.id && op.id !== "—")
        ? `/gestione-anomalie/nuova-segnalazione?op_id=${encodeURIComponent(op.id)}`
        : "/gestione-anomalie/nuova-segnalazione";
      // «Segnala a CAR»: si sceglie fra il CAR dell'OP e i capi reparto di Configurazione.
      const carDellOp = splitPeopleTokens(op.car === "—" ? "" : op.car);
      const carOpzioni = useMemo(() => {
        const visti = new Set();
        const out = [];
        [...carDellOp,
         ...(Array.isArray(CONFIG_LISTS.capi_reparto) ? CONFIG_LISTS.capi_reparto : []),
         ...carScelti].forEach((n) => {
          const nome = String(n || "").trim();
          if (nome && !visti.has(nome.toLowerCase())) { visti.add(nome.toLowerCase()); out.push(nome); }
        });
        return out;
      }, [op.car, carScelti]);
      // Nessun CAR scelto di serie: il CAR dell'OP riceve già il riepilogo delle modifiche,
      // la mail «Segnala a CAR» va solo a chi scegli tu.
      const toggleSegnalaCar = () => setSegnalaCar(!segnalaCar);
      const isCarDellOp = (nome) => carDellOp.some((n) => n.toLowerCase() === String(nome).toLowerCase());
      const toggleCarScelto = (nome) => setCarScelti((prev) => (
        prev.some((n) => n.toLowerCase() === nome.toLowerCase())
          ? prev.filter((n) => n.toLowerCase() !== nome.toLowerCase()) : [...prev, nome]));

      // Preselezione da ?op= (promemoria in dashboard, mail).
      const initialOpApplied = useRef(false);
      useEffect(() => {
        if (initialOpApplied.current || !ordini.length) return;
        initialOpApplied.current = true;
        const found = INITIAL_OP ? ordini.find((o) => String(o.id || "").trim().toLowerCase() === INITIAL_OP) : null;
        const target = found || filteredOrdini[0];
        if (target) setSelectedOpKey(opKey(target));
        if (found && isMobile) setMobilePanel("serie");
      }, [ordini]);

      // ── Anomalie dell'OP ──
      const filteredSeriali = useMemo(() => {
        const q = searchSn.trim().toLowerCase();
        return anomalie.filter((a) => {
          if (snFilter === "da_decidere" && !isDaDecidere(a)) return false;
          if (!q) return true;
          return [a.sn, a.blocco_label, a.testo, a.desc, a.fase, a.local_id && `#${a.local_id}`]
            .some((v) => String(v || "").toLowerCase().includes(q));
        });
      }, [anomalie, searchSn, snFilter]);
      const openSeriali = useMemo(() => filteredSeriali.filter((a) => !a.chiudere), [filteredSeriali]);
      const closedSeriali = useMemo(() => filteredSeriali.filter((a) => a.chiudere), [filteredSeriali]);
      const ordineVisibile = useMemo(() => [...openSeriali, ...closedSeriali], [openSeriali, closedSeriali]);
      const nDaDecidere = useMemo(() => anomalie.filter(isDaDecidere).length, [anomalie]);
      const nAperte = useMemo(() => anomalie.filter((a) => !a.chiudere).length, [anomalie]);

      const sn = useMemo(() => anomalie.find((a) => a.item_id === selectedSnId) || {}, [anomalie, selectedSnId]);
      const posizione = ordineVisibile.findIndex((a) => a.item_id === sn.item_id);
      const isSelectedClosed = Boolean(sn.chiudere);
      const canEditSelected = canEditCurrentOp && !isSelectedClosed && !!sn.item_id;

      useEffect(() => {
        clearForm();
        setSelectedSnId("");
        if (!op || !op.item_id) { setAnomalie([]); return undefined; }
        // Una risposta arrivata dopo un cambio di OP va scartata: altrimenti l'elenco
        // mostrerebbe le anomalie di un altro OP sotto l'intestazione di questo, e un
        // salvataggio scriverebbe l'OP sbagliato sulla riga.
        let alive = true;
        setAnomalie([]);
        setLoadingAnom(true);
        fetch(`${API.anomalie}?op_item_id=${encodeURIComponent(op.item_id)}&op_id=${encodeURIComponent(op.id || "")}`, { credentials: "same-origin" })
          .then(r => readJsonOrThrow(r, "Caricamento anomalie"))
          .then(data => {
            if (!alive) return;
            const list = Array.isArray(data) ? data : [];
            setAnomalie(list);
            // Si apre la prima anomalia che aspetta una decisione.
            const first = list.find(isDaDecidere) || list.find((a) => !a.chiudere);
            setSelectedSnId(first ? first.item_id : "");
            setLoadingAnom(false);
          })
          .catch(e => { if (alive) { console.error("Errore caricamento anomalie:", e); setLoadingAnom(false); } });
        return () => { alive = false; };
      }, [op.item_id]);

      // Valori «di partenza» della decisione: servono a capire se ci sono modifiche.
      const baseline = useMemo(() => {
        const opts = buildAvanzamentoOptions(!!sn.aprire_rdc);
        const av = sn.avanzamento || DEFAULT_AVANZAMENTO;
        return {
          desc: sn.desc || "", note: sn.note || "", pezziPrec: !!sn.pezzi_prec, aprireRdc: !!sn.aprire_rdc,
          rdcNum: sn.numero_rdc || "", segnalare: !!sn.segnalare,
          terzista: !!sn.segnala_terzista, dovePezzi: sn.dove_pezzi || "",
          segnalaCar: !!sn.segnala_car, carScelti: Array.isArray(sn.car_segnalati) ? sn.car_segnalati : [],
          avanzamento: opts.some((o) => o.toLowerCase() === av.toLowerCase()) ? av : (opts[0] || DEFAULT_AVANZAMENTO),
          risposte: Object.fromEntries((sn.descrizioni || []).map((d) => [String(d.id), d.risposta || ""])),
        };
      }, [sn.item_id, sn.desc, sn.note, sn.pezzi_prec, sn.aprire_rdc, sn.numero_rdc, sn.segnalare, sn.segnala_terzista, sn.dove_pezzi, sn.segnala_car, sn.car_segnalati, sn.avanzamento, sn.descrizioni]);

      useEffect(() => {
        if (!sn.item_id) { clearForm(); return; }
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
        resetAmbito();
        setEditDesc(false);
      }, [sn.item_id]);

      const dirty = !!sn.item_id && canEditSelected && (
        desc !== baseline.desc || note !== baseline.note || pezziPrec !== baseline.pezziPrec
        || aprireRdc !== baseline.aprireRdc || segnalare !== baseline.segnalare
        || terzista !== baseline.terzista
        || segnalaCar !== baseline.segnalaCar
        || (segnalaCar && carScelti.join("|") !== baseline.carScelti.join("|"))
        || (aprireRdc && rdcNum !== baseline.rdcNum)
        || normalizeChoice(avanzamento).toLowerCase() !== normalizeChoice(baseline.avanzamento).toLowerCase()
        || Object.keys(descrizioneAnswers).some((k) => (descrizioneAnswers[k] || "") !== (baseline.risposte[k] || ""))
      );

      // Cambio di anomalia/OP con modifiche non salvate: si chiede cosa fare.
      const guard = (action) => {
        if (dirty) { setPendingNav(() => action); return; }
        action();
      };
      const selectSn = (a) => guard(() => { setSelectedSnId(a.item_id); if (isMobile) setMobilePanel("dettaglio"); });
      const selectOp = (o) => guard(() => { setSelectedOpKey(opKey(o)); if (isMobile) setMobilePanel("serie"); });
      const avviaClona = (o) => guard(() => {
        setSelectedOpKey(opKey(o));
        setClona({ opKey: opKey(o), ids: [] });
        setClosedCollapsed(false);
        if (isMobile) setMobilePanel("serie");
      });
      const clonaIds = clona && clona.opKey === opKey(op) ? clona.ids : null;
      const toggleClona = (ids, on) => setClona((prev) => {
        if (!prev) return prev;
        const resto = prev.ids.filter((x) => !ids.includes(x));
        return { ...prev, ids: on ? [...resto, ...ids] : resto };
      });
      const continuaClona = () => {
        if (!clonaIds || !clonaIds.length) return;
        // Stesso ordine dell'elenco, così i blocchi arrivano come li vedi qui.
        const ordinati = anomalie.map((a) => a.local_id).filter((x) => clonaIds.includes(x));
        window.location.href = `/gestione-anomalie/nuova-segnalazione?clona_da=${encodeURIComponent(op.id)}&anomalie=${ordinati.join(",")}`;
      };
      const vaiA = (delta) => {
        if (posizione < 0) return;
        const target = ordineVisibile[posizione + delta];
        if (target) selectSn(target);
      };

      // Altre anomalie aperte dello stesso blocco di seriali.
      // Altre anomalie aperte dell'OP; con «includi già decise» spento, solo quelle da decidere.
      const altreAperte = useMemo(() => (
        anomalie.filter((x) => x.item_id !== sn.item_id && !x.chiudere && (includiDecise || isDaDecidere(x)))
      ), [anomalie, sn && sn.item_id, includiDecise]);
      const stessoBlocco = useMemo(() => (
        sn && sn.blocco_id ? altreAperte.filter((x) => x.blocco_id === sn.blocco_id) : []
      ), [altreAperte, sn && sn.blocco_id]);
      const giaDecise = useMemo(() => (
        anomalie.filter((x) => x.item_id !== sn.item_id && !x.chiudere && !isDaDecidere(x)).length
      ), [anomalie, sn && sn.item_id]);
      const bersagli = useMemo(() => {
        if (ambito === "blocco") return stessoBlocco;
        if (ambito === "op") return altreAperte;
        if (ambito === "mano") return altreAperte.filter((x) => scelteMano.includes(x.item_id));
        return [];
      }, [ambito, stessoBlocco, altreAperte, scelteMano]);
      // Su una «Azione di recupero» senza azione effettuata la chiusura non è ammessa:
      // la decisione si applica, l'anomalia resta aperta.
      const chiudeBersaglio = (x) => chiudereAuto && !(x.serve_azione && !aprireRdc);
      const gruppiPerSn = (lista) => {
        const out = [];
        lista.forEach((x) => {
          const chiave = x.blocco_id ? `b${x.blocco_id}` : `s${x.sn}`;
          let g = out.find((y) => y.chiave === chiave);
          if (!g) { g = { chiave, titolo: x.blocco_label || x.sn || "—", righe: [] }; out.push(g); }
          g.righe.push(x);
        });
        return out;
      };

      // ── Allegati ──
      const attachmentsFor = useRef(null);
      const loadAttachments = async (localId) => {
        attachmentsFor.current = localId;
        setAttachments([]);
        if (!localId) return;
        setLoadingAttachments(true);
        try {
          const r = await fetch(`${API.allegati_list}?local_id=${encodeURIComponent(localId)}`, { credentials: "same-origin" });
          const d = await readJsonOrThrow(r, "Allegati");
          if (attachmentsFor.current !== localId) return;
          if (!r.ok || !d.success) throw new Error(d.error || "Errore caricamento allegati");
          setAttachments(Array.isArray(d.attachments) ? d.attachments : []);
        } catch (e) {
          setAttachments([]);
          flash({ ok: false, text: "Errore allegati: " + e.message });
        }
        setLoadingAttachments(false);
      };
      useEffect(() => { loadAttachments(currentLocalId); }, [currentLocalId]);

      const uploadFiles = async (files, ambito = "") => {
        if (!files.length) return;
        if (!canEditCurrentOp) { flash({ ok: false, text: "Permesso negato: non puoi caricare allegati su questo OP" }); return; }
        if (!currentLocalId) { flash({ ok: false, text: "Seleziona un'anomalia salvata per caricare allegati." }); return; }
        setUploadingAttachments(true);
        try {
          const form = new FormData();
          form.append("local_id", String(currentLocalId));
          files.forEach((f) => form.append("files", f));
          if (ambito) form.append("ambito", ambito);
          const r = await fetch(API.allegati_upload, { method: "POST", headers: { "X-CSRFToken": getCsrfToken() }, body: form, credentials: "same-origin" });
          const d = await readJsonOrThrow(r, "Upload allegati");
          if (Array.isArray(d.attachments)) setAttachments(d.attachments);
          if (Array.isArray(d.errors) && d.errors.length) flash({ ok: false, text: "Upload parziale: " + d.errors.join(" | ") });
          else if (!r.ok) throw new Error(d.error || "Upload non riuscito");
          else flash({ ok: true, text: `${files.length} allegat${files.length === 1 ? "o caricato" : "i caricati"}` });
        } catch (e) {
          flash({ ok: false, text: "Errore upload allegati: " + e.message });
        }
        setUploadingAttachments(false);
      };

      const handleDeleteAttachment = async (fileId) => {
        setConfirmDelete(null);
        if (!currentLocalId || !fileId) return;
        try {
          const r = await fetch(API.allegati_delete, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
            body: JSON.stringify({ local_id: currentLocalId, file_id: fileId }),
            credentials: "same-origin",
          });
          const d = await readJsonOrThrow(r, "Elimina allegato");
          if (!r.ok || !d.success) throw new Error(d.error || "Eliminazione non riuscita");
          setAttachments(Array.isArray(d.attachments) ? d.attachments : []);
        } catch (e) {
          flash({ ok: false, text: "Errore eliminazione allegato: " + e.message });
        }
      };

      const getAttachmentUrl = (fileId, forceDownload = false) =>
        `${API.allegati_file}?local_id=${encodeURIComponent(currentLocalId)}&file_id=${encodeURIComponent(fileId)}${forceDownload ? "&download=1" : ""}`;
      const immagini = attachments.filter((f) => f.is_image);
      // Gli allegati della decisione del capocommessa stanno nel suo riquadro.
      const attAnomalia = attachments.filter((f) => !f.decisione);
      const attDecisione = attachments.filter((f) => f.decisione);
      const renderAttGrid = (list) => (
        <div className="ga-att__grid">
          {list.map((file) => (
                                <div key={file.file_id} className="ga-att__item" title={`${file.name} · ${formatBytes(file.size)}`}>
                                  {file.is_image ? (
                                    <button type="button" className="ga-att__thumb" onClick={() => setLightbox(file.file_id)}>
                                      <img src={getAttachmentUrl(file.file_id)} alt={file.name} loading="lazy" />
                                    </button>
                                  ) : (
                                    <a className="ga-att__thumb ga-att__thumb--file" href={getAttachmentUrl(file.file_id)} target="_blank" rel="noopener">
                                      {(fileExt(file.name).replace(".", "").toUpperCase() || "FILE").slice(0, 4)}
                                    </a>
                                  )}
                                  <div className="ga-att__name">{file.name}</div>
                                  <div className="ga-att__acts">
                                    <a href={getAttachmentUrl(file.file_id, true)} title="Scarica">Scarica</a>
                                    {canEditCurrentOp && (confirmDelete === file.file_id
                                      ? <button type="button" className="is-danger" onClick={() => handleDeleteAttachment(file.file_id)}>Conferma</button>
                                      : <button type="button" onClick={() => setConfirmDelete(file.file_id)}>Elimina</button>)}
                                  </div>
                                </div>
                              ))}
        </div>
      );
      const lightboxIdx = immagini.findIndex((f) => f.file_id === lightbox);

      // ── Salvataggio ──
      const handleSave = async (confermato = false, prossima = false) => {
        if (!op.id || op.id === "—") { flash({ ok: false, text: "Seleziona un ordine prima di salvare" }); return false; }
        if (!canEditCurrentOp) { flash({ ok: false, text: "Permesso negato: non puoi modificare questo OP" }); return false; }
        if (isSelectedClosed) { flash({ ok: false, text: "Anomalia chiusa: in sola lettura" }); return false; }
        if (!currentItemId) { flash({ ok: false, text: "Seleziona un'anomalia" }); return false; }
        if (notaSenzaStato) { flash({ ok: false, text: NOTA_STATO_MSG }, 7000); return false; }
        if (ambito === "mano" && !bersagli.length) { flash({ ok: false, text: "Scegli almeno un'altra anomalia, oppure «Solo questa»." }, 6000); return false; }
        if (bersagli.length && !confermato) { setRiepilogo({ prossima }); return false; }
        setSaving(true);
        let ok = false;
        try {
          const r = await fetch(API.salva, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
            body: JSON.stringify({
              item_id: currentItemId, op_id: op.id, sn: sn.sn || "", desc,
              descrizioni_risposte: descrizioneAnswers, note, pezzi_prec: pezziPrec,
              aprire_rdc: aprireRdc, numero_rdc: aprireRdc ? rdcNum : "", segnalare,
              segnala_terzista: terzista,
              segnala_car: segnalaCar, car_segnalati: segnalaCar ? carScelti : [],
              chiudere: chiudereAuto, avanzamento,
            }),
            credentials: "same-origin",
          });
          const data = await readJsonOrThrow(r, "Salvataggio anomalia");
          if (!data.success) throw new Error(data.error || "risposta non valida");
          ok = true;
          const aggiornato = {
            desc, note, pezzi_prec: pezziPrec, aprire_rdc: aprireRdc, numero_rdc: aprireRdc ? rdcNum : "",
            segnalare, segnala_terzista: terzista,
            segnala_car: segnalaCar && carScelti.length > 0, car_segnalati: segnalaCar ? carScelti : [],
            chiudere: chiudereAuto, avanzamento,
            descrizioni: (sn.descrizioni || []).map((d) => ({ ...d, risposta: descrizioneAnswers[String(d.id)] || "" })),
          };
          setAnomalie((prev) => prev.map((a) => (a.item_id === currentItemId ? { ...a, ...aggiornato } : a)));
          let testo = chiudereAuto ? "Decisione salvata · anomalia chiusa" : "Decisione salvata";
          if (bersagli.length) {
            let n = 0;
            const errori = [];
            for (const f of bersagli) {
              const chiudeF = chiudeBersaglio(f);
              try {
                const rf = await fetch(API.salva, {
                  method: "POST",
                  headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
                  body: JSON.stringify({
                    item_id: f.item_id, op_id: op.id, sn: f.sn || "", desc: f.desc || "",
                    note, pezzi_prec: !!f.pezzi_prec, aprire_rdc: aprireRdc, numero_rdc: aprireRdc ? rdcNum : "",
                    segnalare, segnala_terzista: terzista, chiudere: chiudeF, avanzamento,
                  }),
                  credentials: "same-origin",
                });
                const df = await readJsonOrThrow(rf, "Salvataggio anomalia");
                if (!df.success) throw new Error(df.error || "errore");
                n += 1;
                setAnomalie((prev) => prev.map((a) => (a.item_id === f.item_id ? {
                  ...a, note, aprire_rdc: aprireRdc, numero_rdc: aprireRdc ? rdcNum : "", segnalare,
                  segnala_terzista: terzista, chiudere: chiudeF, avanzamento,
                } : a)));
              } catch (err) {
                errori.push(`#${f.local_id}: ${err.message}`);
              }
            }
            resetAmbito();
            if (errori.length) {
              flash({ ok: false, text: `Salvata; delle altre ${n} aggiornate e ${errori.length} no (${errori.join("; ")})` }, 8000);
              testo = "";
            } else {
              testo += ` · applicata anche ad altr${n === 1 ? "a" : "e"} ${n}`;
            }
          }
          if (testo) flash({ ok: true, text: data.protocollo ? `${testo} · ${data.protocollo}` : testo });
          loadOrdini();
          caricaCoda();
        } catch (e) {
          flash({ ok: false, text: "Errore: " + e.message }, 7000);
        }
        setSaving(false);
        return ok;
      };

      // La prossima è la successiva in elenco ancora da decidere (o la successiva aperta).
      const trovaProssima = (escluse = []) => {
        const via = new Set([sn.item_id, ...escluse]);
        const dopo = ordineVisibile.slice(posizione + 1);
        return dopo.find((a) => isDaDecidere(a) && !via.has(a.item_id))
          || ordineVisibile.find((a) => isDaDecidere(a) && !via.has(a.item_id))
          || dopo.find((a) => !a.chiudere && !via.has(a.item_id));
      };
      const salvaEProssima = async () => {
        const prossima = trovaProssima(bersagli.map((x) => x.item_id));
        if (!(await handleSave(false, true))) return;
        vaiAllaProssima(prossima);
      };
      const vaiAllaProssima = (prossima) => {
        if (prossima) setSelectedSnId(prossima.item_id);
        else flash({ ok: true, text: "Decisione salvata · nessun'altra anomalia da decidere su questo OP" });
      };

      const annullaModifiche = () => {
        setDesc(baseline.desc); setNote(baseline.note); setPezziPrec(baseline.pezziPrec);
        setAprireRdc(baseline.aprireRdc); setRdcNum(baseline.rdcNum); setSegnalare(baseline.segnalare);
        setTerzista(baseline.terzista); setDovePezzi(baseline.dovePezzi);
        setSegnalaCar(baseline.segnalaCar); setCarScelti(baseline.carScelti);
        setAvanzamento(baseline.avanzamento); setDescrizioneAnswers(baseline.risposte); setEditDesc(false);
      };

      // «Segnalato» (cliente/terzista): si registra subito, senza mail di aggiornamento.
      const [segnalatoInCorso, setSegnalatoInCorso] = useState("");
      const toggleSegnalato = async (chi) => {
        if (!sn.local_id || !API.segnalato || segnalatoInCorso) return;
        const campo = `segnalato_${chi}`;
        const acceso = !sn[campo];
        setSegnalatoInCorso(chi);
        try {
          const r = await fetch(API.segnalato, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
            body: JSON.stringify({ local_id: sn.local_id, chi, segnalato: acceso }),
            credentials: "same-origin",
          });
          const data = await readJsonOrThrow(r, "Segnalato");
          if (!data.success) throw new Error(data.error || "risposta non valida");
          setAnomalie((prev) => prev.map((a) => (a.item_id === sn.item_id ? { ...a, [campo]: data.segnalato || null } : a)));
          flash({ ok: true, text: acceso ? `Segnalato ${chi === "cliente" ? "al cliente" : "al terzista"} · registrato, nessuna mail inviata` : "Spunta «Segnalato» tolta" });
        } catch (e) {
          flash({ ok: false, text: "Errore: " + e.message }, 7000);
        }
        setSegnalatoInCorso("");
      };
      const rigaSegnalato = (chi, richiesto, salvato) => {
        if (!richiesto) return null;
        const campo = `segnalato_${chi}`;
        const fatto = sn[campo];
        const label = `Segnalato ${chi === "cliente" ? "al cliente" : "al terzista"}`;
        if (!salvato) {
          return <div key={chi} className="ga-hint">Salva la decisione per poter spuntare «{label}».</div>;
        }
        return (
          <div key={chi} className="ga-segnalato">
            <FlagToggle label={segnalatoInCorso === chi ? "Salvataggio…" : label}
              hint="Registra che l'hai già avvisato: non parte nessuna mail"
              checked={!!fatto} disabled={!canEditCurrentOp || !!segnalatoInCorso} onChange={() => toggleSegnalato(chi)} />
            <span className="ga-hint">{fatto ? `il ${fatto.il}${fatto.da ? ` da ${fatto.da}` : ""} · nessuna mail inviata` : "Si registra subito, senza mail."}</span>
          </div>
        );
      };

      // Riapertura: capocommessa, CAR, controllore o chi modifica l'OP (deciso dal server).
      const riapri = async () => {
        if (!sn.local_id || !API.riapri) return;
        setSaving(true);
        try {
          const r = await fetch(API.riapri, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
            body: JSON.stringify({ local_id: sn.local_id }),
            credentials: "same-origin",
          });
          const data = await readJsonOrThrow(r, "Riapertura anomalia");
          if (!data.success) throw new Error(data.error || "risposta non valida");
          setAnomalie((prev) => prev.map((a) => (a.item_id === sn.item_id
            ? { ...a, chiudere: false, avanzamento: "In attesa", can_riaprire: false } : a)));
          setAvanzamento("In attesa");
          flash({ ok: true, text: `Anomalia #${sn.local_id} riaperta · in attesa di decisione` });
          loadOrdini();
        } catch (e) {
          flash({ ok: false, text: "Errore: " + e.message }, 7000);
        }
        setSaving(false);
      };

      const ricaricaAnomalie = async () => {
        if (!op || !op.item_id) return;
        const r = await fetch(`${API.anomalie}?op_item_id=${encodeURIComponent(op.item_id)}&op_id=${encodeURIComponent(op.id || "")}`, { credentials: "same-origin" });
        const list = await readJsonOrThrow(r, "Caricamento anomalie");
        setAnomalie(Array.isArray(list) ? list : []);
        return Array.isArray(list) ? list : [];
      };
      const postAzione = async (url, body, contesto) => {
        const r = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
          body: JSON.stringify(body),
          credentials: "same-origin",
        });
        const data = await readJsonOrThrow(r, contesto);
        if (!data.success) throw new Error(data.error || "risposta non valida");
        return data;
      };
      const apriTaglia = () => {
        setAzAnom({ tipo: "taglia", op: op.id || "", sn: "", seriali: [], busy: false, err: "" });
      };
      // S/N noti dell'OP di destinazione, come suggerimenti.
      useEffect(() => {
        if (!azAnom || azAnom.tipo !== "taglia" || !API.seriali_op) return undefined;
        const opDest = String(azAnom.op || "").trim();
        if (!opDest) return undefined;
        let alive = true;
        const t = setTimeout(() => {
          fetch(`${API.seriali_op}?op_id=${encodeURIComponent(opDest)}`, { credentials: "same-origin" })
            .then((r) => (r.ok ? r.json() : { seriali: [] }))
            .then((d) => { if (alive) setAzAnom((p) => (p ? { ...p, seriali: Array.isArray(d.seriali) ? d.seriali : [] } : p)); })
            .catch(() => {});
        }, 300);
        return () => { alive = false; clearTimeout(t); };
      }, [azAnom && azAnom.tipo, azAnom && azAnom.op]);
      const confermaAzione = async () => {
        if (!azAnom || !sn.local_id) return;
        const id = sn.local_id;
        if (azAnom.tipo === "taglia") {
          if (!String(azAnom.op || "").trim()) { setAzAnom({ ...azAnom, err: "Indica l'OP." }); return; }
          if (!String(azAnom.sn || "").trim()) { setAzAnom({ ...azAnom, err: "Indica il S/N di destinazione." }); return; }
        }
        setAzAnom({ ...azAnom, busy: true, err: "" });
        try {
          if (azAnom.tipo === "elimina") {
            await postAzione(API.elimina, { local_id: id }, "Elimina anomalia");
            flash({ ok: true, text: `Anomalia #${id} eliminata` });
          } else {
            const dest = ordini.find((o) => String(o.id || "").toLowerCase() === String(azAnom.op).trim().toLowerCase());
            const seriali = String(azAnom.sn).split(/[,;\n]+/).map((s) => s.trim()).filter(Boolean);
            const data = await postAzione(API.sposta, {
              local_id: id, op_id: String(azAnom.op).trim(), op_item_id: dest ? dest.item_id : null, seriali,
            }, "Taglia");
            flash({ ok: true, text: `Anomalia #${id}: ${data.nota || "spostata"}` }, 6000);
          }
          setAzAnom(null);
          setCurrentItemId(null);
          const list = await ricaricaAnomalie();
          const ancora = (list || []).find((a) => a.local_id === id);
          const first = ancora || (list || []).find(isDaDecidere) || (list || []).find((a) => !a.chiudere);
          setSelectedSnId(first ? first.item_id : "");
          loadOrdini();
        } catch (e) {
          setAzAnom((p) => (p ? { ...p, busy: false, err: e.message } : p));
        }
      };

      const apriModificaOp = async (o) => {
        if (!API.op_modifica) return;
        setModOp({ titolo: o.id, dati: null, iniz: null, motivo: "", busy: true, err: "" });
        try {
          const r = await fetch(`${API.op_modifica}?item_id=${encodeURIComponent(o.item_id)}`, { credentials: "same-origin" });
          const d = await readJsonOrThrow(r, "Modifica OP");
          setModOp({ titolo: o.id, dati: { ...d.op }, iniz: { ...d.op }, motivo: "", busy: false, err: "" });
        } catch (e) {
          setModOp({ titolo: o.id, dati: null, iniz: null, motivo: "", busy: false, err: e.message });
        }
      };
      const campoModOp = (campo, valore) => setModOp((p) => (p ? { ...p, dati: { ...p.dati, [campo]: valore }, err: "" } : p));
      const modOpCambiato = !!(modOp && modOp.dati && modOp.iniz
        && ["pn", "capocommessa", "car", "fase", "note", "benestare"].some((k) => String(modOp.dati[k] ?? "").trim() !== String(modOp.iniz[k] ?? "").trim()));
      const salvaModificaOp = async () => {
        if (!modOp || !modOp.dati) return;
        if (!modOpCambiato) { setModOp({ ...modOp, err: "Non hai cambiato nessun dato." }); return; }
        if (String(modOp.motivo || "").trim().length < 5) { setModOp({ ...modOp, err: "Scrivi il motivo della modifica." }); return; }
        setModOp({ ...modOp, busy: true, err: "" });
        try {
          const { item_id, pn, capocommessa, car, fase, note: noteOp, benestare } = modOp.dati;
          const data = await postAzione(API.op_modifica, {
            item_id, pn, capocommessa, car, fase, note: noteOp, benestare, motivazione: modOp.motivo,
          }, "Modifica OP");
          setModOp(null);
          flash({ ok: true, text: `${modOp.titolo}: ${(data.modifiche || []).map((m) => m.etichetta).join(", ") || "dati"} modificati` }, 5000);
          loadOrdini();
        } catch (e) {
          setModOp((p) => (p ? { ...p, busy: false, err: e.message } : p));
        }
      };

      const duplica = () => {
        setMenuOpen(false);
        setCurrentItemId(null);
        flash({ ok: true, text: "Copia pronta: modifica e salva per creare un nuovo record" });
      };

      // Ctrl+S salva, frecce Alt+↑/↓ scorrono le anomalie.
      useEffect(() => {
        const onKey = (e) => {
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
            e.preventDefault();
            if (canEditSelected && !saving) handleSave();
          } else if (e.altKey && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
            e.preventDefault();
            vaiA(e.key === "ArrowDown" ? 1 : -1);
          } else if (e.key === "Escape") {
            setLightbox(null); setMenuOpen(false);
          }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
      });

      useEffect(() => {
        const handler = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
        window.addEventListener("beforeunload", handler);
        return () => window.removeEventListener("beforeunload", handler);
      }, [dirty]);

      const handleOpenReport = (format) => {
        setMenuOpen(false);
        const params = new URLSearchParams();
        if (op.item_id) params.set("op_item_id", op.item_id);
        else if (op.id) params.set("op_id", op.id);
        else if (currentLocalId) params.set("id", currentLocalId);
        else return;
        if (format === "pdf") params.set("format", "pdf");
        window.open(`${API.report}?${params.toString()}`, "_blank", "noopener");
      };

      const statoSel = statoAnomalia(sn);
      const isBenestare = String(op.stato || "").toLowerCase() === "benestare";
      const showCol = (name) => !isMobile || mobilePanel === name;

      // ── Rendering elenco anomalie (con intestazione per blocco di seriali) ──
      const renderAnomalia = (a) => {
        const st = statoAnomalia(a);
        const selected = a.item_id === sn.item_id;
        const inClona = clonaIds && clonaIds.includes(a.local_id);
        return (
          <button type="button" key={a.item_id} className={`ga-an${selected ? " is-sel" : ""}${a.chiudere ? " is-closed" : ""}${inClona ? " is-clona" : ""}`}
            onClick={() => { if (clonaIds) toggleClona([a.local_id], !inClona); selectSn(a); }}>
            {clonaIds
              ? <span className={`ga-an__check${inClona ? " is-on" : ""}`} aria-hidden="true">{inClona ? Ico.check : null}</span>
              : <span className={`ga-an__dot ga-an__dot--${st.variant}`} />}
            <span className="ga-an__main">
              <span className="ga-an__txt">{a.blocco_id ? (a.testo || a.desc || "(nessuna descrizione)") : (a.sn ? `S/N ${a.sn}` : (a.testo || a.desc || "—"))}</span>
              <span className="ga-an__meta">
                <span className={`ga-pill ga-pill--${st.variant}`}>{st.text}</span>
                {a.aprire_rdc && <span className="ga-pill ga-pill--rdc">RDC{a.numero_rdc ? ` ${a.numero_rdc}` : ""}</span>}
                {a.segnalare && <span className="ga-pill ga-pill--cli">Cliente</span>}
                {a.segnala_terzista && <span className="ga-pill ga-pill--ter">Terzista</span>}
                {a.seriali_parziali && <span className="ga-pill ga-pill--muted" title={`Solo sui S/N: ${a.seriali_parziali}`}>Solo {a.seriali_parziali}</span>}
                {!a.blocco_id && (a.testo || a.desc) && <span className="ga-an__sub">{a.testo || a.desc}</span>}
                <span className="ga-an__id">#{a.local_id}</span>
              </span>
            </span>
          </button>
        );
      };
      const renderGrouped = (list) => list.map((a, idx) => {
        const prev = idx > 0 ? list[idx - 1] : null;
        if (!a.blocco_id || (prev && prev.blocco_id === a.blocco_id)) return renderAnomalia(a);
        const delBlocco = list.filter((y) => y.blocco_id === a.blocco_id);
        const daDec = delBlocco.filter(isDaDecidere).length;
        const idsBlocco = delBlocco.map((y) => y.local_id);
        const bloccoTutto = Boolean(clonaIds) && idsBlocco.every((x) => clonaIds.includes(x));
        return (
          <React.Fragment key={`blk-${a.blocco_id}-${a.item_id}`}>
            <div className="ga-blk">
              <div className="ga-blk__sn">
                {clonaIds && (
                  <label className="ga-blk__clona" title="Copia tutte le anomalie di questo blocco">
                    <input type="checkbox" checked={bloccoTutto} onChange={(e) => toggleClona(idsBlocco, e.target.checked)} />
                  </label>
                )}
                {a.blocco_label || a.sn || "—"}
              </div>
              <div className="ga-blk__meta">
                {[a.fase ? `Fase ${a.fase}` : "", a.controllo_operatore, fmtData(a.controllo_data)].filter(Boolean).join(" · ")}
                {daDec > 0 && <span className="ga-blk__todo">{daDec} da decidere</span>}
              </div>
            </div>
            {renderAnomalia(a)}
          </React.Fragment>
        );
      });

      return (
        <div className={`ga${isMobile ? " ga--mobile" : ""}`}>
          {/* ── Barra superiore ── */}
          <header className="ga-top">
            <div className="ga-top__left">
              <a href="/anomalie-menu" className="ga-iconbtn" title="Torna al menu anomalie">{Ico.back}</a>
              <h1 className="ga-top__title">{isMobile && mobilePanel !== "ordini" && op.id ? op.id : "Gestione anomalie"}</h1>
              {!isMobile && op.id && <span className="ga-top__op">{op.id}{op.pn && op.pn !== "—" ? ` · ${op.pn}` : ""}</span>}
            </div>
            <div className="ga-top__right">
              <a className="ga-btn ga-btn--accent" href={nuovaAnomaliaUrl} title="Apri un nuovo controllo con segnalazione di anomalie">
                {Ico.plus}{!isMobile && <span>Nuova segnalazione</span>}
              </a>
              {!isMobile && API.nc_lista && <a className="ga-btn ga-btn--ghost" href={API.nc_lista}>Non conformità</a>}
              <div className="ga-menu">
                <button type="button" className="ga-iconbtn" title="Altre azioni" aria-expanded={menuOpen} onClick={() => setMenuOpen((v) => !v)}>{Ico.more}</button>
                {menuOpen && (
                  <>
                    <div className="ga-menu__scrim" onClick={() => setMenuOpen(false)} />
                    <div className="ga-menu__pop" role="menu">
                      <button type="button" role="menuitem" disabled={!op.id} onClick={() => handleOpenReport()}>Report OP</button>
                      <button type="button" role="menuitem" disabled={!op.id} onClick={() => handleOpenReport("pdf")}>Report OP in PDF</button>
                      <button type="button" role="menuitem" disabled={!canEditSelected} onClick={duplica}>Duplica anomalia come nuovo record</button>
                      {isMobile && API.nc_lista && <a role="menuitem" href={API.nc_lista}>Non conformità</a>}
                      {IS_ADMIN && ADMIN_URL && <a role="menuitem" href={ADMIN_URL}>Configurazione modulo</a>}
                    </div>
                  </>
                )}
              </div>
            </div>
          </header>

          <div className="ga-cols" style={isMobile ? undefined : { gridTemplateColumns: isTablet ? "250px 270px minmax(0,1fr)" : "310px 330px minmax(0,1fr)" }}>

            {/* ── 1. Ordini di produzione ── */}
            <section className="ga-col ga-col--op" style={{ display: showCol("ordini") ? undefined : "none" }}>
              <div className="ga-col__head">
                <div className="ga-col__title">Ordini di produzione</div>
                <div className="ga-chips">
                  {[["aperte", "Con aperte"], ["in_carico", "In carico a me"], ["tutti", "Tutti"]].map(([v, l]) => (
                    <Chip key={v} active={pageFilter === v} count={loadingOrdini ? "…" : contatoriFiltro[v]}
                      onClick={() => setPageFilter(v)}>{l}</Chip>
                  ))}
                </div>
                <div className="ga-search">
                  {Ico.search}
                  <input value={searchOp} onChange={(e) => setSearchOp(e.target.value)} placeholder="Cerca OP, P/N, capocommessa, CAR…" />
                </div>
              </div>
              <div className="ga-col__body">
                {loadingOrdini ? <div className="ga-empty">Caricamento ordini…</div>
                  : filteredOrdini.length === 0 ? (
                    <div className="ga-empty">
                      {pageFilter === "in_carico" ? "Nessun OP con anomalie aperte in carico a te."
                        : pageFilter === "aperte" ? "Nessun OP con anomalie aperte." : "Nessun ordine trovato."}
                    </div>
                  ) : filteredOrdini.map((o) => {
                    const sel = opKey(o) === opKey(op);
                    const tot = Number(o.anomalie_count || 0);
                    const aperte = apertiDi(o);
                    const daDec = daDecidereDi(o);
                    const chiuse = Math.max(0, tot - aperte);
                    return (
                      <div key={opKey(o)} className="ga-op-wrap">
                      <button type="button" className={`ga-op${sel ? " is-sel" : ""}`} onClick={() => selectOp(o)}>
                        <span className="ga-op__row">
                          <span className="ga-op__id">{o.id}</span>
                          {String(o.stato || "").toLowerCase() === "benestare" && <span className="ga-pill ga-pill--ben">Benestare</span>}
                          {daDec > 0 && <span className="ga-op__todo" title="Anomalie in attesa di decisione">{daDec}</span>}
                        </span>
                        <span className="ga-op__pn">P/N {o.pn}</span>
                        <span className="ga-op__people">{Ico.user}{o.capo}{o.car && o.car !== "—" ? ` · CAR ${o.car}` : ""}</span>
                        {tot > 0 ? (
                          <span className="ga-op__bar" title={`${chiuse} chiuse su ${tot}`}>
                            <span className="ga-op__bar-fill" style={{ width: `${Math.round((chiuse / tot) * 100)}%` }} />
                            <span className="ga-op__bar-txt">{aperte} apert{aperte === 1 ? "a" : "e"} · {tot} total{tot === 1 ? "e" : "i"}</span>
                          </span>
                        ) : <span className="ga-op__none">Nessuna anomalia</span>}
                      </button>
                      {(tot > 0 || o.can_modifica_op) && (
                        <span className={`ga-op__acts${clona && clona.opKey === opKey(o) ? " is-on" : ""}`}>
                          {o.can_modifica_op && (
                            <button type="button" className="ga-op__clona" title="Correggi i dati dell'OP che hai inserito tu"
                              onClick={() => apriModificaOp(o)}>
                              {Ico.edit}<span>Modifica OP</span>
                            </button>
                          )}
                          {tot > 0 && (
                            <button type="button" className={`ga-op__clona${clona && clona.opKey === opKey(o) ? " is-on" : ""}`}
                              title="Clona: scegli le anomalie da copiare su un nuovo OP" onClick={() => avviaClona(o)}>
                              {Ico.copy}<span>Clona</span>
                            </button>
                          )}
                        </span>
                      )}
                      </div>
                    );
                  })}
              </div>
            </section>

            {/* ── 2. Anomalie dell'OP ── */}
            <section className="ga-col ga-col--sn" style={{ display: showCol("serie") ? undefined : "none" }}>
              <div className="ga-col__head">
                <div className="ga-col__title">
                  Anomalie {op.id ? <span className="ga-col__sub">{nAperte} apert{nAperte === 1 ? "a" : "e"} su {anomalie.length}</span> : null}
                </div>
                {clonaIds && (
                  <div className="ga-note ga-note--info">
                    <b>Clona {op.id}</b>: spunta le anomalie da copiare sul nuovo OP (anche le chiuse), poi «Continua».
                  </div>
                )}
                <div className="ga-chips">
                  <Chip active={snFilter === "tutte"} onClick={() => setSnFilter("tutte")} count={anomalie.length}>Tutte</Chip>
                  <Chip active={snFilter === "da_decidere"} onClick={() => setSnFilter("da_decidere")} count={nDaDecidere} tone="warn">Da decidere</Chip>
                </div>
                <div className="ga-search">
                  {Ico.search}
                  <input value={searchSn} onChange={(e) => setSearchSn(e.target.value)} placeholder="Cerca S/N, testo, #numero…" />
                </div>
              </div>
              <div className="ga-col__body">
                {loadingAnom ? <div className="ga-empty">Caricamento…</div>
                  : !op.id ? <div className="ga-empty">Seleziona un ordine.</div>
                  : filteredSeriali.length === 0 ? (
                    <div className="ga-empty">
                      {snFilter === "da_decidere" && anomalie.length ? "Nessuna anomalia da decidere: tutto gestito. ✓" : (searchSn ? "Nessuna anomalia corrisponde alla ricerca." : "Nessuna anomalia registrata.")}
                      {canEditCurrentOp && !anomalie.length && <a className="ga-btn ga-btn--accent ga-btn--sm" href={nuovaAnomaliaUrl}>{Ico.plus}Nuova segnalazione</a>}
                    </div>
                  ) : (
                    <>
                      {renderGrouped(openSeriali)}
                      {closedSeriali.length > 0 && (
                        <div className="ga-closed">
                          <button type="button" className="ga-closed__toggle" onClick={() => setClosedCollapsed((v) => !v)}>
                            <span style={{ transform: closedCollapsed ? "rotate(-90deg)" : "none" }}>▾</span> Chiuse ({closedSeriali.length})
                          </button>
                          {!closedCollapsed && renderGrouped(closedSeriali)}
                        </div>
                      )}
                    </>
                  )}
              </div>
              {clonaIds && (
                <div className="ga-clona">
                  <div className="ga-clona__top">
                    <span><b>{clonaIds.length}</b> da copiare</span>
                    <button type="button" className="ga-link" onClick={() => toggleClona(anomalie.map((a) => a.local_id), true)}>Tutte</button>
                    <button type="button" className="ga-link" onClick={() => toggleClona(anomalie.filter((a) => !a.chiudere).map((a) => a.local_id), true)}>Aperte</button>
                    <button type="button" className="ga-link" onClick={() => setClona((p) => (p ? { ...p, ids: [] } : p))}>Nessuna</button>
                  </div>
                  <div className="ga-clona__acts">
                    <button type="button" className="ga-btn ga-btn--ghost-dark ga-btn--xs" onClick={() => setClona(null)}>Annulla</button>
                    <button type="button" className="ga-btn ga-btn--accent ga-btn--xs" disabled={!clonaIds.length} onClick={continuaClona}>Continua {Ico.next}</button>
                  </div>
                </div>
              )}
            </section>

            {/* ── 3. Dettaglio ── */}
            <section className="ga-col ga-col--det" style={{ display: showCol("dettaglio") ? undefined : "none" }}>
              {/* Decisioni salvate sull'OP e non ancora partite nel riepilogo: sempre in vista,
                  anche quando l'anomalia aperta è ormai chiusa. */}
              {coda && coda.n > 0 && (() => {
                const min = Math.max(0, Math.ceil((new Date(coda.partenza).getTime() - Date.now()) / 60000));
                return (
                  <div className="ga-coda" role="status"
                    title="Il riepilogo a capocommessa, CAR e segnalanti parte dopo una pausa sull'OP; ogni salvataggio fa ripartire l'attesa">
                    <span className="ga-coda__dot" />
                    <span className="ga-coda__txt"><b>{coda.n}</b> decision{coda.n === 1 ? "e" : "i"} in attesa di invio · {min > 0 ? `il riepilogo parte fra ${min} min` : "in partenza"}</span>
                    <button type="button" className="ga-btn ga-btn--outline ga-btn--xs" disabled={inviando} onClick={inviaOra}>{inviando ? "Invio…" : "Invia ora"}</button>
                  </div>
                );
              })()}
              {!sn.item_id ? (
                <div className="ga-empty ga-empty--big">
                  {op.id ? "Seleziona un'anomalia dall'elenco." : "Seleziona un ordine di produzione."}
                </div>
              ) : (
                <>
                  <div className="ga-det__head">
                    <div className="ga-det__crumb">
                      <span>{op.id}</span>
                      {op.pn && op.pn !== "—" && <><span className="ga-det__sep">·</span><span>P/N <b className="ga-det__pn">{op.pn}</b></span></>}
                      {sn.fase &&<><span className="ga-det__sep">›</span><span>Fase {sn.fase}</span></>}
                      <span className={`ga-pill ${isBenestare ? "ga-pill--ben" : "ga-pill--muted"}`}>{isBenestare ? "Collaudo di benestare" : "Altro controllo"}</span>
                    </div>
                    <div className="ga-det__titlerow">
                      <h2 className="ga-det__title">Anomalia #{sn.local_id}</h2>
                      <span className={`ga-pill ga-pill--${statoSel.variant} ga-pill--lg`}>{statoSel.text}</span>
                      <div className="ga-det__nav">
                        <button type="button" className="ga-iconbtn ga-iconbtn--light" disabled={posizione <= 0} onClick={() => vaiA(-1)} title="Anomalia precedente (Alt+↑)">{Ico.prev}</button>
                        <span>{posizione + 1} di {ordineVisibile.length}</span>
                        <button type="button" className="ga-iconbtn ga-iconbtn--light" disabled={posizione < 0 || posizione >= ordineVisibile.length - 1} onClick={() => vaiA(1)} title="Anomalia successiva (Alt+↓)">{Ico.next}</button>
                      </div>
                    </div>
                    <PezziInteressati sn={sn} />
                    <div className="ga-det__people">
                      <span><b>Capocommessa</b> {op.capo || "—"}</span>
                      <span><b>CAR</b> {op.car || "—"}</span>
                      {sn.controllo_operatore && <span><b>Segnalata da</b> {sn.controllo_operatore}{sn.controllo_data ? ` il ${fmtData(sn.controllo_data)}` : ""}</span>}
                    </div>
                  </div>

                  <div className="ga-det__body">
                    {!canEditCurrentOp && <div className="ga-note ga-note--warn">Sola lettura: puoi consultare ma non decidere su questo OP.</div>}
                    {isSelectedClosed && (canEditCurrentOp || sn.can_riaprire) && (
                      <div className="ga-note ga-note--ok ga-note--row">
                        <span>Anomalia chiusa: i dati restano consultabili ma non modificabili.</span>
                        {sn.can_riaprire && <button type="button" className="ga-btn ga-btn--outline ga-btn--xs" onClick={riapri} disabled={saving}>{saving ? "Riapertura…" : "Riapri anomalia"}</button>}
                      </div>
                    )}

                    {/* Segnalazione */}
                    <div className="ga-card">
                      <div className="ga-card__head">
                        <span className="ga-card__title">Segnalazione</span>
                        {sn.stato_superficie && <span className="ga-pill ga-pill--sup">{sn.stato_superficie}</span>}
                        {canEditSelected && !editDesc && <button type="button" className="ga-link" onClick={() => setEditDesc(true)}>Modifica testo</button>}
                        {sn.can_sposta && <button type="button" className="ga-link" title="Sposta su un altro S/N dello stesso OP o di un altro OP" onClick={apriTaglia}>✂ Taglia</button>}
                        {sn.can_elimina && <button type="button" className="ga-link ga-link--danger" title="Solo chi l'ha inserita, finché nessuno ci ha lavorato" onClick={() => setAzAnom({ tipo: "elimina", busy: false, err: "" })}>Elimina</button>}
                      </div>
                      {editDesc ? (
                        <textarea className="ga-input" rows={4} value={desc} onChange={(e) => setDesc(e.target.value)} autoFocus />
                      ) : (
                        <div className="ga-desc">{sn.testo || sn.desc || "(nessuna descrizione)"}</div>
                      )}

                      {Array.isArray(sn.descrizioni) && sn.descrizioni.length > 0 && (
                        <div className="ga-multi">
                          {sn.descrizioni.map((detail, index) => (
                            <div key={detail.id} className="ga-multi__item">
                              <div className="ga-multi__title">Descrizione {index + 1} · S/N {(detail.seriali || []).join(", ") || "—"}</div>
                              <div className="ga-desc">{detail.testo}</div>
                              <textarea className="ga-input" rows={2} placeholder="Risposta per questa descrizione…"
                                value={descrizioneAnswers[String(detail.id)] || ""} disabled={!canEditSelected}
                                onChange={(e) => setDescrizioneAnswers((prev) => ({ ...prev, [String(detail.id)]: e.target.value }))} />
                              {detail.risposta_da && <div className="ga-hint">Risposta di {detail.risposta_da}{detail.risposta_il ? ` · ${new Date(detail.risposta_il).toLocaleString("it-IT")}` : ""}</div>}
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Allegati: griglia, trascina, incolla */}
                      <div
                        className={`ga-att${dropOver ? " is-over" : ""}`}
                        tabIndex={canEditCurrentOp ? 0 : -1}
                        onDragOver={(e) => { if (!canEditCurrentOp) return; e.preventDefault(); setDropOver(true); }}
                        onDragLeave={() => setDropOver(false)}
                        onDrop={(e) => { e.preventDefault(); setDropOver(false); if (canEditCurrentOp) uploadFiles(Array.from(e.dataTransfer.files || [])); }}
                        onPaste={(e) => {
                          const files = Array.from((e.clipboardData && e.clipboardData.items) || []).filter((it) => it.kind === "file").map((it) => it.getAsFile()).filter(Boolean);
                          if (files.length && canEditCurrentOp) { e.preventDefault(); uploadFiles(nomeAppunti(files)); }
                        }}
                      >
                        <input ref={fileInputRef} type="file" multiple hidden accept={ALLEGATI_ACCEPT}
                          onChange={(e) => { const f = Array.from(e.target.files || []); e.target.value = ""; uploadFiles(f); }} />
                        <div className="ga-att__head">
                          <span className="ga-card__sub">{Ico.clip} Allegati {attAnomalia.length ? `(${attAnomalia.length})` : ""}</span>
                          {canEditCurrentOp && (
                            <span className="ga-hint">
                              {uploadingAttachments ? "Caricamento…" : <>Trascina qui, <button type="button" className="ga-link" onClick={() => fileInputRef.current && fileInputRef.current.click()}>sfoglia</button> o clicca e premi Ctrl+V</>}
                            </span>
                          )}
                        </div>
                        {loadingAttachments ? <div className="ga-hint">Caricamento allegati…</div>
                          : attAnomalia.length === 0 ? <div className="ga-hint">Nessun allegato.</div>
                          : renderAttGrid(attAnomalia)}
                      </div>
                    </div>

                    {/* Decisione */}
                    <div className={`ga-card ga-card--decision${dirty ? " is-dirty" : ""}`}>
                      <div className="ga-card__head">
                        <span className="ga-card__title">Decisione del capocommessa</span>
                      </div>
                      <PercorsoAnomalia passi={esitiInfo && esitiInfo.local_id === sn.local_id ? esitiInfo.percorso : null} />
                      <div className="ga-flags">
                        <FlagToggle label="Aprire RDC" checked={aprireRdc} disabled={!canEditSelected} onChange={() => setAprireRdc(!aprireRdc)} />
                        <FlagToggle label="Segnalare al cliente" checked={segnalare} disabled={!canEditSelected} onChange={toggleSegnalare} />
                        <FlagToggle label="Segnala a terzista" checked={terzista} disabled={!canEditSelected} onChange={() => setTerzista(!terzista)} />
                        <FlagToggle label="Segnala a CAR" hint="I CAR scelti ricevono una mail con questa anomalia" checked={segnalaCar} disabled={!canEditSelected} onChange={toggleSegnalaCar} />
                        <FlagToggle label="Pezzi precedenti al benestare" checked={pezziPrec} disabled={!canEditSelected} onChange={() => setPezziPrec(!pezziPrec)} />
                      </div>
                      {(segnalare || terzista) && (
                        <div className="ga-segnalati">
                          {rigaSegnalato("cliente", segnalare, baseline.segnalare)}
                          {rigaSegnalato("terzista", terzista, baseline.terzista)}
                        </div>
                      )}
                      {segnalaCar && (
                        <div>
                          <FieldLabel>A quale CAR?</FieldLabel>
                          {carOpzioni.length === 0
                            ? <div className="ga-hint">Nessun CAR sull'OP e nessun capo reparto in Configurazione.</div>
                            : (
                              <div className="ga-chips">
                                {carOpzioni.map((nome) => (
                                  <Chip key={nome} active={carScelti.some((n) => n.toLowerCase() === nome.toLowerCase())}
                                    onClick={() => canEditSelected && toggleCarScelto(nome)}>{nome}{isCarDellOp(nome) ? " · CAR dell'OP" : ""}</Chip>
                                ))}
                              </div>
                            )}
                          <div className="ga-hint">{carScelti.length
                            ? `Al salvataggio la mail «Segnala a CAR» va solo a: ${carScelti.join(", ")} (chi l'ha già ricevuta non la riceve di nuovo).`
                            : "Scegli almeno un CAR: senza scelta la segnalazione non parte."}
                            {" "}Il CAR dell'OP riceve comunque il riepilogo delle modifiche, come sempre.</div>
                        </div>
                      )}
                      {(sn.dove_pezzi || (sn.dettaglio_righe || []).length > 0 || sn.tipo_difetto) && (
                        <div className="ga-ctrl">
                          <div className="ga-ctrl__t">Dal controllore</div>
                          {sn.dove_pezzi && <div>📦 Dove sono i pezzi: <b>{sn.dove_pezzi}</b></div>}
                          {(sn.dettaglio_righe || []).map((r, ri) => <div key={ri} className="ga-ctrl__r">{r}</div>)}
                          {sn.tipo_difetto && <div className="ga-hint">Tipo di difetto: {sn.tipo_difetto}</div>}
                        </div>
                      )}
                      <div className="ga-att ga-att--dec"
                        onDragOver={(e) => { if (canEditCurrentOp && sn.local_id) e.preventDefault(); }}
                        onDrop={(e) => { e.preventDefault(); if (canEditCurrentOp && sn.local_id) uploadFiles(Array.from(e.dataTransfer.files || []), "decisione"); }}>
                        <input ref={fileInputDecRef} type="file" multiple hidden accept={ALLEGATI_ACCEPT}
                          onChange={(e) => { const f = Array.from(e.target.files || []); e.target.value = ""; uploadFiles(f, "decisione"); }} />
                        <div className="ga-att__head">
                          <span className="ga-card__sub">{Ico.clip} Allegati della decisione {attDecisione.length ? `(${attDecisione.length})` : ""}</span>
                          {canEditCurrentOp && sn.local_id && (
                            <span className="ga-hint">
                              {uploadingAttachments ? "Caricamento…" : <>Trascina qui o <button type="button" className="ga-link" onClick={() => fileInputDecRef.current && fileInputDecRef.current.click()}>sfoglia</button></>}
                            </span>
                          )}
                        </div>
                        {attDecisione.length === 0
                          ? <div className="ga-hint">Nessun allegato alla decisione.</div>
                          : renderAttGrid(attDecisione)}
                      </div>
                      <div className="ga-grid2">
                        <div>
                          <FieldLabel>Avanzamento</FieldLabel>
                          <select className={`ga-input${canEditSelected && notaSenzaStato ? " is-invalid" : ""}`} value={avanzamento} onChange={(e) => setAvanzamento(e.target.value)} disabled={!canEditSelected}>
                            {avanzamentoOptions.map((opt) => <option key={opt}>{opt}</option>)}
                          </select>
                          {segnalare && avanzamento === AVANZAMENTO_RISPOSTA_CLIENTE && <div className="ga-hint">L'anomalia resta aperta in attesa del cliente: cambia lo stato quando risponde.</div>}
                        </div>
                        {aprireRdc && (
                          <div>
                            <FieldLabel>Numero RDC</FieldLabel>
                            <input className="ga-input" placeholder="Es. RDC-2026-014" value={rdcNum} onChange={(e) => setRdcNum(e.target.value)} disabled={!canEditSelected} />
                          </div>
                        )}
                      </div>
                      <div>
                        <FieldLabel>Risposta / note per il reparto</FieldLabel>
                        <textarea className="ga-input" rows={3} value={note} onChange={(e) => setNote(e.target.value)} disabled={!canEditSelected}
                          placeholder="Decisione, istruzioni di rilavorazione, riferimenti…" />
                      </div>
                      {canEditSelected && notaSenzaStato && (
                        <div className="ga-note ga-note--warn">{NOTA_STATO_MSG}</div>
                      )}
                      {canEditSelected && chiudereAuto && !sn.chiudere && !aprireRdc && esitiInfo && esitiInfo.serve_azione ? (
                        <div className="ga-note ga-note--warn">La prima decisione è stata «Azione di recupero»: per chiudere registra l'azione effettuata in «Tempi ed esiti».</div>
                      ) : canEditSelected && chiudereAuto && !sn.chiudere && (
                        <div className="ga-note ga-note--ok">Con questa decisione l'anomalia verrà <b>chiusa</b> al salvataggio.</div>
                      )}
                      {canEditSelected && (altreAperte.length > 0 || giaDecise > 0) && (
                        <div className="ga-apply ga-apply--ambito">
                          <div className="ga-apply__t">Applica la stessa decisione anche a</div>
                          <div className="ga-apply__opts" role="radiogroup" aria-label="Applica la stessa decisione anche a">
                            {[
                              ["solo", "Solo questa", null],
                              ...(sn.blocco_id ? [["blocco", "Stesso blocco di seriali", stessoBlocco.length]] : []),
                              ["op", "Tutte le aperte dell'OP", altreAperte.length],
                              ["mano", "Scelte a mano", null],
                            ].map(([k, label, n]) => (
                              <button key={k} type="button" role="radio" aria-checked={ambito === k}
                                className={`ga-chip-opt${ambito === k ? " is-on" : ""}`}
                                disabled={n === 0} onClick={() => setAmbito(k)}>
                                {label}{n != null ? <span className="ga-chip-opt__n">{n}</span> : null}
                              </button>
                            ))}
                          </div>
                          {ambito === "blocco" && <PezziInteressati sn={sn} compact />}
                          {ambito === "mano" && (
                            <div className="ga-apply__mano">
                              <div className="ga-apply__mano-acts">
                                <span className="ga-hint">{scelteMano.filter((id) => altreAperte.some((x) => x.item_id === id)).length} scelte su {altreAperte.length}</span>
                                <button type="button" className="ga-link" onClick={() => setScelteMano(altreAperte.map((x) => x.item_id))}>Tutte</button>
                                <button type="button" className="ga-link" onClick={() => setScelteMano([])}>Nessuna</button>
                              </div>
                              {altreAperte.length === 0 ? <div className="ga-hint">Nessun'altra anomalia {includiDecise ? "aperta" : "da decidere"}.</div> : gruppiPerSn(altreAperte).map((g) => (
                                <div key={g.chiave} className="ga-apply__grp">
                                  <div className="ga-apply__grp-t">S/N {g.titolo}</div>
                                  {g.righe.map((x) => (
                                    <label key={x.item_id} className="ga-apply__row">
                                      <input type="checkbox" checked={scelteMano.includes(x.item_id)}
                                        onChange={(e) => setScelteMano((prev) => (e.target.checked ? [...prev, x.item_id] : prev.filter((id) => id !== x.item_id)))} />
                                      <span className="ga-apply__txt">{x.testo || x.desc || "—"}</span>
                                      <span className="ga-hint">#{x.local_id}{isDaDecidere(x) ? "" : ` · ${x.avanzamento || "decisa"}`}</span>
                                    </label>
                                  ))}
                                </div>
                              ))}
                            </div>
                          )}
                          {giaDecise > 0 && ambito !== "solo" && (
                            <label className="ga-apply__decise">
                              <input type="checkbox" checked={includiDecise} onChange={(e) => setIncludiDecise(e.target.checked)} />
                              <span>Includi anche le {giaDecise} già decise (la loro decisione viene sostituita)</span>
                            </label>
                          )}
                        </div>
                      )}
                    </div>

                    {sn.local_id && (
                      <EsitiAnomalia localId={sn.local_id} avanzamento={sn.avanzamento} chiusa={Boolean(sn.chiudere)} segnalare={Boolean(sn.segnalare)}
                        flash={flash} onInfo={setEsitiInfo}
                        onSaved={({ chiusa }) => {
                          if (chiusa) {
                            setAnomalie((prev) => prev.map((a) => (a.item_id === sn.item_id ? { ...a, chiudere: true, can_riaprire: true } : a)));
                            loadOrdini();
                          }
                          loadAttachments(sn.local_id);
                        }} />
                    )}

                    {op.id && op.id !== "—" && <TimelineOp opId={op.id} opItemId={op.item_id} />}
                  </div>

                  {canEditSelected && (
                    <div className="ga-det__foot">
                      <span className={`ga-det__state${dirty ? " is-dirty" : ""}`}>{dirty ? "● Modifiche non salvate" : "Nessuna modifica"}</span>
                      {dirty && <button type="button" className="ga-btn ga-btn--ghost-dark" onClick={annullaModifiche} disabled={saving}>Annulla</button>}
                      <button type="button" className="ga-btn ga-btn--outline" onClick={() => handleSave()} disabled={saving} title="Ctrl+S">{saving ? "Salvataggio…" : "Salva"}</button>
                      <button type="button" className="ga-btn ga-btn--accent" onClick={salvaEProssima} disabled={saving}>Salva e prossima {Ico.next}</button>
                    </div>
                  )}
                </>
              )}
            </section>
          </div>

          {azAnom && sn.local_id && (
            <div className="ga-modal" role="dialog" aria-modal="true" aria-labelledby="ga-az-t">
              <div className="ga-modal__box">
                <div className="ga-modal__title" id="ga-az-t">{azAnom.tipo === "elimina" ? `Eliminare l'anomalia #${sn.local_id}?` : `✂ Taglia l'anomalia #${sn.local_id}`}</div>
                <div className="ga-hint ga-az__ctx">S/N {sn.sn || "—"} · {sn.testo || sn.desc || "(nessuna descrizione)"}</div>
                {azAnom.tipo === "elimina" ? (
                  <div className="ga-note ga-note--warn">Sparisce dall'OP con i suoi dati; gli allegati restano recuperabili dall'amministratore. Non si può annullare.</div>
                ) : (
                  <>
                    <label className="ga-field"><span>OP di destinazione</span>
                      <input className="ga-input" list="ga-taglia-op" value={azAnom.op} disabled={azAnom.busy}
                        onChange={(e) => setAzAnom({ ...azAnom, op: e.target.value, err: "" })} />
                      <datalist id="ga-taglia-op">{ordini.slice(0, 500).map((o) => <option key={opKey(o)} value={o.id} />)}</datalist>
                    </label>
                    <label className="ga-field"><span>S/N di destinazione</span>
                      <input className="ga-input" list="ga-taglia-sn" value={azAnom.sn} disabled={azAnom.busy} autoFocus
                        placeholder="Es. LCN00012 o LCN00012-LCN00015"
                        onChange={(e) => setAzAnom({ ...azAnom, sn: e.target.value, err: "" })}
                        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); confermaAzione(); } }} />
                      <datalist id="ga-taglia-sn">{(azAnom.seriali || []).slice(0, 500).map((s) => <option key={s} value={s} />)}</datalist>
                    </label>
                    <div className="ga-hint">{String(azAnom.op || "").trim().toLowerCase() === String(op.id || "").toLowerCase()
                      ? "Stesso OP: cambia solo il S/N (nel controllo va nel blocco che ha già quel S/N)."
                      : "Altro OP: passa alla NC di quell'OP e il suo capocommessa la trova nel riepilogo delle modifiche."}</div>
                  </>
                )}
                {azAnom.err && <div className="ga-note ga-note--warn">{azAnom.err}</div>}
                <div className="ga-modal__acts">
                  <button type="button" className="ga-btn ga-btn--ghost-dark" disabled={azAnom.busy} onClick={() => setAzAnom(null)}>Annulla</button>
                  <button type="button" className={`ga-btn ${azAnom.tipo === "elimina" ? "ga-btn--danger" : "ga-btn--accent"}`} disabled={azAnom.busy} onClick={confermaAzione}>
                    {azAnom.busy ? "Attendere…" : (azAnom.tipo === "elimina" ? "Elimina" : "Sposta qui")}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Modifica OP: solo chi l'ha inserito dal portale, con motivazione */}
          {modOp && (
            <div className="ga-modal" role="dialog" aria-modal="true" aria-labelledby="ga-modop-t">
              <div className="ga-modal__box">
                <div className="ga-modal__title" id="ga-modop-t">Modifica OP {modOp.titolo}</div>
                {!modOp.dati ? (
                  <div className="ga-hint">{modOp.busy ? "Caricamento…" : ""}</div>
                ) : (
                  <>
                    <div className="ga-modop__grid">
                      <label className="ga-field"><span>P/N *</span>
                        <input className="ga-input" value={modOp.dati.pn} disabled={modOp.busy} autoFocus
                          onChange={(e) => campoModOp("pn", e.target.value)} />
                      </label>
                      <label className="ga-field"><span>Fase</span>
                        <input className="ga-input" value={modOp.dati.fase} disabled={modOp.busy}
                          onChange={(e) => campoModOp("fase", e.target.value)} />
                      </label>
                      <label className="ga-field"><span>Capocommessa *</span>
                        <input className="ga-input" list="ga-modop-capi" value={modOp.dati.capocommessa} disabled={modOp.busy}
                          onChange={(e) => campoModOp("capocommessa", e.target.value)} />
                        <datalist id="ga-modop-capi">{(Array.isArray(CONFIG_LISTS.capi_commessa) ? CONFIG_LISTS.capi_commessa : []).map((n) => <option key={n} value={n} />)}</datalist>
                      </label>
                      <label className="ga-field"><span>CAR *</span>
                        <input className="ga-input" list="ga-modop-car" value={modOp.dati.car} disabled={modOp.busy}
                          onChange={(e) => campoModOp("car", e.target.value)} />
                        <datalist id="ga-modop-car">{(Array.isArray(CONFIG_LISTS.capi_reparto) ? CONFIG_LISTS.capi_reparto : []).map((n) => <option key={n} value={n} />)}</datalist>
                      </label>
                    </div>
                    <label className="ga-field"><span>Note</span>
                      <input className="ga-input" value={modOp.dati.note} maxLength={180} disabled={modOp.busy}
                        onChange={(e) => campoModOp("note", e.target.value)} />
                    </label>
                    {modOp.dati.benestare_modificabile && (
                      <label className="ga-modop__check">
                        <input type="checkbox" checked={!!modOp.dati.benestare} disabled={modOp.busy}
                          onChange={(e) => campoModOp("benestare", e.target.checked)} />
                        Collaudo di benestare
                      </label>
                    )}
                    <label className="ga-field"><span>Motivo della modifica *</span>
                      <textarea className="ga-input" rows={2} value={modOp.motivo} maxLength={500} disabled={modOp.busy}
                        placeholder="Es. P/N scritto male in apertura"
                        onChange={(e) => setModOp({ ...modOp, motivo: e.target.value, err: "" })} />
                    </label>
                    <div className="ga-hint">Il numero dell'OP non si cambia: per un OP sbagliato usa «Taglia». La modifica resta nella cronologia dell'OP.</div>
                  </>
                )}
                {modOp.err && <div className="ga-note ga-note--warn">{modOp.err}</div>}
                <div className="ga-modal__acts">
                  <button type="button" className="ga-btn ga-btn--ghost-dark" disabled={modOp.busy && !!modOp.dati} onClick={() => setModOp(null)}>Annulla</button>
                  {modOp.dati && (
                    <button type="button" className="ga-btn ga-btn--accent" disabled={modOp.busy || !modOpCambiato} onClick={salvaModificaOp}>
                      {modOp.busy ? "Salvataggio…" : "Salva modifica"}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Riepilogo prima di applicare la decisione ad altre anomalie */}
          {riepilogo && (
            <div className="ga-modal" role="dialog" aria-modal="true" aria-labelledby="ga-riep-t">
              <div className="ga-modal__box ga-modal__box--wide">
                <div className="ga-modal__title" id="ga-riep-t">Applica la decisione a {bersagli.length + 1} anomalie</div>
                <div className="ga-riep__dec">
                  <span><b>Avanzamento</b> {avanzamento}</span>
                  {aprireRdc && <span><b>RDC</b> {rdcNum || "da aprire"}</span>}
                  {segnalare && <span><b>Segnalata al cliente</b></span>}
                  {terzista && <span><b>Segnalata al terzista</b></span>}
                  {segnalaCar && carScelti.length > 0 && <span><b>Segnalata al CAR</b> {carScelti.join(", ")}</span>}
                  {note.trim() && <span className="ga-riep__nota"><b>Note</b> {note.trim()}</span>}
                </div>
                <div className="ga-riep__list">
                  {gruppiPerSn([sn, ...bersagli]).map((g) => (
                    <div key={g.chiave} className="ga-riep__grp">
                      <div className="ga-apply__grp-t">S/N {g.titolo}</div>
                      {g.righe.map((x) => {
                        const chiude = x.item_id === sn.item_id ? chiudereAuto : chiudeBersaglio(x);
                        return (
                          <div key={x.item_id} className="ga-riep__row">
                            <span className="ga-apply__txt">#{x.local_id} {x.testo || x.desc || "—"}{x.item_id === sn.item_id ? " (questa)" : ""}</span>
                            <span className="ga-riep__stato">{x.avanzamento || "In attesa"} → {avanzamento}</span>
                            {chiude ? <span className="ga-pill ga-pill--chiuso">Si chiude</span>
                              : (chiudereAuto && x.serve_azione ? <span className="ga-pill ga-pill--attesa" title="Prima decisione «Azione di recupero»: serve l'azione effettuata">Resta aperta</span> : null)}
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </div>
                {chiudereAuto && bersagli.some((x) => x.serve_azione) && !aprireRdc && (
                  <div className="ga-note ga-note--warn">Le anomalie in «Azione di recupero» ricevono la decisione ma restano aperte finché non si registra l'azione effettuata.</div>
                )}
                <div className="ga-modal__acts">
                  <button type="button" className="ga-btn ga-btn--ghost-dark" onClick={() => setRiepilogo(null)}>Annulla</button>
                  <button type="button" className="ga-btn ga-btn--accent" disabled={saving} onClick={async () => {
                    const prossima = riepilogo.prossima ? trovaProssima(bersagli.map((x) => x.item_id)) : null;
                    const vaiAvanti = riepilogo.prossima;
                    setRiepilogo(null);
                    if (await handleSave(true) && vaiAvanti) vaiAllaProssima(prossima);
                  }}>Conferma e salva {bersagli.length + 1} anomalie</button>
                </div>
              </div>
            </div>
          )}

          {/* Modifiche non salvate prima di cambiare anomalia/OP */}
          {pendingNav && (
            <div className="ga-modal" role="dialog" aria-modal="true">
              <div className="ga-modal__box">
                <div className="ga-modal__title">Modifiche non salvate</div>
                <p>Hai cambiato la decisione sull'anomalia #{sn.local_id} senza salvarla.</p>
                <div className="ga-modal__acts">
                  <button type="button" className="ga-btn ga-btn--ghost-dark" onClick={() => setPendingNav(null)}>Resta qui</button>
                  <button type="button" className="ga-btn ga-btn--outline" onClick={() => { const nav = pendingNav; setPendingNav(null); annullaModifiche(); nav(); }}>Scarta</button>
                  <button type="button" className="ga-btn ga-btn--accent" onClick={async () => { const nav = pendingNav; setPendingNav(null); if (await handleSave()) nav(); }}>Salva e continua</button>
                </div>
              </div>
            </div>
          )}

          {/* Immagine ingrandita */}
          {lightbox && lightboxIdx >= 0 && (
            <div className="ga-lightbox" onClick={() => setLightbox(null)}>
              <img src={getAttachmentUrl(lightbox)} alt={immagini[lightboxIdx].name} onClick={(e) => e.stopPropagation()} />
              <div className="ga-lightbox__bar" onClick={(e) => e.stopPropagation()}>
                <button type="button" disabled={lightboxIdx <= 0} onClick={() => setLightbox(immagini[lightboxIdx - 1].file_id)}>{Ico.prev}</button>
                <span>{immagini[lightboxIdx].name} · {lightboxIdx + 1}/{immagini.length}</span>
                <button type="button" disabled={lightboxIdx >= immagini.length - 1} onClick={() => setLightbox(immagini[lightboxIdx + 1].file_id)}>{Ico.next}</button>
                <a href={getAttachmentUrl(lightbox, true)}>Scarica</a>
                <button type="button" onClick={() => setLightbox(null)}>Chiudi</button>
              </div>
            </div>
          )}

          {saveMsg && <div className={`ga-toast${saveMsg.ok ? "" : " is-err"}`}>{saveMsg.text}</div>}

          {isMobile && (
            <nav className="ga-tabs">
              {[["ordini", "Ordini", Ico.list], ["serie", "Anomalie", Ico.rows], ["dettaglio", "Dettaglio", Ico.edit]].map(([id, label, icon]) => (
                <button key={id} type="button" className={mobilePanel === id ? "is-on" : ""} onClick={() => setMobilePanel(id)}>
                  {icon}{label}{id === "serie" && nDaDecidere > 0 ? <span className="ga-tabs__n">{nDaDecidere}</span> : null}
                </button>
              ))}
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
