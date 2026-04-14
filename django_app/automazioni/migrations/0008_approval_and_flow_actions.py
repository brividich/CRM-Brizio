from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("automazioni", "0007_alter_automationaction_action_type"),
    ]

    operations = [
        # Aggiorna choices AutomationAction.action_type con i nuovi tipi di controllo flusso
        migrations.AlterField(
            model_name="automationaction",
            name="action_type",
            field=models.CharField(
                max_length=40,
                choices=[
                    ("send_email", "Send email"),
                    ("insert_record", "Insert record"),
                    ("update_record", "Update record"),
                    ("update_trigger_record", "Update triggering record"),
                    ("update_dashboard_metric", "Update dashboard metric"),
                    ("write_log", "Write log"),
                    ("delay_schedule", "Delay / Schedule"),
                    ("http_request", "HTTP request"),
                    ("teams_webhook", "Teams webhook"),
                    ("send_approval", "Richiedi Approvazione"),
                    ("do_until", "Do Until (Ripeti fino a condizione)"),
                    ("for_each", "Per Ogni Elemento (For Each)"),
                    ("branch", "Branch / Condizione If-Else"),
                ],
            ),
        ),
        # Aggiorna choices AutomationRunLog.status con WAITING_APPROVAL
        migrations.AlterField(
            model_name="automationrunlog",
            name="status",
            field=models.CharField(
                max_length=20,
                choices=[
                    ("success", "Success"),
                    ("error", "Error"),
                    ("skipped", "Skipped"),
                    ("test", "Test"),
                    ("waiting_approval", "In attesa approvazione"),
                ],
                db_index=True,
            ),
        ),
        # Nuovo modello AutomationApproval
        migrations.CreateModel(
            name="AutomationApproval",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "run_log",
                    models.ForeignKey(
                        help_text="Run log che ha generato questa richiesta.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="approvals",
                        to="automazioni.automationrunlog",
                    ),
                ),
                (
                    "action",
                    models.ForeignKey(
                        blank=True,
                        help_text="Azione send_approval che ha originato la richiesta.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approval_requests",
                        to="automazioni.automationaction",
                    ),
                ),
                (
                    "token",
                    models.UUIDField(
                        db_index=True,
                        default=uuid.uuid4,
                        help_text="Token univoco usato negli URL di approvazione/rifiuto.",
                        unique=True,
                    ),
                ),
                (
                    "approver_emails",
                    models.JSONField(
                        default=list,
                        help_text="Lista email degli approvatori a cui è stata inviata la richiesta.",
                    ),
                ),
                ("subject", models.CharField(help_text="Oggetto dell'email di approvazione.", max_length=512)),
                ("message", models.TextField(blank=True, default="", help_text="Corpo del messaggio inviato all'approvatore.")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "In attesa"),
                            ("approved", "Approvato"),
                            ("rejected", "Rifiutato"),
                            ("expired", "Scaduto"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("decided_by_email", models.CharField(blank=True, default="", help_text="Email di chi ha preso la decisione.", max_length=255)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, help_text="Scadenza della richiesta.", null=True)),
                ("resume_payload", models.JSONField(default=dict, help_text="Payload originale da usare per eseguire le azioni post-decisione.")),
                ("resume_old_payload", models.JSONField(blank=True, help_text="Old payload originale.", null=True)),
                ("approved_actions", models.JSONField(default=list, help_text="Azioni da eseguire se la richiesta viene approvata.")),
                ("rejected_actions", models.JSONField(default=list, help_text="Azioni da eseguire se la richiesta viene rifiutata.")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="automationapproval",
            index=models.Index(fields=["status", "expires_at"], name="autom_approval_status_exp_idx"),
        ),
    ]
