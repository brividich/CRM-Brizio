"""Operazioni che cambiano il registro: salvare, consolidare, annullare.

Le viste non scrivono mai ``RegistroRifiuti`` direttamente: passano da qui,
così validazione, blocco dei genitori, audit e invio a SharePoint sono gli
stessi per il wizard, la modifica e i pulsanti di pagina.

Regole del registro:

- un movimento **consolidato** (``salva``) non si modifica più: si corregge con
  una rettifica (R) o annullandolo;
- un movimento di norma non si **elimina**: si annulla con un motivo, resta a
  registro barrato e non conta più nelle giacenze. Solo una **bozza** mai
  consolidata né trasmessa e senza movimenti collegati si può eliminare
  definitivamente (con motivo: l'audit ne tiene la fotografia, il numero non
  viene riusato);
- un movimento con scarichi collegati si può annullare: gli scarichi restano
  con il loro Rif. Op come traccia ma non risultano più collegati (la verifica
  li elenca); si ricollegano con «Modifica» o restano così;
- un collegamento tolto dal Rif. Op finisce in ``rif_op_storico``.
"""
from __future__ import annotations

import logging
from datetime import date

from django.db import transaction
from django.utils import timezone

from core.audit import log_action

from .catena import indice_per_id, risali_a_carichi, split_rif_op
from .models import RegistroRifiuti
from .validazione import requisiti_consolidamento, valida_movimento, valore_movimento

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
    "annota_collegamenti_tolti",
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


def annota_collegamenti_tolti(registro: RegistroRifiuti, prima: dict | None, utente: str = "") -> list[str]:
    """Riporta in ``rif_op_storico`` i riferimenti tolti dal Rif. Op in questa modifica."""
    if prima is None:
        return []
    nuovi = set(split_rif_op(registro.rif_op))
    tolti = [rid for rid in split_rif_op(prima.get("rif_op")) if rid not in nuovi]
    if tolti:
        oggi = timezone.localdate().strftime("%d/%m/%Y")
        chi = f" ({utente})" if utente else ""
        riga = f"{oggi} · {', '.join(tolti)} · collegamento tolto in modifica{chi}"
        registro.rif_op_storico = "\n".join(x for x in (registro.rif_op_storico, riga) if x)
    return tolti


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
        utente = getattr(getattr(request, "user", None), "username", "") or ""
        annota_collegamenti_tolti(registro, prima, utente)
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


def annulla(request, registro: RegistroRifiuti, motivo: str, utente: str) -> list[RegistroRifiuti]:
    """Annulla un movimento: resta a registro, barrato, e non conta più.

    Ritorna gli scarichi che erano collegati: tengono il riferimento come traccia
    ma non risultano più collegati (il conto del filo ignora gli annullati).
    """
    from .sharepoint import sincronizza

    motivo = (motivo or "").strip()
    if registro.annullato:
        raise ErroreRegistro("Registrazione già annullata.")
    if len(motivo) < 5:
        raise ErroreRegistro("Scrivi il motivo dell'annullamento (almeno 5 caratteri).")
    with transaction.atomic():
        registro = RegistroRifiuti.objects.select_for_update().get(pk=registro.pk)
        figli = figli_attivi(registro)
        registro.annullato = True
        registro.annullato_il = timezone.now()
        registro.annullato_da = utente[:200]
        registro.motivo_annullamento = motivo
        registro.save(update_fields=["annullato", "annullato_il", "annullato_da", "motivo_annullamento", "updated_at"])
    log_action(request, "rentri_movimento_annullato", "rentri",
               {"id_registrazione": registro.id_registrazione, "tipo": registro.tipo, "motivo": motivo,
                **({"scollegati": [f.id_registrazione for f in figli]} if figli else {})},
               oggetto=registro)
    sincronizza(registro)
    return figli


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


# ── Filo (blocco): il carico con i suoi O/M/R ─────────────────────────────────


def movimenti_del_filo(registro: RegistroRifiuti, records: list | None = None) -> list[RegistroRifiuti]:
    """Movimenti validi dello stesso filo del movimento (stesso raggruppamento dell'elenco).

    Un filo è l'insieme dei carichi uniti da scarichi a riferimento multiplo più
    tutti gli O/M/R che risalgono a quei carichi. Uno scarico che non porta a
    nessun carico fa filo con gli altri dello stesso Rif. Op (come nell'elenco).
    """
    if registro.annullato:
        return []
    if records is None:
        records = list(RegistroRifiuti.objects.attivi().order_by("data", "id"))
    by_id = indice_per_id(records)
    carichi_per_id: dict[str, RegistroRifiuti] = {}
    for r in records:
        if r.tipo == "C":
            carichi_per_id.setdefault(str(r.id_registrazione or "").strip(), r)
    ops = [
        (op, [c for c in risali_a_carichi(op.rif_op or "", by_id) if c in carichi_per_id])
        for op in records
        if op.tipo != "C"
    ]

    if registro.tipo == "C":
        seme = {str(registro.id_registrazione or "").strip()}
    else:
        seme = set(next((cids for op, cids in ops if op.pk == registro.pk), []))
    if not seme:
        chiave_rif = str(registro.rif_op or "").strip()
        orfani = [op for op, cids in ops if not cids and str(op.rif_op or "").strip() == chiave_rif]
        return orfani or [registro]

    cresciuto = True
    while cresciuto:
        cresciuto = False
        for _op, cids in ops:
            if cids and seme.intersection(cids) and not seme.issuperset(cids):
                seme.update(cids)
                cresciuto = True
    membri = [carichi_per_id[c] for c in seme if c in carichi_per_id]
    membri += [op for op, cids in ops if seme.intersection(cids)]
    return sorted(membri, key=lambda r: (r.data or date.min, r.pk))


def anteprima_filo(registro: RegistroRifiuti) -> dict:
    """Cosa farebbe «Consolida filo»: righe pronte, già consolidate, incomplete (con cosa manca)."""
    membri = movimenti_del_filo(registro)
    pronte, gia, incomplete = [], [], []
    for r in membri:
        if r.salva:
            gia.append(r)
            continue
        mancanti = requisiti_consolidamento(r)
        if mancanti:
            r.mancanti = mancanti
            incomplete.append(r)
        else:
            pronte.append(r)
    return {"membri": membri, "pronte": pronte, "gia": gia, "incomplete": incomplete}


def consolida_filo(request, registro: RegistroRifiuti, utente: str) -> dict:
    """Consolida tutte le righe complete del filo in una transazione; le incomplete restano bozze."""
    from .sharepoint import sincronizza

    if registro.annullato:
        raise ErroreRegistro("Registrazione annullata: il suo filo non si consolida da qui.")
    esito = anteprima_filo(registro)
    if not esito["pronte"]:
        if esito["incomplete"]:
            raise ErroreRegistro("Nessuna riga del filo è pronta: completa prima quelle senza data, codice o quantità.")
        raise ErroreRegistro("Il filo è già tutto consolidato.")
    adesso = timezone.now()
    fatte = []
    with transaction.atomic():
        pks = [r.pk for r in esito["pronte"]]
        libere = set(
            RegistroRifiuti.objects.select_for_update()
            .filter(pk__in=pks, salva=False, annullato=False)
            .values_list("pk", flat=True)
        )
        for r in esito["pronte"]:
            if r.pk not in libere:
                continue  # consolidata o annullata nel frattempo da un'altra sessione
            r.salva = True
            r.consolidato_il = adesso
            r.consolidato_da = utente[:200]
            r.save(update_fields=["salva", "consolidato_il", "consolidato_da", "updated_at"])
            fatte.append(r)
    for r in fatte:
        log_action(request, "rentri_movimento_consolidato", "rentri",
                   {"id_registrazione": r.id_registrazione, "tipo": r.tipo, "filo": True}, oggetto=r)
        sincronizza(r)
    esito["fatte"] = fatte
    return esito


# ── Eliminazione definitiva (solo bozze isolate) ──────────────────────────────


def motivo_non_eliminabile(registro: RegistroRifiuti, figli: list | None = None) -> str:
    """Perché il movimento non si può eliminare definitivamente ("" = si può)."""
    if registro.annullato:
        return "è già annullata"
    if registro.salva:
        return "è consolidata: si può solo annullare"
    if registro.rentri_si_no:
        return "risulta trasmessa a RENTRI: si può solo annullare"
    figli = figli_attivi(registro) if figli is None else figli
    if figli:
        elenco = ", ".join(f"{f.tipo} {f.id_registrazione}" for f in figli[:4])
        return f"ha movimenti collegati ({elenco}): si può solo annullare"
    return ""


def elimina_definitivamente(request, registro: RegistroRifiuti, motivo: str, utente: str) -> dict:
    """Cancella una bozza isolata. L'audit ne tiene la fotografia; il numero non torna disponibile.

    Se la copia su SharePoint esiste e non si riesce a toglierla, non si elimina
    niente: la lettura da SharePoint la riporterebbe nel registro.
    """
    from .sharepoint import _graph_configured, _graph_delete

    motivo = (motivo or "").strip()
    if len(motivo) < 5:
        raise ErroreRegistro("Scrivi il motivo dell'eliminazione (almeno 5 caratteri).")
    with transaction.atomic():
        registro = RegistroRifiuti.objects.select_for_update().get(pk=registro.pk)
        perche = motivo_non_eliminabile(registro)
        if perche:
            raise ErroreRegistro(f"Non si può eliminare definitivamente: {perche}.")
        if registro.sharepoint_item_id and _graph_configured():
            try:
                ok, errore = _graph_delete(registro.sharepoint_item_id)
            except Exception as exc:  # noqa: BLE001 - rete, token
                ok, errore = False, type(exc).__name__
            if not ok:
                raise ErroreRegistro(
                    f"Copia su SharePoint non eliminata ({str(errore)[:120]}): "
                    "riprova più tardi o annulla la registrazione."
                )
        valore = valore_movimento(registro)
        foto = {
            "id_registrazione": registro.id_registrazione,
            "tipo": registro.tipo,
            "data": registro.data.isoformat() if registro.data else "",
            "codice": registro.codice,
            "quantita": str(valore) if valore is not None else "",
            "unita": registro.unita,
            "rif_op": registro.rif_op,
            "arrivo_fir": registro.arrivo_fir,
            "motivo": motivo,
            "eliminato_da": utente[:200],
        }
        allegato = registro.allegato.name if registro.allegato else ""
        registro.delete()
    if allegato:
        try:
            RegistroRifiuti._meta.get_field("allegato").storage.delete(allegato)
        except Exception:  # noqa: BLE001 - un file orfano non blocca
            logger.warning("RENTRI: allegato %s non rimosso dopo l'eliminazione", allegato, exc_info=True)
    log_action(request, "rentri_movimento_eliminato", "rentri", foto)
    return foto
