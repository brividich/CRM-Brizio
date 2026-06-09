# Migrazione manuale (l'ambiente dev punta a SQL Server, makemigrations richiede connessione):
# nuova tabella debounce + nuovo operatore condizione cooldown_group.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('automazioni', '0017_automationrule_exclusion_group_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='AutomationCooldownGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('group_key', models.CharField(db_index=True, max_length=120)),
                ('group_value', models.CharField(db_index=True, max_length=255)),
                ('last_fired_at', models.DateTimeField(db_index=True)),
            ],
            options={
                'db_table': 'automazioni_cooldowngroup',
                'unique_together': {('group_key', 'group_value')},
            },
        ),
        migrations.AddIndex(
            model_name='automationcooldowngroup',
            index=models.Index(fields=['group_key', 'last_fired_at'], name='autom_cdg_key_time_idx'),
        ),
        migrations.AlterField(
            model_name='automationcondition',
            name='operator',
            field=models.CharField(choices=[('equals', 'Equals'), ('not_equals', 'Not equals'), ('contains', 'Contains'), ('startswith', 'Starts with'), ('endswith', 'Ends with'), ('gt', 'Greater than'), ('gte', 'Greater than or equal'), ('lt', 'Less than'), ('lte', 'Less than or equal'), ('is_true', 'Is true'), ('is_false', 'Is false'), ('in_csv', 'In CSV'), ('not_in_csv', 'Not in CSV'), ('is_empty', 'Is empty'), ('is_not_empty', 'Is not empty'), ('changed', 'Changed'), ('changed_to', 'Changed to'), ('changed_from_to', 'Changed from to'), ('days_from_now_lte', 'Days from now ≤'), ('days_from_now_gte', 'Days from now ≥'), ('days_span_gt', 'Days span >'), ('days_span_gte', 'Days span ≥'), ('cooldown_group', 'Cooldown per gruppo (debounce)')], max_length=30),
        ),
    ]
