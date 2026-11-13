"""MOD.128: un solo elenco dei requisiti per persona.

I corsi, le visite e i DPI «uguali per tutti» del processo (M2M ``corsi_richiesti``,
``visite_richieste``, ``dpi_richiesti``) diventano righe di «Cosa serve a una
persona» valide per tutti i ruoli, bloccanti, che seguono la validità del corso o
della visita (nessuna frequenza propria): lo stato delle persone non cambia.
I M2M vengono svuotati, così nessuno li legge più. Il ritorno indietro rimette
nei M2M le righe nate qui e le cancella.
"""
from django.db import migrations, models
import django.db.models.deletion

NOTA = "Da «Requisiti del processo» (aggiornamento 0225)."


def _avanti(apps, schema_editor):
    Processo = apps.get_model("anagrafica", "ProcessoQualificato")
    Requisito = apps.get_model("anagrafica", "RequisitoPersona")
    for p in Processo.objects.all():
        ordine = (Requisito.objects.filter(processo=p).aggregate(m=models.Max("ordine"))["m"] or 0)
        for campo, tipo, fk in (("corsi_richiesti", "corso", "corso"),
                                ("visite_richieste", "visita", "tipo_visita"),
                                ("dpi_richiesti", "dpi", "categoria_dpi")):
            for obj in getattr(p, campo).all():
                if Requisito.objects.filter(processo=p, tipo=tipo, **{fk: obj}).exists():
                    continue
                ordine += 1
                Requisito.objects.create(processo=p, tipo=tipo, ricorrenza="RICORRENTE",
                                         frequenza_mesi=None, bloccante=True, attivo=True,
                                         ordine=ordine, note=NOTA, **{fk: obj})
            getattr(p, campo).clear()


def _indietro(apps, schema_editor):
    Requisito = apps.get_model("anagrafica", "RequisitoPersona")
    for r in Requisito.objects.filter(note=NOTA).select_related("processo"):
        if r.tipo == "corso" and r.corso_id:
            r.processo.corsi_richiesti.add(r.corso_id)
        elif r.tipo == "visita" and r.tipo_visita_id:
            r.processo.visite_richieste.add(r.tipo_visita_id)
        elif r.tipo == "dpi" and r.categoria_dpi_id:
            r.processo.dpi_richiesti.add(r.categoria_dpi_id)
        r.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0224_mpq_persone_macchine_qualificate"),
        ("dpi", "0019_consegna_confermata_badge"),
    ]

    operations = [
        migrations.AddField(
            model_name="requisitopersona",
            name="tipo_qualifica",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="requisiti_persona_mpq", to="anagrafica.tipoqualifica"),
        ),
        migrations.AddField(
            model_name="requisitopersona",
            name="categoria_dpi",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="requisiti_persona_mpq", to="dpi.categoriadpi"),
        ),
        migrations.AlterField(
            model_name="requisitopersona",
            name="tipo",
            field=models.CharField(choices=[
                ("corso", "Corso di formazione"), ("visita", "Visita medica"),
                ("qualifica", "Qualifica del catalogo"), ("dpi", "DPI consegnato"),
                ("test_visivo", "Test visivo"), ("esame", "Esame / verifica di competenza"),
                ("esperienza", "Ore di esperienza"), ("affiancamento", "Affiancamento"),
                ("certificato", "Certificato"), ("altro", "Altro"),
            ], default="corso", max_length=16),
        ),
        migrations.RunPython(_avanti, _indietro),
    ]
