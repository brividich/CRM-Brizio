"""Mansionario fase 6 (1/3): i riferimenti al vecchio catalogo diventano numeri semplici.

Override individuali e origine degli adempimenti di cambio mansione puntavano al
vecchio catalogo separato ``MansioneRischio``. Qui la colonna resta la stessa
(``mansione_rischio_id`` / ``origine_mansione_rischio_id``) ma perde il vincolo
verso il vecchio catalogo; la 0175 la riscrive con l'id della voce del catalogo
``Mansione`` e la 0176 la ricollega a ``Mansione``. Nessuna colonna rinominata:
su SQL Server la rinomina lascia indici con il vecchio nome.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0173_mansionario_competenze_dati"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="dipendentemansionerischiooverride", name="uniq_override_mansrischio_attivo",
        ),
        migrations.AlterField(
            model_name="dipendentemansionerischiooverride",
            name="mansione_rischio",
            field=models.IntegerField(db_column="mansione_rischio_id", db_index=True),
        ),
        migrations.AlterField(
            model_name="adempimentocambiomansione",
            name="origine_mansione_rischio",
            field=models.IntegerField(db_column="origine_mansione_rischio_id", null=True, blank=True,
                                      db_index=True),
        ),
    ]
