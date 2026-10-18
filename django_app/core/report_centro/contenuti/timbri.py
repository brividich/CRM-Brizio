from core.report_centro.catalogo import LAYOUT_DATI, LAYOUT_STAMPA, voce

MODULO = "timbri"
ETICHETTA = "Timbri"

VOCI = [
    voce("operatore", "Report operatore",
         "Riepilogo dei timbri di un operatore, da stampare.",
         "html", pagina="timbri:index", dati_personali=True, layout=LAYOUT_STAMPA),
    voce("elenco", "Esportazione timbri",
         "CSV dei timbri registrati.",
         "csv", route="timbri:export_csv", pagina="timbri:index", dati_personali=True, layout=LAYOUT_DATI),
]
