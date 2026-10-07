"""Binding ACL v2 delle pagine «Chiedi un report» (reportistica a conversazione).

Con ACL_STRICT_CANONICAL una route senza binding e' negata ai non superuser: il
bootstrap runtime (``acl_bootstrap._REP_ROUTE_BINDINGS``) gira solo a cache
scaduta, quindi i binding nascono qui, al deploy. Create-only: un binding gia'
presente (anche disattivato a mano) non si tocca. Nessun permesso nuovo: chiedere
e scaricare = ``anagrafica.reportistica.view``, salvare come modello = ``.manage``.
"""
from django.db import migrations

VIEW = "anagrafica.reportistica.view"
MANAGE = "anagrafica.reportistica.manage"
ROUTE = {
    "anagrafica:reportistica_chat": VIEW,
    "anagrafica:reportistica_chat_scarica": VIEW,
    "anagrafica:reportistica_chat_salva": MANAGE,
}


def avanti(apps, schema_editor):
    Permesso = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for route, code in ROUTE.items():
        if not Permesso.objects.filter(code=code).exists():
            continue  # reportistica non ancora inizializzata: ci pensera' il bootstrap
        if Binding.objects.filter(route_name=route).exists():
            continue
        Binding.objects.create(route_name=route, path_pattern="", match_strategy="exact", permission_id=code,
                               source_app="anagrafica", priority=80, is_active=True,
                               note="[REP_0132] binding reportistica a conversazione")


    # La voce di menu «Reportistica» resta evidenziata anche sulle pagine della conversazione.
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    for link in Link.objects.filter(url_value="anagrafica:reportistica_index"):
        viste = [v for v in (link.active_view_names or "").split(",") if v.strip()]
        nuove = [v for v in ("anagrafica:reportistica_chat",) if v not in viste]
        if nuove:
            link.active_view_names = ",".join(viste + nuove)
            link.save(update_fields=["active_view_names"])


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(
        route_name__in=list(ROUTE), note="[REP_0132] binding reportistica a conversazione",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0131_reportistica_nuovi_predefiniti"),
        ("core", "0074_admin_subnav_accessi_negati"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
