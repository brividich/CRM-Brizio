"""Spunta «Crea sezione dedicata» sui processi qualificati (MOD.128).

Campi: spunta, sigla, titolo, dove compare. La pagina P11TF12 (migrazioni 0232 e
assets 0172) diventa il primo caso: i processi con «P11TF12» nel nome o fra i
riferimenti prendono la spunta, le due voci di menu fisse lasciano il posto a
quelle create dalla sezione.
"""
from django.db import migrations, models
from django.db.models import Q


def converti(apps, schema_editor):
    from anagrafica.services.mpq_sezioni import sincronizza_menu

    Processo = apps.get_model("anagrafica", "ProcessoQualificato")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    Bottone = apps.get_model("assets", "AssetSidebarButton")
    for p in (Processo.objects.filter(Q(nome__icontains="P11TF12") | Q(riferimenti__codice__icontains="P11TF12"))
              .distinct()):
        p.sezione_dedicata = True
        p.sezione_sigla = "P11TF12"
        p.sezione_titolo = p.sezione_titolo or "Foratura su particolari critici"
        p.save(update_fields=["sezione_dedicata", "sezione_sigla", "sezione_titolo"])
    Link.objects.filter(url_value="anagrafica:mpq_p11tf12").delete()
    Bottone.objects.filter(code="p11tf12").delete()
    sincronizza_menu(Processo=Processo, Link=Link, Bottone=Bottone)


def togli(apps, schema_editor):
    from anagrafica.services.mpq_sezioni import CODICE_BOTTONE, url_qualifiche

    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(
        url_value__startswith=url_qualifiche("X")[:-2]).delete()
    apps.get_model("assets", "AssetSidebarButton").objects.filter(code__startswith=CODICE_BOTTONE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0235_richieste_in_organizzazione"),
        ("assets", "0172_voce_p11tf12"),
    ]

    operations = [
        migrations.AddField(
            model_name="processoqualificato",
            name="sezione_dedicata",
            field=models.BooleanField(
                default=False, verbose_name="Crea sezione dedicata",
                help_text="Togliendo la spunta sparisce la voce di menu, i dati restano."),
        ),
        migrations.AddField(
            model_name="processoqualificato",
            name="sezione_sigla",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=30, verbose_name="Sigla della sezione",
                help_text="Es. P11TF12: è il nome della voce di menu e finisce nell'indirizzo. Più processi con la "
                          "stessa sigla (es. un processo per cliente) finiscono nella stessa pagina."),
        ),
        migrations.AddField(
            model_name="processoqualificato",
            name="sezione_titolo",
            field=models.CharField(blank=True, default="", max_length=120, verbose_name="Titolo della pagina",
                                   help_text="Es. «Foratura su particolari critici»."),
        ),
        migrations.AddField(
            model_name="processoqualificato",
            name="sezione_dove",
            field=models.CharField(
                choices=[("ENTRAMBE", "Qualifiche e Asset"), ("QUALIFICHE", "Solo Qualifiche (persone)"),
                         ("ASSET", "Solo Asset (macchine)")],
                default="ENTRAMBE", max_length=10, verbose_name="Dove compare"),
        ),
        migrations.RunPython(converti, togli),
    ]
