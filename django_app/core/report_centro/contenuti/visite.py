from core.report_centro.catalogo import LAYOUT_EXCEL, voce

MODULO = "visite"
ETICHETTA = "Sorveglianza sanitaria"

VOCI = [
    voce("scadenze", "Scadenze visite mediche",
         "Excel delle visite scadute e in scadenza.",
         "xlsx", route="anagrafica:visite_mediche_export_scadenze", pagina="anagrafica:visite_mediche_dashboard",
         dati_personali=True, layout=LAYOUT_EXCEL,
         pianificabile=(
             ("60gg", "Scadute e in scadenza entro 60 giorni", "anagrafica:visite_mediche_export_scadenze", {"scad": "tutti"}),
             ("mese", "In scadenza nel mese corrente", "anagrafica:visite_mediche_export_scadenze", {"scad": "mese_corrente"}),
             ("prossimo", "In scadenza il mese prossimo", "anagrafica:visite_mediche_export_scadenze", {"scad": "prossimo_mese"}),
         )),
    voce("copertura", "Copertura sorveglianza sanitaria",
         "Excel della copertura del protocollo sanitario per mansione e persona.",
         "xlsx", route="anagrafica:visite_mediche_export_copertura", pagina="anagrafica:visite_mediche_dashboard",
         dati_personali=True, layout=LAYOUT_EXCEL,
         pianificabile=(("tutto", "Copertura completa", "anagrafica:visite_mediche_export_copertura", {}),)),
]
