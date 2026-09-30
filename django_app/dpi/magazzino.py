"""Magazzino DPI: giacenza per modello come somma dei movimenti registrati."""
from __future__ import annotations

from datetime import date

from django.db import transaction
from django.db.models import Sum

from .models import ModelloDPI, MovimentoMagazzinoDPI, RichiestaDPI

Tipo = MovimentoMagazzinoDPI.Tipo

STATO_ESAURITO = "esaurito"
STATO_SOTTO_SCORTA = "sotto"
STATO_OK = "ok"


def giacenza(modello_id: int) -> int:
    return int(MovimentoMagazzinoDPI.objects.filter(modello_id=modello_id).aggregate(t=Sum("quantita"))["t"] or 0)


def giacenze() -> dict[int, int]:
    rows = MovimentoMagazzinoDPI.objects.values("modello_id").annotate(t=Sum("quantita"))
    return {r["modello_id"]: int(r["t"] or 0) for r in rows}


def stato_scorta(qta: int, minima: int) -> str:
    if qta <= 0:
        return STATO_ESAURITO
    if minima and qta <= minima:
        return STATO_SOTTO_SCORTA
    return STATO_OK


def carica_ddt(modello: ModelloDPI, quantita: int, *, ddt_numero: str = "", data: date | None = None,
               fornitore: str = "", note: str = "", user=None) -> MovimentoMagazzinoDPI:
    if quantita <= 0:
        raise ValueError("La quantita' del carico deve essere positiva.")
    return MovimentoMagazzinoDPI.objects.create(
        modello=modello, tipo=Tipo.CARICO, quantita=quantita, data=data or date.today(),
        ddt_numero=ddt_numero[:60], fornitore=fornitore[:150], note=note[:300],
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


@transaction.atomic
def imposta_giacenza(modello: ModelloDPI, nuova: int, *, note: str = "", user=None) -> MovimentoMagazzinoDPI | None:
    """Rettifica d'inventario: porta la giacenza a ``nuova`` registrando la differenza."""
    if nuova < 0:
        raise ValueError("La giacenza non puo' essere negativa.")
    delta = nuova - giacenza(modello.pk)
    if delta == 0:
        return None
    return MovimentoMagazzinoDPI.objects.create(
        modello=modello, tipo=Tipo.RETTIFICA, quantita=delta, note=(note or "Inventario")[:300],
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def scarica_per_consegna(richiesta: RichiestaDPI, data: date, *, user=None) -> tuple[MovimentoMagazzinoDPI | None, int | None]:
    """Scarica dal magazzino la quantita' consegnata. Idempotente per richiesta.

    Ritorna (movimento, giacenza_residua); (None, None) se la richiesta non ha un
    modello DPI (nulla da scaricare). La consegna non viene mai bloccata da una
    giacenza insufficiente: il chiamante segnala il residuo negativo."""
    if not richiesta.modello_dpi_id:
        return None, None
    movimento, created = MovimentoMagazzinoDPI.objects.get_or_create(
        richiesta=richiesta, tipo=Tipo.SCARICO,
        defaults={
            "modello_id": richiesta.modello_dpi_id, "quantita": -int(richiesta.quantita or 1), "data": data,
            "note": f"Consegna {richiesta.numero} - {richiesta.richiedente_nome}"[:300],
            "created_by": user if getattr(user, "is_authenticated", False) else None,
        },
    )
    return movimento, giacenza(richiesta.modello_dpi_id)


# ---------------------------------------------------------------------------
# Reportistica
# ---------------------------------------------------------------------------

def _mesi_indietro(n: int, oggi: date) -> list[date]:
    """Primi giorni degli ultimi ``n`` mesi (incluso il corrente), dal piu' vecchio."""
    y, m = oggi.year, oggi.month
    out = []
    for _ in range(n):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def report(giorni: int, oggi: date | None = None) -> dict:
    """Aggregati per la pagina di report: consumi, carichi, copertura, riordino."""
    from datetime import timedelta

    from django.db.models.functions import TruncMonth

    oggi = oggi or date.today()
    da = oggi - timedelta(days=giorni)
    scarichi = MovimentoMagazzinoDPI.objects.filter(tipo=Tipo.SCARICO, data__gte=da)
    carichi = MovimentoMagazzinoDPI.objects.filter(tipo=Tipo.CARICO, data__gte=da)

    consumati = -int(scarichi.aggregate(t=Sum("quantita"))["t"] or 0)
    caricati = int(carichi.aggregate(t=Sum("quantita"))["t"] or 0)

    per_modello = {
        r["modello_id"]: -int(r["t"] or 0)
        for r in scarichi.values("modello_id").annotate(t=Sum("quantita"))
    }

    # Andamento mensile degli ultimi 12 mesi (indipendente dal periodo scelto).
    mesi = _mesi_indietro(12, oggi)
    mensili = {
        r["m"].date() if hasattr(r["m"], "date") else r["m"]: -int(r["t"] or 0)
        for r in MovimentoMagazzinoDPI.objects.filter(tipo=Tipo.SCARICO, data__gte=mesi[0])
        .annotate(m=TruncMonth("data")).values("m").annotate(t=Sum("quantita"))
    }
    serie = [{"mese": m, "pezzi": mensili.get(m, 0)} for m in mesi]

    per_reparto: dict[str, int] = {}
    for r in scarichi.values("richiesta__richiedente_reparto").annotate(t=Sum("quantita")):
        nome = (r["richiesta__richiedente_reparto"] or "").strip() or "Non indicato"
        per_reparto[nome] = per_reparto.get(nome, 0) - int(r["t"] or 0)

    modelli = list(ModelloDPI.objects.filter(is_active=True).select_related("tipo", "tipo__categoria"))
    giac = giacenze()
    righe = []
    for m in modelli:
        qta = giac.get(m.pk, 0)
        cons = per_modello.get(m.pk, 0)
        medio_giorno = cons / giorni if giorni else 0
        copertura = (qta * giorni) // cons if cons > 0 and qta > 0 else (0 if cons > 0 else None)
        stato = stato_scorta(qta, m.scorta_minima)
        obiettivo = max(2 * m.scorta_minima, round(medio_giorno * 60))
        righe.append({
            "modello": m, "giacenza": qta, "consumo": cons, "stato": stato,
            "copertura": copertura, "suggerito": max(0, obiettivo - qta) if stato != STATO_OK or (copertura is not None and copertura < 30) else 0,
        })

    top = sorted((r for r in righe if r["consumo"] > 0), key=lambda r: -r["consumo"])[:10]
    riordino = sorted(
        (r for r in righe if r["stato"] != STATO_OK or (r["copertura"] is not None and r["copertura"] < 30 and r["suggerito"] > 0)),
        key=lambda r: (r["stato"] != STATO_ESAURITO, r["copertura"] if r["copertura"] is not None else 10**6),
    )
    return {
        "giorni": giorni, "da": da, "consumati": consumati, "caricati": caricati,
        "serie": serie, "serie_max": max([s["pezzi"] for s in serie] + [1]),
        "top": top, "top_max": max([r["consumo"] for r in top] + [1]),
        "reparti": sorted(per_reparto.items(), key=lambda kv: -kv[1]),
        "reparti_max": max(list(per_reparto.values()) + [1]),
        "riordino": riordino, "righe": righe,
        "sotto": sum(1 for r in righe if r["stato"] == STATO_SOTTO_SCORTA),
        "esauriti": sum(1 for r in righe if r["stato"] == STATO_ESAURITO),
        "pezzi_totali": sum(r["giacenza"] for r in righe),
    }
