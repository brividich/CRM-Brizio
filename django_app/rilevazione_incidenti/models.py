from __future__ import annotations

from django.db import models


class RilevazioneIncidente(models.Model):
    """Archivio locale rilevazioni sicurezza (fallback quando SharePoint non è configurato)."""

    nominativo = models.CharField(max_length=255)
    tipologia_scheda = models.CharField(max_length=50)  # Unsafe Condition / Unsafe Act / Near Miss / Accident
    reparto = models.CharField(max_length=150, blank=True)
    data_segnalazione = models.DateTimeField(null=True, blank=True)

    descrizione_attivita = models.TextField(blank=True)
    descrizione_avvenimento = models.TextField(blank=True)

    usa_macchina = models.BooleanField(default=False)
    nome_macchina = models.CharField(max_length=300, blank=True)
    buono_stato_macchina = models.BooleanField(default=False)
    utilizzo_dpi = models.BooleanField(default=False)
    prima_volta = models.BooleanField(default=False)

    persone_coinvolte = models.CharField(max_length=100, blank=True)
    causa_evento = models.CharField(max_length=200, blank=True)
    altre_cause = models.TextField(blank=True)
    misure_tecniche = models.BooleanField(default=False)
    quali_misure = models.TextField(blank=True)

    approvazione_rls = models.CharField(max_length=50, blank=True)
    note_preposto = models.TextField(blank=True)
    note_rspp = models.TextField(blank=True)
    data_approvazione_rls = models.DateField(null=True, blank=True)
    chiusura_rspp = models.BooleanField(default=False)
    data_chiusura_rspp = models.DateField(null=True, blank=True)

    why_1 = models.TextField(blank=True)
    why_2 = models.TextField(blank=True)
    why_3 = models.TextField(blank=True)
    why_4 = models.TextField(blank=True)
    why_5 = models.TextField(blank=True)
    partecipanti = models.TextField(blank=True)

    contatore = models.IntegerField(default=0)
    id_originale = models.IntegerField(null=True, blank=True, help_text="ID originale da CSV/SharePoint")

    class Meta:
        verbose_name = "Rilevazione Incidente"
        verbose_name_plural = "Rilevazioni Incidenti"
        ordering = ["-data_segnalazione"]

    def __str__(self) -> str:
        return f"{self.tipologia_scheda} – {self.nominativo} ({self.data_segnalazione})"

    def as_sp_fields(self) -> dict:
        """Restituisce un dict con i nomi-campo SharePoint usati nei template."""
        date_str = self.data_segnalazione.isoformat() if self.data_segnalazione else ""
        return {
            "Nominativo": self.nominativo,
            "Tipologia_scheda": self.tipologia_scheda,
            "Reparto": self.reparto,
            "Reparto_txt": self.reparto,
            "Data_e_ora_rilevazione": date_str,
            "Descrizione_x0020_attivit_x00e0__x0020_che_x0020_venivano_x0020_svolte_x0020_durante_x0020_l_x0027_accaduto": self.descrizione_attivita,
            "Descrizione_x0020_avvenimento": self.descrizione_avvenimento,
            "Incidenti_causato_da_uso_macchina_x0020_": self.usa_macchina,
            "Nome_x0020_macchina_x002F_attrezzatura_e_utilizzo": self.nome_macchina,
            "Buono_x0020_stato_x0020_macchina_x002F_attrezzatura": self.buono_stato_macchina,
            "Utilizzo_x0020_DPI_x0020_previsti": self.utilizzo_dpi,
            "Prima_x0020_volta_x0020_quasi_x0020_incidente": self.prima_volta,
            "Persone_x0020_coinvolte": self.persone_coinvolte,
            "Causa_x0020_che_x0020_ha_x0020_determinato_x0020_l_x0027_evento": self.causa_evento,
            "Altre_x0020_cause": self.altre_cause,
            "Misure_x0020_tecniche_x002C__x0020_organizzative_x0020_o_x0020_procedurali_x0020_per_x0020_evitare_x0020_che_x0020_possa_x0020_riaccedere_x0020_questo_x0020_genere_x0020_di_x0020_evento": self.misure_tecniche,
            "Quali_x0020_misure_x0020_adottare": self.quali_misure,
            "Approvazione_RLS": self.approvazione_rls,
            "Note_x0020_preposto": self.note_preposto,
            "Note_RSPP_x0020__x002F__x0020_ASPP": self.note_rspp,
            "Data_approvazione_RLS": self.data_approvazione_rls.isoformat() if self.data_approvazione_rls else "",
            "Chiusura_RSPP": self.chiusura_rspp,
            "Data_chiusura_RSPP": self.data_chiusura_rspp.isoformat() if self.data_chiusura_rspp else "",
            "x31__x0020_WHY": self.why_1,
            "x32__x0020_WHY": self.why_2,
            "x33__x0020_WHY": self.why_3,
            "x34__x0020_WHY": self.why_4,
            "x35__x0020_WHY": self.why_5,
            "Partecipanti": self.partecipanti,
        }


class SicurezzaImpostazioni(models.Model):
    """Singleton: configurazione del modulo Sicurezza."""

    sharepoint_site_id = models.CharField(
        max_length=300,
        blank=True,
        help_text="ID sito SharePoint (es. tuodominio.sharepoint.com,{guid},{guid})",
    )
    sharepoint_list_id = models.CharField(
        max_length=200,
        blank=True,
        default="7B90d47760-aa13-459c-86e5-ba1fd97bdddc",
        help_text="ID lista SharePoint delle rilevazioni sicurezza",
    )
    acl_preposti = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Lista di username o email autorizzati alla creazione/modifica segnalazioni "
            "(capireparto, preposti). Lasciare vuoto = accesso aperto a tutti."
        ),
    )
    acl_rspp = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Lista di username o email RSPP/ASPP abilitati all'approvazione e chiusura. "
            "Lasciare vuoto = nessuno (solo admin)."
        ),
    )
    reparti_custom = models.JSONField(
        default=list,
        blank=True,
        help_text="Lista reparti personalizzata (uno per riga). Vuota = usa lista predefinita.",
    )
    cause_evento_custom = models.JSONField(
        default=list,
        blank=True,
        help_text="Lista cause evento personalizzata (una per riga). Vuota = usa lista predefinita.",
    )

    class Meta:
        verbose_name = "Impostazioni Sicurezza"
        verbose_name_plural = "Impostazioni Sicurezza"
        constraints = [
            models.CheckConstraint(check=models.Q(pk=1), name="sicurezzaimpostazioni_singleton"),
        ]

    def __str__(self) -> str:
        return "Impostazioni Sicurezza"

    @classmethod
    def get_singleton(cls) -> "SicurezzaImpostazioni":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
