"""Ambiti dei ruoli: un ruolo per ogni organigramma, senza sostituzioni.

Crea il catalogo degli ambiti, aggiunge ``RuoloOperativo.ambito`` e semina i
quattro ambiti di partenza. **Nessun ruolo esistente viene classificato**: un
ruolo senza ambito continua a comportarsi come prima (concorre al «Ruolo
aziendale» della scheda), e la classificazione la fa una persona dal portale,
perché distinguere produttivo da esecutivo è una decisione organizzativa, non
un'inferenza.
"""

import django.db.models.deletion
from django.db import migrations, models


# nome, icona, colore, ordine, alimenta_scheda, descrizione
AMBITI = [
    ("Produttivo", "🏭", "#1f87cd", 10, True,
     "Assetto organizzativo dell'officina e della produzione: è il ruolo che compare nella scheda dipendente."),
    ("Esecutivo", "🏢", "#7c3aed", 20, False,
     "Ruoli direttivi e di funzione (amministrazione, commerciale, tecnico)."),
    ("Sicurezza ISO 45001", "🦺", "#ea580c", 30, False,
     "Organigramma della sicurezza sul lavoro: datore di lavoro, RSPP, preposti, addetti alle emergenze."),
    ("Sicurezza informazioni ISO 27001", "🔐", "#0f766e", 40, False,
     "Organigramma del sistema di gestione della sicurezza delle informazioni."),
]


def semina_ambiti(apps, schema_editor):
    AmbitoRuolo = apps.get_model("anagrafica", "AmbitoRuolo")
    for nome, icona, colore, ordine, alimenta, descrizione in AMBITI:
        AmbitoRuolo.objects.get_or_create(
            nome=nome,
            defaults={
                "icona": icona,
                "colore": colore,
                "ordine": ordine,
                "alimenta_scheda": alimenta,
                "descrizione": descrizione,
            },
        )
    # Uno solo alimenta la scheda: se l'installazione ne avesse già uno proprio
    # (ri-esecuzione, dati preesistenti) si tiene il più vecchio e si spengono
    # gli altri, senza mai lasciarne zero.
    marcati = list(AmbitoRuolo.objects.filter(alimenta_scheda=True).order_by("pk"))
    if len(marcati) > 1:
        AmbitoRuolo.objects.filter(
            pk__in=[a.pk for a in marcati[1:]]
        ).update(alimenta_scheda=False)


class Migration(migrations.Migration):

    dependencies = [
        ('anagrafica', '0111_ruoli_date_tipologia_e_qualifiche'),
    ]

    operations = [
        migrations.CreateModel(
            name='AmbitoRuolo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=100, unique=True)),
                ('descrizione', models.TextField(blank=True, default='')),
                ('colore', models.CharField(default='#64748b', help_text='Colore esadecimale es. #1d4ed8', max_length=7)),
                ('icona', models.CharField(blank=True, default='', help_text='Emoji o testo breve', max_length=10)),
                ('ordine', models.IntegerField(default=100, help_text='Ordine di presentazione (crescente).')),
                ('alimenta_scheda', models.BooleanField(default=False, help_text="Solo un ambito può alimentarlo: è quello dell'assetto organizzativo vero e proprio. I ruoli degli altri ambiti si sovrappongono senza sostituire il ruolo principale.", verbose_name='Alimenta il «Ruolo aziendale» della scheda')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Ambito del ruolo',
                'verbose_name_plural': 'Ambiti dei ruoli',
                'ordering': ['ordine', 'nome'],
            },
        ),
        migrations.AddField(
            model_name='ruolooperativo',
            name='ambito',
            field=models.ForeignKey(blank=True, help_text='Organigramma di appartenenza. Vuoto = assetto organizzativo principale.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ruoli', to='anagrafica.ambitoruolo', verbose_name='Ambito'),
        ),
        migrations.RunPython(semina_ambiti, migrations.RunPython.noop),
    ]
