"""Mansionario fase 6 (2/3): il vecchio catalogo ``MansioneRischio`` confluisce in ``Mansione``.

Nulla va perso. Per ogni ``MansioneRischio``:

- si usa la voce del catalogo ``Mansione`` con lo stesso nome, o se ne crea una
  (descrizione, livello DVR, revisione e data DVR, attiva/disattiva);
- visite, categorie DPI e fattori di rischio passano alla voce (fattori come
  ``EsposizioneRischio`` di mansione);
- regole formative, override individuali e origine degli adempimenti di cambio
  mansione puntano alla voce.

Ogni ``MansioneLavorativaRischio`` (mansione → mansione di rischio) porta sulla
mansione collegata anche visite, DPI e fattori della mansione di rischio, così
chi aveva quella mansione resta tenuto agli stessi obblighi.

In produzione (15/10/2026) le tabelle del vecchio catalogo sono vuote: la
migrazione non scrive nulla. Il ritorno indietro non ripristina il vecchio
catalogo (i dati restano sul catalogo ``Mansione``).
"""
from django.db import migrations


def _porta_profilo(apps, mr, mansione):
    Esposizione = apps.get_model("anagrafica", "EsposizioneRischio")
    visite = list(mr.visite.all())
    if visite:
        mansione.visite_richieste.add(*visite)
    dpi = list(mr.categorie_dpi.all())
    if dpi:
        mansione.dpi_richiesti.add(*dpi)
    for fattore in mr.fattori.all():
        if not Esposizione.objects.filter(fattore=fattore, mansione=mansione, area__isnull=True,
                                          legacy_anagrafica_id__isnull=True).exists():
            Esposizione.objects.create(fattore=fattore, mansione=mansione, is_active=True,
                                       note="Da mansione di rischio unificata (migrazione 0175)")


def avanti(apps, schema_editor):
    MansioneRischio = apps.get_model("anagrafica", "MansioneRischio")
    Mansione = apps.get_model("anagrafica", "Mansione")
    Link = apps.get_model("anagrafica", "MansioneLavorativaRischio")
    Override = apps.get_model("anagrafica", "DipendenteMansioneRischioOverride")
    Adempimento = apps.get_model("anagrafica", "AdempimentoCambioMansione")
    Regola = apps.get_model("anagrafica", "TrainingRequirementRule")

    mappa = {}
    for mr in MansioneRischio.objects.all().order_by("pk"):
        nome = ((mr.nome or "").strip() or (mr.codice or "").strip() or f"Mansione di rischio {mr.pk}")[:100]
        mansione = Mansione.objects.filter(nome__iexact=nome).first()
        if mansione is None:
            mansione = Mansione.objects.create(
                nome=nome, descrizione=mr.descrizione or "", livello_rischio=mr.livello_rischio_dvr or "",
                dvr_revisione=mr.dvr_revisione or "", dvr_data=mr.dvr_data, is_active=mr.is_active,
            )
        else:
            campi = []
            for campo, valore in (("descrizione", mr.descrizione), ("dvr_revisione", mr.dvr_revisione),
                                  ("dvr_data", mr.dvr_data), ("livello_rischio", mr.livello_rischio_dvr)):
                if valore and not getattr(mansione, campo):
                    setattr(mansione, campo, valore)
                    campi.append(campo)
            if campi:
                mansione.save(update_fields=campi)
        mappa[mr.pk] = mansione
        _porta_profilo(apps, mr, mansione)

    for link in Link.objects.select_related("mansione_rischio", "mansione"):
        _porta_profilo(apps, link.mansione_rischio, link.mansione)

    for regola in Regola.objects.filter(mansione_rischio__isnull=False):
        destinazione = mappa[regola.mansione_rischio_id]
        if regola.mansione_id is None:
            regola.mansione = destinazione
            regola.save(update_fields=["mansione"])
        elif regola.mansione_id != destinazione.pk:
            # La regola valeva per due bersagli: la copia tiene quello della mansione di rischio.
            regola.pk = None
            regola.mansione = destinazione
            regola.mansione_rischio = None
            regola.save()

    # In 0174 i due riferimenti sono diventati numeri semplici: qui l'id del
    # vecchio catalogo diventa l'id della voce del catalogo Mansione.
    attivi = set()
    for o in Override.objects.all().order_by("-attivo", "pk"):
        destinazione = mappa[o.mansione_rischio]
        o.mansione_rischio = destinazione.pk
        campi = ["mansione_rischio"]
        chiave = (o.legacy_anagrafica_id, destinazione.pk)
        if o.attivo:
            if chiave in attivi:
                # Due override attivi finiti sulla stessa voce: resta il primo, l'altro si chiude con traccia.
                o.attivo = False
                o.revoca_motivo = "Unificato: stessa mansione di rischio di un altro override attivo (migrazione 0175)"
                campi += ["attivo", "revoca_motivo"]
            else:
                attivi.add(chiave)
        o.save(update_fields=campi)

    for a in Adempimento.objects.filter(origine_mansione_rischio__isnull=False):
        destinazione = mappa.get(a.origine_mansione_rischio)
        a.origine_mansione_rischio = destinazione.pk if destinazione else None
        a.save(update_fields=["origine_mansione_rischio"])


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0174_mansioni_rischio_unificate_schema"),
    ]

    operations = [
        migrations.RunPython(avanti, migrations.RunPython.noop),
    ]
