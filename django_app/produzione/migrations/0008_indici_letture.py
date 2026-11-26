from django.db import migrations, models


class Migration(migrations.Migration):
    """Indici delle letture di Ordini di produzione (misurati in produzione il 26/11/2026).

    Via: «pn» da solo, «programma_base», «escluso» (booleano, mai usato in ricerca) e «chiave» delle misure (164 MB,
    nessuna ricerca, 99% frammentato). Al loro posto due indici di copertura su ReportCMM: (pn, programma_base) e
    (data), con le colonne che le pagine leggono."""

    dependencies = [("produzione", "0007_articolo_analisi")]

    operations = [
        migrations.RemoveIndex(model_name="reportcmm", name="prod_rcmm_pn_prog"),
        migrations.AlterField(model_name="reportcmm", name="pn", field=models.CharField(max_length=100, verbose_name="P/N")),
        migrations.AlterField(model_name="reportcmm", name="programma_base",
                              field=models.CharField(blank=True, default="", max_length=200, verbose_name="Programma senza revisione")),
        migrations.AlterField(model_name="reportcmm", name="escluso", field=models.BooleanField(default=False)),
        migrations.AlterField(model_name="misuracmm", name="chiave", field=models.CharField(max_length=200)),
        migrations.AddIndex(model_name="reportcmm", index=models.Index(
            fields=["pn", "programma_base"], include=["righe", "escluso", "data", "fuori", "seriale", "op", "letto_il", "escluso_il"], name="prod_rcmm_pn_prog_cop")),
        migrations.AddIndex(model_name="reportcmm", index=models.Index(
            fields=["data"], include=["pn", "righe", "escluso", "fuori"], name="prod_rcmm_data")),
    ]
