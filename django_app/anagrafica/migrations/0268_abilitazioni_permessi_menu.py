"""Abilitazioni: corsi di aggiornamento riconosciuti dal titolo, permessi delle rotte nuove e voce di menu.

- I corsi già legati a un'abilitazione con «aggiornamento» o «refresh» nel titolo diventano
  «Aggiornamento»; gli altri restano «Corso base».
- Le rotte nuove prendono il permesso della rotta sorella (stessa regola della 0265).
- «Abilitazioni per reparto» entra nel menu accanto a «Scadenzario qualifiche». Idempotente.
"""
import re

from django.db import migrations

NOTA = "[ABILITAZIONI_0268] copiato dalla rotta sorella"
ROTTE = {
    "anagrafica:tipo_qualifica_edit": ("anagrafica:tipo_qualifica_serve_a",),
    "anagrafica:qualifiche_scadenzario": ("anagrafica:abilitazioni_persone",),
}
URL = "anagrafica:abilitazioni_persone"
ETICHETTA = "Abilitazioni per reparto"
_AGGIORNAMENTO = re.compile(r"aggiornament|refresh|rinnovo", re.I)


def avanti(apps, schema_editor):
    Corso = apps.get_model("anagrafica", "TrainingCourse")
    for pk, titolo in Corso.objects.filter(qualifica__isnull=False).values_list("pk", "titolo"):
        if _AGGIORNAMENTO.search(titolo or ""):
            Corso.objects.filter(pk=pk).update(qualifica_effetto="AGGIORNAMENTO")

    Binding = apps.get_model("core", "RoutePermissionBinding")
    for sorella, rotte in ROTTE.items():
        modello = Binding.objects.filter(route_name=sorella, is_active=True).order_by("-priority", "pk").first()
        if modello is None:
            continue
        for rotta in rotte:
            if not Binding.objects.filter(route_name=rotta).exists():
                Binding.objects.create(route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
                                       permission_id=modello.permission_id, source_app="anagrafica",
                                       priority=modello.priority, is_active=True, note=NOTA)

    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    if not Link.objects.filter(url_value=URL).exists():
        accanto = (Link.objects.filter(url_value="anagrafica:qualifiche_scadenzario").order_by("-is_active", "id").first()
                   or Link.objects.filter(url_value="anagrafica:qualifiche_list").order_by("-is_active", "id").first())
        if accanto is not None:
            Link.objects.create(
                url_value=URL, url_type="named", etichetta=ETICHETTA, icona="", gruppo=accanto.gruppo,
                categoria=accanto.categoria, ordine=(accanto.ordine or 0) + 1, active_view_names=URL,
                is_active=True, is_sistema=False,
            )


def indietro(apps, schema_editor):
    rotte = [r for g in ROTTE.values() for r in g]
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name__in=rotte, note=NOTA).delete()
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(url_value=URL, is_sistema=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
        ("anagrafica", "0267_abilitazioni_serve_a"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
