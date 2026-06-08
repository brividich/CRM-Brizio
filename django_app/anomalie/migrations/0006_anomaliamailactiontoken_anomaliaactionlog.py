from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import anomalie.mail_action_models


class Migration(migrations.Migration):

    dependencies = [
        ("anomalie", "0005_migrate_custom_roles_to_anagrafica"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AnomaliaMailActionToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(db_index=True, default=anomalie.mail_action_models._default_token, max_length=64, unique=True)),
                ("recipient_legacy_user_id", models.IntegerField(blank=True, db_index=True, null=True)),
                ("recipient_email", models.EmailField(blank=True, default="", max_length=254)),
                ("recipient_display", models.CharField(blank=True, default="", max_length=200)),
                ("op_id", models.CharField(blank=True, db_index=True, default="", max_length=100)),
                ("op_nominativo", models.CharField(blank=True, default="", max_length=255)),
                ("anomalie_ids", models.JSONField(default=list)),
                ("anomalie_snapshot", models.JSONField(default=list)),
                ("action", models.CharField(choices=[("prendi_in_carico", "Prendi in carico"), ("approva", "Approva"), ("respingi", "Respingi"), ("richiedi_modifica", "Richiedi modifica"), ("chiudi", "Chiudi"), ("visualizza", "Visualizza (sola lettura)")], db_index=True, max_length=32)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("is_used", models.BooleanField(db_index=True, default=False)),
                ("is_revoked", models.BooleanField(db_index=True, default=False)),
                ("source_automation", models.CharField(blank=True, default="", max_length=200)),
                ("ip_address_used", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent_used", models.TextField(blank=True, default="")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="anomalia_mail_action_tokens_created", to=settings.AUTH_USER_MODEL)),
                ("recipient_user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="anomalia_mail_action_tokens", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Token azione anomalia via mail",
                "verbose_name_plural": "Token azione anomalie via mail",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="anomaliamailactiontoken",
            index=models.Index(fields=["is_used", "is_revoked", "expires_at"], name="anomalia_token_valid_idx"),
        ),
        migrations.CreateModel(
            name="AnomaliaActionLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("anomalia_id", models.IntegerField(db_index=True)),
                ("op_id", models.CharField(blank=True, db_index=True, default="", max_length=100)),
                ("legacy_user_id", models.IntegerField(blank=True, db_index=True, null=True)),
                ("user_display", models.CharField(blank=True, default="", max_length=200)),
                ("action", models.CharField(db_index=True, max_length=32)),
                ("previous_status", models.CharField(blank=True, default="", max_length=100)),
                ("new_status", models.CharField(blank=True, default="", max_length=100)),
                ("note", models.TextField(blank=True, default="")),
                ("source", models.CharField(choices=[("mail_action", "Link da mail"), ("portal", "Portale"), ("system", "Sistema / Automazione")], db_index=True, default="portal", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.TextField(blank=True, default="")),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("token", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="action_logs", to="anomalie.anomaliamailactiontoken")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Log azione anomalia",
                "verbose_name_plural": "Log azioni anomalie",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="anomaliaactionlog",
            index=models.Index(fields=["anomalia_id", "created_at"], name="anomalia_log_id_date_idx"),
        ),
    ]
