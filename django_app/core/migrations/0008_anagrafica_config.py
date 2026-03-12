from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_checklist"),
    ]

    operations = [
        # Campo reparto aggiunto a UserExtraInfo
        migrations.AddField(
            model_name="userextrainfo",
            name="reparto",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        # Modello OptioneConfig — opzioni dropdown per anagrafica
        migrations.CreateModel(
            name="OptioneConfig",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tipo", models.CharField(db_index=True, max_length=50)),
                ("valore", models.CharField(max_length=200)),
                ("ordine", models.IntegerField(default=100)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["tipo", "ordine", "valore"]},
        ),
        # Modello AnagraficaVoce — campi extra configurabili
        migrations.CreateModel(
            name="AnagraficaVoce",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(max_length=300)),
                ("tipo_campo", models.CharField(
                    choices=[
                        ("check", "Checkbox (fatto/non fatto)"),
                        ("testo", "Testo libero"),
                        ("data", "Data"),
                        ("select", "Scelta da lista"),
                    ],
                    default="testo",
                    max_length=20,
                )),
                ("scelte", models.JSONField(blank=True, default=list, help_text="Solo per tipo_campo=select: lista di stringhe")),
                ("obbligatorio", models.BooleanField(default=False)),
                ("ordine", models.IntegerField(default=100)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["ordine", "id"]},
        ),
        # Modello AnagraficaRisposta — valori per utente
        migrations.CreateModel(
            name="AnagraficaRisposta",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_user_id", models.IntegerField(db_index=True)),
                ("voce", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="risposte", to="core.anagraficavoce")),
                ("valore", models.TextField(blank=True, default="")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"unique_together": {("legacy_user_id", "voce")}},
        ),
    ]
