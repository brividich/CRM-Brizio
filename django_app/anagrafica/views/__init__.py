"""Viste del modulo Anagrafica, spezzate per pilastro (18/10/2026).

Riesporta esplicitamente ogni nome dei sottomoduli e il blocco import storico, così
``from anagrafica.views import X`` e ``views.X`` in ``urls.py`` restano invariati.
Le funzioni condivise non sono legate qui ma lette da ``_helpers`` via ``__getattr__``
(vedi sotto); per i test ``mock.patch`` va su ``anagrafica.views._helpers.X`` per le
funzioni condivise e su ``anagrafica.views.<pilastro>.X`` per le altre.
"""
# ruff: noqa: F401, E402
from __future__ import annotations

import calendar
import csv
import json
import logging
from datetime import timedelta as _timedelta
from collections import defaultdict
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, connections, transaction
from django.db.models import Count, Prefetch, Q
from django.http import (
    Http404, HttpResponse, HttpResponseForbidden, HttpResponseNotFound,
    HttpResponseRedirect, JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
# Alias esplicito: in questo file `timezone` è già importato dentro varie
# funzioni (come `tz`/`_tz`) e `datetime.timezone` è un'altra cosa ancora.
from django.utils import timezone as django_timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods, require_POST

from django.contrib.auth.decorators import login_required
from core import naming
from core.csv_export import BOM, CSV_CONTENT_TYPE, safe_csv_writer
from core.legacy_anagrafica import (
    count_anagrafica_statuses,
    ensure_anagrafica_schema,
    fetch_anagrafica_rows,
    generate_username,
    normalize_legacy_alias,
    upsert_anagrafica_dipendente,
)
from core.legacy_models import AnagraficaDipendente, Ruolo, UtenteLegacy
from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_table_columns

from ..forms import (
    AnagraficaAziendaleForm,
    AnagraficaCivileForm,
    AttestatoFormazioneConfigForm,
    ElearningConfigForm,
    FiglioACaricoFormSet,
    DipendenteLegacyForm,
    TrainingCompletamentoDirettoForm,
    TrainingCompletionRuleForm,
    TrainingCourseDependencyForm,
    TrainingCourseForm,
    TrainingCourseVersionForm,
    TrainingDividiGruppiForm,
    TrainingEnrollmentEditForm,
    TrainingInstructorForm,
    TrainingLessonAttendanceForm,
    TrainingLessonForm,
    TrainingLezioniGeneraForm,
    TrainingPlanForm,
    TrainingProviderDocumentForm,
    TrainingProviderForm,
    TrainingRequirementRuleForm,
    TrainingSessioneUnicaForm,
    TrainingSessionForm,
    TrainingSlideForm,
    TrainingQuizQuestionForm,
    TrainingQuizOptionForm,
    VisitaMedicaForm,
)
from ..models import (
    AnagraficaHRPermission,
    AnagraficaStatPermission,
    AnagraficaVisiteMedichePermission,
    DURATA_VISITA_MAX_MESI,
    RecruitingPermission,
    AreaAziendale,
    Reparto,
    CartellaDocumentoDipendente,
    SubnavCategoriaAnagrafica,
    SubnavLinkAnagrafica,
    DipendenteAnagraficaAziendale,
    DipendenteAnagraficaCivile,
    DipendenteAssegnazione,
    DipendenteCambiamentoOrganizzativo,
    DipendenteQualifica,
    DipendenteRuoloOperativo,
    DipendenteStatLayout,
    DocumentoDipendente,
    ImportazioneRetributiva,
    LivelloContrattuale,
    Mansione,
    OffboardingPratica,
    OffboardingTask,
    OnboardingOffboardingCampo,
    OnboardingPratica,
    OnboardingTask,
    AmbitoRuolo,
    RuoloOperativo,
    RuoloQualifica,
    ImportazioneCedolini,
    SaldoCedolino,
    StoricoContratto,
    TipologiaContratto,
    QualificaSessione,
    TipoQualifica,
    TipoVisitaMedica,
    DipendenteVisitaFacoltativa,
    VisitaMedica,
    VoceRetributiva,
    _classify_pay_item,
)
from ..models_formazione import (
    AnagraficaFormazionePermission,
    AttestatoFormazioneConfig,
    ElearningConfig,
    TrainingAssignment,
    TrainingAttachment,
    TrainingCertificate,
    TrainingCompletionRule,
    TrainingCourse,
    TrainingCourseArgomento,
    TrainingCourseDependency,
    TrainingCourseModule,
    TrainingCourseVersion,
    TrainingDeadline,
    TrainingEmployeeRecord,
    TrainingEnrollment,
    TrainingInstructor,
    TrainingLesson,
    TrainingLessonAttendance,
    TrainingExportLog,
    TrainingPlan,
    TrainingProvider,
    TrainingProviderDocument,
    TrainingRequirementRule,
    TrainingSession,
    TrainingSessionArgomento,
    TrainingScanIntakeConfig,
    TrainingScanLog,
    TrainingSignatureSheet,
    TrainingSlide,
    TrainingQuizQuestion,
    TrainingQuizOption,
    TrainingElearningEnrollment,
)
from ..services.dpi_ingresso import (
    RigaConsegnaIniziale,
    archivia_pdf_cumulativo,
    crea_consegne_iniziali,
    proposta_righe_iniziali,
)
from ..services.visite import (
    completa_referti_visite,
    stato_visite,
    ultime_visite_correnti_ids,
    visite_storico,
)
from ..services import conformita as conformita_service
from ..services import onboarding as onboarding_service
from ..services import account_portale
from ..services import avviso_it_ingresso
from .. import views_account
from ..services import mansionario as mansionario_service
from ..acl_bootstrap import (
    PERM_DOCUMENTI_RISERVATI,
    PERM_FORMAZIONE_APPROVE,
    PERM_FORMAZIONE_MANAGE,
    PERM_FORMAZIONE_VIEW,
    PERM_HR_VIEW,
    PERM_SCHEDA_MANAGE,
    PERM_STATISTICHE_VIEW,
    PERM_VISITE_VIEW,
    PERM_VISITE_EDIT,
    PERM_VISITE_DELETE,
)
from core.upload_limits import DOCUMENT_MAX_BYTES, DOCUMENT_MAX_MB

from automazioni.managed_flows import event_flow
from ..models_rischi import CategoriaCorso, EsposizioneRischio, FattoreRischio
from ..forms import (
    CategoriaCorsoForm,
    EsposizioneRischioForm,
    FattoreRischioForm,
)

logger = logging.getLogger(__name__)



from .dipendenti import (
    cartella_documento_create,
    cartella_documento_delete,
    cartella_documento_edit,
    dipendente_anagrafica_aziendale_save,
    dipendente_anagrafica_civile_save,
    dipendente_assegnazione_annulla,
    dipendente_assegnazione_create,
    dipendente_assegnazione_modifica,
    dipendente_conformita_panel,
    dipendente_contratto_add,
    dipendente_contratto_delete,
    dipendente_contratto_edit,
    dipendente_create,
    dipendente_detail,
    dipendente_esposizione_rischio_add,
    dipendente_esposizione_rischio_remove,
    dipendente_libretto_formativo,
    dipendente_libretto_sanitario,
    dipendente_matricola_set,
    dipendente_offboarding_chiudi,
    dipendente_offboarding_licenziamento,
    dipendente_offboarding_task_update,
    dipendente_print,
    dipendente_qualifica_add,
    dipendente_qualifica_delete,
    dipendente_qualifica_evidenza,
    dipendente_qualifica_storico_evidenza,
    dipendente_qualifica_verifica,
    dipendente_retribuzione_voce_add,
    dipendente_retribuzione_voce_delete,
    dipendente_retribuzione_voce_edit,
    dipendente_retribuzioni,
    dipendente_retribuzioni_export_xlsx,
    dipendente_rimetti_in_forza,
    dipendente_ruolo_assegna,
    dipendente_ruolo_rimuovi,
    dipendente_toggle_active,
    dipendente_username_set,
    dipendente_verbale_dpi,
    dipendente_visita_add,
    dipendente_visita_delete,
    dipendente_visita_edit,
    dipendente_visita_facoltativa_add,
    dipendente_visita_facoltativa_remove,
    dipendenti_list,
    dipendenti_report,
    documenti_list,
    documento_dipendente_delete,
    documento_dipendente_download,
    documento_dipendente_upload,
    documento_sposta_cartella,
    ex_dipendenti_list,
    export_view,
    foto_dipendente,
    index,
    libretto_salva_box,
    onboarding_annulla,
    onboarding_avvia,
    onboarding_chiudi,
    onboarding_date,
    onboarding_detail,
    onboarding_list,
    onboarding_task_update,
    organigramma_persona_popup,
)
from .formazione import (
    attestato_formazione,
    attestato_impostazioni,
    attestato_report_export,
    attestato_salva_box,
    categoria_corso_create,
    categoria_corso_delete,
    categoria_corso_edit,
    categorie_corso_list,
    esposizione_rischio_create,
    esposizione_rischio_delete,
    esposizione_rischio_edit,
    esposizioni_rischio_list,
    fattore_rischio_create,
    fattore_rischio_delete,
    fattore_rischio_edit,
    fattori_rischio_list,
    formazione_allegato_delete,
    formazione_allegato_download,
    formazione_allegato_upload,
    formazione_azienda_create,
    formazione_azienda_delete,
    formazione_azienda_detail,
    formazione_azienda_documento_add,
    formazione_azienda_edit,
    formazione_ccnl_dashboard,
    formazione_ccnl_dipendente_espansione,
    formazione_copertura,
    formazione_corsi_list,
    formazione_corso_allegato_upload,
    formazione_corso_argomento_add,
    formazione_corso_argomento_delete,
    formazione_corso_assegna,
    formazione_corso_attestati_zip,
    formazione_corso_codice_suggest,
    formazione_corso_completamento_diretto,
    formazione_corso_completion_rule_save,
    formazione_corso_create,
    formazione_corso_delete,
    formazione_corso_dep_add,
    formazione_corso_dep_delete,
    formazione_corso_detail,
    formazione_corso_edit,
    formazione_corso_elearning,
    formazione_corso_espansione,
    formazione_corso_registri_pdf,
    formazione_corso_report_iscritti_csv,
    formazione_corso_req_rule_add,
    formazione_corso_req_rule_delete,
    formazione_corso_version_add,
    formazione_corso_version_delete,
    formazione_dashboard,
    formazione_elearning_assign,
    formazione_elearning_hub,
    formazione_elearning_iscritti_csv,
    formazione_elearning_manage,
    formazione_elearning_publish_toggle,
    formazione_elearning_settings,
    formazione_elearning_unassign,
    formazione_ente_documento_delete,
    formazione_ente_documento_download,
    formazione_enti_report,
    formazione_iscrizione_add,
    formazione_iscrizione_attestato_upload,
    formazione_iscrizione_bulk,
    formazione_iscrizione_delete,
    formazione_iscrizione_edit,
    formazione_iscrizione_turni,
    formazione_istruttore_create,
    formazione_istruttore_delete,
    formazione_istruttore_detail,
    formazione_istruttore_documento_add,
    formazione_istruttore_edit,
    formazione_istruttori_list,
    formazione_lezione_add,
    formazione_lezione_delete,
    formazione_lezione_edit,
    formazione_lezione_presenze,
    formazione_lezione_registro,
    formazione_lezione_registro_qr,
    formazione_lezioni_genera,
    formazione_modulo_delete,
    formazione_modulo_save,
    formazione_option_delete,
    formazione_option_save,
    formazione_piani_list,
    formazione_piano_create,
    formazione_piano_delete,
    formazione_piano_detail,
    formazione_piano_edit,
    formazione_plan,
    formazione_presenza_set,
    formazione_qualifica_durata,
    formazione_question_delete,
    formazione_question_import,
    formazione_question_save,
    formazione_quickadd_categoria,
    formazione_quickadd_docente,
    formazione_quickadd_piano,
    formazione_quickadd_qualifica,
    formazione_registro_autocompila,
    formazione_registro_scansione,
    formazione_ricerca,
    formazione_rinnovo_da_scadenzario,
    formazione_scadenzario,
    formazione_scansione_scarica,
    formazione_scansioni_impostazioni,
    formazione_scansioni_log,
    formazione_sessione_argomento_add,
    formazione_sessione_argomento_delete,
    formazione_sessione_argomento_giornate,
    formazione_sessione_attestati,
    formazione_sessione_create,
    formazione_sessione_delete,
    formazione_sessione_detail,
    formazione_sessione_dividi_gruppi,
    formazione_sessione_edit,
    formazione_sessione_espansione,
    formazione_sessione_fascicolo,
    formazione_sessione_iscritti,
    formazione_sessione_programma_riprendi,
    formazione_sessioni_list,
    formazione_slide_delete,
    formazione_slide_import,
    formazione_slide_import_stato,
    formazione_slide_save,
)
from .configurazione import (
    api_dipendente_widget_layout,
    avviso_it_save,
    dipendente_assegnazione_verifica,
    dipendente_dpi_iniziali_proposti,
    impostazioni,
    impostazioni_acl_role_grants_save,
    impostazioni_acl_user_override_save,
    impostazioni_permessi_save,
    scadenzario,
    subnav_categoria_create,
    subnav_categoria_delete,
    subnav_categoria_edit,
    subnav_link_create,
    subnav_link_delete,
    subnav_link_edit,
    widget_permissions,
    workflow_campo_create,
    workflow_campo_delete,
    workflow_campo_update,
)
from .qualifiche import (
    dpi_categoria_create,
    dpi_categoria_delete,
    dpi_categoria_edit,
    dpi_modello_create,
    dpi_modello_delete,
    dpi_modello_edit,
    dpi_taglia_create,
    dpi_taglia_delete,
    dpi_taglia_edit,
    dpi_tipo_create,
    dpi_tipo_delete,
    dpi_tipo_edit,
    qualifica_sessione_candidati,
    qualifica_sessione_create,
    qualifica_sessione_delete,
    qualifica_sessione_detail,
    qualifica_sessione_partecipante_add,
    qualifica_sessione_partecipante_remove,
    qualifica_sessione_report_csv,
    qualifica_sessioni_list,
    qualifiche_dashboard,
    qualifiche_list,
    qualifiche_scadenzario,
    skill_matrix_macchina,
    skm_copertura,
    skm_impostazioni,
    skm_match_validazione,
    skm_refresh,
    skm_scadenzario,
    tipo_qualifica_create,
    tipo_qualifica_delete,
    tipo_qualifica_detail,
    tipo_qualifica_edit,
)
from .retribuzioni import (
    cedolini_import,
    contratti_import,
    livello_contrattuale_create,
    livello_contrattuale_delete,
    livello_contrattuale_edit,
    ratei_export,
    ratei_list,
    retribuzioni_globale,
    retribuzioni_globale_export,
    retribuzioni_import,
    tipologia_contratto_create,
    tipologia_contratto_delete,
    tipologia_contratto_edit,
)
from .struttura import (
    ambito_ruolo_create,
    ambito_ruolo_delete,
    ambito_ruolo_edit,
    area_aziendale_create,
    area_aziendale_delete,
    area_aziendale_edit,
    area_create,
    area_delete,
    area_edit,
    mansione_create,
    mansione_delete,
    mansione_edit,
    mansione_requisiti,
    mansioni_list,
    organigramma,
    organigramma_albero,
    organigramma_diagramma,
    ruoli_aziendali_list,
    ruoli_operativi_list,
    ruolo_aziendale_create,
    ruolo_aziendale_delete,
    ruolo_aziendale_edit,
    ruolo_operativo_create,
    ruolo_operativo_delete,
    ruolo_operativo_dipendenti,
    ruolo_operativo_edit,
    ruolo_qualifica_aggiungi,
    ruolo_qualifica_rimuovi,
)
from .visite import (
    conformita_report,
    libretto_sanitario_generale,
    matrice_competenze,
    referto_gestione,
    sicurezza_hub,
    sicurezza_ricerca,
    sicurezza_wizard,
    tipo_visita_medica_bulk_edit,
    tipo_visita_medica_create,
    tipo_visita_medica_delete,
    tipo_visita_medica_edit,
    visita_medica_dettaglio,
    visita_medica_elimina,
    visita_medica_superata,
    visite_mediche_api_cerca_dipendente,
    visite_mediche_candidati,
    visite_mediche_dashboard,
    visite_mediche_export_copertura,
    visite_mediche_export_scadenze,
    visite_mediche_nuova_sessione,
    visite_mediche_sessione_delete,
    visite_mediche_sessione_detail,
    visite_mediche_sessione_partecipante_add,
    visite_mediche_sessioni,
)


from . import _helpers, configurazione, dipendenti, formazione, qualifiche, retribuzioni, struttura, visite  # noqa: E402

_PILASTRI = (_helpers, configurazione, dipendenti, formazione, qualifiche, retribuzioni, struttura, visite)


def __getattr__(name):
    """Tutto ciò che non è una view di ``urls.py`` si legge dal sottomodulo al momento
    dell'accesso, non viene copiato qui.

    Così ``from anagrafica.views import _is_anagrafica_admin`` dentro una funzione
    (views_*.py vicini, export, templatetag, ai_assistant) vede il valore corrente di
    ``anagrafica.views._helpers.X`` (o ``anagrafica.views.<pilastro>.X``): un
    ``mock.patch`` lì vale per tutti i chiamanti, come quando c'era un solo ``views.py``.
    """
    for mod in _PILASTRI:
        try:
            return getattr(mod, name)
        except AttributeError:
            continue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
