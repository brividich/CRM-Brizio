from core.report_centro.catalogo import LAYOUT_CORE_PDF, voce

MODULO = "security"
ETICHETTA = "SOC sicurezza informatica"

VOCI = [
    voce("report", "Report periodico SOC",
         "Report di periodo su eventi, vulnerabilità e casi.",
         ("html", "pdf"), route="security:report_pdf", pagina="security:report", layout=LAYOUT_CORE_PDF),
    voce("incidenti", "Registro incidenti",
         "Registro degli incidenti di sicurezza e scheda del singolo incidente.",
         "pdf", route=("security:incidents_register_pdf", "security:incident_pdf"), pagina="security:incidents",
         layout=LAYOUT_CORE_PDF, norma="NIS2 / GDPR art. 33",
         pianificabile=(("registro", "Registro completo", "security:incidents_register_pdf", {}),)),
]
