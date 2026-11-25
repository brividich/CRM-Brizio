"""Menu del modulo KICK-OFF da 10 a 7 voci (25/11/2026).

- «Programmi», «Registro FAI» e «Report FAI» diventano una voce sola, «Programmi e FAI»
  (le tre pagine hanno le schede in alto).
- «Calendario» esce dal menu: si apre dalla Dashboard KICK-OFF («Calendario incontri»).
- «Le mie attività KICK-OFF» diventa «Le mie attività» (siamo già nel modulo).
Le pagine e i permessi non cambiano; le voci nascoste restano (is_visible=False).
"""

from django.db import migrations

NASCOSTE = ("tasks-sub-calendario", "tasks-sub-registro-fai", "tasks-sub-report-fai")
ETICHETTE = {
    "tasks-sub-programmi": ("Programmi", "Programmi e FAI"),
    "tasks-sub-mie-azioni": ("Le mie attività KICK-OFF", "Le mie attività"),
}


def applica(apps, schema_editor):
    N = apps.get_model("core", "NavigationItem")
    N.objects.filter(code__in=NASCOSTE).update(is_visible=False)
    for code, (_prima, dopo) in ETICHETTE.items():
        N.objects.filter(code=code).update(label=dopo)


def ripristina(apps, schema_editor):
    N = apps.get_model("core", "NavigationItem")
    N.objects.filter(code__in=NASCOSTE).update(is_visible=True)
    for code, (prima, _dopo) in ETICHETTE.items():
        N.objects.filter(code=code).update(label=prima)


class Migration(migrations.Migration):
    dependencies = [("core", "0116_tasks_subnav_mie_attivita_kickoff")]
    operations = [migrations.RunPython(applica, ripristina)]
