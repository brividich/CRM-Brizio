import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from dati_bi.viste import ripristina_viste_sqlite, sospendi_viste_sqlite


class Migration(migrations.Migration):
    """Ticket aperto per conto di un collega: chi l'ha compilato davvero."""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tickets", "0015_mappa_ticket"),
    ]

    operations = [
        migrations.RunPython(sospendi_viste_sqlite, ripristina_viste_sqlite),
        migrations.AddField(
            model_name="ticket",
            name="aperto_da_user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tickets_aperti_per_altri",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="aperto_da_nome",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.RunPython(ripristina_viste_sqlite, sospendi_viste_sqlite),
    ]
