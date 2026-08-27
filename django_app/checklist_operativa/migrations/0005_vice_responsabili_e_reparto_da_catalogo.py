"""Vice responsabili (più di uno) e reparto preso dal catalogo anagrafica.

Due cambi indipendenti, in una sola migrazione perché toccano la stessa
mansione di template:

* ``vice_responsabili`` — M2M verso ``core.AnagraficaDipendente`` su template e
  voce. È un M2M e non una seconda FK perché la sostituzione reale è spesso
  condivisa (due colleghi coprono lo stesso reparto a turno).
* ``reparto`` — da testo libero a FK verso ``anagrafica.Reparto``. Il testo
  esistente viene riagganciato per nome (case-insensitive); ciò che non trova
  un reparto in catalogo resta vuoto, e la mansione lo mostra come «—».
  In pratica il campo era vuoto ovunque (il seed da Excel non lo popolava), ma
  il travaso c'è lo stesso: perdere silenziosamente un'etichetta scritta a mano
  sarebbe il modo peggiore di scoprirlo.
"""
from django.db import migrations, models
import django.db.models.deletion


def _reparto_testo_a_catalogo(apps, schema_editor):
    ChecklistTaskTemplate = apps.get_model("checklist_operativa", "ChecklistTaskTemplate")
    Reparto = apps.get_model("anagrafica", "Reparto")

    per_nome = {
        (reparto.nome or "").strip().casefold(): reparto.pk
        for reparto in Reparto.objects.all()
    }
    if not per_nome:
        return

    da_aggiornare = []
    for template in ChecklistTaskTemplate.objects.exclude(reparto=""):
        reparto_id = per_nome.get((template.reparto or "").strip().casefold())
        if reparto_id:
            template.reparto_catalogo_id = reparto_id
            da_aggiornare.append(template)
    if da_aggiornare:
        ChecklistTaskTemplate.objects.bulk_update(da_aggiornare, ["reparto_catalogo"])


def _reparto_catalogo_a_testo(apps, schema_editor):
    ChecklistTaskTemplate = apps.get_model("checklist_operativa", "ChecklistTaskTemplate")
    da_aggiornare = []
    for template in ChecklistTaskTemplate.objects.exclude(reparto_catalogo__isnull=True).select_related(
        "reparto_catalogo"
    ):
        template.reparto = template.reparto_catalogo.nome or ""
        da_aggiornare.append(template)
    if da_aggiornare:
        ChecklistTaskTemplate.objects.bulk_update(da_aggiornare, ["reparto"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0070_ofi_registro_toplevel_nav"),
        ("anagrafica", "0113_assegnazione_ruolo_parallelo"),
        ("checklist_operativa", "0004_vincoli_evento_e_voce"),
    ]

    operations = [
        migrations.AddField(
            model_name="checklisttasktemplate",
            name="vice_responsabili",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Sostituti che possono eseguire e confermare la mansione quando il "
                    "responsabile è assente. Se ne possono indicare più di uno."
                ),
                related_name="checklist_task_templates_vice",
                to="core.anagraficadipendente",
                verbose_name="Vice responsabili",
            ),
        ),
        migrations.AddField(
            model_name="chiusuravoce",
            name="vice_responsabili",
            field=models.ManyToManyField(
                blank=True,
                help_text="Chi può confermare al posto del responsabile se è assente.",
                related_name="checklist_voci_vice",
                to="core.anagraficadipendente",
                verbose_name="Vice responsabili",
            ),
        ),
        migrations.AddField(
            model_name="checklisttasktemplate",
            name="reparto_catalogo",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="checklist_task_templates",
                to="anagrafica.reparto",
                verbose_name="Reparto",
            ),
        ),
        migrations.RunPython(_reparto_testo_a_catalogo, _reparto_catalogo_a_testo),
        migrations.RemoveField(model_name="checklisttasktemplate", name="reparto"),
        migrations.RenameField(
            model_name="checklisttasktemplate",
            old_name="reparto_catalogo",
            new_name="reparto",
        ),
    ]
