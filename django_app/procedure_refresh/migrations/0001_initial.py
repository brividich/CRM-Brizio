from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProcedureDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=50, unique=True, verbose_name="Codice documento")),
                ("title", models.CharField(max_length=300, verbose_name="Titolo")),
                ("category", models.CharField(blank=True, default="", max_length=100, verbose_name="Categoria")),
                ("document_type", models.CharField(choices=[("MT", "MT"), ("MTSI", "MTSI"), ("ALTRO", "Altro")], db_index=True, default="MT", max_length=10, verbose_name="Tipo documento")),
                ("owner_department", models.CharField(blank=True, default="", max_length=150, verbose_name="Reparto responsabile")),
                ("description", models.TextField(blank=True, default="", verbose_name="Descrizione")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Attivo")),
                ("requires_acknowledgement", models.BooleanField(default=True, verbose_name="Richiede presa visione")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Documento procedura",
                "verbose_name_plural": "Documenti procedura",
                "ordering": ["document_type", "code"],
            },
        ),
        migrations.CreateModel(
            name="ProcedureRevision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("revision_code", models.CharField(max_length=50, verbose_name="Codice revisione")),
                ("revision_date", models.DateField(verbose_name="Data revisione")),
                ("effective_date", models.DateField(verbose_name="Data efficacia")),
                ("source_type", models.CharField(choices=[("sharepoint", "SharePoint"), ("fileserver", "File server")], default="sharepoint", max_length=20, verbose_name="Sorgente")),
                ("source_url", models.URLField(blank=True, default="", max_length=2048, verbose_name="URL SharePoint")),
                ("source_path", models.CharField(blank=True, default="", max_length=1024, verbose_name="Path file server")),
                ("file_name", models.CharField(max_length=300, verbose_name="Nome file")),
                ("file_hash", models.CharField(blank=True, default="", max_length=128, verbose_name="Hash file")),
                ("is_current", models.BooleanField(db_index=True, default=False, verbose_name="Revisione corrente")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="revisions", to="procedure_refresh.proceduredocument", verbose_name="Documento")),
                ("published_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pr_published_revisions", to=settings.AUTH_USER_MODEL, verbose_name="Pubblicato da")),
            ],
            options={
                "verbose_name": "Revisione procedura",
                "verbose_name_plural": "Revisioni procedura",
                "ordering": ["-revision_date"],
            },
        ),
        migrations.CreateModel(
            name="ProcedureCampaign",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200, verbose_name="Nome campagna")),
                ("description", models.TextField(blank=True, default="", verbose_name="Descrizione")),
                ("status", models.CharField(choices=[("draft", "Bozza"), ("published", "Pubblicata"), ("closed", "Chiusa"), ("archived", "Archiviata")], db_index=True, default="draft", max_length=20, verbose_name="Stato")),
                ("start_date", models.DateField(verbose_name="Data inizio")),
                ("due_date", models.DateField(verbose_name="Scadenza")),
                ("published_at", models.DateTimeField(blank=True, null=True, verbose_name="Pubblicata il")),
                ("closed_at", models.DateTimeField(blank=True, null=True, verbose_name="Chiusa il")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pr_created_campaigns", to=settings.AUTH_USER_MODEL, verbose_name="Creata da")),
            ],
            options={
                "verbose_name": "Campagna refresh",
                "verbose_name_plural": "Campagne refresh",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ProcedureCampaignDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_mandatory", models.BooleanField(default=True, verbose_name="Obbligatoria")),
                ("display_order", models.PositiveIntegerField(default=0, verbose_name="Ordine")),
                ("campaign", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="campaign_documents", to="procedure_refresh.procedurecampaign", verbose_name="Campagna")),
                ("revision", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="campaign_documents", to="procedure_refresh.procedurerevision", verbose_name="Revisione")),
            ],
            options={
                "verbose_name": "Documento in campagna",
                "verbose_name_plural": "Documenti in campagna",
                "ordering": ["display_order", "id"],
            },
        ),
        migrations.CreateModel(
            name="ProcedureAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("assigned_at", models.DateTimeField(auto_now_add=True, verbose_name="Assegnato il")),
                ("due_date", models.DateField(blank=True, null=True, verbose_name="Scadenza")),
                ("status", models.CharField(choices=[("assigned", "Assegnata"), ("opened", "Aperta"), ("read_confirmed", "Presa visione confermata"), ("overdue", "Scaduta"), ("cancelled", "Annullata")], db_index=True, default="assigned", max_length=20, verbose_name="Stato")),
                ("first_opened_at", models.DateTimeField(blank=True, null=True, verbose_name="Prima apertura")),
                ("last_opened_at", models.DateTimeField(blank=True, null=True, verbose_name="Ultima apertura")),
                ("read_confirmed_at", models.DateTimeField(blank=True, null=True, verbose_name="Conferma presa visione")),
                ("read_confirmed_flag", models.BooleanField(default=False, verbose_name="Presa visione confermata")),
                ("user_note", models.TextField(blank=True, default="", verbose_name="Nota utente")),
                ("manager_note", models.TextField(blank=True, default="", verbose_name="Nota manager")),
                ("open_count", models.PositiveIntegerField(default=0, verbose_name="Numero aperture")),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True, verbose_name="IP")),
                ("user_agent", models.TextField(blank=True, default="", verbose_name="User agent")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("campaign", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assignments", to="procedure_refresh.procedurecampaign", verbose_name="Campagna")),
                ("revision", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assignments", to="procedure_refresh.procedurerevision", verbose_name="Revisione")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="procedure_assignments", to=settings.AUTH_USER_MODEL, verbose_name="Utente")),
                ("assigned_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pr_assignments_given", to=settings.AUTH_USER_MODEL, verbose_name="Assegnato da")),
            ],
            options={
                "verbose_name": "Assegnazione",
                "verbose_name_plural": "Assegnazioni",
                "ordering": ["-assigned_at"],
            },
        ),
        migrations.CreateModel(
            name="ProcedureReadEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("opened", "Aperta"), ("confirmed", "Confermata"), ("reminder_sent", "Reminder inviato"), ("reassigned", "Riassegnata"), ("exported", "Esportata")], db_index=True, max_length=20, verbose_name="Tipo evento")),
                ("event_at", models.DateTimeField(auto_now_add=True, verbose_name="Timestamp")),
                ("notes", models.TextField(blank=True, default="", verbose_name="Note")),
                ("meta_json", models.TextField(blank=True, default="", verbose_name="Metadati JSON")),
                ("assignment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="procedure_refresh.procedureassignment", verbose_name="Assegnazione")),
                ("event_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pr_read_events", to=settings.AUTH_USER_MODEL, verbose_name="Eseguito da")),
            ],
            options={
                "verbose_name": "Evento lettura",
                "verbose_name_plural": "Eventi lettura",
                "ordering": ["-event_at"],
            },
        ),
        # ── Constraints ────────────────────────────────────────────────────
        migrations.AddConstraint(
            model_name="procedurerevision",
            constraint=models.UniqueConstraint(
                fields=["document", "revision_code"],
                name="pr_unique_doc_revision_code",
            ),
        ),
        migrations.AddConstraint(
            model_name="procedurecampaigndocument",
            constraint=models.UniqueConstraint(
                fields=["campaign", "revision"],
                name="pr_unique_campaign_revision",
            ),
        ),
        # ── Indexes ────────────────────────────────────────────────────────
        migrations.AddIndex(
            model_name="procedureassignment",
            index=models.Index(fields=["user", "status"], name="pr_assign_user_status"),
        ),
        migrations.AddIndex(
            model_name="procedureassignment",
            index=models.Index(fields=["campaign", "status"], name="pr_assign_campaign_status"),
        ),
        migrations.AddIndex(
            model_name="procedureassignment",
            index=models.Index(fields=["revision", "status"], name="pr_assign_revision_status"),
        ),
    ]
