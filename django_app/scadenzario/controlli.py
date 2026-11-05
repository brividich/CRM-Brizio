"""«Da sistemare» del pannello: cosa manca alle scadenze generiche, con il link per farlo."""
from __future__ import annotations

from django.urls import reverse
from django.utils import timezone


def da_sistemare() -> list[dict]:
    """Solo voci con qualcosa da fare; le gravi (mail o accessi persi) prima."""
    from . import avvisi as av
    from .fonte import SOURCE, chiave_categoria
    from .models import CategoriaScadenza, RegolaVisibilita, ScadenzaGenerica
    from .visibilita import chiavi_di

    oggi = timezone.localdate()
    elenco = reverse("scadenzario:elenco")
    categorie = list(CategoriaScadenza.objects.filter(is_active=True))
    attive = ScadenzaGenerica.objects.filter(is_active=True, categoria__is_active=True)
    con_attivita = set(attive.values_list("categoria_id", flat=True))
    chiavi_regole = set(RegolaVisibilita.objects.filter(chiave__startswith=SOURCE).values_list("chiave", flat=True))

    voci = []

    def aggiungi(n, titolo, spiegazione, link, grave=False):
        if n:
            voci.append({"n": n, "titolo": titolo, "spiegazione": spiegazione, "link": link, "grave": grave})

    aggiungi(
        sum(1 for c in categorie if c.pk in con_attivita and not c.destinatari),
        "Categorie senza destinatari del riepilogo",
        "Le loro attività senza email propria non avvisano nessuno.",
        reverse("scadenzario:categorie"), grave=True,
    )
    aggiungi(
        attive.filter(data_scadenza__lt=oggi).count(),
        "Attività scadute",
        "Da rinnovare, o da sospendere se non servono più.",
        f"{elenco}?stato=scadute", grave=True,
    )
    if SOURCE not in chiavi_regole:
        aggiungi(
            sum(1 for c in categorie if chiavi_di(SOURCE, chiave_categoria(c.pk))[1] not in chiavi_regole),
            "Categorie senza nessuno assegnato",
            "Le vedono solo chi gestisce il pannello e il responsabile dell'attività.",
            reverse("scadenzario:categorie"),
        )
    aggiungi(
        attive.filter(responsabile__isnull=True).count(),
        "Attività senza responsabile",
        "Il responsabile le trova con «Solo le mie»: selezionale e assegnalo in blocco.",
        f"{elenco}?senza=responsabile",
    )
    aggiungi(
        len(av.anteprima()["senza"]),
        "Attività nel preavviso senza destinatari",
        "Niente avviso singolo: compaiono solo nel riepilogo mensile della categoria.",
        reverse("scadenzario:avvisi"),
    )
    return voci
