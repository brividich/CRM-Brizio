"""Wizard per profilo SNMP, colonna di profilo e lettore OID (sonda) di un dispositivo.

Ogni passo e' un ModelForm sul sottoinsieme di campi del passo; alla conferma
l'oggetto viene ricostruito da tutti i passi e passa da ``full_clean`` (anche i
vincoli di unicita'): nessuna entita' incoerente arriva al DB.
"""
from __future__ import annotations

import re

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms import modelform_factory
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.text import slugify

from . import errori_snmp
from .forms import SezioniFormMixin
from .models import ColonnaProfiloSNMP, DispositivoSNMP, Macchina, ProfiloSNMP, SondaSNMP
from .wizard import TEST_TIMEOUT, MotoreWizard, Passo

CAMPI_SOGLIE = ("soglia_warning_min", "soglia_warning_max", "soglia_critica_min", "soglia_critica_max")


class _BasePasso(SezioniFormMixin, forms.ModelForm):
    """Etichette leggibili e controlli che dipendono solo dai campi del passo."""

    def clean(self):
        data = super().clean()
        pattern = data.get("sys_descr_pattern")
        if pattern:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                self.add_error("sys_descr_pattern", f"Espressione regolare non valida: {exc}")
        for campo_min, campo_max, etichetta in (("soglia_warning_min", "soglia_warning_max", "di avviso"),
                                                ("soglia_critica_min", "soglia_critica_max", "critica")):
            minimo, massimo = data.get(campo_min), data.get(campo_max)
            if minimo is not None and massimo is not None and minimo > massimo:
                self.add_error(campo_max, f"La soglia massima {etichetta} deve essere ≥ della minima.")
        return data


def _passo(modello, campi, **attrs):
    return modelform_factory(modello, form=_BasePasso, fields=campi, **attrs)


class WizardModello(MotoreWizard):
    """Oggetto ricostruito dai passi: ``modello`` + chiavi esterne del contesto."""
    modello = None

    def istanza(self):
        obj = self.modello(**self.chiavi_contesto())
        campi_modello = {f.name for f in self.modello._meta.get_fields()}
        for passo in self.passi:
            if passo.form_class is None:
                continue
            form = self.form_valido(passo.chiave)
            if form is None:
                return None
            for nome, valore in form.cleaned_data.items():
                if nome in campi_modello:
                    setattr(obj, nome, valore)
        return obj

    # (chiave del contesto, modello): l'oggetto di partenza deve esistere ancora.
    contesto_richiesto = None

    def __init__(self, request, wid):
        super().__init__(request, wid)
        if self.contesto_richiesto:
            chiave, modello = self.contesto_richiesto
            if not modello.objects.filter(pk=self.ctx.get(chiave)).exists():
                self.chiudi()
                raise KeyError(self.wid)  # la view lo tratta come wizard scaduto

    def chiavi_contesto(self):
        return {}

    def completa(self, obj):
        """Ritocchi prima del salvataggio: in fondo all'ordine delle colonne/sonde esistenti."""
        from django.db.models import Max
        if "ordine" in {f.name for f in self.modello._meta.get_fields()} and self.chiavi_contesto():
            massimo = self.modello.objects.filter(**self.chiavi_contesto()).aggregate(m=Max("ordine"))["m"]
            obj.ordine = (massimo or 0) + 1

    def salva(self, *, bozza):
        obj = self.istanza()
        if obj is None:
            raise ValueError("wizard incompleto")
        self.completa(obj)
        obj.full_clean()  # ValidationError gestita dalla view: resta nel wizard
        with transaction.atomic():
            obj.save()
        self.chiudi()
        return obj

    def riepilogo(self):
        obj = self.istanza()
        if obj is None:
            return []
        righe = []
        campi_modello = {f.name for f in self.modello._meta.get_fields()}
        for passo in self.passi:
            if passo.form_class is None:
                continue
            form = self.form_valido(passo.chiave)
            for nome in form.fields:
                valore = form.cleaned_data.get(nome)
                if nome not in campi_modello or valore in (None, ""):
                    continue
                display = getattr(obj, f"get_{nome}_display", None)
                righe.append((form.fields[nome].label, display() if display else valore))
        return righe


# --- Profilo SNMP -------------------------------------------------------------------

PassoProfiloForm = _passo(ProfiloSNMP, ["nome", "slug", "produttore", "categoria", "famiglia_modelli", "descrizione"],
                          widgets={"descrizione": forms.Textarea(attrs={"rows": 3})})
PassoRiconoscimentoForm = _passo(ProfiloSNMP, ["sys_object_id_prefix", "sys_descr_pattern", "oid_riconoscimento"])
PassoParametriProfiloForm = _passo(ProfiloSNMP, ["versione", "porta", "timeout", "note"],
                                   widgets={"note": forms.Textarea(attrs={"rows": 3})})


class _ProfiloForm(PassoProfiloForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["slug"].help_text = "Vuoto = ricavato dal nome."

    def clean(self):
        data = super().clean()
        if not data.get("slug") and data.get("nome"):
            base = slugify(f"{data.get('produttore', '')} {data['nome']}")[:70] or "profilo"
            slug, n = base, 1
            while ProfiloSNMP.objects.filter(slug=slug).exists():
                n += 1
                slug = f"{base}-{n}"
            data["slug"] = slug
        return data


class WizardProfilo(WizardModello):
    tipo = "profilo"
    titolo = "Nuovo profilo SNMP"
    modello = ProfiloSNMP
    passi = (
        Passo("profilo", "Profilo", "Produttore, modelli coperti e categoria.", _ProfiloForm),
        Passo("riconoscimento", "Riconoscimento", "Come il portale associa il profilo a un apparato trovato "
              "in rete. Sotto vedi quali apparati già registrati verrebbero riconosciuti.", PassoRiconoscimentoForm),
        Passo("parametri", "Parametri SNMP", "Vuoti = configurazione globale.", PassoParametriProfiloForm),
        Passo("riepilogo", "Riepilogo", "Dopo la conferma aggiungi le colonne (OID) con il wizard dedicato."),
    )

    def url_annulla(self):
        return reverse("contatori:snmp_profili")

    def contesto_passo(self, chiave):
        if chiave != "riconoscimento":
            return {}
        form = self.form_valido("riconoscimento") or self.form("riconoscimento")
        dati = form.cleaned_data if form.is_bound and form.is_valid() else self.dati("riconoscimento")
        prefisso = str(dati.get("sys_object_id_prefix") or "").strip().lstrip(".")
        pattern = dati.get("sys_descr_pattern") or ""
        if not prefisso and not pattern:
            return {"riconosciuti": None}
        try:
            regex = re.compile(pattern, re.IGNORECASE) if pattern else None
        except re.error:
            regex = None
        riconosciuti = []
        for d in DispositivoSNMP.objects.exclude(sys_object_id="", sys_description="").only(
                "pk", "nome", "sys_object_id", "sys_description")[:500]:
            oid = (d.sys_object_id or "").lstrip(".")
            if (prefisso and (oid == prefisso or oid.startswith(prefisso + "."))) or (
                    regex and regex.search((d.sys_description or "")[:300])):  # testo limitato: regex sicura
                riconosciuti.append(d)
        return {"riconosciuti": riconosciuti[:20]}

    def fine(self, obj, *, bozza):
        return (reverse("contatori:snmp_profilo_edit", args=[obj.pk]), "success",
                f"Profilo «{obj.nome}» creato: ora aggiungi le colonne con «+ Colonna guidata».",
                "snmp_profilo_creato_wizard", {"slug": obj.slug})


# --- Colonna di profilo e lettore OID ----------------------------------------------

CAMPI_OID = ["nome", "oid", "modalita", "aggregazione"]


class _ProvaForm(forms.Form):
    """Apparato su cui provare l'OID: dispositivi SNMP o MFC con indirizzo."""
    bersaglio = forms.ChoiceField(label="Apparato su cui provare l'OID", required=False)

    def __init__(self, *args, profilo_pk=None, **kwargs):
        super().__init__(*args, **kwargs)
        scelte = [("", "— nessuna prova: la colonna resta «non verificata» —")]
        dispositivi = DispositivoSNMP.objects.filter(attivo=True).order_by("nome")
        if profilo_pk:  # prima chi usa gia' il profilo
            dispositivi = sorted(dispositivi, key=lambda d: d.profilo_snmp_id != profilo_pk)
        scelte += [(f"d:{d.pk}", f"{d.nome} · {d.host}") for d in dispositivi]
        scelte += [(f"m:{m.pk}", f"MFC {m.reparto} · {m.host}")
                   for m in Macchina.objects.filter(attiva=True, host__isnull=False).order_by("reparto")]
        self.fields["bersaglio"].choices = scelte
        self.fields["bersaglio"].widget.attrs["class"] = "js-searchable"


class ProvaOIDMixin:
    """Passo «prova»: lettura reale dell'OID (GET/WALK) su un apparato, fuori da transazioni."""
    azioni = {"prova": ("prova", "esegui_prova")}

    def bersaglio(self):
        valore = self.dati("prova").get("bersaglio") or ""
        tipo, _, pk = valore.partition(":")
        if not pk.isdigit():
            return None
        modello = DispositivoSNMP if tipo == "d" else Macchina if tipo == "m" else None
        return modello.objects.filter(pk=int(pk)).first() if modello else None

    def firma_prova(self):
        oid, obj = self.form_valido("oid"), self.bersaglio()
        if oid is None or obj is None:
            return ""
        d = oid.cleaned_data
        return salted_hmac("contatori.wizard.prova",
                           f"{d['oid']}|{d['modalita']}|{d['aggregazione']}|{obj._meta.model_name}:{obj.pk}").hexdigest()

    def prova_valida(self):
        esito = self.extra("prova") or {}
        return bool(esito.get("ok")) and esito.get("firma") == self.firma_prova() != ""

    def esegui_prova(self):
        from .models import ImpostazioniSNMP
        from .services import _community_snmp, _parametri_snmp
        from .snmp import SNMPError, leggi_specifiche
        form = self.form("prova", data=self.request.POST)
        if not form.is_valid():
            # Mai provare in silenzio sull'apparato scelto in precedenza.
            return "Apparato non valido o non più disponibile: scegline un altro dall'elenco."
        self.memorizza("prova", form)
        oid, obj = self.form_valido("oid"), self.bersaglio()
        if oid is None:
            return "Completa prima il passo «OID»."
        if obj is None or not obj.host:
            return "Scegli un apparato con indirizzo IP su cui provare l'OID."
        cfg = ImpostazioniSNMP.get_solo()
        porta, timeout, versione = _parametri_snmp(obj, cfg)
        d = oid.cleaned_data
        esito = {"ok": False, "firma": self.firma_prova(), "bersaglio": str(obj), "quando": timezone.now().isoformat()}
        try:
            valori, errori = leggi_specifiche(
                obj.host, [{"oid": d["oid"], "modalita": d["modalita"], "aggregazione": d["aggregazione"]}],
                community=_community_snmp(obj, cfg), port=porta, timeout=min(timeout, TEST_TIMEOUT),
                version=versione)
        except SNMPError as exc:
            valori, errori = {}, {d["oid"]: errori_snmp.testo_con_codice(exc)}
        if d["oid"] in valori:
            valore = valori[d["oid"]]
            testo = valore.decode("latin-1", "replace") if isinstance(valore, bytes) else str(valore)
            try:
                errori_snmp.valore_numerico(valore, d["nome"])
                numerico = True
            except errori_snmp.ErroreSNMPCatalogato:
                numerico = False
            esito.update(ok=True, valore=testo[:200], numerico=numerico)
        else:
            testo = errori.get(d["oid"], "nessuna risposta")
            esito["errore"] = errori_snmp.da_eccezione(
                errori_snmp.ErroreSNMPCatalogato(errori_snmp.classifica(testo).codice, testo[:300]))
        self.imposta_extra("prova", esito)
        return ""

    def contesto_passo(self, chiave):
        return {"prova": self.extra("prova"), "prova_valida": self.prova_valida()}

    def audit_prova(self):
        esito = self.extra("prova") or {}
        oid = self.form_valido("oid")
        return {"oid": oid.cleaned_data["oid"] if oid else "", "bersaglio": esito.get("bersaglio", ""),
                "esito": "ok" if esito.get("ok") else (esito.get("errore") or {}).get("codice", "")}

    def errore_valore(self, valore_form):
        """SNMP-006 se un contatore MFC e' stato provato con un valore non numerico."""
        esito = self.extra("prova") or {}
        if valore_form.cleaned_data.get("contatore_mfc") and self.prova_valida() and not esito.get("numerico"):
            return ("[SNMP-006] Il valore letto in prova non è un numero: questo OID non può essere "
                    "un contatore MFC.")
        return ""


class WizardColonna(ProvaOIDMixin, WizardModello):
    tipo = "colonna"
    titolo = "Nuova colonna del profilo"
    modello = ColonnaProfiloSNMP
    contesto_richiesto = ("profilo", ProfiloSNMP)
    passi = (
        Passo("oid", "OID", "Nome e OID da leggere; WALK per le colonne MIB (es. porte).",
              _passo(ColonnaProfiloSNMP, CAMPI_OID)),
        Passo("prova", "Prova sull'apparato", "Facoltativa ma consigliata: se riesce la colonna è «verificata».",
              _ProvaForm),
        Passo("valore", "Interpretazione", "Tipo del valore, unità, fattore e se è un contatore MFC.",
              _passo(ColonnaProfiloSNMP, ["tipo_valore", "unita", "fattore", "contatore_mfc", "etichette"])),
        Passo("soglie", "Soglie", "Lascia vuoto per non segnalare.", _passo(ColonnaProfiloSNMP, list(CAMPI_SOGLIE))),
        Passo("riepilogo", "Riepilogo", "Controlla e conferma."),
    )

    @classmethod
    def da_query(cls, get):
        pk = get.get("profilo", "")
        if not pk.isdigit() or not ProfiloSNMP.objects.filter(pk=int(pk)).exists():
            raise ValueError("profilo")
        return {}, {"profilo": int(pk)}

    def profilo_snmp(self):
        return ProfiloSNMP.objects.get(pk=self.ctx["profilo"])

    def chiavi_contesto(self):
        return {"profilo_id": self.ctx["profilo"]}

    def kwargs_form(self, chiave):
        return {"profilo_pk": self.ctx["profilo"]} if chiave == "prova" else {}

    def blocco(self, chiave):
        oid = self.form_valido("oid")
        if chiave == "oid" and oid and ColonnaProfiloSNMP.objects.filter(
                profilo_id=self.ctx["profilo"], oid=oid.cleaned_data["oid"]).exists():
            return "Questo OID è già una colonna del profilo."
        valore = self.form_valido("valore")
        if chiave == "valore" and valore:
            contatore = valore.cleaned_data.get("contatore_mfc")
            if contatore and ColonnaProfiloSNMP.objects.filter(profilo_id=self.ctx["profilo"],
                                                               contatore_mfc=contatore).exists():
                return "Il profilo ha già una colonna per questo contatore MFC."
            return self.errore_valore(valore)
        return ""

    def contesto_passo(self, chiave):
        return {**super().contesto_passo(chiave), "titolo_contesto": f"Profilo {self.profilo_snmp()}"}

    def url_annulla(self):
        return reverse("contatori:snmp_profilo_edit", args=[self.ctx["profilo"]])

    def completa(self, obj):
        super().completa(obj)
        esito = self.extra("prova") or {}
        if self.prova_valida():
            obj.verificata = True
            obj.fonte = f"Wizard {timezone.localdate():%d/%m/%Y} su {esito.get('bersaglio', '')}"[:200]

    def fine(self, obj, *, bozza):
        stato = "verificata" if obj.verificata else "non verificata"
        return (reverse("contatori:snmp_profilo_edit", args=[obj.profilo_id]), "success",
                f"Colonna «{obj.nome}» aggiunta ({stato}). I dispositivi che usano il profilo la ricevono "
                "alla prossima applicazione del profilo.", "snmp_colonna_creata_wizard",
                {"profilo": obj.profilo_id, "oid": obj.oid, "verificata": obj.verificata})


class _ProvaSondaForm(forms.Form):
    """La sonda si prova sempre sul suo dispositivo: nessuna scelta."""
    bersaglio = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, profilo_pk=None, **kwargs):
        super().__init__(*args, **kwargs)


class WizardSonda(ProvaOIDMixin, WizardModello):
    tipo = "sonda"
    titolo = "Nuovo lettore OID"
    modello = SondaSNMP
    contesto_richiesto = ("dispositivo", DispositivoSNMP)
    passi = (
        Passo("oid", "OID", "Nome e OID da leggere su questo dispositivo.", _passo(SondaSNMP, CAMPI_OID)),
        Passo("prova", "Prova sul dispositivo", "Obbligatoria: l'OID deve rispondere.", _ProvaSondaForm),
        Passo("valore", "Interpretazione", "Tipo del valore, unità e fattore.",
              _passo(SondaSNMP, ["tipo_valore", "unita", "fattore", "etichette"])),
        Passo("soglie", "Soglie", "Lascia vuoto per non segnalare.", _passo(SondaSNMP, list(CAMPI_SOGLIE))),
        Passo("riepilogo", "Riepilogo", "Controlla e conferma."),
    )

    @classmethod
    def da_query(cls, get):
        pk = get.get("dispositivo", "")
        if not pk.isdigit() or not DispositivoSNMP.objects.filter(pk=int(pk)).exists():
            raise ValueError("dispositivo")
        return {"prova": {"bersaglio": f"d:{pk}"}}, {"dispositivo": int(pk)}

    def chiavi_contesto(self):
        return {"dispositivo_id": self.ctx["dispositivo"]}

    def form(self, chiave, data=None):
        if chiave == "prova" and data is not None:
            data = {"bersaglio": f"d:{self.ctx['dispositivo']}"}  # mai un altro apparato
        if chiave == "prova" and data is None:
            return _ProvaSondaForm(initial={"bersaglio": f"d:{self.ctx['dispositivo']}"})
        return super().form(chiave, data)

    def blocco(self, chiave):
        oid = self.form_valido("oid")
        if chiave == "oid" and oid and SondaSNMP.objects.filter(
                dispositivo_id=self.ctx["dispositivo"], oid=oid.cleaned_data["oid"]).exists():
            return "Questo OID è già configurato per il dispositivo."
        if chiave == "prova" and not self.prova_valida():
            return "Esegui la prova e fai in modo che l'OID risponda: senza prova riuscita il lettore non si crea."
        return ""

    def contesto_passo(self, chiave):
        dispositivo = DispositivoSNMP.objects.get(pk=self.ctx["dispositivo"])
        return {**super().contesto_passo(chiave), "titolo_contesto": f"Dispositivo {dispositivo.nome}"}

    def url_annulla(self):
        return reverse("contatori:snmp_dispositivo", args=[self.ctx["dispositivo"]])

    def fine(self, obj, *, bozza):
        return (reverse("contatori:snmp_dispositivo", args=[obj.dispositivo_id]), "success",
                f"Lettore OID «{obj.nome}» aggiunto e verificato.", "snmp_sonda_creata_wizard",
                {"dispositivo": obj.dispositivo_id, "oid": obj.oid})


__all__ = ["WizardProfilo", "WizardColonna", "WizardSonda", "ValidationError"]
