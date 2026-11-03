"""Sinonimi delle categorie asset: le parole comuni con cui si cerca un asset nel ticket.

Prima proposta per le categorie che in produzione hanno nomi tecnici («Chiller»,
«Bruciatori»...): riempie solo i sinonimi vuoti, poi si correggono da Impostazioni asset.
"""
from django.db import migrations, models

from dati_bi.viste import ripristina_viste_sqlite, sospendi_viste_sqlite

PROPOSTA = {
    "chiller": "condizionatore, climatizzatore, clima, aria condizionata, split, raffrescamento",
    "heating, ventilation and air conditioning": "condizionatore, clima, riscaldamento, caldaia, ventilazione, aria condizionata",
    "bruciatori": "caldaia, riscaldamento, bruciatore, termosifoni",
    "caldaia": "riscaldamento, bruciatore, termosifoni",
    "impianti termici": "caldaia, riscaldamento, condizionatore, clima",
    "compressore": "aria compressa",
    "carroponte": "gru, paranco, sollevamento",
    "gru": "carroponte, paranco, sollevamento",
    "paranco": "carroponte, gru, sollevamento",
    "carrelli elevatori": "muletto, carrello",
    "transpallet": "carrello, transpallet elettrico",
    "kardex": "magazzino verticale",
    "lavapavimenti": "pulizia pavimenti, lavasciuga",
    "forni": "forno, trattamento termico",
    "fotovoltaico": "pannelli solari, impianto solare",
    "impianti fotovoltaici": "pannelli solari, impianto solare",
    "impianto fotovoltaico": "pannelli solari, impianto solare",
}


def avanti(apps, schema_editor):
    AssetCategory = apps.get_model("assets", "AssetCategory")
    for categoria in AssetCategory.objects.filter(sinonimi=""):
        proposta = PROPOSTA.get(" ".join((categoria.label or "").split()).casefold())
        if proposta:
            categoria.sinonimi = proposta
            categoria.save(update_fields=["sinonimi"])


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0158_collector_eventi_non_leggibile'),
    ]

    operations = [
        migrations.RunPython(sospendi_viste_sqlite, ripristina_viste_sqlite),
        migrations.AddField(
            model_name='assetcategory',
            name='sinonimi',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.RunPython(avanti, migrations.RunPython.noop),
        migrations.RunPython(ripristina_viste_sqlite, sospendi_viste_sqlite),
    ]
