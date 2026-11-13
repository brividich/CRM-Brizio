import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('anomalie', '0029_anomalia_incaricato'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AnomaliaActionNota',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('testo', models.TextField()),
                ('user_display', models.CharField(blank=True, default='', max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('log', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='note_margine', to='anomalie.anomaliaactionlog')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Nota sul registro anomalie',
                'verbose_name_plural': 'Note sul registro anomalie',
                'ordering': ['created_at'],
            },
        ),
    ]
