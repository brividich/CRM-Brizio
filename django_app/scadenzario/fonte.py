"""Fonte «Scadenze generiche» dello scadenzario globale (``/scadenze``).

Chiavi: ``generiche`` → ``generiche|cat-<id categoria>`` → ``generiche|cat-<id>|s<id attività>``.
Senza regole le vedono gli amministratori del pannello e il responsabile della
singola attività; tutti gli altri le ricevono dalle regole del pannello.
"""
from __future__ import annotations

from django.urls import reverse

SOURCE = "generiche"


def chiave_categoria(categoria_id: int) -> str:
    return f"cat-{int(categoria_id)}"


def chiave_attivita(scadenza_id: int) -> str:
    return f"s{int(scadenza_id)}"


def collect_generiche(ctx) -> list:
    from dashboard.scadenze_providers import ScadenzaItem

    from .models import ScadenzaGenerica
    from .visibilita import puo_gestire_pannello

    qs = (
        ScadenzaGenerica.objects.select_related("categoria", "asset", "responsabile")
        .filter(is_active=True, categoria__is_active=True, data_scadenza__isnull=False,
                data_scadenza__lte=ctx.orizzonte)
        .order_by("data_scadenza", "pk")
    )
    if not ctx.sistema and not puo_gestire_pannello(ctx.request):
        user_id = getattr(getattr(ctx.request, "user", None), "id", None)
        if not user_id:
            return []
        qs = qs.filter(responsabile_id=user_id)
    items = []
    for s in qs:
        # Il soggetto è il link alla scheda nello Scadenzario: mai vuoto.
        soggetto = s.ubicazione or (s.asset.name if s.asset_id else "") or s.titolo
        items.append(ScadenzaItem(
            source=SOURCE,
            kind=chiave_categoria(s.categoria_id),
            kind_label=s.categoria.nome,
            titolo=s.titolo,
            soggetto=soggetto,
            reparto="",
            data_scadenza=s.data_scadenza,
            giorni=(s.data_scadenza - ctx.oggi).days,
            url=reverse("scadenzario:scadenza_dettaglio", args=[s.pk]),
            extra={"categoria_id": s.categoria_id, "scadenza_id": s.pk, "validita_mesi": s.validita_mesi, "responsabile_id": s.responsabile_id},
            elemento=chiave_attivita(s.pk),
            elemento_label=s.titolo,
        ))
    return items
