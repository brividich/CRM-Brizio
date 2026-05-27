from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anomalie", "0002_anomalielegacyroleaccessrule"),
    ]

    operations = [
        migrations.AddField(
            model_name="anomalieroleaccessrule",
            name="list_scope",
            field=models.CharField(
                choices=[
                    ("ALL", "Tutti gli OP"),
                    ("ASSIGNED", "Solo OP in carico (capocommessa/CAR)"),
                    ("OWN_ANOMALIE", "Solo OP con proprie anomalie create"),
                ],
                default="ALL",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="anomalieuseraccessrule",
            name="list_scope",
            field=models.CharField(
                choices=[
                    ("ALL", "Tutti gli OP"),
                    ("ASSIGNED", "Solo OP in carico (capocommessa/CAR)"),
                    ("OWN_ANOMALIE", "Solo OP con proprie anomalie create"),
                ],
                default="ALL",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="anomalielegacyroleaccessrule",
            name="list_scope",
            field=models.CharField(
                choices=[
                    ("ALL", "Tutti gli OP"),
                    ("ASSIGNED", "Solo OP in carico (capocommessa/CAR)"),
                    ("OWN_ANOMALIE", "Solo OP con proprie anomalie create"),
                ],
                default="ALL",
                max_length=20,
            ),
        ),
    ]
