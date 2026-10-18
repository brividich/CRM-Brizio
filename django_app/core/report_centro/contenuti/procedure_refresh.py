from core.report_centro.catalogo import LAYOUT_DATI, LAYOUT_STAMPA, voce

MODULO = "procedure_refresh"
ETICHETTA = "Procedure (presa visione)"

VOCI = [
    voce("report", "Report prese visione",
         "Per utente, per documento, per campagna e matrice complessiva.",
         "html", pagina="procedure_refresh:report_matrix", dati_personali=True, layout=LAYOUT_STAMPA),
    voce("export", "Esportazione prese visione",
         "CSV delle assegnazioni e delle conferme di lettura.",
         "csv", route="procedure_refresh:export_csv", pagina="procedure_refresh:admin_dashboard",
         dati_personali=True, layout=LAYOUT_DATI),
]
