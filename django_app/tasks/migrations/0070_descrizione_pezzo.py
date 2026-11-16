import re

from django.db import migrations, models

# Nomi nati dalla proposta automatica: «KICK-OFF 12» e «Cliente · P/N · KICK-OFF 12».
NOME_AUTOMATICO = re.compile(r"(^|·\s*)kick[\s_-]*off\s*\d*$", re.IGNORECASE)


def _oggetto(cliente, pn, rev):
    # Copia di tasks.models.comporre_oggetto (senza descrizione pezzo, che qui e' vuota).
    pn = (pn or "").strip()
    rev = (rev or "").strip()
    if pn and rev:
        pn = f"{pn} rev. {rev}"
    parti = [(cliente or "").strip(), pn]
    return (" · ".join(p for p in parti if p) or "Kickoff")[:180]


def togli_progressivo(apps, schema_editor):
    """L'oggetto dei kickoff non porta piu' il progressivo «KICK-OFF n».

    Solo i nomi ancora automatici: quelli scritti a mano restano come sono.
    La lettura si chiude prima di scrivere (SQL Server via ODBC, HY010).
    """
    Project = apps.get_model("tasks", "Project")
    righe = list(Project.objects.values_list("pk", "name", "client_name", "part_number", "revisione"))
    for pk, nome, cliente, pn, rev in righe:
        nome = (nome or "").strip()
        if nome and not NOME_AUTOMATICO.search(nome):
            continue
        nuovo = _oggetto(cliente, pn, rev)
        if nuovo != nome:
            Project.objects.filter(pk=pk).update(name=nuovo)


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0069_punto_odg_voci'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='descrizione_pezzo',
            field=models.CharField(blank=True, default='', max_length=180, verbose_name='Descrizione pezzo'),
        ),
        migrations.RunPython(togli_progressivo, migrations.RunPython.noop),
    ]
