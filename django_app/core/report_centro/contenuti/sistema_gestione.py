from core.report_centro.catalogo import LAYOUT_CORE_PDF, LAYOUT_EXCEL, voce

MODULO = "sistema_gestione"
ETICHETTA = "Sistema di gestione"

VOCI = [
    voce("audit", "Documenti di audit",
         "Piano, rapporto e verbale dell'audit, e versioni archiviate.",
         "pdf", route=("sistema_gestione:audit_export", "sistema_gestione:audit_versione_download"),
         pagina="sistema_gestione:audit_index", layout=LAYOUT_CORE_PDF, norma="ISO 19011"),
    voce("programma", "Programma di audit",
         "PDF del programma annuale degli audit.",
         "pdf", route="sistema_gestione:programma_export_pdf", pagina="sistema_gestione:audit_index",
         layout=LAYOUT_CORE_PDF),
    voce("rilievi", "Rilievi di audit",
         "Excel dei rilievi aperti e chiusi.",
         "xlsx", route="sistema_gestione:audit_rilievi_export", pagina="sistema_gestione:audit_index",
         layout=LAYOUT_EXCEL,
         pianificabile=(("tutti", "Tutti i rilievi", "sistema_gestione:audit_rilievi_export", {}),)),
]
