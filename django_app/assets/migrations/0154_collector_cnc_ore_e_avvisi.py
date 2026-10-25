from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0153_macrete'),
    ]

    operations = [
        migrations.AddField(
            model_name='collegamentomtconnect',
            name='unita_ore',
            field=models.CharField(blank=True, choices=[('', 'Automatica (dal modello dati)'), ('h', 'Ore'), ('min', 'Minuti'), ('s', 'Secondi')], default='', max_length=3),
        ),
        migrations.AddField(
            model_name='collegamentomtconnect',
            name='matricola_opcua',
            field=models.CharField(blank=True, default='', max_length=60),
        ),
        migrations.AddField(
            model_name='collegamentomtconnect',
            name='modello_dati',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='collegamentomtconnect',
            name='avviso_ore_ogni',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='collegamentomtconnect',
            name='avviso_ore_da',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name='collegamentomtconnect',
            name='avviso_ore_testo',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
    ]
