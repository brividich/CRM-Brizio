from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("diario_preposto", "0003_alter_diarioprepostoimpostazioni_acl_scrittura"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="diarioprepostoimpostazioni",
            constraint=models.CheckConstraint(
                check=models.Q(pk=1),
                name="diarioprepostoimpostazioni_singleton",
            ),
        ),
    ]
