"""Operazioni che cambiano il registro: salvare, consolidare, annullare.

Le viste non scrivono mai ``RegistroRifiuti`` direttamente: passano da qui,
così validazione, blocco dei genitori, audit e invio a SharePoint sono gli
stessi per il wizard, la modifica e i pulsanti di pagina.

Regole del registro:

- un movimento **consolidato** (``salva``) non si modifica più: si corregge con
  una rettifica (R) o annullandolo;
- un movimento non si **elimina**: si annulla con un motivo, resta a registro
  barrato e non conta più nelle giacenze;
- un movimento con scarichi collegati ancora validi non si annulla finché non
  si annullano prima quelli.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from core.audit import log_action

from .catena import split_rif_op
from .models import RegistroRifiuti
from .validazione import requisiti_consolidamento, valida_movimento

logger = logging.getLogger(__name__)

__all__ = [
    "ErroreRegistro",
    "CAMPI_DATI",
    "fotografia",
    "salva_movimento",
    "consolida",
    "annulla",
    "segna_trasmesso",
    "figli_attivi",
    "consolida_in_blocco",
]

# Campi che descrivono il movimento (quelli confrontati prima/dopo una modifica).
CAMPI_DATI = (
    "data", "codice", "quantita", "unita", "rettifica_scarico", "rif_op",
    "pericolosita", "arrivo_fir", "note_rentri", "rentri_si_no", "carico_scarico",
)


class ErroreRegistro(Exception):
    """Operazione rifiutata: ``errori`` sono i messaggi da mostrare all'utente."""

    def __init__(self, errori, *, stato_http: int = 400):
        self.errori = [errori] if isinstance(errori, str) else list(errori)
        self.stato_http = stato_http
        super().__init__("; ".join(self.errori))


def fotografia(registro: RegistroRifiuti) -> dict:
    return {campo: getattr(registro, campo) for campo in CAMPI_DATI}


def _modifiche(prima: dict | None, registro: RegistroRifiuti) -> dict:
    if prima is None:
        return {}
    out = {}
    for campo in CAMPI_DATI:
        old, new = prima.get(campo), getattr(registro, campo)
        if old != new:
            out[campo] = {"old": str(old) if old is not None else None, "new": str(new) if new is not None else None}
    return out


def _blocca_contesto(registro: RegistroRifiuti) -> None:
    """Blocca genitori e movimenti dello stesso codice fino alla fine della transazione.

    Due scarichi dello stesso carico salvati insieme si mettono in fila: il
    secondo rilegge giacenza e collegamenti dopo il primo.
    """
    refs = split_rif_op(registro.rif_op)
    if refs:
        list(RegistroRifiuti.objects.select_for_update().filter(id_registrazione__in=refs).values_list("pk", flat=True))
    if registro.tipo in ("O", "M") and registro.codice:
        list(
            RegistroRifiuti.objects.select_for_update()
            .filter(tipo="C", codice=registro.codice)
            .values_list("pk", flat=True)
        )


def salva_movimento(request, registro: RegistroRifiuti, *, prima: dict | None) -> RegistroRifiuti:
    """Valida e salva un movimento nuovo (``prima=None``) o modificato.

    Solleva :class:`ErroreRegistro` se il movimento non è valido o è bloccato.
    L'invio a SharePoint avviene dopo il salvataggio e non lo annulla mai.
    """
    from .sharepoint import sincronizza

    nuovo = prima is None
    if not nuovo and registro.bloccato:
        raise ErroreRegistro(
            "Registrazione consolidata o annullata: non si modifica. "
            "Per correggerla registra una rettifica (R) o annullala.",
            stato_http=409,
        )
    if not registro.carico_scarico:
        registro.carico_scarico = registro.tipo

    with transaction.atomic():
        _blocca_contesto(registro)
        errori = valida_movimento(registro, prima=prima)
        if errori:
            raise ErroreRegistro(errori)
        registro.save()

    modifiche = _modifiche(prima, registro)
    if nuovo or modifiche:
        log_action(
            request,
            "rentri_movimento_creato" if nuovo else "rentri_movimento_modificato",
            "rentri",
            {
                "id_registrazione": registro.id_registrazione,
                "tipo": registro.tipo,
                "codice": registro.codice,
                **({"modifiche": modifiche} if modifiche else {}),
            },
            oggetto=registro,
        )
    sincronizza(registro)
    return registro


def consolida(request, registro: RegistroRifiuti, utente: str) -> None:
    """Consolida un movimento: da qui in poi i suoi dati non si modificano più."""
    from .sharepoint import sincronizza

    if registro.annullato:
        raise ErroreRegistro("Registrazione annullata: non si consolida.")
    if registro.salva:
        raise ErroreRegistro("Registrazione già consolidata.")
    mancanti = requisiti_consolidamento(registro)
    if mancanti:
        raise ErroreRegistro(f"Non si può consolidare: {', '.join(mancanti)}. Completala prima con «Modifica».")
    registro.salva = True
    registro.consolidato_il = timezone.now()
    registro.consolidato_da = utente[:200]
    registro.save(update_fields=["salva", "consolidato_il", "consolidato_da", "updated_at"])
    log_action(request, "rentri_movimento_consolidato", "rentri",
               {"id_registrazione": registro.id_registrazione, "tipo": registro.tipo}, oggetto=registro)
    sincronizza(registro)


def segna_trasmesso(request, registro: RegistroRifiuti, trasmesso: bool) -> None:
    """Segna (o toglie) la trasmissione a RENTRI: l'unico campo ammesso dopo il consolidamento."""
    from .sharepoint import sincronizza

    if registro.annullato:
        raise ErroreRegistro("Registrazione annullata.")
    if registro.rentri_si_no == trasmesso:
        return
    registro.rentri_si_no = trasmesso
    registro.save(update_fields=["rentri_si_no", "updated_at"])
    log_action(request, "rentri_movimento_trasmesso" if trasmesso else "rentri_movimento_non_trasmesso", "rentri",
               {"id_registrazione": registro.id_registrazione}, oggetto=registro)
    sincronizza(registro)


def figli_attivi(registro: RegistroRifiuti) -> list[RegistroRifiuti]:
    """Movimenti validi che citano questo nel proprio ``rif_op``."""
    rid = (registro.id_registrazione or "").strip()
    if not rid:
        return []
    qs = (
        RegistroRifiuti.objects.attivi()
        .exclude(pk=registro.pk)
        .filter(rif_op__contains=rid)
        .order_by("data", "id")
    )
    return [r for r in qs if rid in split_rif_op(r.rif_op)]


def annulla(request, registro: RegistroRifiuti, motivo: str, utente: str) -> None:
    """Annulla un movimento: resta a registro, barrato, e non conta più."""
    from .sharepoint import sincronizza

    motivo = (motivo or "").strip()
    if registro.annullato:
        raise ErroreRegistro("Registrazione già annullata.")
    if len(motivo) < 5:
        raise ErroreRegistro("Scrivi il motivo dell'annullamento (almeno 5 caratteri).")
    with transaction.atomic():
        registro = RegistroRifiuti.objects.select_for_update().get(pk=registro.pk)
        figli = figli_attivi(registro)
        if figli:
            elenco = ", ".join(f"{f.tipo} {f.id_registrazione}" for f in figli[:5])
            raise ErroreRegistro(f"Prima annulla i movimenti collegati: {elenco}.", stato_http=409)
        registro.annullato = True
        registro.annullato_il = timezone.now()
        registro.annullato_da = utente[:200]
        registro.motivo_annullamento = motivo
        registro.save(update_fields=["annullato", "annullato_il", "annullato_da", "motivo_annullamento", "updated_at"])
    log_action(request, "rentri_movimento_annullato", "rentri",
               {"id_registrazione": registro.id_registrazione, "tipo": registro.tipo, "motivo": motivo},
               oggetto=registro)
    sincronizza(registro)


def consolida_in_blocco(request, fino_al, utente: str, *, applica: bool = True) -> dict:
    """Consolida tutte le bozze complete con data fino a `fino_al` compreso.

    Le incomplete restano bozze e sono contate per motivo. Una sola voce di audit
    riassuntiva (più l'audit automatico dei campi su ogni riga). Niente invio a
    SharePoint riga per riga: se Graph è configurato le righe restano segnate in
    ``sync_errore`` e ``rentri_sync_riprova`` le reinvia.
    """
    from collections import Counter

    from .sharepoint import _graph_configured

    bozze = list(
        RegistroRifiuti.objects.attivi().filter(salva=False, data__lte=fino_al).order_by("data", "id")
    )
    incomplete: Counter = Counter()
    pronte = []
    for r in bozze:
        mancanti = requisiti_consolidamento(r)
        if mancanti:
            incomplete.update(mancanti)
        else:
            pronte.append(r)
    esito = {
        "consolidabili": len(pronte),
        "incomplete": len(bozze) - len(pronte),
        "mancanze": dict(incomplete),
        "fino_al": fino_al.isoformat(),
    }
    if not applica or not pronte:
        return esito
    adesso = timezone.now()
    nota_sync = "Da reinviare dopo il consolidamento in blocco" if _graph_configured() else ""
    with transaction.atomic():
        for r in pronte:
            r.salva = True
            r.consolidato_il = adesso
            r.consolidato_da = utente[:200]
            campi = ["salva", "consolidato_il", "consolidato_da", "updated_at"]
            if nota_sync:
                r.sync_errore = nota_sync
                campi.append("sync_errore")
            r.save(update_fields=campi)
    log_action(request, "rentri_consolidamento_in_blocco", "rentri", esito)
    return esito
