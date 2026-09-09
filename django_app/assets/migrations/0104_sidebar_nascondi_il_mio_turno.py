"""«Il mio turno» esce dal menu: il suo lavoro e' dentro «Da fare».

Le due pagine raccontavano lo stesso lavoro manutentivo da due angoli diversi:
«Il mio turno» partiva dagli ordini di lavoro (``WorkOrder``), «Da fare» dalle
manutenzioni dovute (``MaintenanceOccurrence``). Chi entrava trovava due code e
doveva capire da solo quale delle due fosse quella vera.

Ora «Da fare» apre con il blocco «I miei interventi» — in corso, bloccati,
urgenti — che e' l'unica cosa che «Il mio turno» mostrava e lei no. Il menu ha
una sola pagina operativa.

Nessun URL sparisce: ``/assets/manutenzione/il-mio-turno/`` continua a
rispondere e la view resta al suo posto. Qui si nasconde soltanto il pulsante,
che vive a database (``AssetSidebarButton``, seminato dalla 0097): cambiare il
codice non toccherebbe nessuna installazione esistente.

Reversibile: al rollback la voce torna visibile.
"""
from django.db import migrations


def avanti(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    nascosti = Button.objects.filter(code="il_mio_turno", is_visible=True).update(is_visible=False)
    print(f"  [assets 0104] Voce 'Il mio turno' nascosta dal menu: {nascosti}.")


def indietro(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    Button.objects.filter(code="il_mio_turno").update(is_visible=True)


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0103_sidebar_attivita_voce_unica"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
