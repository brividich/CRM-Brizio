from core.report_centro.catalogo import LAYOUT_EXCEL, voce

MODULO = "visite"
ETICHETTA = "Sorveglianza sanitaria"

VOCI = [
    voce("scadenze", "Scadenze visite mediche",
         "Excel delle visite scadute e in scadenza.",
         "xlsx", route="anagrafica:visite_mediche_export_scadenze", pagina="anagrafica:visite_mediche_dashboard",
         dati_personali=True, layout=LAYOUT_EXCEL),
    voce("copertura", "Copertura sorveglianza sanitaria",
         "Excel della copertura del protocollo sanitario per mansione e persona.",
         "xlsx", route="anagrafica:visite_mediche_export_copertura", pagina="anagrafica:visite_mediche_dashboard",
         dati_personali=True, layout=LAYOUT_EXCEL),
]
