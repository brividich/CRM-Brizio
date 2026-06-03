from django.db import migrations, models


def seed_caporeparto_role(apps, schema_editor):
    TaskRoleDefinition = apps.get_model("tasks", "TaskRoleDefinition")
    TaskRoleDefinition.objects.update_or_create(
        code="CR",
        defaults={
            "name": "Caporeparto",
            "description": "Caporeparto di reparto. In modalità anagrafica viene derivato automaticamente dai Reparti.",
            "is_system": True,
            "is_active": True,
            "order_index": 25,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0030_taskdependency'),
    ]

    operations = [
        migrations.AddField(
            model_name='taskimpostazioni',
            name='roles_source',
            field=models.CharField(
                choices=[('anagrafica', 'Da anagrafica (Reparti)'), ('manual', 'Manuale')],
                default='anagrafica',
                help_text=(
                    'Anagrafica: i Caporeparto sono derivati automaticamente dai Reparti '
                    'e usati come candidati nel campo Capocommessa dei kickoff. '
                    'Manuale: le assegnazioni CR e CC vengono gestite dalla tabella sotto.'
                ),
                max_length=16,
                verbose_name='Fonte ruoli Caporeparto / Capocommessa',
            ),
        ),
        migrations.RunPython(seed_caporeparto_role, migrations.RunPython.noop),
    ]
