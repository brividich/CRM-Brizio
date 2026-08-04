"""Vincoli di integrità su evento e voce (additiva, nessun dato modificato).

- ``co_evento_data_fine_gte_data_inizio``: un evento non può finire prima di
  cominciare. Fino a qui la regola viveva solo (e in modo incompleto) nella UI.
- ``co_voce_unica_per_evento_e_template``: indice **filtrato** su
  ``(evento, template)`` con ``template IS NOT NULL``. Il filtro serve due volte:
  tiene fuori le voci aggiunte a mano (template NULL) e aggira il fatto che su
  SQL Server un indice unique considera uguali fra loro tutti i NULL.

Entrambi sono supportati da SQL Server (``CHECK`` di tabella e indice unique
filtrato, ``supports_partial_indexes`` in mssql-django). Prima di crearli si
verificano i dati esistenti: meglio un errore leggibile in fase di migrate che
un errore di indice del driver.
"""
from django.conf import settings
from django.db import migrations, models


def _verifica_dati_esistenti(apps, schema_editor):
    from django.db.models import Count, F

    ChiusuraEvento = apps.get_model("checklist_operativa", "ChiusuraEvento")
    ChiusuraVoce = apps.get_model("checklist_operativa", "ChiusuraVoce")

    date_incoerenti = list(
        ChiusuraEvento.objects.filter(data_fine__isnull=False, data_fine__lt=F("data_inizio"))
        .values_list("pk", flat=True)
    )
    if date_incoerenti:
        raise RuntimeError(
            "checklist_operativa: eventi con data_fine precedente a data_inizio "
            f"(id: {date_incoerenti}). Correggi le date prima di applicare i vincoli."
        )

    duplicati = list(
        ChiusuraVoce.objects.filter(template__isnull=False)
        .values("evento_id", "template_id")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .order_by()
    )
    if duplicati:
        raise RuntimeError(
            "checklist_operativa: stesso template presente più volte nello stesso evento "
            f"({duplicati}). Elimina le voci duplicate prima di applicare i vincoli."
        )


class Migration(migrations.Migration):

    dependencies = [
        ('checklist_operativa', '0003_seed_navigation'),
        ('core', '0070_ofi_registro_toplevel_nav'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(_verifica_dati_esistenti, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='chiusuraevento',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ('data_fine__isnull', True),
                    ('data_fine__gte', models.F('data_inizio')),
                    _connector='OR',
                ),
                name='co_evento_data_fine_gte_data_inizio',
            ),
        ),
        migrations.AddConstraint(
            model_name='chiusuravoce',
            constraint=models.UniqueConstraint(
                condition=models.Q(('template__isnull', False)),
                fields=('evento', 'template'),
                name='co_voce_unica_per_evento_e_template',
            ),
        ),
    ]
