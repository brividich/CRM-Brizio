"""Onboarding a fasi: riallinea le voci esistenti e dà il binding ACL alla rotta nuova.

1. Le voci delle pratiche già aperte ricevono fase, ordine, tipo e scadenza
   (dalla data di ingresso della pratica) secondo il nuovo piano; account e
   visita preassuntiva diventano verificabili in automatico.
2. ``anagrafica:onboarding_date`` (modifica di data di ingresso e fine prova)
   eredita il binding di ``anagrafica:onboarding_task_update``: con
   ACL_STRICT_CANONICAL una rotta senza binding è negata ai non superuser.
   Create-only, come la 0135.
3. Voce di menu «Posizioni aperte» accanto a Recruiting; la Pipeline accende
   la voce Recruiting.
"""
from datetime import timedelta

from django.db import migrations

FASE_PER_CODICE = {
    "it_account_ad": ("PRE", "ACCOUNT"),
    "visita_preassuntiva": ("PRE", "VISITA"),
    "hr_badge_accessi": ("GIORNO1", "MANUALE"),
    "dpi_consegna_iniziale": ("GIORNO1", "MANUALE"),
    "responsabile_postazione_affiancamento": ("GIORNO1", "MANUALE"),
    "formazione_corsi_obbligatori": ("60GG", "MANUALE"),
}
ORDINE_FASE = {"PRE": 0, "GIORNO1": 100, "SETTIMANA1": 200, "60GG": 300, "PROVA": 400}
OFFSET_FASE = {"PRE": -1, "GIORNO1": 0, "SETTIMANA1": 7, "60GG": 60}

ROTTE = {"anagrafica:onboarding_date": "anagrafica:onboarding_task_update"}
NOTA = "[ONBOARDING_0138] copiato da {}"


def avanti(apps, schema_editor):
    Task = apps.get_model("anagrafica", "OnboardingTask")
    for task in Task.objects.select_related("pratica").order_by("pratica_id", "id"):
        fase, tipo = FASE_PER_CODICE.get(task.codice, ("PRE", "MANUALE"))
        task.fase = fase
        task.tipo = tipo
        task.ordine = ORDINE_FASE[fase] + (task.id % 100)
        ingresso = task.pratica.data_assunzione
        task.scadenza = ingresso + timedelta(days=OFFSET_FASE[fase]) if ingresso else None
        task.save(update_fields=["fase", "tipo", "ordine", "scadenza"])

    # Voce di menu «Posizioni aperte» accanto a Recruiting (Persone › Ingressi).
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    recruiting = Link.objects.filter(url_value="anagrafica:recruiting_list").order_by("id").first()
    if recruiting is not None and not Link.objects.filter(url_value="anagrafica:recruiting_posizioni").exists():
        Link.objects.create(
            categoria_id=recruiting.categoria_id, etichetta="Posizioni aperte", icona="",
            gruppo=recruiting.gruppo, url_type="named", url_value="anagrafica:recruiting_posizioni",
            active_view_names=",".join([
                "anagrafica:recruiting_posizioni", "anagrafica:recruiting_posizione_detail",
                "anagrafica:recruiting_posizione_create", "anagrafica:recruiting_posizione_edit",
            ]),
            ordine=recruiting.ordine + 1, apri_nuova_tab=False, is_active=True, is_sistema=False,
        )
    if recruiting is not None and "anagrafica:recruiting_pipeline" not in (recruiting.active_view_names or ""):
        nomi = [n for n in (recruiting.active_view_names or "").split(",") if n.strip()]
        recruiting.active_view_names = ",".join(nomi + ["anagrafica:recruiting_pipeline"])
        recruiting.save(update_fields=["active_view_names"])

    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        modello = Binding.objects.filter(route_name=sorella, is_active=True).order_by("-priority", "pk").first()
        if modello is None:
            continue
        Binding.objects.create(
            route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
            permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
            is_active=True, note=NOTA.format(sorella),
        )


def indietro(apps, schema_editor):
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(
        url_value="anagrafica:recruiting_posizioni").delete()
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0137_ingressi_posizioni_offerta_fasi"),
        ("core", "0074_admin_subnav_accessi_negati"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
