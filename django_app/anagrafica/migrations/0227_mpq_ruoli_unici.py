"""MOD.128: Qualificato / Addetto / Controllore / Part 145 diventano ruoli del processo.

Per ogni abilitazione i booleani storici diventano ruoli standard (``codice_modulo``)
nel M2M ``ruoli_processo``; un ruolo esistente con lo stesso nome viene adottato.
I booleani restano come copia calcolata. Ritorno: si tolgono i ruoli standard creati.
"""
from django.db import migrations, models

STANDARD = (("QUALIFICATO", "Qualificato", "is_qualificato"), ("ADDETTO", "Addetto", "is_addetto"),
            ("CONTROLLORE", "Controllore", "is_controllore"), ("PART145", "Part 145", "is_part145"))


def _avanti(apps, schema_editor):
    Ab = apps.get_model("anagrafica", "AbilitazioneProcesso")
    Ruolo = apps.get_model("anagrafica", "RuoloProcesso")
    cache = {}
    for ab in Ab.objects.all().iterator():
        for i, (codice, nome, campo) in enumerate(STANDARD):
            if not getattr(ab, campo):
                continue
            chiave = (ab.processo_id, codice)
            if chiave not in cache:
                r = (Ruolo.objects.filter(processo_id=ab.processo_id, codice_modulo=codice).first()
                     or Ruolo.objects.filter(processo_id=ab.processo_id, nome__iexact=nome).first())
                if r is None:
                    r = Ruolo.objects.create(processo_id=ab.processo_id, nome=nome, codice_modulo=codice, ordine=i)
                elif r.codice_modulo != codice:
                    r.codice_modulo = codice
                    r.save(update_fields=["codice_modulo"])
                cache[chiave] = r
            ab.ruoli_processo.add(cache[chiave])


def _indietro(apps, schema_editor):
    Ruolo = apps.get_model("anagrafica", "RuoloProcesso")
    Ruolo.objects.exclude(codice_modulo="").filter(requisiti__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0226_mpq_requisiti_alternativi"),
    ]

    operations = [
        migrations.AddField(
            model_name="ruoloprocesso",
            name="codice_modulo",
            field=models.CharField(blank=True, choices=[
                ("QUALIFICATO", "Qualificato"), ("ADDETTO", "Addetto"),
                ("CONTROLLORE", "Controllore"), ("PART145", "Part 145"),
            ], default="", max_length=16),
        ),
        migrations.RunPython(_avanti, _indietro),
    ]
