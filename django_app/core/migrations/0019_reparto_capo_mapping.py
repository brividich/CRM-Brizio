from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_merge_0016_navigationitem_parent_code_0017_loginbanner"),
    ]

    operations = [
        migrations.CreateModel(
            name="RepartoCapoMapping",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reparto",     models.CharField(db_index=True, max_length=200)),
                ("caporeparto", models.CharField(max_length=200)),
                ("is_active",   models.BooleanField(default=True)),
                ("created_at",  models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["reparto"],
                "verbose_name": "Associazione reparto → capo reparto",
                "verbose_name_plural": "Associazioni reparto → capo reparto",
            },
        ),
        migrations.AlterUniqueTogether(
            name="repartocapomapping",
            unique_together={("reparto", "caporeparto")},
        ),
    ]
