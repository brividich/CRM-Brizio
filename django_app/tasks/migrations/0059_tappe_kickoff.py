from django.db import migrations, models

# (tappa, nome, slug, descrizione, lavoro macchina)
NUOVI = (
    ("MATERIALI", "Arrivo materiali", "arrivo-materiali", "Materiale per la commessa in casa entro la data.", False),
    ("MACCHINA", "Scelta macchina", "scelta-macchina", "Macchina su cui gira la commessa: abilitati, assenze e manutenzione.", True),
    ("TERZISTA", "Lavorazione terzista", "lavorazione-terzista", "Lavorazione esterna: fornitore e rientro.", False),
    ("PROCESSI", "Processi speciali", "processi-speciali", "Processo speciale qualificato richiesto dalla commessa.", False),
)
ESISTENTI = (("CAM", "programmazione-cam"), ("CMM", "programmazione-cmm"), ("FAI", "esecuzione-fai"))
CAMPI = {
    "MACCHINA": ("macchina", "Macchina", "asset", "CNC,WORK_MACHINE"),
    "TERZISTA": ("fornitore", "Fornitore", "text", ""),
    "PROCESSI": ("processo", "Processo", "text", ""),
}


def seed(apps, schema_editor):
    Categoria = apps.get_model("tasks", "TaskCategory")
    Campo = apps.get_model("tasks", "TaskCategoryField")
    for tappa, slug in ESISTENTI:
        Categoria.objects.filter(slug=slug, tappa="").update(tappa=tappa)
    for tappa, nome, slug, descrizione, macchina in NUOVI:
        if Categoria.objects.filter(tappa=tappa).exists():
            continue
        cat = Categoria.objects.filter(slug=slug).first() or Categoria.objects.filter(name__iexact=nome).first()
        if cat is None:
            cat = Categoria.objects.create(name=nome, slug=slug, description=descrizione, is_machine_work=macchina)
        cat.tappa = tappa
        cat.save(update_fields=["tappa"])
        if tappa in CAMPI:
            code, label, tipo, filtro = CAMPI[tappa]
            if not Campo.objects.filter(category=cat, code=code).exists():
                Campo.objects.create(
                    category=cat, code=code, label=label, field_type=tipo, asset_type_filter=filtro, order_index=1,
                )


class Migration(migrations.Migration):
    dependencies = [("tasks", "0058_fai_voci_situazione")]
    operations = [
        migrations.AddField(
            model_name="project",
            name="tappe_escluse",
            field=models.JSONField(blank=True, default=list, verbose_name="Tappe che non servono"),
        ),
        migrations.AddField(
            model_name="taskcategory",
            name="tappa",
            field=models.CharField(
                blank=True, choices=[
                    ("MATERIALI", "Arrivo materiali"), ("CAM", "Programma CAM"), ("CMM", "Programma CMM"),
                    ("MACCHINA", "Macchina"), ("TERZISTA", "Terzista"), ("PROCESSI", "Processi speciali"), ("FAI", "FAI"),
                ], db_index=True, default="", help_text="Attività base del percorso del kickoff che questo tipo rappresenta.",
                max_length=10, verbose_name="Tappa del kickoff",
            ),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
