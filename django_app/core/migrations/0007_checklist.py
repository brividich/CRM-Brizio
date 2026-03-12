from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_userextrainfo"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChecklistVoce",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tipo_checklist", models.CharField(choices=[("checkin", "Check-in (Onboarding)"), ("checkout", "Check-out (Offboarding)")], db_index=True, max_length=20)),
                ("label", models.CharField(max_length=300)),
                ("tipo_campo", models.CharField(choices=[("check", "Checkbox (fatto/non fatto)"), ("testo", "Testo libero"), ("data", "Data"), ("select", "Scelta da lista")], default="check", max_length=20)),
                ("scelte", models.JSONField(blank=True, default=list, help_text="Solo per tipo_campo=select: lista di stringhe")),
                ("obbligatorio", models.BooleanField(default=False)),
                ("ordine", models.IntegerField(default=100)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["tipo_checklist", "ordine", "id"]},
        ),
        migrations.CreateModel(
            name="ChecklistEsecuzione",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_user_id", models.IntegerField(db_index=True)),
                ("utente_nome", models.CharField(blank=True, default="", max_length=200)),
                ("tipo_checklist", models.CharField(choices=[("checkin", "Check-in (Onboarding)"), ("checkout", "Check-out (Offboarding)")], max_length=20)),
                ("data_esecuzione", models.DateTimeField(auto_now_add=True)),
                ("eseguita_da_id", models.IntegerField(blank=True, null=True)),
                ("eseguita_da_nome", models.CharField(blank=True, default="", max_length=200)),
                ("note", models.TextField(blank=True, default="")),
                ("completata", models.BooleanField(default=True)),
            ],
            options={"ordering": ["-data_esecuzione"]},
        ),
        migrations.CreateModel(
            name="ChecklistRisposta",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("esecuzione", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="risposte", to="core.checklistesecuzione")),
                ("voce_id", models.IntegerField()),
                ("voce_label", models.CharField(max_length=300)),
                ("voce_tipo", models.CharField(max_length=20)),
                ("valore", models.TextField(blank=True, default="")),
            ],
        ),
    ]
