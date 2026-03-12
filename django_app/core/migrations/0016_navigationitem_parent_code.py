from django.db import migrations


class Migration(migrations.Migration):
    """
    Migrazione placeholder: il campo parent_code e' gia' stato aggiunto
    dalla 0014_navigationitem_parent_code. Questa voce esiste per mantenere
    la catena di dipendenze con le migrazioni successive.
    """

    dependencies = [
        ("core", "0015_siteconfig"),
    ]

    operations = []
