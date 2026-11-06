"""Reportistica DPI: una sola definizione di conformita' e di stato della ricevuta.

Per ogni persona contano le categorie **dovute**: quelle segnate come obbligatorie per tutti piu'
quelle richieste dalla sua mansione di rischio (la stessa fonte de «La mia dotazione»). Per
categoria vale l'ultima consegna non sostituita; la scadenza e' ``data_scadenza_stimata``.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Q, Sum
from django.utils import timezone

from .dotazione import GIORNI_AVVISO
from .models import CategoriaDPI, ConfermaConsegnaDPI, ConsegnaDPI, RichiestaDPI, StatoRichiesta

logger = logging.getLogger(__name__)

OK = "ok"
IN_SCADENZA = "in_scadenza"
SCADUTO = "scaduto"
MANCANTE = "mancante"
NON_PREVISTO = "non_previsto"
DA_SISTEMARE = "da_sistemare"

ETICHETTE = {
    OK: "In regola",
    IN_SCADENZA: "In scadenza",
    SCADUTO: "Scaduto",
    MANCANTE: "Mancante",
    NON_PREVISTO: "Nessun DPI dovuto",
}
FILTRI_ESITO = (
    (DA_SISTEMARE, "Da sistemare"),
    (MANCANTE, "Con DPI mancanti"),
    (SCADUTO, "Con DPI scaduti"),
    (IN_SCADENZA, "In scadenza"),
    (OK, "In regola"),
    (NON_PREVISTO, "Nessun DPI dovuto"),
)
_GRAVITA = {MANCANTE: 0, SCADUTO: 1, IN_SCADENZA: 2, OK: 3}

FIRMATA = "firmata"
CON_BADGE = "con_badge"
CONFERMATA = "confermata"
DA_CONFERMARE = "da_confermare"
CONTESTATA = "contestata"
SENZA_FIRMA = "senza_firma"
FILTRI_RICEVUTA = (
    (FIRMATA, "Firmata"),
    (CON_BADGE, "Confermata con badge"),
    (CONFERMATA, "Confermata via mail"),
    (DA_CONFERMARE, "Da confermare"),
    (CONTESTATA, "Contestata"),
    (SENZA_FIRMA, "Senza firma"),
)


def _dovute_per_mansione(legacy_ids: list[int]) -> tuple[dict[int, list], bool]:
    """Categorie dalla mansione di rischio. Il secondo valore segnala che il calcolo e' fallito."""
    if not legacy_ids:
        return {}, False
    try:
        from anagrafica.services import mansionario

        dettagli = mansionario.requisiti_dipendenti_dettaglio(legacy_ids)
        return {i: list(d["requisiti"]["dpi"]) for i, d in dettagli.items()}, False
    except Exception:  # noqa: BLE001
        logger.exception("Requisiti DPI della mansione non calcolati per il report")
        return {}, True


def _ultime_consegne() -> dict[tuple[int, int], ConsegnaDPI]:
    consegne_valide = (
        ConsegnaDPI.objects.filter(
            richiesta__stato=StatoRichiesta.CONSEGNATA,
            richiesta__richiedente_legacy_id__isnull=False,
            sostituita_da__isnull=True,
        )
        .select_related("richiesta")
        .order_by("-data_consegna", "-created_at")
    )
    ultime: dict[tuple[int, int], ConsegnaDPI] = {}
    for c in consegne_valide:
        ultime.setdefault((c.richiesta.richiedente_legacy_id, c.richiesta.categoria_id), c)
    return ultime


def _richieste_aperte() -> dict[tuple[int, int], str]:
    aperte: dict[tuple[int, int], str] = {}
    righe = RichiestaDPI.objects.filter(
        stato__in=[StatoRichiesta.INVIATA, StatoRichiesta.APPROVATA], richiedente_legacy_id__isnull=False
    ).order_by("created_at").values_list("richiedente_legacy_id", "categoria_id", "numero")
    for legacy_id, categoria_id, numero in righe:
        aperte.setdefault((legacy_id, categoria_id), numero)
    return aperte


def stato_consegna(consegna: ConsegnaDPI | None, oggi) -> str:
    if consegna is None:
        return MANCANTE
    scadenza = consegna.data_scadenza_stimata
    if scadenza and scadenza < oggi:
        return SCADUTO
    if scadenza and scadenza <= oggi + timedelta(days=GIORNI_AVVISO):
        return IN_SCADENZA
    return OK


def conformita(dipendenti: list[dict], *, categoria_id: int | None = None, tutte_le_categorie: bool = False, oggi=None) -> dict:
    """Situazione delle persone indicate. ``dipendenti``: righe con ``id``, nominativo, reparto, mansione.

    Con ``tutte_le_categorie`` compaiono anche le categorie non dovute: se non consegnate valgono
    «non previsto» e non pesano sull'esito.
    """
    oggi = oggi or timezone.localdate()
    categorie = list(CategoriaDPI.objects.filter(is_active=True).order_by("order_index", "nome"))
    if categoria_id:
        categorie = [c for c in categorie if c.pk == categoria_id]
    obbligatorie = {c.pk for c in categorie if c.obbligatoria_mansionario}

    ids = [int(d["id"]) for d in dipendenti]
    da_mansione, errore = _dovute_per_mansione(ids)
    ultime = _ultime_consegne()
    aperte = _richieste_aperte()

    persone = []
    conteggi = dict.fromkeys((OK, IN_SCADENZA, SCADUTO, MANCANTE, NON_PREVISTO, DA_SISTEMARE), 0)
    for d in dipendenti:
        pid = int(d["id"])
        dovute = obbligatorie | {c.pk for c in da_mansione.get(pid, [])}
        righe = []
        for c in categorie:
            dovuta = c.pk in dovute
            if not dovuta and not tutte_le_categorie:
                continue
            consegna = ultime.get((pid, c.pk))
            stato = stato_consegna(consegna, oggi)
            if not dovuta and consegna is None:
                stato = NON_PREVISTO
            righe.append({
                "categoria": c, "consegna": consegna, "stato": stato, "etichetta": ETICHETTE[stato], "dovuta": dovuta,
                "origine": "Per tutti" if c.pk in obbligatorie else ("Dalla mansione" if dovuta else "Non dovuta"),
                "richiesta_in_corso": aperte.get((pid, c.pk), ""),
            })
        stati = [r["stato"] for r in righe if r["dovuta"]]
        esito = min(stati, key=_GRAVITA.__getitem__) if stati else NON_PREVISTO
        # Una persona conta in ogni stato che ha: con un DPI scaduto e uno mancante sta in entrambi.
        presenti = set(stati) if stati else {NON_PREVISTO}
        if esito != OK:
            presenti.discard(OK)
        for stato in presenti:
            conteggi[stato] += 1
        conteggi[DA_SISTEMARE] += bool(presenti & {MANCANTE, SCADUTO})
        persone.append({
            **d, "id": pid, "esito": esito, "esito_etichetta": ETICHETTE[esito], "righe": righe, "stati": presenti,
            "da_sistemare": [r for r in righe if r["dovuta"] and r["stato"] in (MANCANTE, SCADUTO, IN_SCADENZA)],
            "conforme": esito in (OK, IN_SCADENZA),
        })
    # sort stabile: a parita' di esito resta l'ordine alfabetico ricevuto.
    persone.sort(key=lambda p: _GRAVITA.get(p["esito"], 9))
    conteggi["totale"] = len(persone)
    return {"persone": persone, "conteggi": conteggi, "errore_requisiti": errore}


def filtra_esito(persone: list[dict], esito: str) -> list[dict]:
    if esito == DA_SISTEMARE:
        return [p for p in persone if p["stati"] & {MANCANTE, SCADUTO}]
    return [p for p in persone if esito in p["stati"]] if esito else persone


def testo_da_sistemare(persona: dict) -> str:
    """Una riga leggibile, uguale a video e negli export."""
    parti = []
    for r in persona["da_sistemare"]:
        testo = f'{r["categoria"].nome}: {r["etichetta"].lower()}'
        if r["consegna"] and r["consegna"].data_scadenza_stimata:
            testo += f' il {r["consegna"].data_scadenza_stimata:%d-%m-%Y}'
        if r["richiesta_in_corso"]:
            testo += f' (richiesta {r["richiesta_in_corso"]} in corso)'
        parti.append(testo)
    return "; ".join(parti)


# ---------------------------------------------------------------------------
# Registro delle consegne
# ---------------------------------------------------------------------------

def _q_ricevuta(chiave: str) -> Q:
    non_firmata = Q(firmato_ricevuta=False)
    return {
        FIRMATA: Q(firmato_ricevuta=True, confermata_badge_il__isnull=True),
        CON_BADGE: Q(confermata_badge_il__isnull=False),
        CONFERMATA: non_firmata & Q(conferma__stato=ConfermaConsegnaDPI.Stato.CONFERMATA),
        DA_CONFERMARE: non_firmata & Q(conferma__stato=ConfermaConsegnaDPI.Stato.IN_ATTESA),
        CONTESTATA: non_firmata & Q(conferma__stato=ConfermaConsegnaDPI.Stato.CONTESTATA),
        SENZA_FIRMA: non_firmata & Q(conferma__isnull=True),
    }[chiave]


def ricevuta(consegna: ConsegnaDPI) -> str:
    if consegna.confermata_badge_il:
        return CON_BADGE
    if consegna.firmato_ricevuta:
        return FIRMATA
    if consegna.conferma_id is None:
        return SENZA_FIRMA
    return {
        ConfermaConsegnaDPI.Stato.CONFERMATA: CONFERMATA,
        ConfermaConsegnaDPI.Stato.CONTESTATA: CONTESTATA,
    }.get(consegna.conferma.stato, DA_CONFERMARE)


def consegne(*, da, a, scope=None, reparto: str = "", categoria_id: int | None = None, q: str = "", esito_ricevuta: str = "", filtro_centro=None):
    """Consegne del periodo nel perimetro di chi guarda. ``scope`` None = tutti.

    Ritorna (queryset, totali delle righe selezionate, conteggi per stato della ricevuta). I conteggi
    non dipendono dal filtro sulla ricevuta: restano fermi mentre si clicca da uno stato all'altro.
    """
    qs = ConsegnaDPI.objects.filter(
        richiesta__stato=StatoRichiesta.CONSEGNATA, data_consegna__gte=da, data_consegna__lte=a
    )
    if scope is not None:
        qs = qs.filter(richiesta__richiedente_legacy_id__in=list(scope))
    if filtro_centro is not None:
        qs = filtro_centro.applica(qs, "richiesta__richiedente_legacy_id")
    if reparto:
        qs = qs.filter(richiesta__richiedente_reparto=reparto)
    if categoria_id:
        qs = qs.filter(richiesta__categoria_id=categoria_id)
    if q:
        qs = qs.filter(
            Q(richiesta__richiedente_nome__icontains=q) | Q(richiesta__numero__icontains=q)
            | Q(richiesta__modello_dpi__nome__icontains=q) | Q(richiesta__modello_dpi__codice__icontains=q)
        )
    conteggi = {chiave: qs.filter(_q_ricevuta(chiave)).count() for chiave, _ in FILTRI_RICEVUTA}
    if esito_ricevuta in conteggi:
        qs = qs.filter(_q_ricevuta(esito_ricevuta))
    totali = {
        "consegne": qs.count(),
        "pezzi": int(qs.aggregate(t=Sum("richiesta__quantita"))["t"] or 0),
        "persone": qs.values("richiesta__richiedente_nome").distinct().count(),
    }
    qs = qs.select_related(
        "richiesta", "richiesta__categoria", "richiesta__tipo_dpi", "richiesta__modello_dpi", "richiesta__taglia_dpi", "conferma"
    ).order_by("-data_consegna", "-created_at")
    return qs, totali, conteggi


def descrizione_dpi(richiesta: RichiestaDPI) -> str:
    nome = (richiesta.modello_dpi and richiesta.modello_dpi.nome) or (richiesta.tipo_dpi and richiesta.tipo_dpi.nome)
    taglia = richiesta.taglia_dpi and f"taglia {richiesta.taglia_dpi.valore}"
    return " · ".join(p for p in (nome, taglia) if p)
