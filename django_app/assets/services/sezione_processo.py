"""Sezione dedicata di un processo qualificato (MOD.128), es. P11TF12.

Un processo con la spunta «Crea sezione dedicata» ha una pagina sua: cose da sistemare,
scadenze, macchine qualificate, utensili critici, Technical Plan, registro utensili
(MOD.176), persone abilitate e formazione. Più processi con la stessa sigla finiscono
nella stessa pagina. Una sola costruzione per le due pagine (Asset e Qualifiche): cambia
solo l'ordine delle sezioni. Si mostrano solo le parti che il processo usa davvero.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from .part145_dossier import BADGE as BADGE_PART145
from .part145_dossier import Sezione, _d, _documenti_sgi, _formazione_richiesta, _stato_scadenza

logger = logging.getLogger(__name__)

GIORNI_SCADENZE = 90

# Esito sintetico della qualifica macchina (colonna con badge).
ESITI_MACCHINA = {"qualificata": "Qualificata", "in_scadenza": "In scadenza", "scaduta": "Scaduta",
                  "da_qualificare": "Da qualificare", "da_valutare": "Da valutare", "sospesa": "Sospesa",
                  "declassata": "Declassata", "non_richiesta": "Qualifica non registrata"}

BADGE = dict(BADGE_PART145)
BADGE.update({v: "ko" for v in ("Da valutare", "Sospesa", "Qualifica non registrata", "TCP raggiunto",
                                "Nessuna revisione approvata")})
BADGE.update({v: "warn" for v in ("Da qualificare", "Declassata", "In attesa di approvazione")})
BADGE.update({v: "ok" for v in ("Approvata", "In uso")})

PRIORITA_ALTA = "Alta"
PRIORITA_MEDIA = "Media"
TIPI_PRIORITA_ALTA = {"Processo scaduto", "Processo non attivo", "Macchina scaduta", "Macchina da valutare",
                      "Macchina sospesa", "Requisito macchina scaduto", "Utensile al TCP",
                      "Technical Plan senza revisione approvata", "Abilitazione sospesa", "Abilitazione revocata",
                      "Persona non qualificata", "Formazione scaduta"}

# Ordine delle sezioni per pagina: in Asset prima macchine e utensili, in Qualifiche prima le persone.
ORDINE_ASSET = ["aperte", "scadenze", "macchine", "utensili", "technical_plan", "registro", "processo",
                "personale", "formazione", "documenti"]
ORDINE_QUALIFICHE = ["aperte", "scadenze", "personale", "formazione", "processo", "macchine", "utensili",
                     "technical_plan", "registro", "documenti"]


def processi(sigla: str):
    """I processi con la sezione dedicata di questa sigla."""
    from anagrafica.services.mpq_sezioni import processi_della_sigla

    return processi_della_sigla(sigla).order_by("nome", "id")


def titolo_sezione(sigla: str, elenco) -> str:
    titolo = next((p.sezione_titolo.strip() for p in elenco if (p.sezione_titolo or "").strip()), "")
    return f"{sigla} – {titolo}" if titolo else sigla


def _sicuro(avvisi: list, cosa: str, funzione, predefinito):
    """Una parte che si rompe non fa cadere la pagina: avviso in pagina e log."""
    try:
        return funzione()
    except Exception:
        logger.exception("Sezione dedicata MOD.128: %s non disponibile", cosa)
        avvisi.append(f"{cosa}: dati non disponibili in questo momento (errore registrato nei log).")
        return predefinito


def costruisci(sigla: str, *, oggi=None, con_personale: bool = True, ordine=None, giorni: int = GIORNI_SCADENZE) -> dict:
    """Tutta la pagina. Il personale (dati MOD.128) solo con il permesso sui processi qualificati."""
    from anagrafica.models_mpq import AbilitazioneProcesso, RegistroUtensile, TechnicalPlanRevisione

    oggi = oggi or timezone.localdate()
    limite = oggi + timedelta(days=giorni)
    avvisi: list[str] = []
    elenco = list(processi(sigla).select_related("cliente", "ente_certificatore").prefetch_related("riferimenti"))

    def apri(processo, ancora=""):
        if not con_personale:
            return None
        return ("Apri il processo", reverse("anagrafica:mpq_processo_detail", args=[processo.pk]) + ancora)

    # ── Processo ─────────────────────────────────────────────────────────────
    s_proc = Sezione("processo", "Processo", ["Processo", "Cliente / ente", "Stato", "Scadenza", "Esito scadenza",
                                              "Frequenza macchine", "Riesame persona dopo"],
                     nota="Il processo nel registro dei processi qualificati (MOD.128).",
                     vuoto="Nessun processo con questa sezione dedicata.", chiusa=True)
    for p in elenco:
        scad = p.scadenza_effettiva
        s_proc.aggiungi([p.nome, str(p.cliente) if p.cliente_id else "", p.get_stato_display(), _d(scad),
                         _stato_scadenza(scad, oggi) if p.tipo_validita != p.VALIDITA_ILLIMITATA else "Illimitata",
                         f"{p.frequenza_macchine_mesi} mesi" if p.frequenza_macchine_mesi else "",
                         f"{p.inattivita_mesi} mesi senza attività" if p.inattivita_mesi else ""], apri(p))

    # ── Macchine qualificate (MOD.161) ───────────────────────────────────────
    s_macc = Sezione("macchine", "Macchine qualificate",
                     ["Asset", "Nome", "Reparto", "Esito", "Qualifica", "Ultima verifica", "Esito verifica",
                      "Requisiti macchina"],
                     nota="Macchine collegate al processo, con qualifica e scadenza proprie. La verifica (MOD.161) "
                          "confronta i parametri della macchina con le tolleranze del processo; dopo un "
                          "intervento correttivo la macchina torna «Da valutare».",
                     vuoto="Nessuna macchina: dal processo, sezione «Macchine qualificate», collega le macchine.")
    righe_macchine: list = []

    def _carica_macchine():
        from anagrafica.services.mpq_macchine import righe_macchine as _righe

        out = []
        for p in elenco:
            for r in _righe(p, oggi=oggi):
                out.append((p, r))
        return out

    righe_macchine = _sicuro(avvisi, "Macchine qualificate", _carica_macchine, [])
    ultime_verifiche: dict = {}
    qm_ids = [r["qualifica"].pk for _, r in righe_macchine if r["qualifica"] is not None]
    if qm_ids:
        from anagrafica.models_mpq import VerificaMacchina

        for v in VerificaMacchina.objects.filter(qualifica_id__in=qm_ids).order_by("qualifica_id", "-data", "-id"):
            ultime_verifiche.setdefault(v.qualifica_id, v)
    for p, r in righe_macchine:
        a, qm, st = r["asset"], r["qualifica"], r["stato"]
        v = ultime_verifiche.get(qm.pk) if qm else None
        requisiti = ", ".join(f"{x['nome']}: {x['label']}" for x in r["requisiti"])
        azione = (("Apri la qualifica", reverse("anagrafica:mpq_qualifica_macchina", args=[qm.pk]))
                  if qm and con_personale else apri(p, "#attrezzature"))
        s_macc.aggiungi([a.asset_tag, a.name, a.reparto, ESITI_MACCHINA.get(st["codice"], st["label"]), st["label"],
                         _d(v.data) if v else "", v.get_esito_display() if v else "", requisiti], azione, asset_id=a.pk)

    # ── Utensili critici ─────────────────────────────────────────────────────
    s_ut = Sezione("utensili", "Utensili critici",
                   ["Codice", "Descrizione", "Tipo", "Diametro (mm)", "Fornitore certificato", "Riaffilatura"],
                   nota="Utensili identificati come critici per il processo, con il fornitore certificato dal cliente.",
                   vuoto="Nessun utensile critico: dal processo, «Utensili e Technical Plan», aggiungili.")
    for p in elenco:
        for u in p.utensili_critici.filter(attivo=True).order_by("codice"):
            riaff = "No"
            if u.riaffilabile:
                riaff = f"Sì, max {u.riaffilature_max}" if u.riaffilature_max else "Sì"
                if u.fornitore_riaffilatura:
                    riaff += f" · {u.fornitore_riaffilatura}"
            s_ut.aggiungi([u.codice, u.descrizione, u.get_tipo_display(), u.diametro_mm or "", u.fornitore, riaff],
                          ("Apri gli utensili", reverse("anagrafica:mpq_utensili", args=[p.pk])) if con_personale else None)

    # ── Technical Plan ───────────────────────────────────────────────────────
    s_tp = Sezione("technical_plan", "Technical Plan",
                   ["P/N", "Tipologia di foro", "Revisione valida", "Approvata il", "Approvata da", "In approvazione"],
                   nota="Un Technical Plan per tipologia di foro critico di un P/N: in produzione vale solo "
                        "l'ultima revisione approvata dal cliente.",
                   vuoto="Nessun Technical Plan: dal processo, «Utensili e Technical Plan», crealo per ogni P/N.")
    tp_senza_rev: list = []
    tp_in_approvazione: list = []
    for p in elenco:
        for tp in p.technical_plan.prefetch_related("revisioni").order_by("part_number", "tipologia_foro"):
            revs = list(tp.revisioni.all())
            valide = sorted((r for r in revs if r.stato == TechnicalPlanRevisione.STATO_APPROVATA),
                            key=lambda r: r.numero, reverse=True)
            bozze = [r for r in revs if r.stato == TechnicalPlanRevisione.STATO_BOZZA]
            cor = valide[0] if valide else None
            if cor is None:
                tp_senza_rev.append(tp)
            if bozze:
                tp_in_approvazione.append(tp)
            s_tp.aggiungi([tp.part_number, tp.tipologia_foro, f"Rev. {cor.numero}" if cor else "Nessuna revisione approvata",
                           _d(cor.data_approvazione) if cor else "", cor.approvato_da if cor else "",
                           "In attesa di approvazione" if bozze else ""],
                          ("Apri il Technical Plan", reverse("anagrafica:mpq_tp", args=[tp.pk])) if con_personale else None)

    # ── Registro utensili MOD.176 ────────────────────────────────────────────
    s_reg = Sezione("registro", "Utensili in uso (MOD.176)",
                    ["Utensile / kit", "P/N", "Utensile critico", "Stato", "Utilizzo", "TCP", "Residuo", "Aperto il"],
                    nota="Ogni utensile o kit montato si segue fino al punto di cambio (TCP) "
                         "del Technical Plan. Qui quelli ancora in uso o arrivati al TCP.",
                    vuoto="Nessun utensile in uso registrato nel MOD.176.")
    registri = _sicuro(avvisi, "Registro MOD.176", lambda: list(
        RegistroUtensile.objects.filter(passo__revisione__plan__processo__in=elenco)
        .exclude(stato=RegistroUtensile.STATO_CHIUSO)
        .select_related("passo", "passo__utensile", "passo__revisione__plan").prefetch_related("righe")
        .order_by("stato", "aperto_il")), [])
    for reg in registri:
        passo = reg.passo
        s_reg.aggiungi([reg.identificativo, passo.revisione.plan.part_number,
                        passo.utensile.codice if passo.utensile_id else "", reg.get_stato_display(), reg.utilizzo,
                        f"{passo.tcp_limite} {passo.get_tcp_unita_display().lower()}" if passo.tcp_limite else "",
                        reg.residuo if reg.residuo is not None else "", _d(reg.aperto_il)],
                       ("Apri il registro", reverse("anagrafica:mpq_registro", args=[reg.pk])) if con_personale else None)

    # ── Personale abilitato ──────────────────────────────────────────────────
    abilitazioni: list = []
    nomi: dict = {}
    stati_persona: dict = {}
    if con_personale and elenco:
        def _carica_personale():
            from anagrafica.services.mpq_persone import contesto_processo, stato_persona
            from anagrafica.views_mpq import _nomi_map

            elenco_ab = list(AbilitazioneProcesso.objects.filter(processo__in=elenco)
                             .select_related("processo").prefetch_related("certificazioni", "ruoli_processo")
                             .order_by("processo__nome", "legacy_anagrafica_id"))
            stati = {}
            for p in elenco:
                del_processo = [a for a in elenco_ab if a.processo_id == p.pk]
                if not del_processo:
                    continue
                ctx = contesto_processo(p, del_processo)
                for a in del_processo:
                    if a.nominativo_esterno or not a.legacy_anagrafica_id:
                        continue
                    try:
                        stati[a.pk] = stato_persona(a, oggi=oggi, contesto=ctx)
                    except Exception:
                        logger.exception("Sezione dedicata MOD.128: qualifica non calcolabile per abilitazione %s", a.pk)
            return elenco_ab, _nomi_map([a.legacy_anagrafica_id for a in elenco_ab]), stati

        abilitazioni, nomi, stati_persona = _sicuro(avvisi, "Personale abilitato", _carica_personale, ([], {}, {}))

    def nome_persona(ab):
        if ab.nominativo_esterno:
            return f"{ab.nominativo_esterno} (esterno)"
        return nomi.get(ab.legacy_anagrafica_id) or f"#{ab.legacy_anagrafica_id}"

    stati_ab = dict(AbilitazioneProcesso.STATO_CHOICES)
    s_pers = Sezione("personale", "Personale abilitato",
                     ["Persona", "Ruoli", "Stato abilitazione", "Qualifica sul processo", "Prima scadenza",
                      "Ultima attività"],
                     nota="Persone abilitate al processo per ruolo (Ingegneria, Programmazione, Operatore…). "
                          "«Qualifica sul processo» è lo stesso calcolo del processo: corsi, visite e requisiti "
                          "di «Cosa serve a una persona».",
                     vuoto="Nessuna persona abilitata: dal processo aggiungi le abilitazioni.")
    if abilitazioni:
        from anagrafica.services.mpq_ruoli import nomi_ruoli

        for ab in abilitazioni:
            st = stati_persona.get(ab.pk)
            s_pers.aggiungi([nome_persona(ab), ", ".join(nomi_ruoli(ab)), stati_ab.get(ab.stato, ab.stato),
                             st["label"] if st else "—", _d(st["scadenza"]) if st else "", _d(ab.ultima_attivita)],
                            ("Apri la persona", reverse("anagrafica:dipendente_detail", args=[ab.legacy_anagrafica_id]))
                            if ab.legacy_anagrafica_id and not ab.nominativo_esterno else apri(ab.processo))

    # ── Formazione richiesta ─────────────────────────────────────────────────
    formazione, formazione_mancante = [], []
    if abilitazioni:
        formazione, formazione_mancante = _sicuro(avvisi, "Formazione del personale",
                                                  lambda: _formazione_richiesta(elenco, abilitazioni), ([], []))
    scadenzario = ("Apri lo scadenzario", reverse("anagrafica:formazione_scadenzario"))
    stati_formazione = {"VALIDO": "Valida", "IN_SCADENZA_30": "Entro 30 giorni", "IN_SCADENZA_90": "Entro 90 giorni",
                        "SCADUTO": "Scaduta", "MAI_FREQUENTATO": "Mai frequentata", "UNA_TANTUM": "Valida"}
    s_form = Sezione("formazione", "Formazione richiesta", ["Persona", "Corso", "Stato", "Ultimo completamento", "Scadenza"],
                     nota="Corsi richiesti dal processo (es. corso di consapevolezza, ogni 12 mesi) per le persone "
                          "abilitate, dallo scadenzario della formazione.",
                     vuoto="Nessun corso richiesto: dal processo, «Cosa serve a una persona», aggiungi i corsi.")
    for dl in sorted(formazione, key=lambda x: (x.data_scadenza or oggi.replace(year=oggi.year + 50), x.legacy_anagrafica_id)):
        s_form.aggiungi([nomi.get(dl.legacy_anagrafica_id) or f"#{dl.legacy_anagrafica_id}", str(dl.corso),
                         stati_formazione.get(dl.stato_scadenza, dl.stato_scadenza), _d(dl.data_ultimo_completamento),
                         _d(dl.data_scadenza)], scadenzario)
    for persona, corso in formazione_mancante:
        s_form.aggiungi([nomi.get(persona) or f"#{persona}", str(corso), "Mai frequentata", "", ""], scadenzario)

    # ── Scadenze ─────────────────────────────────────────────────────────────
    s_scad = Sezione("scadenze", f"Scadenze entro {giorni} giorni (e già scadute)",
                     ["Data", "Tipo", "Riferimento", "Dettaglio", "Stato"], vuoto=f"Nessuna scadenza nei prossimi {giorni} giorni.")
    scadenze: list = []
    for p in elenco:
        scad = p.scadenza_effettiva
        if scad and scad <= limite:
            scadenze.append(([scad, "Processo", p.nome, "", _stato_scadenza(scad, oggi)], apri(p)))
    for p, r in righe_macchine:
        scad = r["stato"]["scadenza"]
        if r["qualifica"] is not None and scad and scad <= limite:
            scadenze.append(([scad, "Qualifica macchina", f"{r['asset'].asset_tag} — {r['asset'].name}", p.nome,
                              _stato_scadenza(scad, oggi)], ("Apri la scheda", reverse("assets:asset_view", args=[r["asset"].pk]))))
        for x in r["requisiti"]:
            if x["prossima"] and x["prossima"] <= limite:
                scadenze.append(([x["prossima"], "Requisito macchina", f"{r['asset'].asset_tag} — {r['asset'].name}",
                                  x["nome"], _stato_scadenza(x["prossima"], oggi)],
                                 ("Apri la scheda", reverse("assets:asset_view", args=[r["asset"].pk]))))
    for ab in abilitazioni:
        st = stati_persona.get(ab.pk)
        if st and st["scadenza"] and st["scadenza"] <= limite:
            scadenze.append(([st["scadenza"], "Qualifica persona", nome_persona(ab), ab.processo.nome,
                              _stato_scadenza(st["scadenza"], oggi)], apri(ab.processo)))
    for dl in formazione:
        if dl.data_scadenza and dl.data_scadenza <= limite:
            scadenze.append(([dl.data_scadenza, "Formazione", nomi.get(dl.legacy_anagrafica_id) or f"#{dl.legacy_anagrafica_id}",
                              str(dl.corso), _stato_scadenza(dl.data_scadenza, oggi)], scadenzario))
    scadenze.sort(key=lambda t: t[0][0])
    for riga, azione in scadenze:
        riga[0] = _d(riga[0])
        s_scad.aggiungi(riga, azione)

    # ── Da sistemare ─────────────────────────────────────────────────────────
    s_aperte = Sezione("aperte", "Da sistemare", ["Priorità", "Tipo", "Riferimento", "Dettaglio"],
                       nota="Situazioni aperte, prima quelle a priorità alta (fermano il processo o l'audit).",
                       vuoto="Nessuna situazione aperta.")

    def aperta(tipo, riferimento, dettaglio, azione):
        s_aperte.aggiungi([PRIORITA_ALTA if tipo in TIPI_PRIORITA_ALTA else PRIORITA_MEDIA, tipo, riferimento, dettaglio],
                          azione)

    for p in elenco:
        if p.stato != p.STATO_ATTIVO:
            aperta("Processo non attivo", p.nome, p.get_stato_display(), apri(p))
        scad = p.scadenza_effettiva
        if scad and scad < oggi:
            aperta("Processo scaduto", p.nome, f"scaduto il {_d(scad)}", apri(p))
        if p.frequenza_macchine_mesi and not any(pp.pk == p.pk for pp, _ in righe_macchine):
            aperta("Processo senza macchine", p.nome, "nessuna macchina collegata", apri(p, "#attrezzature"))
        if con_personale and not any(ab.processo_id == p.pk and ab.stato == ab.STATO_ATTIVA for ab in abilitazioni):
            aperta("Processo senza persone abilitate", p.nome, "nessuna abilitazione attiva", apri(p))
    for p, r in righe_macchine:
        a, st = r["asset"], r["stato"]
        rif = f"{a.asset_tag} — {a.name}"
        scheda = ("Apri la scheda", reverse("assets:asset_view", args=[a.pk]))
        if st["codice"] == "scaduta":
            aperta("Macchina scaduta", rif, st["label"], scheda)
        elif st["codice"] == "da_valutare":
            aperta("Macchina da valutare", rif, "dopo un intervento: serve una verifica (MOD.161)", scheda)
        elif st["codice"] == "sospesa":
            aperta("Macchina sospesa", rif, (r["qualifica"].motivo_stato if r["qualifica"] else "") or p.nome, scheda)
        elif st["codice"] in ("da_qualificare", "non_richiesta"):
            aperta("Macchina da qualificare", rif, "nessuna verifica conforme registrata", scheda)
        for x in r["problemi"]:
            aperta("Requisito macchina scaduto", rif, f"{x['nome']}: {x['label']}", scheda)
    for reg in registri:
        if reg.stato == RegistroUtensile.STATO_TCP or (reg.residuo is not None and reg.residuo <= 0):
            aperta("Utensile al TCP", reg.identificativo, "punto di cambio raggiunto: sostituire e chiudere il MOD.176",
                   ("Apri il registro", reverse("anagrafica:mpq_registro", args=[reg.pk])) if con_personale else None)
    for tp in tp_senza_rev:
        aperta("Technical Plan senza revisione approvata", f"{tp.part_number} · {tp.tipologia_foro}",
               "non utilizzabile in produzione finché il cliente non approva una revisione",
               ("Apri il Technical Plan", reverse("anagrafica:mpq_tp", args=[tp.pk])) if con_personale else None)
    for tp in tp_in_approvazione:
        if tp not in tp_senza_rev:
            aperta("Revisione Technical Plan in approvazione", f"{tp.part_number} · {tp.tipologia_foro}",
                   "in produzione resta valida la revisione approvata precedente",
                   ("Apri il Technical Plan", reverse("anagrafica:mpq_tp", args=[tp.pk])) if con_personale else None)
    for ab in abilitazioni:
        if ab.stato != ab.STATO_ATTIVA:
            aperta(f"Abilitazione {stati_ab.get(ab.stato, ab.stato).lower()}", nome_persona(ab), ab.processo.nome,
                   apri(ab.processo))
            continue
        st = stati_persona.get(ab.pk)
        if st and not st.get("operativa", True):
            aperta("Persona non qualificata", nome_persona(ab), st["label"], apri(ab.processo))
    for dl in formazione:
        if dl.stato_scadenza in ("SCADUTO", "MAI_FREQUENTATO"):
            aperta("Formazione scaduta" if dl.stato_scadenza == "SCADUTO" else "Formazione mancante",
                   nomi.get(dl.legacy_anagrafica_id) or f"#{dl.legacy_anagrafica_id}", str(dl.corso), scadenzario)
    for persona, corso in formazione_mancante:
        aperta("Formazione mancante", nomi.get(persona) or f"#{persona}", str(corso), scadenzario)
    s_aperte.ordina(lambda riga: 0 if riga[0] == PRIORITA_ALTA else 1)

    # ── Documenti ────────────────────────────────────────────────────────────
    # I riferimenti del processo (procedure, moduli, approvazioni del cliente) con la
    # revisione corrente nel registro SGI quando il codice c'è; sempre il MOD.128.
    s_doc = Sezione("documenti", "Documenti di riferimento",
                    ["Documento", "A cosa serve", "Titolo nel registro SGI", "Revisione", "Data revisione"],
                    nota="I riferimenti registrati sul processo, con la revisione corrente nel registro SGI "
                         "(Procedure) quando il codice c'è.", chiusa=True)
    voci_doc = [("MOD.128", "Registro dei processi qualificati: personale abilitato", None)]
    for p in elenco:
        for rif in p.riferimenti.all():
            perche = " · ".join(x for x in (rif.get_tipo_display(), rif.note, p.nome if len(elenco) > 1 else "") if x)
            voci_doc.append((rif.codice, perche, p))
    revisioni = _sicuro(avvisi, "Documenti SGI",
                        lambda: _documenti_sgi([(c, perche) for c, perche, _ in voci_doc]), [])
    revisioni = revisioni or [{"rev": None}] * len(voci_doc)  # registro SGI non leggibile: righe senza revisione
    for (codice, perche, p), doc in zip(voci_doc, revisioni, strict=True):
        rev = doc["rev"]
        if rev is None:
            s_doc.aggiungi([codice, perche, "", "", ""], apri(p) if p is not None else None)
            continue
        s_doc.aggiungi([rev.document.code, perche, rev.document.title, rev.revision_code or "—",
                        _d(rev.revision_date)],
                       ("Apri il documento", reverse("procedure_refresh:document_open", args=[rev.pk])))

    per_codice = {s.codice: s for s in (s_aperte, s_scad, s_proc, s_macc, s_ut, s_tp, s_reg, s_pers, s_form, s_doc)}
    if not con_personale:
        per_codice.pop("personale")
        per_codice.pop("formazione")
    # Solo le parti che il processo usa: niente utensili, Technical Plan o MOD.176 vuoti;
    # le macchine si mostrano se ce ne sono o se il processo le richiede (frequenza).
    for codice, sez in (("utensili", s_ut), ("technical_plan", s_tp), ("registro", s_reg)):
        if not sez.righe:
            per_codice.pop(codice)
    if not s_macc.righe and not any(p.frequenza_macchine_mesi for p in elenco):
        per_codice.pop("macchine")
    sezioni = [per_codice[c] for c in (ordine or ORDINE_ASSET) if c in per_codice]

    # ── Riquadri ─────────────────────────────────────────────────────────────
    alte = sum(1 for r in s_aperte.righe if r[0] == PRIORITA_ALTA)
    scadute = sum(1 for r in s_scad.righe if r[-1] == "Scaduta")
    operative = sum(1 for _, r in righe_macchine if r["operativa"])
    al_tcp = sum(1 for reg in registri if reg.stato == RegistroUtensile.STATO_TCP)
    kpi = [
        {"etichetta": "Da sistemare", "valore": len(s_aperte.righe), "sezione": "aperte",
         "nota": f"{alte} a priorità alta" if alte else "nessuna urgente",
         "stato": "ko" if alte else ("warn" if s_aperte.righe else "ok")},
        {"etichetta": f"Scadenze {giorni} giorni", "valore": len(s_scad.righe), "sezione": "scadenze",
         "nota": f"{scadute} già scadute" if scadute else "nessuna scaduta",
         "stato": "ko" if scadute else ("warn" if s_scad.righe else "ok")},
        {"etichetta": "Macchine", "valore": len(righe_macchine), "sezione": "macchine",
         "nota": f"{operative} operative", "stato": "ko" if operative < len(righe_macchine) else ("" if righe_macchine else "warn")},
        {"etichetta": "Utensili critici", "valore": len(s_ut.righe), "sezione": "utensili",
         "nota": f"{len(registri)} in uso" + (f" · {al_tcp} al TCP" if al_tcp else ""), "stato": "ko" if al_tcp else ""},
        {"etichetta": "Technical Plan", "valore": len(s_tp.righe), "sezione": "technical_plan",
         "nota": f"{len(tp_senza_rev)} senza revisione approvata" if tp_senza_rev else "tutti approvati",
         "stato": "ko" if tp_senza_rev else ""},
    ]
    if con_personale:
        persone = len({(a.legacy_anagrafica_id, a.nominativo_esterno) for a in abilitazioni if a.stato == a.STATO_ATTIVA})
        non_ok = sum(1 for a in abilitazioni if a.stato == a.STATO_ATTIVA
                     and not (stati_persona.get(a.pk) or {}).get("operativa", True))
        voce = {"etichetta": "Persone abilitate", "valore": persone, "sezione": "personale",
                "nota": f"{non_ok} non qualificate" if non_ok else "tutte qualificate",
                "stato": "warn" if not persone or non_ok else ""}
        kpi.insert(2 if ordine == ORDINE_QUALIFICHE else len(kpi), voce)
    kpi = [k for k in kpi if k["sezione"] in per_codice]
    titolo = titolo_sezione(sigla, elenco)
    return {"oggi": oggi, "sigla": sigla, "titolo": titolo, "processi": elenco, "kpi": kpi, "sezioni": sezioni,
            "con_personale": con_personale, "avvisi": avvisi, "badge": BADGE,
            # Per gli export (stesse funzioni del Dossier PART 145).
            "titolo_export": titolo, "nome_file": f"sezione-{slugify(sigla)}-{oggi:%Y%m%d}",
            "riepilogo": [(k["etichetta"], k["valore"]) for k in kpi]}
