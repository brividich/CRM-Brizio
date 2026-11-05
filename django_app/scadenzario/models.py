"""Scadenzario generale del portale.

Due parti:

1. **Scadenze generiche** (ex app «Scadenzario» Flask sul NAS): categorie con i
   destinatari degli avvisi, attività con scadenza, rinnovi registrati e registro
   degli avvisi inviati. È una delle fonti della pagina ``/scadenze``.
2. **Configurazione dello scadenzario**: per ogni voce del catalogo (fonte →
   tipo → elemento, vedi ``scadenzario/catalogo.py``) si decide se compare e chi
   la vede, per ruolo del portale, ruolo aziendale (organigramma) o persona.

Le chiavi delle voci sono testuali (``fonte``, ``fonte|tipo``,
``fonte|tipo|elemento``): il catalogo è dinamico, una voce nuova in un modulo
compare da sola senza migrazioni.
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.private_attachments import PrivateAttachmentStorage


def _add_months(giorno, mesi: int):
    from dateutil.relativedelta import relativedelta

    return giorno + relativedelta(months=int(mesi))


def _email_pulite(testo: str) -> list[str]:
    parti = [p.strip() for p in str(testo or "").replace(";", ",").replace("\n", ",").split(",")]
    visti, esito = set(), []
    for p in parti:
        if p and p.lower() != "none" and p.lower() not in visti:
            visti.add(p.lower())
            esito.append(p)
    return esito


class CategoriaScadenza(models.Model):
    nome = models.CharField(max_length=150, unique=True)
    descrizione = models.TextField(blank=True, default="")
    email_avviso = models.TextField(
        blank=True, default="",
        help_text="Indirizzi del riepilogo mensile della categoria, separati da virgola.",
    )
    preavviso_giorni = models.PositiveIntegerField(
        null=True, blank=True, help_text="Preavviso predefinito delle attività (vuoto = impostazione generale)."
    )
    ripeti_ogni_giorni = models.PositiveIntegerField(
        null=True, blank=True, help_text="Ogni quanti giorni ripetere l'avviso (vuoto = impostazione generale)."
    )
    avvisa_dopo_scadenza = models.BooleanField(
        default=True, help_text="Continua ad avvisare anche quando l'attività è scaduta e non rinnovata."
    )
    is_active = models.BooleanField(default=True)
    legacy_id = models.PositiveIntegerField(null=True, blank=True, unique=True, help_text="families.id del vecchio scadenzario")
    creato_il = models.DateTimeField(auto_now_add=True)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Categoria di scadenze"
        verbose_name_plural = "Categorie di scadenze"

    def __str__(self) -> str:
        return self.nome

    @property
    def destinatari(self) -> list[str]:
        return _email_pulite(self.email_avviso)


class ScadenzaGenerica(models.Model):
    categoria = models.ForeignKey(CategoriaScadenza, on_delete=models.PROTECT, related_name="scadenze")
    titolo = models.CharField(max_length=200)
    descrizione = models.TextField(blank=True, default="")
    ubicazione = models.CharField(max_length=200, blank=True, default="")
    ultimo_controllo = models.DateField(null=True, blank=True)
    validita_mesi = models.PositiveIntegerField(
        null=True, blank=True, help_text="Con l'ultimo controllo calcola la scadenza; al rinnovo la successiva."
    )
    data_scadenza = models.DateField(null=True, blank=True, db_index=True)
    preavviso_giorni = models.PositiveIntegerField(null=True, blank=True)
    ripeti_ogni_giorni = models.PositiveIntegerField(null=True, blank=True)
    email_avviso = models.TextField(
        blank=True, default="", help_text="Indirizzi dell'avviso della singola attività, separati da virgola."
    )
    responsabile = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="scadenze_generiche",
    )
    asset = models.ForeignKey(
        "assets.Asset", null=True, blank=True, on_delete=models.SET_NULL, related_name="scadenze_generiche",
    )
    fornitore = models.ForeignKey(
        "anagrafica.Fornitore", null=True, blank=True, on_delete=models.SET_NULL, related_name="scadenze_generiche",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    legacy_id = models.PositiveIntegerField(null=True, blank=True, unique=True, help_text="products.id del vecchio scadenzario")
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    creato_il = models.DateTimeField(auto_now_add=True)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["data_scadenza", "titolo", "pk"]
        verbose_name = "Scadenza generica"
        verbose_name_plural = "Scadenze generiche"

    def __str__(self) -> str:
        return self.titolo

    def clean(self):
        self.titolo = (self.titolo or "").strip()
        if not self.titolo:
            raise ValidationError({"titolo": "Inserisci il nome dell'attività."})

    def calcola_scadenza(self):
        """Scadenza dall'ultimo controllo e dalla validità; None se manca uno dei due."""
        if self.ultimo_controllo and self.validita_mesi:
            return _add_months(self.ultimo_controllo, self.validita_mesi)
        return None

    @property
    def destinatari(self) -> list[str]:
        return _email_pulite(self.email_avviso)

    def preavviso_effettivo(self, predefinito: int) -> int:
        for valore in (self.preavviso_giorni, self.categoria.preavviso_giorni):
            if valore is not None:
                return int(valore)
        return int(predefinito)

    def ripeti_effettivo(self, predefinito: int) -> int:
        for valore in (self.ripeti_ogni_giorni, self.categoria.ripeti_ogni_giorni):
            if valore is not None:
                return max(1, int(valore))
        return max(1, int(predefinito))

    def giorni_alla_scadenza(self, oggi=None) -> int | None:
        if not self.data_scadenza:
            return None
        return (self.data_scadenza - (oggi or timezone.localdate())).days


def _rinnovo_upload_to(instance, filename: str) -> str:
    import uuid
    from pathlib import Path

    suffisso = Path(filename or "").suffix.lower()[:10]
    return f"scadenzario/rinnovi/{instance.scadenza_id or 'tmp'}/{uuid.uuid4().hex}{suffisso}"


class RinnovoScadenza(models.Model):
    """Controllo/rinnovo eseguito: aggiorna l'ultimo controllo e la scadenza."""

    scadenza = models.ForeignKey(ScadenzaGenerica, on_delete=models.CASCADE, related_name="rinnovi")
    eseguito_il = models.DateField()
    scadenza_precedente = models.DateField(null=True, blank=True)
    nuova_scadenza = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    allegato = models.FileField(
        upload_to=_rinnovo_upload_to, blank=True, max_length=255,
        storage=PrivateAttachmentStorage(download_hint="Usa {% url 'scadenzario:rinnovo_allegato' r.id %}."),
    )
    allegato_nome = models.CharField(max_length=255, blank=True, default="")
    registrato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    registrato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-eseguito_il", "-pk"]
        verbose_name = "Rinnovo di una scadenza"
        verbose_name_plural = "Rinnovi delle scadenze"


class AvvisoInviato(models.Model):
    TIPO_ATTIVITA = "ATTIVITA"
    TIPO_RIEPILOGO = "RIEPILOGO"
    TIPO_CHOICES = [(TIPO_ATTIVITA, "Avviso attività"), (TIPO_RIEPILOGO, "Riepilogo categoria")]

    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default=TIPO_ATTIVITA)
    scadenza = models.ForeignKey(
        ScadenzaGenerica, null=True, blank=True, on_delete=models.CASCADE, related_name="avvisi",
    )
    categoria = models.ForeignKey(
        CategoriaScadenza, null=True, blank=True, on_delete=models.CASCADE, related_name="avvisi",
    )
    destinatari = models.TextField(blank=True, default="")
    riuscito = models.BooleanField(default=True)
    esito = models.CharField(max_length=500, blank=True, default="")
    inviato_il = models.DateTimeField(default=timezone.now, db_index=True)
    importato = models.BooleanField(default=False, help_text="Arriva dal registro del vecchio scadenzario")

    class Meta:
        ordering = ["-inviato_il", "-pk"]
        verbose_name = "Avviso inviato"
        verbose_name_plural = "Avvisi inviati"


class VoceConfig(models.Model):
    """Impostazione di una voce del catalogo (``fonte``, ``fonte|tipo``, ``fonte|tipo|elemento``).

    I campi vuoti ereditano dalla voce superiore; senza nessuna impostazione la
    voce compare e la vede chi ha già il permesso del modulo.
    """

    MODALITA_EREDITA = ""
    MODALITA_MODULO = "MODULO"
    MODALITA_REGOLE = "REGOLE"
    MODALITA_CHOICES = [
        (MODALITA_EREDITA, "Come la voce superiore"),
        (MODALITA_MODULO, "Chi ha il permesso del modulo, più le regole"),
        (MODALITA_REGOLE, "Solo chi è nelle regole"),
    ]

    chiave = models.CharField(max_length=300, unique=True)
    etichetta = models.CharField(max_length=300, blank=True, default="", help_text="Etichetta al momento del salvataggio")
    attiva = models.BooleanField(null=True, blank=True, help_text="Vuoto = come la voce superiore")
    modalita = models.CharField(max_length=10, choices=MODALITA_CHOICES, blank=True, default=MODALITA_EREDITA)
    aggiornato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["chiave"]
        verbose_name = "Impostazione voce dello scadenzario"
        verbose_name_plural = "Impostazioni voci dello scadenzario"

    def __str__(self) -> str:
        return self.chiave


class RegolaVisibilita(models.Model):
    """Chi vede (o gestisce) una voce e tutto ciò che sta sotto.

    Esattamente uno fra ruolo del portale, ruolo aziendale e persona.
    «Gestisce» conta solo per le scadenze generiche (inserire, modificare,
    rinnovare le attività della categoria).
    """

    LIVELLO_VEDE = "VEDE"
    LIVELLO_GESTISCE = "GESTISCE"
    LIVELLO_CHOICES = [(LIVELLO_VEDE, "Vede"), (LIVELLO_GESTISCE, "Vede e gestisce")]

    chiave = models.CharField(max_length=300, db_index=True)
    ruolo_portale = models.ForeignKey(
        "core.AccessGroup", null=True, blank=True, on_delete=models.CASCADE, related_name="regole_scadenzario",
    )
    ruolo_aziendale = models.ForeignKey(
        "anagrafica.RuoloOperativo", null=True, blank=True, on_delete=models.CASCADE, related_name="regole_scadenzario",
    )
    persona_legacy_id = models.PositiveIntegerField(null=True, blank=True, db_index=True, help_text="utenti.id")
    persona_nome = models.CharField(max_length=200, blank=True, default="")
    livello = models.CharField(max_length=10, choices=LIVELLO_CHOICES, default=LIVELLO_VEDE)
    creato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["chiave", "pk"]
        verbose_name = "Regola di visibilità dello scadenzario"
        verbose_name_plural = "Regole di visibilità dello scadenzario"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(ruolo_portale__isnull=False, ruolo_aziendale__isnull=True, persona_legacy_id__isnull=True)
                    | Q(ruolo_portale__isnull=True, ruolo_aziendale__isnull=False, persona_legacy_id__isnull=True)
                    | Q(ruolo_portale__isnull=True, ruolo_aziendale__isnull=True, persona_legacy_id__isnull=False)
                ),
                name="scadenzario_regola_un_solo_destinatario",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.chiave} → {self.destinatario_label}"

    @property
    def destinatario_label(self) -> str:
        if self.ruolo_portale_id:
            return f"Ruolo del portale: {self.ruolo_portale.label}"
        if self.ruolo_aziendale_id:
            return f"Ruolo aziendale: {self.ruolo_aziendale.nome}"
        return f"Persona: {self.persona_nome or self.persona_legacy_id}"

    @property
    def destinatario_breve(self) -> str:
        if self.ruolo_portale_id:
            return self.ruolo_portale.label
        if self.ruolo_aziendale_id:
            return self.ruolo_aziendale.nome
        return self.persona_nome or str(self.persona_legacy_id)


class PresaInCarico(models.Model):
    """Qualcuno ha detto «me ne occupo io» per una scadenza dello scadenzario globale.

    La chiave identifica la singola scadenza (fonte, tipo, link al modulo e data,
    vedi ``scadenzario.calendario.chiave_scadenza``): quando la scadenza si sposta
    (rinnovo, nuova data) la presa in carico non vale più da sola.
    """

    chiave = models.CharField(max_length=64, unique=True)
    descrizione = models.CharField(max_length=400, blank=True, default="", help_text="Scadenza al momento della presa in carico")
    data_scadenza = models.DateField(null=True, blank=True)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scadenze_in_carico")
    nota = models.CharField(max_length=300, blank=True, default="")
    creato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creato_il", "-pk"]
        verbose_name = "Scadenza presa in carico"
        verbose_name_plural = "Scadenze prese in carico"

    def __str__(self) -> str:
        return f"{self.descrizione} → {self.utente}"


class VistaSalvata(models.Model):
    """Combinazione di filtri dello scadenzario salvata da una persona."""

    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="viste_scadenzario")
    nome = models.CharField(max_length=80)
    parametri = models.CharField(max_length=1000, blank=True, default="", help_text="Querystring dei filtri (chiavi ammesse)")
    predefinita = models.BooleanField(default=False)
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome", "pk"]
        verbose_name = "Vista salvata dello scadenzario"
        verbose_name_plural = "Viste salvate dello scadenzario"
        constraints = [
            models.UniqueConstraint(fields=["utente", "nome"], name="scadenzario_vista_nome_unico"),
        ]

    def __str__(self) -> str:
        return self.nome


class FotoScadenze(models.Model):
    """Fotografia giornaliera dei numeri dello scadenzario, per fonte (andamento nel tempo)."""

    data = models.DateField(db_index=True)
    fonte = models.CharField(max_length=40)
    scadute = models.PositiveIntegerField(default=0)
    entro_30 = models.PositiveIntegerField(default=0)
    totale = models.PositiveIntegerField(default=0, help_text="Scadute + prossimi 90 giorni")

    class Meta:
        ordering = ["data", "fonte"]
        verbose_name = "Fotografia dello scadenzario"
        verbose_name_plural = "Fotografie dello scadenzario"
        constraints = [
            models.UniqueConstraint(fields=["data", "fonte"], name="scadenzario_foto_data_fonte"),
        ]

    def __str__(self) -> str:
        return f"{self.data} {self.fonte}: {self.scadute} scadute"
