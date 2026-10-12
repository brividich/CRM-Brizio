"""Robustezza visite mediche: vincolo unico, periodicità massima, permesso di modifica.

Prima del vincolo «una visita attiva per persona, tipo e giorno» i doppioni storici
vanno messi da parte SENZA cancellarli (dato sanitario): per ogni gruppo resta
attiva la visita con l'id più alto — quella che lo scadenziario già considera
corrente a parità di data — e le altre vengono segnate come superate, con motivo
e una riga di audit ciascuna. Restano nello storico, nel libretto e con i loro
referti; si ripristinano dalla scheda della visita. Il rollback le riattiva.
"""
from django.core.validators import MaxValueValidator
from django.db import migrations, models
from django.db.models import Count
from django.utils import timezone

MARCATORE = "[0166]"
MOTIVO = (
    MARCATORE + " Doppione della visita #{principale} (stesso dipendente, tipo e data): "
    "messa da parte all'introduzione del vincolo di unicità, nessun dato cancellato."
)


def parcheggia_doppioni(apps, schema_editor):
    VisitaMedica = apps.get_model("anagrafica", "VisitaMedica")
    AuditLog = apps.get_model("core", "AuditLog")
    attive = VisitaMedica.objects.filter(superata_il__isnull=True)
    gruppi = (
        attive.values("legacy_anagrafica_id", "tipo_id", "data_svolgimento")
        .annotate(n=Count("id")).filter(n__gt=1).order_by()
    )
    adesso = timezone.now()
    parcheggiate = 0
    for g in gruppi:
        ids = list(
            attive.filter(
                legacy_anagrafica_id=g["legacy_anagrafica_id"], tipo_id=g["tipo_id"],
                data_svolgimento=g["data_svolgimento"],
            ).order_by("-pk").values_list("pk", flat=True)
        )
        principale, doppioni = ids[0], ids[1:]
        for pk in doppioni:
            # update(): niente save(), che ricalcolerebbe scadenze e requisiti.
            VisitaMedica.objects.filter(pk=pk).update(
                superata_il=adesso, superata_motivo=MOTIVO.format(principale=principale),
            )
            AuditLog.objects.create(
                utente_display="migrazione anagrafica 0166",
                azione="VISITA_MEDICA_DOPPIONE_SUPERATO",
                modulo="anagrafica",
                dettaglio={
                    "visita_id": pk,
                    "visita_principale_id": principale,
                    "dipendente_id": g["legacy_anagrafica_id"],
                    "tipo_visita_id": g["tipo_id"],
                    "data_svolgimento": g["data_svolgimento"].isoformat(),
                },
                oggetto_tipo="anagrafica.visitamedica",
                oggetto_id=str(pk),
            )
            parcheggiate += 1
    if parcheggiate:
        print(f"\n  anagrafica 0166: {parcheggiate} visite doppie segnate come superate (audit "
              f"VISITA_MEDICA_DOPPIONE_SUPERATO).")


def ripristina_doppioni(apps, schema_editor):
    VisitaMedica = apps.get_model("anagrafica", "VisitaMedica")
    VisitaMedica.objects.filter(superata_motivo__startswith=MARCATORE).update(
        superata_il=None, superata_da=None, superata_motivo="",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("anagrafica", "0165_formazione_integrita_mod040"),
        ("core", "0075_notifica_archivio"),
    ]

    operations = [
        migrations.RunPython(parcheggia_doppioni, ripristina_doppioni),
        migrations.AddConstraint(
            model_name="visitamedica",
            constraint=models.UniqueConstraint(
                condition=models.Q(superata_il__isnull=True),
                fields=("legacy_anagrafica_id", "tipo", "data_svolgimento"),
                name="uniq_visita_medica_persona_tipo_data",
            ),
        ),
        migrations.AlterField(
            model_name="tipovisitamedica",
            name="durata_mesi",
            field=models.PositiveSmallIntegerField(
                default=12,
                help_text="Periodicità in mesi: la scadenza parte dalla data dell'ultima visita "
                          "(0 = nessuna scadenza, massimo 120).",
                validators=[MaxValueValidator(120)],
            ),
        ),
        migrations.AddField(
            model_name="anagraficavisitemedichepermission",
            name="richiedi_permesso_modifica",
            field=models.BooleanField(
                default=False,
                help_text="Se attivo, registrare, modificare o superare una visita richiede il "
                          "permesso canonico «Anagrafica - Modifica visite mediche»; chi ha solo "
                          "l'accesso alle visite le consulta in sola lettura. Spento = chi vede "
                          "le visite può anche registrarle (comportamento storico).",
            ),
        ),
    ]
