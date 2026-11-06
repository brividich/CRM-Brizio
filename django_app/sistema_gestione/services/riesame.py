"""Riesame della direzione (MT CN 19, MOD.062): verbale, argomenti, obiettivi.

Gli indicatori arrivano dai report di Report conformità, gli stessi del pacchetto di
ingresso, e si fissano nel verbale: dopo l'approvazione non cambiano più. Gli obiettivi
fissati in un verbale tornano nel successivo per il livello di raggiungimento.
"""
from __future__ import annotations

import logging
from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..models import Riesame, RiesameArgomento, RiesameObiettivo, RiesamePartecipante

logger = logging.getLogger(__name__)

# Testi brevi scritti per il portale. Riferimenti ai punti di MT CN 19 §6.4; SSL, ISMS e PdR
# coprono le altre norme del MOD.062. Ogni verbale ne conserva una copia, quindi cambiarli
# qui non tocca i verbali già scritti.
ARGOMENTI = [
    ("a-b", Riesame.GRUPPO_INGRESSO, "Rischi, punti di forza e debolezza, opportunità e minacce", ()),
    ("c", Riesame.GRUPPO_INGRESSO, "Politica aziendale: adeguatezza e diffusione", ()),
    ("d", Riesame.GRUPPO_INGRESSO, "Risultati rispetto agli obiettivi e azioni operative non chiuse", ()),
    ("e", Riesame.GRUPPO_INGRESSO, "Prestazioni dei processi e indicatori",
     ("verifiche-periodiche", "manutenzione", "processi-speciali")),
    ("f", Riesame.GRUPPO_INGRESSO, "Risultati degli audit interni e dell'ente di certificazione",
     ("audit-interni", "certificazioni-audit-esterni")),
    ("g", Riesame.GRUPPO_INGRESSO, "Clienti: reclami e soddisfazione", ()),
    ("h-k", Riesame.GRUPPO_INGRESSO, "Non conformità e stato delle azioni correttive", ("registro-nc-ofi",)),
    ("i", Riesame.GRUPPO_INGRESSO, "Risultati dei fornitori", ("albo-fornitori",)),
    ("j", Riesame.GRUPPO_INGRESSO, "Adeguatezza delle risorse", ("competenze", "efficacia-formazione")),
    ("l", Riesame.GRUPPO_INGRESSO, "Modifiche al sistema per innovazioni tecniche e organizzative", ()),
    ("m", Riesame.GRUPPO_INGRESSO, "Opportunità e richieste di miglioramento", ()),
    ("o", Riesame.GRUPPO_INGRESSO, "Ambiente di lavoro: temperatura, umidità, illuminazione, pulizia", ()),
    ("SSL", Riesame.GRUPPO_INGRESSO, "Salute e sicurezza sul lavoro", ("eventi-sicurezza", "dpi", "scadenziario-legale")),
    ("ISMS", Riesame.GRUPPO_INGRESSO, "Sicurezza delle informazioni", ("dichiarazione-applicabilita", "sicurezza-it")),
    ("PdR", Riesame.GRUPPO_INGRESSO, "Parità di genere: esiti del Comitato Guida", ()),
    ("U1", Riesame.GRUPPO_USCITA, "Opportunità di miglioramento decise", ()),
    ("U2", Riesame.GRUPPO_USCITA, "Modifiche decise al sistema di gestione", ()),
    ("U3", Riesame.GRUPPO_USCITA, "Risorse necessarie", ()),
]
_REPORT_PER_CODICE = {codice: report for codice, _gruppo, _titolo, report in ARGOMENTI}


class TransizioneNonAmmessa(Exception):
    pass


def prossimo_riesame(oggi: date | None = None) -> date | None:
    """Entro quando va fatto il prossimo (MT CN 19 §6.1: almeno annuale); ``None`` se non ce n'è uno approvato."""
    ultimo = (Riesame.objects.filter(stato=Riesame.STATO_APPROVATO).order_by("-data").values_list("data", flat=True)
              .first())
    if not ultimo:
        return None
    try:
        return ultimo.replace(year=ultimo.year + 1)
    except ValueError:  # 29 febbraio
        return ultimo.replace(year=ultimo.year + 1, day=28)


def indicatori_report(riesame: Riesame, slugs, aree: set[str] | None) -> list[dict]:
    """Gli indicatori dei report indicati, nel periodo del verbale. ``aree`` limita a quelle di chi prepara."""
    from report_conformita.corrections import corrected_result
    from report_conformita.registry import ReportParams, get_report

    params = ReportParams(date_from=riesame.periodo_dal, date_to=riesame.periodo_al, today=timezone.localdate())
    out = []
    for slug in slugs:
        definizione = get_report(slug)
        if definizione is None or (aree is not None and definizione.area not in aree):
            continue
        try:
            risultato = corrected_result(definizione, params)
        except Exception:
            logger.exception("riesame: report %s non calcolabile", slug)
            out.append({"slug": slug, "titolo": definizione.title, "errore": True, "kpi": []})
            continue
        out.append({"slug": slug, "titolo": definizione.title, "errore": False,
                    "kpi": [{"label": k.label, "value": str(k.value), "tone": k.tone} for k in risultato.kpis]})
    return out


def aggiorna_indicatori(riesame: Riesame, aree: set[str] | None) -> None:
    if not riesame.modificabile:
        raise TransizioneNonAmmessa("Il verbale non è in bozza: gli indicatori restano quelli fissati.")
    for argomento in riesame.argomenti.all():
        slugs = _REPORT_PER_CODICE.get(argomento.codice, ())
        if slugs:
            argomento.indicatori = indicatori_report(riesame, slugs, aree)
            argomento.save(update_fields=["indicatori"])
    riesame.indicatori_aggiornati_il = timezone.now()
    riesame.save(update_fields=["indicatori_aggiornati_il", "updated_at"])


@transaction.atomic
def crea_riesame(riesame: Riesame, *, utente, aree: set[str] | None) -> Riesame:
    """Salva il nuovo verbale con gli argomenti, gli indicatori e i partecipanti dell'ultimo verbale."""
    precedente = Riesame.objects.order_by("-data", "-pk").first()
    riesame.preparato_da = utente
    riesame.save()
    RiesameArgomento.objects.bulk_create([
        RiesameArgomento(riesame=riesame, codice=codice, gruppo=gruppo, titolo=titolo, ordine=i)
        for i, (codice, gruppo, titolo, _report) in enumerate(ARGOMENTI)
    ])
    if precedente:
        for p in precedente.partecipanti.all():
            RiesamePartecipante.objects.create(riesame=riesame, funzione=p.funzione, nome=p.nome, utente=p.utente)
    aggiorna_indicatori(riesame, aree)
    return riesame


def obiettivi_precedenti(riesame: Riesame):
    """Gli obiettivi dei verbali approvati che questo verbale deve valutare."""
    return (RiesameObiettivo.objects.filter(riesame__stato=Riesame.STATO_APPROVATO).exclude(riesame=riesame)
            .filter(Q(stato=RiesameObiettivo.STATO_APERTO, chiuso_in__isnull=True) | Q(chiuso_in=riesame))
            .select_related("riesame", "responsabile", "processo").order_by("scadenza", "pk"))


@transaction.atomic
def valuta_precedente(riesame: Riesame, obiettivo: RiesameObiettivo, *, stato: str, nota: str) -> None:
    """Livello di raggiungimento. «Ripianificato» crea il nuovo obiettivo in questo verbale, una volta sola."""
    if not riesame.modificabile:
        raise TransizioneNonAmmessa("Il verbale non è in bozza.")
    if stato not in dict(RiesameObiettivo.STATO_CHOICES):
        raise ValueError("Stato non valido.")
    obiettivo.stato = stato
    obiettivo.nota = nota.strip()
    obiettivo.chiuso_in = None if stato == RiesameObiettivo.STATO_APERTO else riesame
    obiettivo.save(update_fields=["stato", "nota", "chiuso_in"])
    copia = RiesameObiettivo.objects.filter(riesame=riesame, origine=obiettivo)
    if stato == RiesameObiettivo.STATO_RIPIANIFICATO and not copia.exists():
        RiesameObiettivo.objects.create(
            riesame=riesame, origine=obiettivo, descrizione=obiettivo.descrizione, processo=obiettivo.processo,
            indicatore=obiettivo.indicatore, risultato_atteso=obiettivo.risultato_atteso,
            responsabile=obiettivo.responsabile, risorse=obiettivo.risorse)
    elif stato != RiesameObiettivo.STATO_RIPIANIFICATO:
        copia.delete()


def problemi_proposta(riesame: Riesame) -> list[str]:
    """Cosa manca secondo MT CN 19 §6.5 prima di proporre il verbale alla Direzione."""
    problemi = []
    if not riesame.documenti_esaminati.strip():
        problemi.append("Indica i documenti esaminati.")
    if not riesame.partecipanti.exists():
        problemi.append("Indica i partecipanti.")
    vuoti = [a.codice for a in riesame.argomenti.all() if not a.analisi.strip()]
    if vuoti:
        problemi.append(f"Argomenti senza analisi: {', '.join(vuoti)}. Se uno non si applica, scrivilo.")
    senza_nota = [o for o in obiettivi_precedenti(riesame) if not o.nota.strip()]
    if senza_nota:
        problemi.append(f"Obiettivi precedenti senza livello di raggiungimento: {len(senza_nota)}.")
    incompleti = [o for o in riesame.obiettivi.select_related("responsabile") if not (o.responsabile_id and o.scadenza)]
    if incompleti:
        problemi.append(f"Nuovi obiettivi senza responsabile o scadenza: {len(incompleti)}.")
    return problemi


def proponi(riesame: Riesame) -> None:
    if riesame.stato != Riesame.STATO_BOZZA:
        raise TransizioneNonAmmessa("Si propone solo un verbale in bozza.")
    problemi = problemi_proposta(riesame)
    if problemi:
        raise TransizioneNonAmmessa(" ".join(problemi))
    riesame.stato = Riesame.STATO_PROPOSTO
    riesame.proposto_il = timezone.now()
    riesame.save(update_fields=["stato", "proposto_il", "updated_at"])


def riporta_in_bozza(riesame: Riesame) -> None:
    if riesame.stato != Riesame.STATO_PROPOSTO:
        raise TransizioneNonAmmessa("Solo un verbale proposto torna in bozza.")
    riesame.stato = Riesame.STATO_BOZZA
    riesame.save(update_fields=["stato", "updated_at"])


@transaction.atomic
def approva(riesame: Riesame, *, utente) -> None:
    """Approvazione del DIG: il verbale non cambia più, gli obiettivi valutati restano fissati nel testo."""
    if riesame.stato != Riesame.STATO_PROPOSTO:
        raise TransizioneNonAmmessa("Si approva solo un verbale proposto.")
    riesame.fotografia_precedenti = [
        {"descrizione": o.descrizione, "verbale": str(o.riesame), "risultato_atteso": o.risultato_atteso,
         "stato": o.get_stato_display(), "nota": o.nota}
        for o in obiettivi_precedenti(riesame)
    ]
    riesame.stato = Riesame.STATO_APPROVATO
    riesame.approvato_da = utente
    riesame.approvato_il = timezone.now()
    riesame.save(update_fields=["fotografia_precedenti", "stato", "approvato_da", "approvato_il", "updated_at"])


def obiettivi_aperti():
    """Gli obiettivi in corso dei verbali approvati, dalla scadenza più vicina."""
    return (RiesameObiettivo.objects.filter(riesame__stato=Riesame.STATO_APPROVATO, stato=RiesameObiettivo.STATO_APERTO)
            .select_related("riesame", "responsabile", "processo").order_by("scadenza", "pk"))
