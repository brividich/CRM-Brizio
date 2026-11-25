"""Project manager e Capocommessa diventano un ruolo solo: «Capocommessa» (CC).

- Team delle commesse: ogni PM diventa CC (chi era già CC resta una riga sola).
- Candidati del ruolo (TaskRoleAssignment): chi era PM compare fra i capocommessa.
- Ruolo di sistema «Project manager» disattivato nel catalogo; regola di accesso PM → CC (se manca quella CC).
- Impostazioni «Poteri e avvisi»: PM sostituito da CC.

Il ritorno indietro non separa più i ruoli (non si sa chi era PM): lascia tutto CC.
"""

from django.db import migrations, models


def _sostituisci(codici: str) -> str:
    visti = []
    for c in (codici or "").split(","):
        c = c.strip().upper()
        if not c:
            continue
        c = "CC" if c == "PM" else c
        if c not in visti:
            visti.append(c)
    return ",".join(visti)


def unisci(apps, schema_editor):
    ProjectMember = apps.get_model("tasks", "ProjectMember")
    TaskRoleAssignment = apps.get_model("tasks", "TaskRoleAssignment")
    TaskRoleDefinition = apps.get_model("tasks", "TaskRoleDefinition")
    TaskImpostazioni = apps.get_model("tasks", "TaskImpostazioni")

    for m in ProjectMember.objects.filter(role_code="PM").order_by("id"):
        if ProjectMember.objects.filter(project_id=m.project_id, user_id=m.user_id, role_code="CC").exists():
            m.delete()
        else:
            m.role_code = "CC"
            m.save(update_fields=["role_code"])

    for a in TaskRoleAssignment.objects.filter(role_type="PM").order_by("id"):
        if TaskRoleAssignment.objects.filter(user_id=a.user_id, role_type="CC").exists():
            a.delete()
        else:
            a.role_type = "CC"
            a.save(update_fields=["role_type"])

    TaskRoleDefinition.objects.filter(code="PM").update(is_active=False)

    # Regole di accesso per ruolo (role_type unico): se c'è già quella del capocommessa vince lei.
    TaskRoleAccessRule = apps.get_model("tasks", "TaskRoleAccessRule")
    if TaskRoleAccessRule.objects.filter(role_type="CC").exists():
        TaskRoleAccessRule.objects.filter(role_type="PM").delete()
    else:
        TaskRoleAccessRule.objects.filter(role_type="PM").update(role_type="CC")

    for cfg in TaskImpostazioni.objects.all():
        cfg.poteri_ruoli = _sostituisci(cfg.poteri_ruoli)
        cfg.avvisi_destinatari = _sostituisci(cfg.avvisi_destinatari)
        cfg.save(update_fields=["poteri_ruoli", "avvisi_destinatari"])


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0074_operazione_periodo_note"),
    ]

    operations = [
        migrations.AlterField(
            model_name="taskimpostazioni",
            name="poteri_ruoli",
            field=models.CharField(
                blank=True, default="CC", help_text="Ruoli del team che modificano tutto sulla commessa, date comprese, senza approvazione.",
                max_length=60, verbose_name="Ruoli con pieni poteri",
            ),
        ),
        migrations.RunPython(unisci, migrations.RunPython.noop),
    ]
