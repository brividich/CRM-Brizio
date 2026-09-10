from django.conf import settings
from django.db import migrations, models


def copy_team_to_m2m(apps, schema_editor):
    """Travasa i tre referenti singoli nei nuovi elenchi multipli."""
    Project = apps.get_model("tasks", "Project")
    pairs = (
        ("project_manager_id", "project_managers"),
        ("capo_commessa_id", "capi_commessa"),
        ("programmer_id", "programmers"),
    )
    for project in Project.objects.all().iterator():
        for fk_name, m2m_name in pairs:
            user_id = getattr(project, fk_name, None)
            if user_id:
                getattr(project, m2m_name).add(user_id)


def copy_team_back(apps, schema_editor):
    """Reverse: riporta nel campo singolo il primo referente di ogni ruolo."""
    Project = apps.get_model("tasks", "Project")
    pairs = (
        ("project_manager_id", "project_managers"),
        ("capo_commessa_id", "capi_commessa"),
        ("programmer_id", "programmers"),
    )
    for project in Project.objects.all().iterator():
        changed = False
        for fk_name, m2m_name in pairs:
            first = getattr(project, m2m_name).order_by("id").first()
            if first is not None:
                setattr(project, fk_name, first.id)
                changed = True
        if changed:
            project.save(update_fields=[fk for fk, _ in pairs])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tasks", "0041_meetingagendaproposal"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="project_managers",
            field=models.ManyToManyField(blank=True, related_name="projects_as_pm", to=settings.AUTH_USER_MODEL, verbose_name="Project manager"),
        ),
        migrations.AddField(
            model_name="project",
            name="capi_commessa",
            field=models.ManyToManyField(blank=True, related_name="projects_as_cc", to=settings.AUTH_USER_MODEL, verbose_name="Capocommessa"),
        ),
        migrations.AddField(
            model_name="project",
            name="programmers",
            field=models.ManyToManyField(blank=True, related_name="projects_as_prg", to=settings.AUTH_USER_MODEL, verbose_name="Programmatore"),
        ),
        migrations.AddField(
            model_name="project",
            name="caporeparti",
            field=models.ManyToManyField(blank=True, related_name="projects_as_cr", to=settings.AUTH_USER_MODEL, verbose_name="Caporeparto"),
        ),
        migrations.RunPython(copy_team_to_m2m, copy_team_back),
        migrations.RemoveField(model_name="project", name="project_manager"),
        migrations.RemoveField(model_name="project", name="capo_commessa"),
        migrations.RemoveField(model_name="project", name="programmer"),
    ]
