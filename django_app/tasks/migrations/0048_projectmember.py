"""Team del kickoff in una tabella sola: ProjectMember(project, user, role_code).

Travasa i quattro elenchi M2M (project_managers, capi_commessa, programmers,
caporeparti) nelle righe con codice ruolo PM / CC / PRG / CR, poi rimuove i
campi. Reversibile: all'indietro ricrea i campi e rimette ogni riga
nell'elenco del suo ruolo.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

ROLE_FIELDS = (
    ("project_managers", "PM"),
    ("capi_commessa", "CC"),
    ("programmers", "PRG"),
    ("caporeparti", "CR"),
)


def m2m_to_members(apps, schema_editor):
    Project = apps.get_model("tasks", "Project")
    ProjectMember = apps.get_model("tasks", "ProjectMember")
    rows = []
    for field, code in ROLE_FIELDS:
        through = getattr(Project, field).through
        pairs = through.objects.order_by("id").values_list("project_id", "user_id")
        rows.extend(ProjectMember(project_id=pid, user_id=uid, role_code=code) for pid, uid in pairs)
    ProjectMember.objects.bulk_create(rows, batch_size=500)


def members_to_m2m(apps, schema_editor):
    Project = apps.get_model("tasks", "Project")
    ProjectMember = apps.get_model("tasks", "ProjectMember")
    field_by_code = {code: field for field, code in ROLE_FIELDS}
    for field, code in ROLE_FIELDS:
        through = getattr(Project, field).through
        through.objects.bulk_create(
            [
                through(project_id=pid, user_id=uid)
                for pid, uid in ProjectMember.objects.filter(role_code=code)
                .order_by("id")
                .values_list("project_id", "user_id")
            ],
            batch_size=500,
        )
    unknown = ProjectMember.objects.exclude(role_code__in=list(field_by_code)).count()
    if unknown:
        raise RuntimeError(f"{unknown} membri con ruoli senza campo M2M: rollback impossibile senza perdita dati")


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0047_remove_kickoffmeeting_agenda_items"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectMember",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role_code", models.CharField(db_index=True, max_length=32, verbose_name="Ruolo")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="members", to="tasks.project", verbose_name="Kickoff")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="kickoff_memberships", to=settings.AUTH_USER_MODEL, verbose_name="Persona")),
            ],
            options={
                "verbose_name": "Membro del team kickoff",
                "verbose_name_plural": "Team kickoff",
                "ordering": ["project", "role_code", "id"],
                "constraints": [models.UniqueConstraint(fields=("project", "user", "role_code"), name="tasks_projectmember_uniq")],
            },
        ),
        migrations.RunPython(m2m_to_members, members_to_m2m),
        migrations.RemoveField(model_name="project", name="capi_commessa"),
        migrations.RemoveField(model_name="project", name="caporeparti"),
        migrations.RemoveField(model_name="project", name="programmers"),
        migrations.RemoveField(model_name="project", name="project_managers"),
    ]
