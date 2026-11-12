from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scadenzario", "0003_presa_viste_foto"),
    ]

    operations = [
        migrations.AddField(
            model_name="scadenzagenerica",
            name="collegata_tipo",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="scadenzagenerica",
            name="collegata_id",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="scadenzagenerica",
            name="unita",
            field=models.BooleanField(default=False, help_text="Voce unica con quella del modulo collegato, che dà la data."),
        ),
        migrations.AddIndex(
            model_name="scadenzagenerica",
            index=models.Index(fields=["collegata_tipo", "collegata_id"], name="scad_gen_collegata_idx"),
        ),
    ]
