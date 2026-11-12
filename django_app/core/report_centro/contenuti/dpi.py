from core.report_centro.catalogo import LAYOUT_CORE_PDF, LAYOUT_DATI, LAYOUT_EXCEL, voce

MODULO = "dpi"
ETICHETTA = "DPI"

VOCI = [
    voce("conformita_persone", "Conformità DPI delle persone",
         "Chi ha i DPI dovuti e chi no, con esito e cosa sistemare per ogni persona; estrazione Excel e PDF.",
         ("html", "xlsx", "pdf"), route="dpi:report_persone", pagina="dpi:report_persone",
         dati_personali=True, layout=LAYOUT_CORE_PDF,
         pianificabile=(("da_sistemare", "Persone da sistemare (Excel)", "dpi:report_persone", {"esito": "da_sistemare", "export": "xlsx"}),)),
    voce("registro_consegne", "Registro consegne DPI",
         "Consegne del periodo con persona, DPI, ricevuta e scadenza; estrazione Excel e PDF.",
         ("html", "xlsx", "pdf"), route="dpi:report_consegne", pagina="dpi:report_consegne",
         dati_personali=True, layout=LAYOUT_CORE_PDF,
         pianificabile=(("ultimi_90", "Ultimi 90 giorni (Excel)", "dpi:report_consegne", {"export": "xlsx"}),)),
    voce("conformita", "Conformità DPI di una persona",
         "I DPI dovuti a una persona con stato, ultima consegna e scadenza; estrazione Excel.",
         ("html", "xlsx"), route="dpi:report_conformita", pagina="dpi:report_conformita",
         dati_personali=True, layout=LAYOUT_EXCEL),
    voce("magazzino", "Magazzino DPI",
         "Giacenze e movimenti del magazzino DPI, con estrazione CSV.",
         ("html", "csv"), route="dpi:magazzino_report", pagina="dpi:magazzino_report", layout=LAYOUT_DATI),
]
