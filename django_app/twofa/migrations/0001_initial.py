import django.db.models.deletion
import django.utils.timezone
import twofa.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TwoFactorPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=False)),
                ("required_role_ids", models.JSONField(blank=True, default=list)),
                (
                    "when_required",
                    models.CharField(
                        choices=[("always", "Sempre (interno + esterno)"), ("external_only", "Solo da rete esterna")],
                        default="external_only",
                        max_length=20,
                    ),
                ),
                ("internal_networks", models.JSONField(blank=True, default=list)),
                ("allowed_methods", models.JSONField(default=twofa.models._default_allowed_methods)),
                ("session_validity_seconds", models.IntegerField(default=28800)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"verbose_name": "Policy 2FA"},
        ),
        migrations.CreateModel(
            name="UserTwoFactor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "method",
                    models.CharField(
                        choices=[("totp", "App Authenticator (TOTP)"), ("email", "Email")],
                        default="email",
                        max_length=10,
                    ),
                ),
                ("totp_secret_enc", models.CharField(blank=True, max_length=256)),
                ("totp_confirmed", models.BooleanField(default=False)),
                ("email_override", models.EmailField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("force_setup", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="twofa",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"verbose_name": "2FA utente", "verbose_name_plural": "2FA utenti"},
        ),
        migrations.CreateModel(
            name="TwoFactorChallenge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code_hash", models.CharField(max_length=64)),
                ("expires_at", models.DateTimeField()),
                ("used", models.BooleanField(default=False)),
                ("attempts", models.IntegerField(default=0)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="twofa_challenges",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"verbose_name": "Challenge 2FA"},
        ),
    ]
