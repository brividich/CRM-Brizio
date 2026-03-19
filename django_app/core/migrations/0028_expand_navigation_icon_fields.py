from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0027_useruipreference_sidebar_footer_actions"),
    ]

    operations = [
        migrations.AlterField(
            model_name="modulecategory",
            name="icon",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Emoji, testo breve o URL immagine (.ico, .png, .svg) mostrato nella sidebar per la categoria.",
                max_length=500,
            ),
        ),
        migrations.AlterField(
            model_name="navigationitem",
            name="icon",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Emoji, testo breve o URL immagine (.ico, .png, .svg) mostrato accanto alla label.",
                max_length=500,
            ),
        ),
    ]
