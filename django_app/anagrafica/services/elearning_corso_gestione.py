"""Pagina di gestione di un corso e-learning: stato chiaro, risultati unificati, persone assegnabili, export.

- ``stato_corso``: il corso è visibile ai dipendenti? con l'elenco dei controlli e lo stato del link aperto;
- ``righe_risultati``: una riga per persona, che sia assegnata, iscritta o tutte e due
  (chi è assegnato e non ha mai aperto il corso risulta «Da iniziare");
- ``persone_assegnabili``: dipendenti attivi con reparto, area, mansione e stato sul corso, per il pannello «Assegna»;
- ``domande_difficili``: domande sbagliate più spesso nei tentativi consegnati;
- righe per gli export (Excel/PDF): esiti, domande, risposte dal link aperto, registro dei completamenti.
"""
from __future__ import annotations

from django.utils import timezone

DA_INIZIARE, IN_CORSO, COMPLETATO, NON_SUPERATO, ESONERATO = (
    "da_iniziare", "in_corso", "completato", "non_superato", "esonerato")
ETICHETTE = {DA_INIZIARE: "Da iniziare", IN_CORSO: "In corso", COMPLETATO: "Completato",
             NON_SUPERATO: "Non superato", ESONERATO: "Esonerato"}
TONI = {DA_INIZIARE: "grey", IN_CORSO: "amber", COMPLETATO: "green", NON_SUPERATO: "orange", ESONERATO: "grey"}
ORDINE = [NON_SUPERATO, IN_CORSO, DA_INIZIARE, COMPLETATO, ESONERATO]


def _anagrafica(ids) -> dict[int, dict]:
    from core.legacy_anagrafica import fetch_anagrafica_rows
    ids = sorted({int(i) for i in ids if i})
    if not ids:
        return {}
    try:
        return {int(r["id"]): r for r in fetch_anagrafica_rows(ids=ids) if r.get("id")}
    except Exception:
        return {}


def _aziendale(ids) -> dict[int, dict]:
    from ..models import DipendenteAnagraficaAziendale
    out = {}
    for d in (DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id__in=list(ids))
              .select_related("area_aziendale")):
        out[d.legacy_anagrafica_id] = {"reparto": d.area or "",
                                       "area": getattr(d.area_aziendale, "nome", "") if d.area_aziendale_id else ""}
    return out


def _nome(r: dict, legacy_id: int) -> str:
    nome = f"{(r.get('cognome') or '').strip().upper()} {(r.get('nome') or '').strip()}".strip()
    return nome or f"#{legacy_id}"


# ─────────────────────────────────────────────────────────────────────────────
# Stato del corso
# ─────────────────────────────────────────────────────────────────────────────

def stato_corso(corso, *, n_slide: int, n_domande: int, n_invalid: int, link) -> dict:
    pubblicato = bool(corso.is_elearning and corso.is_active and corso.stato == "ATTIVO")
    controlli = [
        {"ok": n_slide > 0, "testo": f"{n_slide} slide" if n_slide else "Nessuna slide",
         "aiuto": "" if n_slide else "Aggiungi almeno una slide da «Slide e quiz»."},
        {"ok": n_domande > 0 and not n_invalid,
         "testo": (f"{n_domande} domande nel quiz" if n_domande else "Quiz senza domande")
                  + (f", {n_invalid} da sistemare" if n_invalid else ""),
         "aiuto": "Ogni domanda deve avere la risposta giusta." if n_invalid else
                  ("Senza quiz il corso si completa guardando le slide." if not n_domande else "")},
        {"ok": pubblicato, "testo": "Pubblicato" if pubblicato else "Non pubblicato (bozza)",
         "aiuto": "" if pubblicato else "Premi «Pubblica» in alto."},
    ]
    if link is None or not link.attivo:
        link_stato, link_testo = "spento", "Link aperto spento"
    elif link.scade_il and timezone.localdate() > link.scade_il:
        link_stato, link_testo = "scaduto", f"Link aperto scaduto il {link.scade_il:%d-%m-%Y}"
    elif not pubblicato or not n_slide:
        link_stato, link_testo = "bloccato", ("Link aperto attivo, ma non funziona finché il corso è in bozza"
                                              if not pubblicato else "Link aperto attivo, ma il corso non ha slide")
    else:
        link_stato, link_testo = "ok", "Link aperto funzionante"
    pronto = n_slide > 0 and not n_invalid
    if pubblicato and not n_slide:
        frase = "Il corso è pubblicato ma senza slide non è visibile: aggiungile da «Slide e quiz»."
    elif pubblicato and pronto:
        frase = "Il corso è online: i dipendenti lo trovano in «Corsi online», gli assegnati anche tra le loro attività."
    elif pubblicato:
        frase = "Il corso è online ma ha qualcosa da sistemare."
    elif pronto:
        frase = "Il corso è pronto ma non è visibile: premi «Pubblica»."
    else:
        frase = "Il corso non è visibile ai dipendenti: completa i contenuti e pubblicalo."
    return {"visibile": pubblicato and n_slide > 0, "pronto": pronto, "controlli": controlli, "frase": frase,
            "link_stato": link_stato, "link_testo": link_testo}


# ─────────────────────────────────────────────────────────────────────────────
# Risultati per persona
# ─────────────────────────────────────────────────────────────────────────────

def righe_risultati(corso) -> list[dict]:
    from ..models_formazione import TrainingAssignment, TrainingElearningEnrollment
    from .elearning_quiz import tentativi_rimasti
    from .elearning_regole import regola_corso

    from ..models_elearning import TrainingElearningRispostaAperta
    from ..models_formazione import TrainingEmployeeRecord

    from .formazione_completamento import COMPLETATO as P_COMPLETATO
    from .formazione_completamento import DA_REGISTRARE as P_DA_REGISTRARE
    from .formazione_completamento import SCADUTO as P_SCADUTO
    from .formazione_completamento import stati_persona_corso

    assegnazioni = {}
    for a in TrainingAssignment.objects.filter(corso=corso).order_by("ciclo", "pk"):
        assegnazioni[a.legacy_anagrafica_id] = a  # vince l'ultimo ciclo
    iscrizioni = {}
    for e in TrainingElearningEnrollment.objects.filter(corso=corso).order_by("ciclo"):
        iscrizioni[e.legacy_anagrafica_id] = e  # vince l'ultimo ciclo
    # Chi ha un completamento (anche link aperto o aula, senza iscrizione): compare fra le righe;
    # conta come completato solo se idoneo e non scaduto (regola unica stato persona × corso).
    record_validi = set(TrainingEmployeeRecord.objects.filter(corso=corso)
                        .values_list("legacy_anagrafica_id", flat=True))
    da_link = set(TrainingElearningRispostaAperta.objects.filter(corso=corso, record__isnull=False)
                  .values_list("legacy_anagrafica_id", flat=True))
    from ..models_elearning import TrainingElearningPartecipazioneAperta
    aperte = {}
    for pa in (TrainingElearningPartecipazioneAperta.objects.filter(corso=corso, legacy_anagrafica_id__isnull=False)
               .order_by("registrato_il")):
        aperte[pa.legacy_anagrafica_id] = pa
    ids = set(assegnazioni) | set(iscrizioni) | set(record_validi) | set(aperte)
    anag, azi = _anagrafica(ids), _aziendale(ids)
    regola = regola_corso(corso)
    oggi = timezone.localdate()
    stati_p = stati_persona_corso(corso, ids, oggi=oggi)
    righe = []
    for lid in ids:
        a, e = assegnazioni.get(lid), iscrizioni.get(lid)
        sp = stati_p.get(lid)
        rec = sp.record if sp is not None and sp.codice == P_COMPLETATO else None
        aperta = a is not None and a.stato not in ("COMPLETATO", "ESONERATO")
        # L'iscrizione e-learning conta solo se è del ciclo dell'assegnazione (o più recente).
        if e is not None and a is not None and e.ciclo < a.ciclo:
            e_ciclo = None
        else:
            e_ciclo = e
        etichetta = ""
        if a is not None and a.stato == "ESONERATO":
            stato = ESONERATO
        elif rec is not None and not aperta:
            stato = COMPLETATO
        elif e_ciclo is not None and e_ciclo.stato == "COMPLETATO" and rec is not None:
            stato = COMPLETATO
        elif sp is not None and sp.codice == P_DA_REGISTRARE:
            stato, etichetta = IN_CORSO, "Da registrare"
        elif e_ciclo is None and lid in aperte and not aperte[lid].completata_il:
            stato = IN_CORSO
        elif e_ciclo is not None and e_ciclo.stato == "NON_SUPERATO":
            stato = NON_SUPERATO
        elif e_ciclo is not None and e_ciclo.stato != "COMPLETATO" and (
                e_ciclo.stato == "IN_CORSO" or e_ciclo.ultima_slide_ordine):
            stato = IN_CORSO
        else:
            stato = DA_INIZIARE
            if sp is not None and sp.codice == P_SCADUTO and not aperta:
                etichetta = "Scaduto"
        r = anag.get(lid, {})
        tot = (e.n_slide_totali if e else 0) or 0
        viste = (e.ultima_slide_ordine if e else 0) or 0
        pa = aperte.get(lid)
        if e is None and pa is not None:
            tot = corso.slides.filter(is_active=True).count()
            viste = len(pa.slide_viste or {})
        scadenza = a.due_date if a else None
        righe.append({
            "legacy_id": lid,
            "nome": _nome(r, lid),
            "reparto": azi.get(lid, {}).get("reparto") or r.get("reparto") or "",
            "assegnato": a is not None,
            "assegnazione": a,
            "scadenza": scadenza,
            "in_ritardo": bool(scadenza and scadenza < oggi and stato not in (COMPLETATO, ESONERATO)),
            "stato": stato, "etichetta": etichetta or ETICHETTE[stato], "tono": TONI[stato],
            "enrollment": e,
            "slide": f"{viste}/{tot}" if tot else "—",
            "slide_pct": min(100, round(100 * viste / tot)) if tot else (100 if stato == COMPLETATO else 0),
            "best": e.best_punteggio_pct if e else None,
            "tentativi": e.n_tentativi if e else 0,
            "minuti": round((e.secondi_accreditati or 0) / 60) if e else (round((pa.secondi or 0) / 60) if pa else 0),
            "completato_il": (rec.data_completamento if rec is not None else None) if stato == COMPLETATO else None,
            "da_link_aperto": lid in da_link or lid in aperte,
            "esauriti": bool(e and e.stato != "COMPLETATO" and tentativi_rimasti(e, regola) == 0),
            "ha_utente": bool(r.get("utente_id")),
        })
    righe.sort(key=lambda x: (ORDINE.index(x["stato"]), not x["in_ritardo"], x["nome"]))
    return righe


def numeri(righe: list[dict]) -> dict:
    conta = {k: 0 for k in ETICHETTE}
    for r in righe:
        conta[r["stato"]] += 1
    tot = len(righe) - conta[ESONERATO]
    iniziati = sum(1 for r in righe if r["stato"] in (IN_CORSO, COMPLETATO, NON_SUPERATO))
    punteggi = [float(r["best"]) for r in righe if r["best"] is not None]
    tentati = [r["tentativi"] for r in righe if r["tentativi"]]
    minuti = [r["minuti"] for r in righe if r["minuti"]]
    return {
        "persone": tot,
        "assegnati": sum(1 for r in righe if r["assegnato"]),
        "conta": conta,
        "iniziati": iniziati,
        "completati_pct": round(100 * conta[COMPLETATO] / tot) if tot else 0,
        "media_punteggio": round(sum(punteggi) / len(punteggi)) if punteggi else None,
        "media_tentativi": round(sum(tentati) / len(tentati), 1) if tentati else None,
        "media_minuti": round(sum(minuti) / len(minuti)) if minuti else None,
        "in_ritardo": sum(1 for r in righe if r["in_ritardo"]),
    }


def domande_difficili(corso, limite: int = 6) -> list[dict]:
    from ..models_formazione import TrainingQuizAttempt
    stat: dict = {}
    for rj in (TrainingQuizAttempt.objects.filter(corso=corso, stato="INVIATO")
               .values_list("risposte_json", flat=True)):
        for v in (rj or {}).get("risposte", []) if isinstance(rj, dict) else []:
            testo = v.get("domanda") or ""
            s = stat.setdefault(testo, {"domanda": testo, "totale": 0, "errate": 0})
            s["totale"] += 1
            s["errate"] += 0 if v.get("giusta") else 1
    elenco = [dict(s, pct=round(100 * s["errate"] / s["totale"])) for s in stat.values() if s["totale"]]
    elenco.sort(key=lambda s: (-s["pct"], -s["errate"]))
    return elenco[:limite]


# ─────────────────────────────────────────────────────────────────────────────
# Persone assegnabili (pannello «Assegna»)
# ─────────────────────────────────────────────────────────────────────────────

def persone_assegnabili(corso) -> list[dict]:
    from ..models import DipendenteAnagraficaAziendale
    from ..models_formazione import TrainingAssignment, TrainingElearningEnrollment

    attivi = list(DipendenteAnagraficaAziendale.objects.filter(data_cessazione__isnull=True)
                  .values_list("legacy_anagrafica_id", flat=True))
    anag, azi = _anagrafica(attivi), _aziendale(attivi)
    assegnati = set(TrainingAssignment.objects.filter(corso=corso).values_list("legacy_anagrafica_id", flat=True))
    completati = set(TrainingElearningEnrollment.objects.filter(corso=corso, stato="COMPLETATO")
                     .values_list("legacy_anagrafica_id", flat=True))
    # Completato = ha un completamento valido del corso, da qualunque strada (aula, link aperto, sessione).
    from .formazione_completamento import ids_con_completamento_valido
    completati |= ids_con_completamento_valido(corso, attivi)
    out = []
    for lid in attivi:
        r = anag.get(lid)
        if r is None or lid in assegnati:
            continue
        out.append({
            "legacy_id": lid, "nome": _nome(r, lid),
            "reparto": azi.get(lid, {}).get("reparto") or r.get("reparto") or "",
            "area": azi.get(lid, {}).get("area") or "",
            "mansione": r.get("mansione") or "",
            "ha_utente": bool(r.get("utente_id")),
            "completato": lid in completati,
        })
    out.sort(key=lambda x: x["nome"])
    return out


def persone_iscrivibili(sessione) -> list[dict]:
    """Dipendenti attivi non ancora iscritti alla sessione, con lo stato rispetto al corso.

    ``stato``: ``da_formare`` (nessun completamento valido), ``in_scadenza`` (scade entro 90
    giorni), ``in_regola``. ``assegnato`` = ha un'assegnazione aperta del corso."""
    from datetime import timedelta

    from ..models import DipendenteAnagraficaAziendale
    from ..models_formazione import TrainingAssignment, TrainingEmployeeRecord, TrainingEnrollment

    corso = sessione.corso
    attivi = list(DipendenteAnagraficaAziendale.objects.filter(data_cessazione__isnull=True)
                  .values_list("legacy_anagrafica_id", flat=True))
    anag, azi = _anagrafica(attivi), _aziendale(attivi)
    iscritti = set(TrainingEnrollment.objects.filter(sessione=sessione).values_list("legacy_anagrafica_id", flat=True))
    assegnati = set(TrainingAssignment.objects.filter(corso=corso).exclude(stato__in=("COMPLETATO", "ESONERATO"))
                    .values_list("legacy_anagrafica_id", flat=True))
    oggi = timezone.localdate()
    tra90 = oggi + timedelta(days=90)
    migliore: dict[int, object] = {}
    for lid, scad in TrainingEmployeeRecord.objects.filter(corso=corso).values_list("legacy_anagrafica_id", "data_scadenza"):
        attuale = migliore.get(lid, "assente")
        if scad is None or attuale is None:
            migliore[lid] = None  # una tantum o senza scadenza: in regola per sempre
        elif attuale == "assente" or scad > attuale:
            migliore[lid] = scad
    out = []
    for lid in attivi:
        r = anag.get(lid)
        if r is None or lid in iscritti:
            continue
        scad = migliore.get(lid, "assente")
        if scad == "assente" or (scad is not None and scad < oggi):
            stato = "da_formare"
        elif scad is not None and scad <= tra90:
            stato = "in_scadenza"
        else:
            stato = "in_regola"
        out.append({
            "legacy_id": lid, "nome": _nome(r, lid),
            "reparto": azi.get(lid, {}).get("reparto") or r.get("reparto") or "",
            "area": azi.get(lid, {}).get("area") or "",
            "mansione": r.get("mansione") or "",
            "ha_utente": bool(r.get("utente_id")),
            "stato": stato, "scadenza": scad if scad not in ("assente", None) else None,
            "assegnato": lid in assegnati,
        })
    out.sort(key=lambda x: x["nome"])
    return out


def opzioni(persone: list[dict], chiave: str) -> list[str]:
    return sorted({p[chiave] for p in persone if p[chiave]}, key=str.lower)


# ─────────────────────────────────────────────────────────────────────────────
# Export
# ─────────────────────────────────────────────────────────────────────────────

def _d(v):
    return v.strftime("%d-%m-%Y") if v else ""


def export_esiti(corso):
    righe = righe_risultati(corso)
    intest = ["Persona", "Reparto", "Assegnato", "Scadenza", "Stato", "Slide", "Miglior punteggio %",
              "Tentativi", "Minuti", "Completato il"]
    dati = [[r["nome"], r["reparto"], "Sì" if r["assegnato"] else "No", _d(r["scadenza"]),
             r["etichetta"] + (" (in ritardo)" if r["in_ritardo"] else ""), r["slide"],
             r["best"] if r["best"] is not None else "", r["tentativi"], r["minuti"], _d(r["completato_il"])]
            for r in righe]
    return "Esiti per persona", intest, dati


def export_domande(corso):
    elenco = domande_difficili(corso, limite=500)
    return ("Analisi delle domande", ["Domanda", "Risposte date", "Errate", "% errate"],
            [[d["domanda"], d["totale"], d["errate"], d["pct"]] for d in elenco])


def export_link(corso):
    from ..models_elearning import TrainingElearningRispostaAperta
    intest = ["Cognome", "Nome", "Inviato il", "Esito", "Giuste", "Totali", "Abbinamento", "Nota"]
    dati = []
    for r in TrainingElearningRispostaAperta.objects.filter(corso=corso).order_by("-inviato_il"):
        dati.append([r.cognome, r.nome, timezone.localtime(r.inviato_il).strftime("%d-%m-%Y %H:%M") if r.inviato_il else "",
                     "Superato" if r.superato else "Non superato", r.n_corrette, r.n_totali,
                     r.get_stato_display(), r.nota or ""])
    return "Risposte dal link aperto", intest, dati


def export_registro(corso):
    from .elearning_report import registro
    intest = ["Data", "Persona", "Versione", "Ciclo", "Minuti effettivi", "Slide", "Tentativi", "Punteggio %",
              "Protocollo", "Impronta"]
    dati = [[timezone.localtime(r["data"]).strftime("%d-%m-%Y %H:%M"), r["dipendente"], r["versione"], r["ciclo"],
             r["minuti_effettivi"], r["slide"], r["tentativi"], r["punteggio"], r["protocollo"], r["impronta"]]
            for r in registro(corso_id=corso.pk)]
    return "Registro dei completamenti", intest, dati


EXPORT = {"esiti": export_esiti, "domande": export_domande, "link": export_link, "registro": export_registro}
