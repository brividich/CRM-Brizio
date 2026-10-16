"""«KPI» esce dal menu Manutenzione: i suoi indicatori sono nella Panoramica.

La pagina KPI e la Panoramica erano due letture della stessa vista
(``_responsabile_response``): ora c'e' una pagina sola, con sei numeri in testa e
«Dettaglio indicatori» per tutto il resto. ``/assets/manutenzione/quadro/kpi/``
continua a rispondere (redirect alla Panoramica, ``#dettaglio``) e i report
storici restano raggiungibili da «Report e budget».

Qui si nasconde soltanto la voce del menu laterale (``AssetSidebarButton``
``report_asset`` sotto «Manutenzione», etichetta «KPI»): la barra di sezione la
toglie da ``maintenance_nav`` e i due menu devono coincidere. Una voce
``report_asset`` spostata altrove a mano non viene toccata.

Reversibile: al rollback la voce torna visibile.
"""
from django.db import migrations


def avanti(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    nascosti = Button.objects.filter(
        code="report_asset", parent__code="maintenance_hub", is_visible=True
    ).update(is_visible=False)
    print(f"\n  [assets 0135] Voce 'KPI' nascosta dal menu Manutenzione: {nascosti}.")


def indietro(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    Button.objects.filter(code="report_asset", parent__code="maintenance_hub").update(is_visible=True)


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0134_workorder_origin_ticket_backfill"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
