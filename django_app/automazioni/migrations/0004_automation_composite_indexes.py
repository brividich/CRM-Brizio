from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("automazioni", "0003_alter_automationaction_action_type"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="automationrunlog",
            index=models.Index(fields=["rule", "status"], name="automrunlog_rule_status_idx"),
        ),
        migrations.AddIndex(
            model_name="automationrunlog",
            index=models.Index(fields=["source_code", "operation_type"], name="automrunlog_src_optype_idx"),
        ),
        migrations.AddIndex(
            model_name="automationactionlog",
            index=models.Index(fields=["run_log", "status"], name="automactionlog_run_status_idx"),
        ),
    ]
