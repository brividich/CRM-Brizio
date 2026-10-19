from core.report_centro.catalogo import LAYOUT_DATI, voce

MODULO = "assenze"
ETICHETTA = "Assenze"

VOCI = [
    voce("elenco", "Elenco assenze",
         "CSV delle richieste di assenza, generale o del capo reparto.",
         "csv", route=("assenze_export_csv", "assenze_car_export_csv"), pagina="assenze_menu",
         dati_personali=True, layout=LAYOUT_DATI),
]
