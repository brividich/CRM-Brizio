from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("security", "0016_security_cases_gestione"),
    ]

    operations = [
        migrations.AddField(
            model_name="securitymailboxsource",
            name="folders",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
