from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0005_alter_categoriaticket_id_alter_ticket_stato_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='data_prevista_risoluzione',
            field=models.DateField(
                blank=True,
                null=True,
                help_text='Data prevista risoluzione (valorizzata quando il ticket è IN_ATTESA)',
            ),
        ),
    ]
