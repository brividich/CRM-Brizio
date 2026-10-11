"""Hub «Amministrazione anagrafica» (prompt 03, obiettivo C).

Una pagina a schede che raccoglie configurazione, viste elenco, cataloghi, import con lo storico
centralizzato e manutenzione. Le pagine di destinazione restano dove sono (link da email, QR e
automazioni continuano a funzionare): l'hub le raccoglie e mostra solo quelle che l'utente può
aprire, chiedendolo alla stessa politica del middleware ACL. Il controllo vero resta sulle pagine.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse

SCHEDE = [
    ("configurazione", "Configurazione"),
    ("viste", "Viste elenco"),
    ("cataloghi", "Cataloghi"),
    ("import", "Import e storico"),
    ("manutenzione", "Manutenzione"),
]


@dataclass(frozen=True)
class Voce:
    scheda: str
    rotta: str
    titolo: str
    descrizione: str
    query: str = ""


VOCI = [
    Voce("configurazione", "anagrafica:impostazioni", "Navigazione del modulo", "Categorie e link della barra di navigazione.", "tab=navigazione"),
    Voce("configurazione", "anagrafica:impostazioni", "Workflow e campi", "Campi personalizzati dei flussi.", "tab=workflow"),
    Voce("configurazione", "anagrafica:impostazioni", "Permessi del modulo", "Ruoli e override per utente.", "tab=permessi"),
    Voce("configurazione", "anagrafica:widget_permissions", "Widget della scheda", "Chi vede quali riquadri della scheda dipendente."),
    Voce("configurazione", "anagrafica:attestato_impostazioni", "Attestati", "Modello e firme degli attestati di formazione."),
    Voce("configurazione", "anagrafica:formazione_elearning_settings", "E-learning", "Impostazioni dei corsi online."),
    Voce("configurazione", "anagrafica:elearning_impostazioni_corsi", "Corsi online", "Catalogo e pubblicazione dei corsi e-learning."),
    Voce("configurazione", "anagrafica:formazione_scansioni_impostazioni", "Scansioni formazione", "Cartelle e regole di acquisizione dei fogli firme."),
    Voce("configurazione", "anagrafica:referti_impostazioni", "Referti sanitari", "Acquisizione e abbinamento dei referti."),
    Voce("configurazione", "anagrafica:skm_impostazioni", "Skill matrix", "Livelli e regole della matrice competenze."),
    Voce("configurazione", "anagrafica:sicurezza_operativa_config", "Mansioni e rischi", "Configurazione della sicurezza operativa."),
    Voce("configurazione", "dpi:impostazioni", "DPI", "Impostazioni del modulo DPI."),
    Voce("viste", "anagrafica:viste_elenco", "Viste elenco dipendenti", "Colonne, ordine, preset ISO/HR/Sicurezza e vista predefinita."),
    Voce("cataloghi", "anagrafica:impostazioni", "Mansioni", "Catalogo mansioni e requisiti.", "tab=mansioni"),
    Voce("cataloghi", "anagrafica:impostazioni", "Aree aziendali", "Aree dei reparti.", "tab=aree-aziendali"),
    Voce("cataloghi", "anagrafica:impostazioni", "Reparti", "Reparti e capireparto.", "tab=aree"),
    Voce("cataloghi", "anagrafica:impostazioni", "Ruoli", "Catalogo ruoli.", "tab=ruoli"),
    Voce("cataloghi", "anagrafica:impostazioni", "Qualifiche", "Tipi di qualifica.", "tab=qualifiche"),
    Voce("cataloghi", "anagrafica:impostazioni", "Livelli contrattuali", "Livelli del CCNL.", "tab=livelli"),
    Voce("cataloghi", "anagrafica:impostazioni", "Tipologie di contratto", "Tipologie contrattuali.", "tab=tipologie"),
    Voce("cataloghi", "anagrafica:impostazioni", "Visite mediche", "Tipi di visita e periodicità.", "tab=visite-mediche"),
    Voce("cataloghi", "anagrafica:impostazioni", "DPI", "Categorie, modelli e taglie.", "tab=dpi"),
    Voce("cataloghi", "anagrafica:impostazioni", "Cartelle documenti", "Cartelle dei documenti del dipendente.", "tab=documenti"),
    Voce("cataloghi", "anagrafica:mpq_cruscotto", "MOD.128 processi e qualifiche", "Processi, clienti e requisiti di qualifica."),
    Voce("import", "anagrafica:retribuzioni_import", "Importa retribuzioni", "CSV mensile dello studio paghe."),
    Voce("import", "anagrafica:cedolini_import", "Importa cedolini", "Saldi ferie/permessi/ROL dal file cedolini."),
    Voce("import", "anagrafica:contratti_import", "Importa contratti", "Storico contrattuale da CSV."),
]

COMANDI_MANUTENZIONE = [
    ("pulisci_scadenze_hr", "Riallinea le scadenze HR orfane o duplicate (prima in prova, poi con --apply)."),
    ("normalizza_nomi_dipendenti", "Riporta i nominativi dei dipendenti alla forma COGNOME NOME."),
    ("normalizza_nomi_utenti", "Stessa normalizzazione sui nomi degli utenti portale."),
    ("acl_fallback_report --only-unbound", "Rotte del portale ancora senza binding ACL canonico."),
]


def _consentita(request, url: str) -> bool:
    from core.middleware import acl_allows_path

    return acl_allows_path(url.split("?", 1)[0], django_user=request.user, legacy_user=getattr(request, "legacy_user", None),
                           request=None)


def _voci_visibili(request, scheda: str) -> list[dict]:
    visibili = []
    for voce in VOCI:
        if voce.scheda != scheda:
            continue
        try:
            url = reverse(voce.rotta)
        except NoReverseMatch:
            continue
        if not _consentita(request, url):
            continue
        visibili.append({"titolo": voce.titolo, "descrizione": voce.descrizione, "url": f"{url}?{voce.query}" if voce.query else url})
    return visibili


def _utente(u) -> str:
    if u is None:
        return "—"
    return (u.get_full_name() or u.username or "").strip() or "—"


def storico_import(request, limite: int = 60) -> list[dict]:
    """Import recenti di tutte le fonti, dal più recente. Retribuzioni e cedolini solo per HR."""
    from .models import ImportazioneCedolini, ImportazioneRetributiva
    from .models_elearning import TrainingElearningImport
    from .views import _check_hr_permission

    righe: list[dict] = []
    if _check_hr_permission(request):
        for imp in ImportazioneRetributiva.objects.select_related("importato_da").order_by("-data_importazione")[:limite]:
            righe.append({"fonte": "Retribuzioni", "tipo": "retribuzioni", "pk": imp.pk, "quando": imp.data_importazione,
                          "chi": _utente(imp.importato_da), "file": imp.file_nome or imp.get_origine_display(),
                          "ok": imp.righe_ok, "scartate": imp.righe_errore, "n_scarti": len(imp.scarti or []), "nota": imp.note})
        for imp in ImportazioneCedolini.objects.select_related("importato_da").order_by("-data_importazione")[:limite]:
            righe.append({"fonte": "Cedolini", "tipo": "cedolini", "pk": imp.pk, "quando": imp.data_importazione,
                          "chi": _utente(imp.importato_da), "file": imp.file_nome or imp.get_origine_display(),
                          "ok": imp.righe_ok, "scartate": imp.righe_errore + imp.righe_non_trovate,
                          "n_scarti": len(imp.scarti or []), "nota": imp.note})
    for imp in TrainingElearningImport.objects.select_related("creato_da", "corso").order_by("-creato_il")[:limite]:
        righe.append({"fonte": "Slide e-learning", "tipo": "", "pk": imp.pk, "quando": imp.creato_il, "chi": _utente(imp.creato_da),
                      "file": imp.nome_file, "ok": imp.n_slide, "scartate": 1 if imp.stato == imp.ERRORE else 0, "n_scarti": 0,
                      "nota": imp.errore or imp.get_stato_display()})
    righe.sort(key=lambda r: r["quando"], reverse=True)
    return righe[:limite]


@login_required
def amministrazione_hub(request):
    from .views import _is_anagrafica_admin

    if not _is_anagrafica_admin(request):
        messages.error(request, "Accesso riservato agli amministratori dell'anagrafica.")
        return redirect("anagrafica:dipendenti_list")
    codici = [c for c, _ in SCHEDE]
    scheda = request.GET.get("scheda") or "configurazione"
    if scheda not in codici:
        scheda = "configurazione"
    contesto = {"schede": SCHEDE, "scheda": scheda, "voci": _voci_visibili(request, scheda)}
    if scheda == "import":
        contesto["storico"] = storico_import(request)
    elif scheda == "viste":
        from .models_elenco import VistaElenco

        contesto["viste"] = list(VistaElenco.objects.filter(attiva=True).order_by("ordine", "nome"))
    elif scheda == "manutenzione":
        contesto["comandi"] = COMANDI_MANUTENZIONE
    return render(request, "anagrafica/pages/amministrazione_hub.html", contesto)


@login_required
def import_scarti_export(request, tipo: str, pk: int):
    """Scarico xlsx delle righe scartate di un import (valori sempre testo, mai formule)."""
    from core.excel_export import make_xlsx_response

    from .models import ImportazioneCedolini, ImportazioneRetributiva
    from .views import _check_hr_permission, _is_anagrafica_admin

    modelli = {"retribuzioni": ImportazioneRetributiva, "cedolini": ImportazioneCedolini}
    if tipo not in modelli:
        raise Http404
    if not (_is_anagrafica_admin(request) and _check_hr_permission(request)):
        messages.error(request, "Lo scarto degli import HR è riservato agli amministratori con permesso HR.")
        return redirect("anagrafica:dipendenti_list")
    imp = modelli[tipo].objects.filter(pk=pk).first()
    if imp is None:
        raise Http404
    from core.audit import log_action

    log_action(request, "export", "anagrafica", {"lista": f"scarti_import_{tipo}", "import_id": imp.pk, "n_righe": len(imp.scarti or [])})
    righe = [[str(s.get("riga", "")), str(s.get("chiave", "")), str(s.get("motivo", ""))] for s in (imp.scarti or [])]
    return make_xlsx_response(filename=f"scarti_{tipo}_{imp.pk}.xlsx", columns=["Riga", "Chiave (CF)", "Motivo"], rows=righe,
                              sheet_title="Scarti", title=f"Scarti import {tipo} #{imp.pk}", subtitle=imp.file_nome or "",
                              filters_label=f"{len(righe)} righe")
