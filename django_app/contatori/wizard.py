"""Motore dei wizard guidati del modulo Contatori e wizard «Nuovo dispositivo SNMP».

Stato in sessione, una voce per wizard aperto (avanti/indietro senza perdere dati).
I campi segreti (community, chiavi v3) entrano in sessione solo cifrati con
``credential_crypto.cifra``. Nessun salvataggio a DB fino alla conferma, salvo la
bozza esplicita. Le chiamate SNMP avvengono sempre fuori da ``transaction.atomic``.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from . import errori_snmp
from .forms_wizard import (
    CAMPI_SEGRETI, PassoAssociazioneForm, PassoCredenzialiForm, PassoReteForm, PassoTipoForm,
)
from .models import CommunitySNMP, DispositivoSNMP, ImpostazioniSNMP, ProfiloSNMP, StatoSNMP

logger = logging.getLogger(__name__)

SESSIONE = "contatori_wizard"
MAX_APERTI = 5           # wizard aperti per sessione: i piu' vecchi vengono scartati
TEST_TIMEOUT = 3          # secondi per tentativo, 1 retry solo sul timeout
MAX_COLONNE_MAPPATURA = 40


@dataclass(frozen=True)
class Passo:
    chiave: str
    titolo: str
    descrizione: str
    form_class: type | None = None


class MotoreWizard:
    """Stato e navigazione; le sottoclassi definiscono ``tipo``, ``passi`` e la conferma."""
    tipo = ""
    titolo = ""
    passi: tuple[Passo, ...] = ()

    def __init__(self, request, wid):
        self.request = request
        self.wid = str(wid)
        self.stato = request.session.get(SESSIONE, {}).get(self.wid)
        if not self.stato or self.stato.get("tipo") != self.tipo:
            raise KeyError(self.wid)

    # --- ciclo di vita -----------------------------------------------------
    @classmethod
    def avvia(cls, request, iniziali=None):
        aperti = request.session.get(SESSIONE, {})
        if len(aperti) >= MAX_APERTI:
            for vecchio in sorted(aperti, key=lambda k: aperti[k].get("creato", ""))[:len(aperti) - MAX_APERTI + 1]:
                aperti.pop(vecchio)
        wid = str(uuid.uuid4())
        aperti[wid] = {"tipo": cls.tipo, "passo": 0, "dati": iniziali or {}, "extra": {},
                       "creato": timezone.now().isoformat()}
        request.session[SESSIONE] = aperti
        return wid

    def _salva(self):
        aperti = self.request.session.get(SESSIONE, {})
        aperti[self.wid] = self.stato
        self.request.session[SESSIONE] = aperti
        self.request.session.modified = True

    def chiudi(self):
        aperti = self.request.session.get(SESSIONE, {})
        aperti.pop(self.wid, None)
        self.request.session[SESSIONE] = aperti

    # --- navigazione -------------------------------------------------------
    @property
    def indice(self):
        return self.stato["passo"]

    @property
    def passo(self):
        return self.passi[self.indice]

    def vai(self, indice):
        self.stato["passo"] = max(0, min(indice, len(self.passi) - 1))
        self._salva()

    def extra(self, chiave):
        return self.stato["extra"].get(chiave)

    def imposta_extra(self, chiave, valore):
        self.stato["extra"][chiave] = valore
        self._salva()

    # --- dati dei passi ----------------------------------------------------
    def kwargs_form(self, chiave):
        return {}

    def dati(self, chiave):
        """Dati salvati del passo, con i segreti decifrati (solo in memoria)."""
        from .credential_crypto import decifra
        dati = dict(self.stato["dati"].get(chiave, {}))
        cifrati = dati.pop("_segreti", "")
        if cifrati:
            dati.update(json.loads(decifra(cifrati)))
        return dati

    def form(self, chiave, data=None):
        passo = next(p for p in self.passi if p.chiave == chiave)
        if passo.form_class is None:
            return None
        if data is None:
            # Modifiche non ancora valide lasciate tornando indietro hanno la precedenza.
            iniziali = {**self.dati(chiave), **self.stato.get("bozze", {}).get(chiave, {})}
            return passo.form_class(initial=iniziali, **self.kwargs_form(chiave))
        precedenti = self.dati(chiave)
        if (any(precedenti.get(n) for n in CAMPI_SEGRETI) and not data.get("community_salvata")
                and not data.get("usa_globale")):
            # PasswordInput non ripropone il valore: campo vuoto = mantieni quello gia' inserito.
            data = data.copy()
            for nome in CAMPI_SEGRETI:
                if not data.get(nome) and precedenti.get(nome):
                    data[nome] = precedenti[nome]
        return passo.form_class(data=data, **self.kwargs_form(chiave))

    def memorizza(self, chiave, form):
        """Salva i valori grezzi del form valido; i segreti solo cifrati."""
        from .credential_crypto import cifra
        precedenti = self.dati(chiave)
        # Credenziale scelta dal catalogo o globale: i segreti digitati prima si scartano.
        scelta_esplicita = bool(form.cleaned_data.get("community_salvata") or form.cleaned_data.get("usa_globale"))
        valori, segreti = {}, {}
        for nome in form.fields:
            valore = form[nome].value()
            if nome in CAMPI_SEGRETI:
                # PasswordInput non ripropone il valore: vuoto = mantieni il precedente.
                segreti[nome] = "" if scelta_esplicita else (valore or precedenti.get(nome, ""))
            else:
                valori[nome] = valore
        if any(segreti.values()):
            valori["_segreti"] = cifra(json.dumps(segreti))
        self.stato["dati"][chiave] = valori
        self.stato.setdefault("bozze", {}).pop(chiave, None)
        self._salva()

    def ricorda_bozza(self, chiave, form):
        """Valori non validi (mai i segreti) da riproporre quando si torna sul passo."""
        self.stato.setdefault("bozze", {})[chiave] = {
            nome: form[nome].value() for nome in form.fields if nome not in CAMPI_SEGRETI}
        self._salva()

    def form_valido(self, chiave):
        passo = next(p for p in self.passi if p.chiave == chiave)
        if passo.form_class is None:
            return None
        if chiave not in self.stato["dati"]:
            return None
        form = self.form(chiave, data=self.dati(chiave))
        return form if form.is_valid() else None

    def primo_passo_incompleto(self, fino_a=None):
        """Indice del primo passo con form non valido (riconvalida lato server)."""
        for i, passo in enumerate(self.passi[:fino_a]):
            if passo.form_class is not None and self.form_valido(passo.chiave) is None:
                return i
        return None


# --- Wizard «Nuovo dispositivo SNMP» ---------------------------------------------

class WizardDispositivo(MotoreWizard):
    tipo = "dispositivo"
    titolo = "Nuovo dispositivo SNMP"
    passi = (
        Passo("tipo", "Tipo e modello", "Che apparato è e, se lo conosci, il suo modello.", PassoTipoForm),
        Passo("rete", "Rete", "Dove si trova in rete e quale versione SNMP usa.", PassoReteForm),
        Passo("credenziali", "Credenziali", "Con cosa il portale si presenta all'apparato.",
              PassoCredenzialiForm),
        Passo("test", "Test di connessione", "Obbligatorio: il portale legge identità e modello."),
        Passo("mappatura", "Mappatura contatori", "Valori realmente letti per ogni colonna del profilo."),
        Passo("associazione", "Asset e reparto", "Collega il dispositivo al registro Asset.",
              PassoAssociazioneForm),
        Passo("riepilogo", "Riepilogo", "Controlla e conferma."),
    )
    TEST = 3  # indice del passo di test

    def memorizza(self, chiave, form):
        super().memorizza(chiave, form)
        if chiave == "rete":
            # Si salva l'IP gia' risolto: niente DNS a ogni rivalidazione e firma del test stabile
            # anche con DNS round-robin. Il nome digitato resta solo per la visualizzazione.
            self.stato["dati"]["rete"].update(host=form.cleaned_data["host"], nome_digitato=form.data.get("host", ""))
            self._salva()

    def kwargs_form(self, chiave):
        if chiave == "credenziali":
            return {"globale_disponibile": bool(ImpostazioniSNMP.get_solo().community)}
        return {}

    def form(self, chiave, data=None):
        form = super().form(chiave, data)
        if chiave == "credenziali" and form is not None:
            # La versione arriva dal passo «Rete»: unica fonte, il campo nascosto la ricalca.
            versione = (self.dati("rete").get("versione") or "v2c")
            if form.is_bound:
                form.data = form.data.copy() if hasattr(form.data, "copy") else dict(form.data)
                form.data["versione"] = versione
            else:
                form.initial["versione"] = versione
        return form

    # --- parametri risolti ---------------------------------------------------
    def parametri(self):
        """(host, porta, versione, segreto) dai passi validi; segreto mai salvato in chiaro."""
        from .credential_crypto import decifra
        rete, cred = self.form_valido("rete"), self.form_valido("credenziali")
        if rete is None or cred is None:
            return None
        versione = rete.cleaned_data["versione"]
        salvata = cred.cleaned_data.get("community_salvata")
        if cred._segreto_inline:
            segreto = cred._segreto_inline
        elif salvata is not None:
            segreto = decifra(salvata.segreto_cifrato)
        else:
            segreto = ImpostazioniSNMP.get_solo().community
        return rete.cleaned_data["host"], rete.cleaned_data["porta"], versione, segreto

    def firma(self):
        """Impronta di rete+credenziali: se cambiano dopo il test, il test va rifatto."""
        parametri = self.parametri()
        if parametri is None:
            return ""
        return salted_hmac("contatori.wizard.test", "|".join(map(str, parametri))).hexdigest()

    def test_valido(self):
        esito = self.extra("test") or {}
        return bool(esito.get("ok")) and esito.get("firma") == self.firma() != ""

    def profilo(self):
        tipo = self.form_valido("tipo")
        if tipo is not None and tipo.cleaned_data.get("profilo"):
            return tipo.cleaned_data["profilo"]
        rilevato = (self.extra("test") or {}).get("profilo_id")
        return ProfiloSNMP.objects.filter(pk=rilevato, attivo=True).first() if rilevato else None

    # --- azioni SNMP (fuori da transazioni) ------------------------------------
    def esegui_test(self):
        from .snmp import SNMPError, SYS_DESCR, SYS_OBJECT_ID, _testo, leggi_oids
        from .services import oid_riconoscimento_attivi, trova_profilo_snmp
        parametri = self.parametri()
        if parametri is None:
            return False
        host, porta, versione, segreto = parametri
        esito = {"ok": False, "firma": self.firma(), "quando": timezone.now().isoformat()}
        errore = None
        # Come il polling notturno: anche gli OID di riconoscimento dei profili, per i
        # modelli con sysObjectID generico. Un OID assente non fa fallire il test.
        sonde = [oid for oid in oid_riconoscimento_attivi() if oid not in (SYS_DESCR, SYS_OBJECT_ID)]
        for _tentativo in range(2):  # 1 retry, solo se il primo va in timeout
            try:
                valori, _errori = leggi_oids(host, [SYS_DESCR, SYS_OBJECT_ID, *sonde], community=segreto,
                                             port=porta, timeout=TEST_TIMEOUT, version=versione,
                                             max_duration=TEST_TIMEOUT + 2)
            except SNMPError as exc:
                errore = errori_snmp.da_eccezione(exc, host=host, porta=porta, timeout=TEST_TIMEOUT)
                if errore["codice"] != "SNMP-003":
                    break
                continue
            descr, object_id = _testo(valori.get(SYS_DESCR)), _testo(valori.get(SYS_OBJECT_ID))
            if not descr and not object_id:
                errore = errori_snmp.da_eccezione(errori_snmp.ErroreSNMPCatalogato(
                    "SNMP-005", "Il dispositivo risponde ma non espone sysDescr né sysObjectID."))
                break
            profilo = trova_profilo_snmp(sys_object_id=object_id, sys_description=descr,
                                         valori_riconoscimento={o: valori.get(o) for o in sonde if o in valori})
            esito.update(ok=True, sys_descr=descr[:500], sys_object_id=object_id[:255],
                         profilo_id=profilo.pk if profilo else None,
                         profilo_nome=str(profilo) if profilo else "")
            errore = None
            break
        if errore:
            esito["errore"] = errore
        self.imposta_extra("test", esito)
        self.imposta_extra("mappatura", None)  # valori letti con parametri vecchi: da rileggere
        return True

    def profilo_diverso_dal_rilevato(self):
        """Profilo scelto al passo 1 diverso da quello riconosciuto dal test (o None)."""
        tipo = self.form_valido("tipo")
        scelto = tipo.cleaned_data.get("profilo") if tipo is not None else None
        rilevato = (self.extra("test") or {}).get("profilo_id")
        if scelto and rilevato and scelto.pk != rilevato:
            return (self.extra("test") or {}).get("profilo_nome", "")
        return None

    def leggi_mappatura(self):
        from .snmp import SNMPError, leggi_specifiche
        profilo, parametri = self.profilo(), self.parametri()
        if profilo is None or parametri is None or not self.test_valido():
            return
        host, porta, versione, segreto = parametri
        colonne = list(profilo.colonne.filter(attiva=True).order_by("ordine", "pk")[:MAX_COLONNE_MAPPATURA])
        specifiche = [{"oid": c.oid, "modalita": c.modalita, "aggregazione": c.aggregazione} for c in colonne]
        try:
            valori, errori = leggi_specifiche(host, specifiche, community=segreto, port=porta,
                                              timeout=TEST_TIMEOUT, version=versione)
        except SNMPError as exc:
            valori, errori = {}, {c.oid: str(exc) for c in colonne}
        righe = []
        for c in colonne:
            riga = {"nome": c.nome, "oid": c.oid, "contatore": c.get_contatore_mfc_display() if c.contatore_mfc else "",
                    "valore": None, "errore": None}
            if c.oid in valori:
                riga["valore"] = str(valori[c.oid])[:120]
                if c.contatore_mfc:
                    try:
                        errori_snmp.valore_numerico(valori[c.oid], c.nome)
                    except errori_snmp.ErroreSNMPCatalogato as exc:
                        riga["errore"] = errori_snmp.da_eccezione(exc)
            else:
                riga["errore"] = errori_snmp.da_eccezione(errori_snmp.ErroreSNMPCatalogato(
                    errori_snmp.classifica(errori.get(c.oid, "")).codice,
                    errori.get(c.oid, "nessuna risposta")[:300]))
            righe.append(riga)
        self.imposta_extra("mappatura", {"profilo_id": profilo.pk, "righe": righe})

    def proposta_asset(self):
        from .services import trova_asset_snmp
        parametri = self.parametri()
        if parametri is None:
            return None, ""
        try:
            return trova_asset_snmp(host=parametri[0])
        except Exception:  # la proposta e' facoltativa: non deve bloccare il passo
            logger.exception("Proposta asset non disponibile nel wizard per %s", parametri[0])
            return None, ""

    # --- salvataggio -----------------------------------------------------------
    def _credenziale(self, host, cred):
        """CommunitySNMP da usare: quella scelta, oppure una nuova cifrata nel catalogo."""
        from .credential_crypto import cifra
        if cred._segreto_inline:
            versione = cred.cleaned_data["versione"]
            base = f"{'SNMPv3' if versione == 'v3' else 'Community'} dispositivo {host}"[:72]
            nome, n = base, 1
            # Mai sovrascrivere una voce esistente del catalogo: altri apparati potrebbero usarla.
            while CommunitySNMP.objects.filter(nome=nome).exists():
                n += 1
                nome = f"{base} ({n})"
            return CommunitySNMP.objects.create(nome=nome, versione=versione,
                                                segreto_cifrato=cifra(cred._segreto_inline))
        return cred.cleaned_data.get("community_salvata")

    def salva(self, *, bozza):
        """Crea il dispositivo. Senza bozza servono tutti i passi validi e il test superato."""
        tipo, rete = self.form_valido("tipo"), self.form_valido("rete")
        cred = self.form_valido("credenziali")
        assoc = self.form_valido("associazione")
        if tipo is None or rete is None or (not bozza and (cred is None or not self.test_valido())):
            raise ValueError("wizard incompleto")
        esito = self.extra("test") or {}
        verificato = self.test_valido()
        host = rete.cleaned_data["host"]
        with transaction.atomic():
            dispositivo = DispositivoSNMP(
                nome=tipo.cleaned_data["nome"], categoria=tipo.cleaned_data["categoria"], host=host,
                porta=rete.cleaned_data["porta"], versione=rete.cleaned_data["versione"],
                community_salvata=self._credenziale(host, cred) if cred is not None else None,
                profilo_snmp=self.profilo(), verificato=verificato,
                posizione=assoc.cleaned_data["posizione"] if assoc else "",
                note=assoc.cleaned_data["note"] if assoc else "",
                asset=assoc.cleaned_data["asset"] if assoc else None,
            )
            if verificato:
                dispositivo.snmp_stato = StatoSNMP.OK
                dispositivo.snmp_ultimo_controllo = timezone.now()
                dispositivo.sys_description = esito.get("sys_descr", "")
                dispositivo.sys_object_id = esito.get("sys_object_id", "")
            dispositivo.save()
            if dispositivo.profilo_snmp_id:
                from .services import applica_profilo_dispositivo
                applica_profilo_dispositivo(dispositivo, dispositivo.profilo_snmp)
        self.chiudi()
        return dispositivo


WIZARD = {WizardDispositivo.tipo: WizardDispositivo}
