from core.report_centro.catalogo import LAYOUT_DATI, LAYOUT_EXCEL, voce

MODULO = "admin_portale"
ETICHETTA = "Amministrazione"

VOCI = [
    voce("riesame_accessi", "Riesame periodico degli accessi",
         "Excel di ruoli e permessi per il riesame periodico degli accessi.",
         "xlsx", route="admin_portale:ruoli_portale_riesame", pagina="admin_portale:ruoli_portale",
         dati_personali=True, layout=LAYOUT_EXCEL, norma="ISO/IEC 27001 A.5.18"),
    voce("registro_postazioni", "Registro d'uso delle postazioni condivise",
         "Excel di chi ha usato quale PC condiviso, quando entra ed esce e come è uscito (dall'audit).",
         "xlsx", route="admin_portale:postazioni_registro_excel", pagina="admin_portale:postazioni_registro",
         dati_personali=True, layout=LAYOUT_EXCEL, norma="ISO/IEC 27001 A.8.15"),
    voce("registro_emissioni", "Registro emissioni report",
         "CSV del registro del Centro report: chi ha scaricato quale report, quando e con quali filtri.",
         "csv", route="admin_portale:centro_report_registro_csv", pagina="admin_portale:centro_report",
         dati_personali=True, layout=LAYOUT_DATI),
]
