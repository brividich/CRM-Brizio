"""Prefisso porte dello switch (es. "A0"): collega allo switch le porte A0.x.x senza switch indicato.

Numerata 0137 perche' 0134-0136 sono gia' usate da branch assets non ancora integrati.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0133_permessi_dismetti_elimina_asset"),
    ]

    operations = [
        migrations.AddField(
            model_name="asset",
            name="switch_prefisso_porte",
            field=models.CharField(blank=True, db_index=True, default="", max_length=20, verbose_name="Prefisso porte switch"),
        ),
    ]
