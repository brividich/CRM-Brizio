from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0043_alter_assetcalendarevent_source_key"),
    ]

    operations = [
        migrations.CreateModel(
            name="SoftwareLicense",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(choices=[("SOFTWARE", "Software"), ("ANTIVIRUS", "Antivirus"), ("OFFICE", "Office")], db_index=True, default="SOFTWARE", max_length=20)),
                ("vendor", models.CharField(blank=True, default="", max_length=120)),
                ("product_name", models.CharField(max_length=200)),
                ("edition", models.CharField(blank=True, default="", max_length=120)),
                ("license_reference", models.CharField(blank=True, default="", max_length=120)),
                ("account_email", models.CharField(blank=True, default="", max_length=200)),
                ("assigned_anagrafica_id", models.IntegerField(blank=True, db_index=True, null=True)),
                ("assigned_legacy_user_id", models.IntegerField(blank=True, db_index=True, null=True)),
                ("assigned_to_display", models.CharField(blank=True, default="", max_length=200)),
                ("assigned_reparto", models.CharField(blank=True, default="", max_length=120)),
                ("seats_total", models.PositiveIntegerField(blank=True, null=True)),
                ("seats_used", models.PositiveIntegerField(default=1)),
                ("purchase_date", models.DateField(blank=True, null=True)),
                ("renewal_date", models.DateField(blank=True, null=True)),
                ("expiry_date", models.DateField(blank=True, db_index=True, null=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("auto_renew", models.BooleanField(default=False)),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("asset", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="software_licenses", to="assets.asset")),
            ],
            options={
                "verbose_name": "Licenza software",
                "verbose_name_plural": "Licenze software",
                "ordering": ["category", "vendor", "product_name", "id"],
            },
        ),
    ]
