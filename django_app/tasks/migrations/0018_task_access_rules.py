from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tasks", "0017_task_categories"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskRoleAccessRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "role_type",
                    models.CharField(
                        choices=[
                            ("PM", "Project manager"),
                            ("CC", "Capocommessa"),
                            ("PRG", "Programmatore"),
                        ],
                        db_index=True,
                        max_length=8,
                        unique=True,
                    ),
                ),
                (
                    "access_level",
                    models.CharField(
                        choices=[
                            ("NONE", "Nessun accesso extra"),
                            ("READ_ALL", "Vede tutto"),
                            ("EDIT_ASSIGNED", "Modifica solo i task assegnati"),
                            ("EDIT_ALL", "Modifica tutto"),
                        ],
                        db_index=True,
                        default="NONE",
                        max_length=20,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Regola accesso ruolo KICK-OFF",
                "verbose_name_plural": "Regole accesso ruoli KICK-OFF",
                "ordering": ["role_type"],
            },
        ),
        migrations.CreateModel(
            name="TaskUserAccessRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "access_level",
                    models.CharField(
                        choices=[
                            ("NONE", "Nessun accesso extra"),
                            ("READ_ALL", "Vede tutto"),
                            ("EDIT_ASSIGNED", "Modifica solo i task assegnati"),
                            ("EDIT_ALL", "Modifica tutto"),
                        ],
                        db_index=True,
                        default="READ_ALL",
                        max_length=20,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="task_access_rule",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Override accesso utente KICK-OFF",
                "verbose_name_plural": "Override accesso utenti KICK-OFF",
                "ordering": ["user__last_name", "user__first_name", "user_id"],
            },
        ),
    ]
