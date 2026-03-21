from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CategoriaDPI",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=100)),
                ("descrizione", models.TextField(blank=True, default="")),
                ("immagine", models.ImageField(blank=True, null=True, upload_to="dpi/categorie/")),
                ("icona_emoji", models.CharField(blank=True, default="🦺", max_length=10)),
                ("vita_utile_giorni", models.PositiveIntegerField(
                    blank=True, null=True,
                    help_text="Vita utile stimata in giorni (per calcolo scadenza automatica alla consegna)",
                )),
                ("unita_misura", models.CharField(blank=True, default="pz", max_length=30)),
                ("scorta_minima", models.PositiveIntegerField(
                    default=0,
                    help_text="Soglia minima in magazzino per segnalazione",
                )),
                ("is_active", models.BooleanField(default=True)),
                ("order_index", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Categoria DPI",
                "verbose_name_plural": "Categorie DPI",
                "ordering": ["order_index", "nome"],
            },
        ),
        migrations.CreateModel(
            name="DPIImpostazioni",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("responsabile_nome", models.CharField(blank=True, default="", max_length=200)),
                ("responsabile_email", models.EmailField(blank=True, default="")),
                ("note_generali", models.TextField(blank=True, default="")),
                ("notifica_nuova_richiesta", models.BooleanField(
                    default=False,
                    help_text="Invia email al responsabile per ogni nuova richiesta",
                )),
                ("notifica_email_extra", models.TextField(
                    blank=True, default="",
                    help_text="Indirizzi email aggiuntivi per notifiche, uno per riga",
                )),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Impostazioni DPI",
                "verbose_name_plural": "Impostazioni DPI",
            },
        ),
        migrations.CreateModel(
            name="RichiestaDPI",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("numero", models.CharField(editable=False, max_length=30, unique=True)),
                ("quantita", models.PositiveIntegerField(default=1)),
                ("motivazione", models.TextField(blank=True, default="")),
                ("stato", models.CharField(
                    choices=[
                        ("INVIATA", "Inviata"),
                        ("APPROVATA", "Approvata"),
                        ("CONSEGNATA", "Consegnata"),
                        ("RIFIUTATA", "Rifiutata"),
                        ("ANNULLATA", "Annullata"),
                    ],
                    db_index=True,
                    default="INVIATA",
                    max_length=15,
                )),
                ("richiedente_legacy_id", models.IntegerField(blank=True, db_index=True, null=True)),
                ("richiedente_nome", models.CharField(max_length=200)),
                ("richiedente_email", models.CharField(blank=True, default="", max_length=200)),
                ("richiedente_reparto", models.CharField(blank=True, default="", max_length=100)),
                ("note_gestione", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("categoria", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="richieste",
                    to="dpi.categoriadpi",
                )),
                ("created_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="dpi_richieste_create",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "verbose_name": "Richiesta DPI",
                "verbose_name_plural": "Richieste DPI",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ConsegnaDPI",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("data_consegna", models.DateField()),
                ("consegnato_da_nome", models.CharField(blank=True, default="", max_length=200)),
                ("note_consegna", models.TextField(blank=True, default="")),
                ("firmato_ricevuta", models.BooleanField(default=False)),
                ("data_scadenza_stimata", models.DateField(
                    blank=True, null=True,
                    help_text="Scadenza stimata per rinnovo (calcolata automaticamente da vita utile categoria)",
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("richiesta", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="consegna",
                    to="dpi.richiestadpi",
                )),
            ],
            options={
                "verbose_name": "Consegna DPI",
                "verbose_name_plural": "Consegne DPI",
            },
        ),
        migrations.CreateModel(
            name="RichiestaDPICommento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("autore_nome", models.CharField(max_length=200)),
                ("testo", models.TextField()),
                ("is_interno", models.BooleanField(
                    default=False,
                    help_text="Nota interna (non visibile al richiedente)",
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("richiesta", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="commenti",
                    to="dpi.richiestadpi",
                )),
            ],
            options={
                "verbose_name": "Commento richiesta DPI",
                "verbose_name_plural": "Commenti richieste DPI",
                "ordering": ["created_at"],
            },
        ),
    ]
