"""Operazioni di dominio della checklist chiusure — NOVICROM HUB.

Qui vivono **solo** le operazioni che scrivono su più righe o che cambiano lo
stato di un evento/voce/proposta. Le view restano responsabili di request,
form, messaggi, redirect e autorizzazioni: nessun service layer generico, solo
funzioni concrete con la transazione circoscritta a ciò che serve.

Due invarianti guidano il modulo:

1. **un evento chiuso è archiviato**: non riceve voci nuove, le sue voci non si
   confermano né si sconfermano più (la chiusura è il punto in cui il registro
   diventa storico, e riaprirlo di fatto dalla pagina Gestione lo falserebbe);
2. **una proposta si decide una volta sola**: il secondo POST — doppio click,
   refresh, due amministratori sulla stessa pagina — non deve creare un secondo
   template né una seconda voce. Da qui il ``select_for_update`` + ricontrollo
   dello stato dentro la transazione, invece del solo controllo lato UI.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import ChecklistTaskTemplate, ChiusuraEvento, ChiusuraProposta, ChiusuraVoce

__all__ = [
    "ChecklistStatoError",
    "eventi_con_progresso",
    "crea_evento_con_voci",
    "genera_voci_da_template",
    "salva_voce",
    "conferma_voce",
    "annulla_conferma_voce",
    "chiudi_evento",
    "decidi_proposta",
]


class ChecklistStatoError(Exception):
    """Operazione rifiutata perché incompatibile con lo stato corrente.

    Il messaggio è già scritto per l'utente finale (italiano, senza gergo): le
    view lo passano a ``messages.error`` così com'è.
    """


# ---------------------------------------------------------------------------
# Lettura
# ---------------------------------------------------------------------------

def eventi_con_progresso(queryset=None):
    """Eventi con voci totali/confermate già annotate, per le liste.

    Senza questo, ogni riga della pagina di riepilogo costa quattro query
    (``voci_totali``, ``voci_confermate`` e le due che ``percentuale_completamento``
    richiama a sua volta). Le proprietà del modello leggono l'annotazione quando
    c'è e restano valide per chi non la usa.
    """
    qs = ChiusuraEvento.objects.all() if queryset is None else queryset
    return qs.annotate(
        n_voci_totali=Count("voci", distinct=True),
        n_voci_confermate=Count("voci", filter=Q(voci__confermato=True), distinct=True),
    )


# ---------------------------------------------------------------------------
# Eventi e voci
# ---------------------------------------------------------------------------

def _evento_bloccato(evento_id: int) -> ChiusuraEvento:
    """Rilegge l'evento con lock di riga: chi arriva dopo aspetta e vede lo stato vero."""
    return ChiusuraEvento.objects.select_for_update().get(pk=evento_id)


def _assert_aperta(evento: ChiusuraEvento) -> None:
    if evento.stato == ChiusuraEvento.STATO_CHIUSA:
        raise ChecklistStatoError(
            f"La chiusura «{evento.nome}» è archiviata: non è più modificabile."
        )


@transaction.atomic
def crea_evento_con_voci(evento: ChiusuraEvento, user=None) -> tuple[ChiusuraEvento, int]:
    """Salva l'evento e genera in blocco le voci dai template attivi.

    Le due scritture stanno o cadono insieme: un evento senza le sue mansioni
    sarebbe una checklist vuota che nessuno si accorge di dover ripopolare.
    """
    evento.creato_da = user
    evento.save()
    return evento, genera_voci_da_template(evento)


@transaction.atomic
def genera_voci_da_template(evento: ChiusuraEvento) -> int:
    """Crea una voce per ogni template attivo non ancora presente nell'evento.

    Idempotente per costruzione (salta i template già istanziati) e serializzata
    dal lock sull'evento: due richieste in parallelo non generano il doppio delle
    voci — la seconda trova il lavoro già fatto e ne crea zero.
    """
    evento_bloccato = _evento_bloccato(evento.pk)
    _assert_aperta(evento_bloccato)

    gia_presenti = set(
        ChiusuraVoce.objects.filter(evento=evento_bloccato, template__isnull=False)
        .values_list("template_id", flat=True)
    )
    nuove = [
        ChiusuraVoce(
            evento=evento_bloccato,
            template=template,
            ordine=template.ordine,
            descrizione=template.descrizione,
            responsabile=template.responsabile,
        )
        for template in ChecklistTaskTemplate.objects.filter(attivo=True).order_by("ordine", "id")
        if template.pk not in gia_presenti
    ]
    if nuove:
        ChiusuraVoce.objects.bulk_create(nuove)
    return len(nuove)


@transaction.atomic
def salva_voce(evento: ChiusuraEvento, voce: ChiusuraVoce) -> ChiusuraVoce:
    """Aggiunge o aggiorna una voce dell'evento, rifiutando gli eventi archiviati."""
    evento_bloccato = _evento_bloccato(evento.pk)
    _assert_aperta(evento_bloccato)
    voce.evento = evento_bloccato
    voce.save()
    return voce


@transaction.atomic
def conferma_voce(voce_id: int, dipendente, note: str = "") -> ChiusuraVoce:
    """Segna la voce come eseguita dal proprio responsabile."""
    voce = ChiusuraVoce.objects.select_for_update().get(pk=voce_id)
    _assert_aperta(ChiusuraEvento.objects.get(pk=voce.evento_id))
    voce.conferma(dipendente, note=note)
    return voce


@transaction.atomic
def annulla_conferma_voce(voce_id: int) -> ChiusuraVoce:
    """Riporta la voce «da fare». Il lock di riga la mette in fila con la conferma."""
    voce = ChiusuraVoce.objects.select_for_update().get(pk=voce_id)
    _assert_aperta(ChiusuraEvento.objects.get(pk=voce.evento_id))
    voce.annulla_conferma()
    return voce


@transaction.atomic
def chiudi_evento(evento_id: int) -> bool:
    """Archivia l'evento. Ritorna ``False`` se era già chiuso (nessuna scrittura)."""
    evento = _evento_bloccato(evento_id)
    if evento.stato == ChiusuraEvento.STATO_CHIUSA:
        return False
    evento.stato = ChiusuraEvento.STATO_CHIUSA
    evento.save(update_fields=["stato"])
    return True


# ---------------------------------------------------------------------------
# Proposte
# ---------------------------------------------------------------------------

@transaction.atomic
def decidi_proposta(
    proposta_id: int,
    *,
    approva: bool,
    note_admin: str = "",
    aggiungi_al_template: bool = False,
    user=None,
) -> ChiusuraProposta:
    """Approva o rifiuta una proposta, una volta sola.

    L'approvazione può toccare tre tabelle (proposta, template, voce): o passano
    tutte o non passa nessuna. Il ricontrollo dello stato **dentro** la
    transazione, dopo il lock, è ciò che rende la seconda richiesta un errore di
    stato pulito invece di un secondo template e di una seconda voce.
    """
    proposta = ChiusuraProposta.objects.select_for_update().get(pk=proposta_id)
    if proposta.stato != ChiusuraProposta.STATO_IN_ATTESA:
        raise ChecklistStatoError(
            f"La proposta #{proposta.pk} è già stata gestita "
            f"({proposta.get_stato_display().lower()}): nessuna modifica applicata."
        )

    proposta.note_admin = note_admin
    proposta.gestito_da = user
    proposta.gestito_il = timezone.now()

    if not approva:
        proposta.stato = ChiusuraProposta.STATO_RIFIUTATA
        proposta.save()
        return proposta

    evento = None
    if proposta.evento_id:
        evento = _evento_bloccato(proposta.evento_id)
        if evento.stato == ChiusuraEvento.STATO_CHIUSA:
            raise ChecklistStatoError(
                f"La chiusura «{evento.nome}» è archiviata: la proposta non può più "
                "generare una voce. Rifiutala, oppure aggiungi la mansione al template "
                "dalla configurazione."
            )

    proposta.stato = ChiusuraProposta.STATO_APPROVATA
    proposta.aggiungi_al_template = aggiungi_al_template

    if aggiungi_al_template:
        proposta.template_generato = ChecklistTaskTemplate.objects.create(
            descrizione=proposta.descrizione,
            responsabile=proposta.responsabile_suggerito,
            creato_da=user,
            note=f"Da proposta #{proposta.pk} di {proposta.proposto_da}",
        )

    if evento is not None:
        proposta.voce_generata = ChiusuraVoce.objects.create(
            evento=evento,
            template=proposta.template_generato,
            descrizione=proposta.descrizione,
            responsabile=proposta.responsabile_suggerito,
        )

    proposta.save()
    return proposta
