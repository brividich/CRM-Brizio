from django.contrib import admin

from .models import (
    AnagraficaHRPermission,
    AnagraficaVisiteMedichePermission,
    DipendenteCambiamentoOrganizzativo,
    DocumentoDipendente,
    Fornitore,
    FornitoreDocumento,
    FornitoreOrdine,
    FornitoreValutazione,
    ImportazioneRetributiva,
    LivelloContrattuale,
    OffboardingPratica,
    OffboardingTask,
    OnboardingOffboardingCampo,
    QualificaSessione,
    StoricoContratto,
    TipologiaContratto,
    TipoVisitaMedica,
    VisitaMedica,
    VoceRetributiva,
)
from .models_rischi import (
    CategoriaCorso,
    EsposizioneRischio,
    FattoreRischio,
)
from .models_formazione import (
    AnagraficaFormazionePermission,
    TrainingAssignment,
    TrainingCertificate,
    TrainingCompletionRule,
    TrainingCourse,
    TrainingCourseDependency,
    TrainingCourseModule,
    TrainingCourseVersion,
    TrainingDeadline,
    TrainingEmployeeRecord,
    TrainingEnrollment,
    TrainingExportLog,
    TrainingInstructor,
    TrainingLesson,
    TrainingLessonAttendance,
    TrainingPlan,
    TrainingRequirementRule,
    TrainingSession,
    TrainingSlide,
    TrainingQuizQuestion,
    TrainingQuizOption,
    TrainingElearningEnrollment,
    TrainingQuizAttempt,
    ElearningConfig,
)


class FornitoreDocumentoInline(admin.TabularInline):
    model = FornitoreDocumento
    extra = 0
    readonly_fields = ("uploaded_by", "uploaded_at")


class FornitoreOrdineInline(admin.TabularInline):
    model = FornitoreOrdine
    extra = 0
    readonly_fields = ("created_by", "created_at")


class FornitoreValutazioneInline(admin.TabularInline):
    model = FornitoreValutazione
    extra = 0
    readonly_fields = ("valutato_da", "created_at", "media")
    fields = ("data", "qualita", "puntualita", "comunicazione", "media", "note", "valutato_da")

    def media(self, obj):
        return obj.media
    media.short_description = "Media"


@admin.register(Fornitore)
class FornitoreAdmin(admin.ModelAdmin):
    list_display = ("ragione_sociale", "categoria", "citta", "telefono", "email", "is_active", "punteggio_medio")
    list_filter = ("categoria", "is_active")
    search_fields = ("ragione_sociale", "piva", "email", "citta")
    inlines = [FornitoreDocumentoInline, FornitoreOrdineInline, FornitoreValutazioneInline]
    readonly_fields = ("created_at", "updated_at")


@admin.register(AnagraficaHRPermission)
class AnagraficaHRPermissionAdmin(admin.ModelAdmin):
    list_display = ("accesso",)

    def has_add_permission(self, request):
        return not AnagraficaHRPermission.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class VoceRetributivaInline(admin.TabularInline):
    model = VoceRetributiva
    extra = 0
    readonly_fields = ("tax_code", "pay_item", "categoria", "importo", "is_changed", "importo_precedente", "data_competenza")
    fields = ("tax_code", "pay_item", "categoria", "importo", "is_changed", "importo_precedente")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(QualificaSessione)
class QualificaSessioneAdmin(admin.ModelAdmin):
    list_display = ("tipo", "data_conseguimento", "data_scadenza", "ente", "created_by", "created_at")
    list_filter = ("tipo__categoria", "tipo", "data_conseguimento")
    search_fields = ("tipo__nome", "ente", "note")
    readonly_fields = ("created_at", "updated_at", "created_by")
    date_hierarchy = "data_conseguimento"


@admin.register(ImportazioneRetributiva)
class ImportazioneRetributivaAdmin(admin.ModelAdmin):
    list_display = ("data_competenza", "file_nome", "righe_ok", "righe_errore", "importato_da", "data_importazione")
    list_filter = ("data_competenza",)
    readonly_fields = ("data_importazione", "importato_da", "righe_totali", "righe_ok", "righe_errore")
    inlines = []

    def has_add_permission(self, request):
        return False


@admin.register(TipologiaContratto)
class TipologiaContrattoAdmin(admin.ModelAdmin):
    list_display = ("codice", "nome", "ordine", "is_active")
    list_editable = ("nome", "ordine", "is_active")
    ordering = ("ordine", "codice")


@admin.register(LivelloContrattuale)
class LivelloContrattualeAdmin(admin.ModelAdmin):
    list_display = ("codice", "descrizione", "ordine", "is_active")
    list_editable = ("descrizione", "ordine", "is_active")
    ordering = ("ordine", "codice")


@admin.register(DipendenteCambiamentoOrganizzativo)
class DipendenteCambiamentoOrganizzativoAdmin(admin.ModelAdmin):
    list_display = ("legacy_anagrafica_id", "tipo", "valore_precedente", "valore_nuovo",
                    "data_effetto", "created_by", "created_at")
    list_filter = ("tipo", "data_effetto")
    search_fields = ("legacy_anagrafica_id", "valore_precedente", "valore_nuovo", "note")
    readonly_fields = ("legacy_anagrafica_id", "tipo", "valore_precedente", "valore_nuovo",
                       "data_effetto", "note", "created_at", "created_by")
    date_hierarchy = "data_effetto"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class OffboardingTaskInline(admin.TabularInline):
    model = OffboardingTask
    extra = 0
    readonly_fields = ("created_at", "updated_at", "completed_at", "completed_by")
    fields = ("categoria", "titolo", "stato", "note", "completed_at", "completed_by")


@admin.register(OffboardingPratica)
class OffboardingPraticaAdmin(admin.ModelAdmin):
    list_display = (
        "legacy_anagrafica_id", "dipendente_nome", "motivo",
        "data_cessazione_prevista", "stato", "created_at", "closed_at",
    )
    list_filter = ("stato", "motivo", "data_cessazione_prevista")
    search_fields = ("legacy_anagrafica_id", "dipendente_nome", "reparto", "mansione", "note_hr")
    readonly_fields = ("created_at", "updated_at", "closed_at", "created_by", "updated_by", "closed_by")
    date_hierarchy = "created_at"
    inlines = [OffboardingTaskInline]


@admin.register(OnboardingOffboardingCampo)
class OnboardingOffboardingCampoAdmin(admin.ModelAdmin):
    list_display = ("fase", "campo_label", "campo_key", "sezione", "categoria", "obbligatorio", "is_active", "ordine")
    list_filter = ("fase", "categoria", "obbligatorio", "is_active")
    search_fields = ("campo_label", "campo_key", "sezione", "note")
    list_editable = ("categoria", "obbligatorio", "is_active", "ordine")
    readonly_fields = ("created_at", "updated_at")


@admin.register(StoricoContratto)
class StoricoContrattoAdmin(admin.ModelAdmin):
    list_display = ("tax_code", "legacy_anagrafica_id", "data_inizio", "data_fine",
                    "tipologia_contratto", "codice_livello", "qualifica_nome", "created_at")
    list_filter = ("tipologia_contratto", "codice_livello")
    search_fields = ("tax_code", "qualifica_nome", "ccnl")
    readonly_fields = ("created_at", "importato_da")


# ---------------------------------------------------------------------------
# Documenti dipendente / Visite mediche
# ---------------------------------------------------------------------------

@admin.register(DocumentoDipendente)
class DocumentoDipendenteAdmin(admin.ModelAdmin):
    list_display = (
        "tipo", "nome_originale", "legacy_anagrafica_id",
        "oggetto_riferimento_tipo", "oggetto_riferimento_id",
        "dimensione_bytes", "created_at", "created_by_display",
    )
    list_filter = ("tipo", "created_at")
    search_fields = ("nome_originale", "descrizione", "legacy_anagrafica_id")
    readonly_fields = (
        "file", "nome_originale", "tipo_mime", "dimensione_bytes",
        "oggetto_riferimento_tipo", "oggetto_riferimento_id",
        "created_at", "created_by", "created_by_display",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False


@admin.register(TipoVisitaMedica)
class TipoVisitaMedicaAdmin(admin.ModelAdmin):
    list_display = ("nome", "durata_mesi", "obbligatoria", "is_active")
    list_filter = ("obbligatoria", "is_active")
    list_editable = ("durata_mesi", "obbligatoria", "is_active")
    search_fields = ("nome", "descrizione")
    filter_horizontal = ("ruoli_operativi",)


@admin.register(VisitaMedica)
class VisitaMedicaAdmin(admin.ModelAdmin):
    list_display = (
        "legacy_anagrafica_id", "tipo", "data_svolgimento",
        "data_scadenza", "esito", "medico_competente",
    )
    list_filter = ("tipo", "esito", "data_svolgimento")
    search_fields = ("legacy_anagrafica_id", "medico_competente", "note")
    readonly_fields = ("data_scadenza", "created_at", "updated_at", "created_by", "updated_by")
    date_hierarchy = "data_svolgimento"


@admin.register(AnagraficaVisiteMedichePermission)
class AnagraficaVisiteMedichePermissionAdmin(admin.ModelAdmin):
    list_display = ("accesso",)

    def has_add_permission(self, request):
        return not AnagraficaVisiteMedichePermission.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Formazione HR — Admin minimale (PATCH-01)
# ---------------------------------------------------------------------------

@admin.register(AnagraficaFormazionePermission)
class AnagraficaFormazionePermissionAdmin(admin.ModelAdmin):
    list_display = ("accesso_visualizzazione", "accesso_modifica", "accesso_export", "accesso_validazione")

    def has_add_permission(self, request):
        return not AnagraficaFormazionePermission.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TrainingPlan)
class TrainingPlanAdmin(admin.ModelAdmin):
    list_display = ("codice", "nome", "categoria", "stato", "is_active", "created_at")
    list_filter = ("categoria", "stato", "is_active")
    search_fields = ("codice", "nome")
    readonly_fields = ("created_at", "updated_at", "created_by")


@admin.register(TrainingCourse)
class TrainingCourseAdmin(admin.ModelAdmin):
    list_display = ("codice", "titolo", "piano", "categoria", "durata_ore_teorica", "validita_mesi", "obbligatorio", "is_elearning", "stato", "is_active")
    list_filter = ("stato", "obbligatorio", "is_elearning", "is_active", "piano", "categoria")
    search_fields = ("codice", "titolo")
    readonly_fields = ("created_at", "updated_at", "created_by")
    autocomplete_fields = ("categoria",)


# ─────────────────────────────────────────────────────────────
# E-learning — Slide / Quiz / Iscrizioni / Tentativi
# ─────────────────────────────────────────────────────────────

@admin.register(TrainingSlide)
class TrainingSlideAdmin(admin.ModelAdmin):
    list_display = ("corso", "ordine", "titolo", "is_immagine", "is_active", "updated_at")
    list_filter = ("is_active", "corso")
    search_fields = ("titolo", "contenuto", "corso__codice", "corso__titolo")
    list_editable = ("ordine",)
    readonly_fields = ("created_at", "updated_at", "created_by")

    @admin.display(boolean=True, description="Immagine")
    def is_immagine(self, obj):
        return obj.is_immagine


class TrainingQuizOptionInline(admin.TabularInline):
    model = TrainingQuizOption
    extra = 2
    fields = ("ordine", "testo", "corretta")


@admin.register(TrainingQuizQuestion)
class TrainingQuizQuestionAdmin(admin.ModelAdmin):
    list_display = ("corso", "ordine", "testo", "is_active")
    list_filter = ("is_active", "corso")
    search_fields = ("testo", "corso__codice", "corso__titolo")
    list_editable = ("ordine",)
    inlines = [TrainingQuizOptionInline]


@admin.register(TrainingQuizOption)
class TrainingQuizOptionAdmin(admin.ModelAdmin):
    list_display = ("domanda", "ordine", "testo", "corretta")
    list_filter = ("corretta",)
    search_fields = ("testo", "domanda__testo")


@admin.register(TrainingElearningEnrollment)
class TrainingElearningEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("legacy_anagrafica_id", "corso", "stato", "ultima_slide_ordine", "best_punteggio_pct", "n_tentativi", "data_completamento")
    list_filter = ("stato", "corso")
    search_fields = ("legacy_anagrafica_id", "corso__codice", "corso__titolo")
    readonly_fields = ("data_iscrizione", "updated_at", "record_completamento")


@admin.register(TrainingQuizAttempt)
class TrainingQuizAttemptAdmin(admin.ModelAdmin):
    list_display = ("legacy_anagrafica_id", "corso", "punteggio_pct", "n_corrette", "n_totali", "superato", "inviato_il")
    list_filter = ("superato", "corso")
    search_fields = ("legacy_anagrafica_id", "corso__codice", "corso__titolo")
    readonly_fields = ("iniziato_il", "inviato_il", "risposte_json", "record", "utente")


@admin.register(ElearningConfig)
class ElearningConfigAdmin(admin.ModelAdmin):
    list_display = ("__str__", "quiz_punteggio_minimo_default", "validita_mesi_default", "max_tentativi_quiz", "updated_at")
    readonly_fields = ("updated_at", "updated_by")


# ─────────────────────────────────────────────────────────────
# Safety — Fattori di Rischio / Categorie Corso / Esposizioni
# ─────────────────────────────────────────────────────────────

@admin.register(FattoreRischio)
class FattoreRischioAdmin(admin.ModelAdmin):
    list_display = (
        "codice", "nome", "categoria",
        "periodicita_formazione_mesi", "periodicita_sorveglianza_mesi",
        "richiede_formazione", "richiede_visita_medica", "richiede_dpi", "is_active",
    )
    list_filter = ("categoria", "is_active", "richiede_formazione", "richiede_visita_medica", "richiede_dpi")
    search_fields = ("codice", "nome", "descrizione")
    filter_horizontal = ("tipi_visita", "categorie_dpi")
    readonly_fields = ("created_at", "updated_at")


@admin.register(CategoriaCorso)
class CategoriaCorsoAdmin(admin.ModelAdmin):
    list_display = ("codice", "nome", "n_fattori", "n_corsi", "is_active")
    list_filter = ("is_active",)
    search_fields = ("codice", "nome", "descrizione")
    filter_horizontal = ("fattori_rischio",)
    readonly_fields = ("created_at", "updated_at")

    def n_fattori(self, obj):
        return obj.fattori_rischio.count()
    n_fattori.short_description = "Fattori"

    def n_corsi(self, obj):
        return obj.corsi.count()
    n_corsi.short_description = "Corsi"


@admin.register(EsposizioneRischio)
class EsposizioneRischioAdmin(admin.ModelAdmin):
    list_display = ("fattore", "mansione", "area", "legacy_anagrafica_id", "is_active", "created_at")
    list_filter = ("is_active", "fattore__categoria")
    search_fields = ("fattore__codice", "fattore__nome", "mansione__nome", "area__nome", "legacy_anagrafica_id")
    autocomplete_fields = ("fattore",)
    raw_id_fields = ("mansione", "area")
    readonly_fields = ("created_at",)


@admin.register(TrainingCourseVersion)
class TrainingCourseVersionAdmin(admin.ModelAdmin):
    list_display = ("corso", "version_label", "titolo_snapshot", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("corso__codice", "version_label", "titolo_snapshot")
    readonly_fields = ("created_at", "revised_by")


@admin.register(TrainingCompletionRule)
class TrainingCompletionRuleAdmin(admin.ModelAdmin):
    list_display = (
        "corso", "ore_minime_percentuale", "presenza_minima_percentuale",
        "richiede_esame_finale", "richiede_firma_presenza", "richiede_attestato",
        "richiede_validazione_hr", "is_active",
    )
    list_filter = ("richiede_esame_finale", "richiede_attestato", "richiede_validazione_hr", "is_active")
    search_fields = ("corso__codice", "corso__titolo")
    readonly_fields = ("corso",)


@admin.register(TrainingCourseDependency)
class TrainingCourseDependencyAdmin(admin.ModelAdmin):
    list_display = ("corso_principale", "prerequisito", "obbligatorio")
    list_filter = ("obbligatorio",)
    search_fields = ("corso_principale__codice", "prerequisito__codice")


@admin.register(TrainingCourseModule)
class TrainingCourseModuleAdmin(admin.ModelAdmin):
    list_display = ("corso_padre", "corso_modulo", "ordine", "obbligatorio")
    list_filter = ("obbligatorio",)
    search_fields = ("corso_padre__codice", "corso_modulo__codice")


@admin.register(TrainingRequirementRule)
class TrainingRequirementRuleAdmin(admin.ModelAdmin):
    list_display = (
        "corso", "piano", "mansione", "area", "ruolo_operativo",
        "legacy_anagrafica_id", "is_mandatory", "is_active", "created_at",
    )
    list_filter = ("is_mandatory", "is_active", "mansione", "area")
    search_fields = ("corso__codice", "piano__codice", "legacy_anagrafica_id")
    readonly_fields = ("created_at", "created_by")


@admin.register(TrainingInstructor)
class TrainingInstructorAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo", "ragione_sociale", "email", "telefono", "is_active")
    list_filter = ("tipo", "is_active")
    search_fields = ("nome", "ragione_sociale", "email")
    readonly_fields = ("created_at",)


@admin.register(TrainingAssignment)
class TrainingAssignmentAdmin(admin.ModelAdmin):
    list_display = ("legacy_anagrafica_id", "corso", "stato", "data_assegnazione", "due_date")
    list_filter = ("stato",)
    search_fields = ("legacy_anagrafica_id", "corso__codice", "corso__titolo")
    readonly_fields = ("data_assegnazione", "created_at", "assigned_by")


@admin.register(TrainingSession)
class TrainingSessionAdmin(admin.ModelAdmin):
    list_display = ("codice_sessione", "corso", "stato", "modalita", "data_inizio", "data_fine", "docente")
    list_filter = ("stato", "modalita")
    search_fields = ("codice_sessione", "corso__codice", "corso__titolo")
    readonly_fields = ("created_at", "updated_at", "created_by")
    date_hierarchy = "data_inizio"


@admin.register(TrainingLesson)
class TrainingLessonAdmin(admin.ModelAdmin):
    list_display = ("sessione", "numero", "data", "ora_inizio", "ora_fine", "argomento", "docente")
    list_filter = ("sessione__stato",)
    search_fields = ("sessione__codice_sessione", "argomento")
    readonly_fields = ("created_at", "updated_by")
    date_hierarchy = "data"


@admin.register(TrainingEnrollment)
class TrainingEnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        "legacy_anagrafica_id", "sessione", "stato",
        "ore_frequentate", "percentuale_presenza", "idoneo", "data_completamento",
    )
    list_filter = ("stato", "idoneo")
    search_fields = ("legacy_anagrafica_id", "sessione__codice_sessione")
    readonly_fields = ("created_at", "updated_at", "iscritto_da")
    date_hierarchy = "data_completamento"


@admin.register(TrainingLessonAttendance)
class TrainingLessonAttendanceAdmin(admin.ModelAdmin):
    list_display = (
        "legacy_anagrafica_id", "lezione", "stato_presenza",
        "ore_effettive", "firma_ingresso", "firma_uscita", "signature_status",
    )
    list_filter = ("stato_presenza", "signature_status", "firma_ingresso", "firma_uscita")
    search_fields = ("legacy_anagrafica_id", "lezione__sessione__codice_sessione")
    readonly_fields = ("created_at", "updated_at", "registrato_da", "signed_at")


_SNAPSHOT_FIELDS_EMPLOYEE_RECORD = (
    "course_code_snapshot", "course_title_snapshot", "course_version_snapshot",
    "plan_code_snapshot", "plan_name_snapshot", "duration_hours_snapshot",
    "validity_months_snapshot", "completion_rule_snapshot_json",
    "session_code_snapshot", "teacher_name_snapshot", "completion_calculation_snapshot_json",
)


@admin.register(TrainingEmployeeRecord)
class TrainingEmployeeRecordAdmin(admin.ModelAdmin):
    list_display = (
        "legacy_anagrafica_id", "corso", "data_completamento",
        "ore_frequentate", "percentuale_presenza", "idoneo", "data_scadenza",
    )
    list_filter = ("idoneo",)
    search_fields = ("legacy_anagrafica_id", "corso__codice", "corso__titolo")
    readonly_fields = ("created_at", "validato_da") + _SNAPSHOT_FIELDS_EMPLOYEE_RECORD
    date_hierarchy = "data_completamento"

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(TrainingCertificate)
class TrainingCertificateAdmin(admin.ModelAdmin):
    list_display = ("legacy_anagrafica_id", "record", "numero_attestato", "data_rilascio", "rilasciato_da")
    search_fields = ("legacy_anagrafica_id", "numero_attestato")
    readonly_fields = ("created_at", "created_by")
    date_hierarchy = "data_rilascio"


@admin.register(TrainingDeadline)
class TrainingDeadlineAdmin(admin.ModelAdmin):
    list_display = (
        "legacy_anagrafica_id", "corso", "stato_scadenza",
        "data_scadenza", "giorni_alla_scadenza", "is_required", "needs_refresh", "ricalcolato_il",
    )
    list_filter = ("stato_scadenza", "is_required", "needs_refresh")
    search_fields = ("legacy_anagrafica_id", "corso__codice")
    readonly_fields = ("ricalcolato_il",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(TrainingExportLog)
class TrainingExportLogAdmin(admin.ModelAdmin):
    list_display = ("tipo", "righe_esportate", "generato_da", "generato_il", "ip_address")
    list_filter = ("tipo",)
    readonly_fields = ("tipo", "filtri_json", "righe_esportate", "generato_da", "generato_il", "ip_address")
    date_hierarchy = "generato_il"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ─────────────────────────────────────────────────────────────
# MOD.128 MPQ — Mansionario Processi Qualificati
# ─────────────────────────────────────────────────────────────

from .models_mpq import (
    AbilitazioneProcesso,
    CertificazioneIndividuale,
    ClienteQualificante,
    MpqStorico,
    ProcessoQualificato,
    RiferimentoProcesso,
)


@admin.register(ClienteQualificante)
class ClienteQualificanteAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo", "codice", "certificatore", "is_active")
    list_filter = ("tipo", "is_active")
    search_fields = ("nome", "codice")
    readonly_fields = ("created_at",)


class RiferimentoProcessoInline(admin.TabularInline):
    model = RiferimentoProcesso
    extra = 1
    fields = ("codice", "tipo", "note")


class AbilitazioneProcessoInline(admin.TabularInline):
    model = AbilitazioneProcesso
    extra = 0
    fields = (
        "legacy_anagrafica_id", "is_qualificato", "is_addetto",
        "is_controllore", "is_part145", "stato",
    )


@admin.register(ProcessoQualificato)
class ProcessoQualificatoAdmin(admin.ModelAdmin):
    list_display = (
        "nome", "cliente", "regime", "livello", "tipo_validita",
        "scadenza_effettiva", "stato",
    )
    list_filter = ("stato", "regime", "tipo_validita", "personale_modalita", "cliente")
    search_fields = ("nome", "cliente__nome", "riferimento_dichiarazione", "riferimenti__codice")
    autocomplete_fields = ()
    filter_horizontal = ("reparti", "clienti_addizionali")
    readonly_fields = ("created_at", "updated_at", "scadenza_effettiva")
    inlines = [RiferimentoProcessoInline, AbilitazioneProcessoInline]


class CertificazioneIndividualeInline(admin.TabularInline):
    model = CertificazioneIndividuale
    extra = 0
    fields = ("schema", "numero", "livello", "data_scadenza", "ente_certificatore", "stato")


@admin.register(AbilitazioneProcesso)
class AbilitazioneProcessoAdmin(admin.ModelAdmin):
    list_display = (
        "legacy_anagrafica_id", "processo", "is_qualificato",
        "is_addetto", "is_controllore", "is_part145", "stato",
    )
    list_filter = ("stato", "is_addetto", "is_controllore", "is_part145", "processo__cliente")
    search_fields = ("legacy_anagrafica_id", "processo__nome")
    readonly_fields = ("created_at", "updated_at")
    inlines = [CertificazioneIndividualeInline]


@admin.register(CertificazioneIndividuale)
class CertificazioneIndividualeAdmin(admin.ModelAdmin):
    list_display = ("abilitazione", "schema", "numero", "livello", "data_scadenza", "stato")
    list_filter = ("stato", "schema", "ente_certificatore")
    search_fields = ("numero", "schema", "abilitazione__legacy_anagrafica_id")
    readonly_fields = ("created_at",)


@admin.register(MpqStorico)
class MpqStoricoAdmin(admin.ModelAdmin):
    list_display = ("registrato_il", "evento", "processo", "abilitazione", "origine", "registrato_da")
    list_filter = ("origine",)
    search_fields = ("evento", "dettaglio", "processo__nome")
    readonly_fields = ("registrato_il", "registrato_da")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
