from django.db import migrations

TIPI = (
    ("Programmazione CAM", "programmazione-cam", "CAM", "Richiede il programma CAM."),
    ("Programmazione CMM", "programmazione-cmm", "CMM", "Richiede il programma CMM."),
    ("Esecuzione FAI", "esecuzione-fai", "FAI", "Richiede la scheda FAI."),
)


def seed(apps, schema_editor):
    Categoria = apps.get_model("tasks", "TaskCategory")
    # I nuovi tipi ereditano il ruolo dedicato della «Programmazione» già in uso.
    generica = Categoria.objects.filter(name__iexact="Programmazione").first()
    for nome, slug, kind, descrizione in TIPI:
        esistente = Categoria.objects.filter(name__iexact=nome).first() or Categoria.objects.filter(slug=slug).first()
        if esistente:
            if not esistente.richiede:
                esistente.richiede = kind
                esistente.save(update_fields=["richiede"])
            continue
        Categoria.objects.create(
            name=nome, slug=slug, richiede=kind, description=descrizione,
            role_type=generica.role_type if generica and kind != "FAI" else "",
            order_index=generica.order_index if generica else 0,
        )


class Migration(migrations.Migration):
    dependencies = [("tasks", "0055_attivita_programma")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
