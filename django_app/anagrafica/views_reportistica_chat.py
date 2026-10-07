"""Reportistica a conversazione: «chiedi un report» a parole.

Stessi cancelli della reportistica (``anagrafica.reportistica.view`` per chiedere
e scaricare, ``.manage`` per salvare come modello), stesse sezioni con i loro
permessi ulteriori, stesso archivio e stesso AuditLog. Lo stato sta nella
sessione dell'utente: nessun record finche' non si scarica o si salva.
Nell'AuditLog non finisce il testo libero (puo' contenere nomi), solo cosa e'
stato composto.
"""
from __future__ import annotations

import logging
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models import ReportGenerato
from .reportistica import conversazione, motore
from .reportistica import sezioni as catalogo
from .reportistica.dati import carica_dipendenti
from .reportistica.forms import scelte_perimetro
from .reportistica.permessi import can_manage, can_view
from .views_reportistica import MODULE, _nega, _scarica_nuovo

logger = logging.getLogger(__name__)

_CHAT = "rp_chat"
_MAX_STORICO_SESSIONE = 20
ESEMPI = (
    "Matrice della formazione sicurezza del reparto Produzione, solo i corsi scaduti",
    "Elenco del personale con qualifiche e abilitazioni, in Excel",
    "Organico e turnover dell'anno scorso, con assunzioni e cessazioni",
    "Scadenzario dei prossimi 60 giorni raggruppato per mese",
)


def _nuova() -> dict:
    return {"id": uuid.uuid4().hex, "specifica": conversazione.specifica_vuota(), "storico": [], "avvisi": [], "ai": True}


def _stato(request) -> dict:
    stato = request.session.get(_CHAT)
    if not isinstance(stato, dict) or not isinstance(stato.get("specifica"), dict) or not stato.get("id"):
        stato = _nuova()
    return stato


def _salva(request, stato: dict) -> None:
    stato["storico"] = list(stato.get("storico") or [])[-_MAX_STORICO_SESSIONE:]
    request.session[_CHAT] = stato
    request.session.modified = True


def _rinormalizza(request, stato: dict, grezza: dict) -> None:
    """Ogni modifica, anche dai comandi della pagina, ripassa dalla validazione."""
    dipendenti = carica_dipendenti()
    spec, avvisi = conversazione.normalizza_specifica(grezza, request, scelte_perimetro(dipendenti), dipendenti)
    stato["specifica"] = spec
    stato["avvisi"] = avvisi


def _riepilogo(specifica: dict) -> list[dict]:
    """Le sezioni scelte, in chiaro, con le sole opzioni diverse dal predefinito."""
    out = []
    for i, voce in enumerate(specifica.get("sezioni") or []):
        sezione = catalogo.get(voce["sezione"])
        if sezione is None:
            continue
        predefiniti = sezione.valori_opzioni(None)
        per_nome = {o.nome: o for o in sezione.tutte_le_opzioni()}
        dettagli = []
        for nome, valore in (voce.get("opzioni") or {}).items():
            o = per_nome.get(nome)
            if o is None or valore == predefiniti.get(nome):
                continue
            if o.tipo in (catalogo.SCELTA, catalogo.MULTI):
                nomi = dict(o.elenco_scelte())
                testo = ", ".join(nomi.get(v, v) for v in (valore if isinstance(valore, list) else [valore]))
            elif o.tipo == catalogo.SI_NO:
                testo = "sì" if valore else "no"
            else:
                testo = str(valore)
            dettagli.append(f"{o.etichetta}: {testo or 'nessuno'}")
        if voce.get("colonne"):
            colonne = dict(sezione.colonne)
            dettagli.append("Colonne: " + ", ".join(colonne.get(c, c) for c in voce["colonne"]))
        out.append({"indice": i, "titolo": sezione.titolo, "dettagli": dettagli})
    return out


def _messaggio(request, stato: dict, testo: str) -> None:
    dipendenti = carica_dipendenti()
    esito = conversazione.interpreta(
        testo, request=request, specifica=stato["specifica"], storico=stato.get("storico") or [],
        scelte_perimetro=scelte_perimetro(dipendenti), dipendenti=dipendenti,
    )
    stato["specifica"] = esito.specifica
    stato["avvisi"] = esito.avvisi
    stato["ai"] = esito.ai
    stato["storico"] = list(stato.get("storico") or []) + [
        {"role": "user", "content": testo},
        {"role": "assistant", "content": esito.risposta},
    ]
    if esito.specifica["sezioni"]:
        try:
            from ai_assistant.apprendimento import registra_proposta

            registra_proposta(modulo=conversazione.MODULO_AI, azione=conversazione.AZIONE_AI,
                              oggetto_ref=stato["id"], user=request.user,
                              proposta=conversazione.riassunto_decisione(esito.specifica))
        except Exception:  # noqa: BLE001 - l'apprendimento non blocca mai la richiesta
            logger.debug("reportistica: proposta AI non registrata", exc_info=True)
    log_action(request, "reportistica_chat_richiesta", MODULE, {
        "conversazione": stato["id"], "ai": esito.ai, "caratteri": len(testo),
        "sezioni": [s["sezione"] for s in esito.specifica["sezioni"]],
    })


def _imposta(request, stato: dict) -> None:
    """Comandi della pagina: titolo, destinatario, formato, periodo, cessati."""
    spec = dict(stato["specifica"])
    spec["titolo"] = request.POST.get("titolo", spec.get("titolo", ""))
    spec["destinatario"] = request.POST.get("destinatario", spec.get("destinatario", ""))
    spec["formato"] = request.POST.get("formato", spec.get("formato", "pdf"))
    spec["periodo"] = {"tipo": request.POST.get("periodo_tipo", ""), "da": request.POST.get("data_da", ""),
                       "a": request.POST.get("data_a", "")}
    spec["perimetro"] = {**(spec.get("perimetro") or {}), "includi_cessati": bool(request.POST.get("includi_cessati"))}
    _rinormalizza(request, stato, spec)


@login_required
def reportistica_chat(request):
    if not can_view(request):
        return _nega(request)
    stato = _stato(request)
    if request.method == "POST":
        azione = (request.POST.get("azione") or "messaggio").strip()
        if request.POST.get("nuova"):
            stato = _nuova()  # richiesta partita dalla pagina Reportistica: si riparte da zero
        if azione == "nuova":
            stato = _nuova()
        elif azione == "messaggio":
            testo = (request.POST.get("messaggio") or "").strip()[:conversazione.MAX_MESSAGGIO]
            if testo:
                _messaggio(request, stato, testo)
        elif azione == "togli":
            try:
                indice = int(request.POST.get("indice", "-1"))
            except ValueError:
                indice = -1
            spec = dict(stato["specifica"])
            spec["sezioni"] = [s for i, s in enumerate(spec.get("sezioni") or []) if i != indice]
            _rinormalizza(request, stato, spec)
        elif azione == "imposta":
            _imposta(request, stato)
        _salva(request, stato)
        # PRG: un ricaricamento della pagina non rimanda la richiesta all'AI.
        return redirect("anagrafica:reportistica_chat")

    documento = None
    if stato["specifica"].get("sezioni"):
        _modello, documento = conversazione.componi(stato["specifica"], request)
    return render(request, "anagrafica/pages/reportistica_chat.html", {
        "page_title": "Chiedi un report",
        "stato": stato,
        "specifica": stato["specifica"],
        "riepilogo": _riepilogo(stato["specifica"]),
        "documento": documento,
        "periodi": list(conversazione.PERIODI.items()),
        "esempi": ESEMPI,
        "can_manage": can_manage(request),
    })


@login_required
@require_POST
def reportistica_chat_scarica(request):
    if not can_view(request):
        return _nega(request)
    stato = _stato(request)
    specifica = stato["specifica"]
    if not specifica.get("sezioni"):
        messages.error(request, "Il report non ha ancora sezioni: chiedi prima quali dati ti servono.")
        return redirect("anagrafica:reportistica_chat")
    formato = request.POST.get("formato")
    if formato not in (ReportGenerato.FORMATO_PDF, ReportGenerato.FORMATO_XLSX):
        formato = specifica.get("formato") or ReportGenerato.FORMATO_PDF
    modello, documento = conversazione.componi(specifica, request)
    parametri = motore.Parametri(
        periodo_tipo=modello.periodo_tipo, data_da=modello.data_da, data_a=modello.data_a,
        perimetro=conversazione.perimetro_di(specifica), titolo=modello.titolo_documento,
        destinatario=modello.destinatario,
    )
    try:
        from ai_assistant.apprendimento import registra_decisione

        registra_decisione(modulo=conversazione.MODULO_AI, azione=conversazione.AZIONE_AI, oggetto_ref=stato["id"],
                           user=request.user,
                           decisione={**conversazione.riassunto_decisione(specifica), "formato": formato})
    except Exception:  # noqa: BLE001
        logger.debug("reportistica: decisione AI non registrata", exc_info=True)
    return _scarica_nuovo(request, modello, documento, parametri, formato,
                          (request.POST.get("note_archivio") or "").strip(),
                          extra={"conversazione": stato["id"], "specifica": specifica})


@login_required
@require_POST
def reportistica_chat_salva(request):
    if not can_manage(request):
        return _nega(request, "Non hai i permessi per creare modelli di report.")
    stato = _stato(request)
    if not stato["specifica"].get("sezioni"):
        messages.error(request, "Il report non ha ancora sezioni da salvare.")
        return redirect("anagrafica:reportistica_chat")
    modello = conversazione.salva_come_modello(stato["specifica"], nome=request.POST.get("nome") or "",
                                               user=request.user)
    log_action(request, "reportistica_modello_salvato", MODULE,
               {"modello": modello.pk, "nome": modello.nome, "da_conversazione": stato["id"]},
               oggetto_tipo="report_modello", oggetto_id=str(modello.pk))
    messages.success(request, f"Modello «{modello.nome}» creato: rifinisci testi e impaginazione, poi salvalo.")
    return redirect("anagrafica:reportistica_modello_edit", pk=modello.pk)
