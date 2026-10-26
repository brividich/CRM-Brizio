from __future__ import annotations

import ipaddress

from django import forms

from . import regole
from .models import AmministratoreSistema, ApparatoInfra, FonteLog, Impostazioni, Indagine, VerificaAnnuale


class _Data(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class ImpostazioniForm(forms.ModelForm):
    class Meta:
        model = Impostazioni
        fields = ["attivo", "conservazione_mesi", "cartella_archivio", "copia_cartella", "copia_sharepoint",
                  "syslog_attivo", "syslog_indirizzo", "syslog_porta", "syslog_tcp", "orario_inizio", "orario_fine",
                  "controlli_lavoratori_ok", "controlli_lavoratori_nota", "account_raccoglitori"]
        labels = {
            "attivo": "Raccolta accesa",
            "account_raccoglitori": "Account dei raccoglitori di log",
            "conservazione_mesi": "Conservazione (mesi)",
            "cartella_archivio": "Cartella dell'archivio",
            "copia_cartella": "Seconda copia su cartella di rete",
            "copia_sharepoint": "Seconda copia su SharePoint (cartella dell'audit)",
            "syslog_attivo": "Ricevi syslog (ESXi, switch, firewall, NAS)",
            "syslog_indirizzo": "Indirizzo di ascolto",
            "syslog_porta": "Porta",
            "syslog_tcp": "Anche TCP (oltre a UDP)",
            "orario_inizio": "Dalle",
            "orario_fine": "Alle",
            "controlli_lavoratori_ok": "Informativa ai dipendenti e accordi verificati",
            "controlli_lavoratori_nota": "Riferimento (documento, data, chi ha verificato)",
        }
        help_texts = {
            "conservazione_mesi": "Minimo 6 mesi (Garante). Consigliati 12: coprono la verifica annuale.",
            "cartella_archivio": "Vuota = cartella privata del portale. Su un altro disco del server, non su una share.",
            "copia_cartella": "Es. \\\\nas\\registro-log. L'account del raccoglitore deve poterci scrivere.",
            "orario_fine": "Gli accessi degli amministratori fuori da questo orario (e nel fine settimana) vengono evidenziati.",
            "controlli_lavoratori_ok": "Serve per accendere accessi ai file, stampe e USB sulle fonti: sono controlli "
                                       "sull'attività dei lavoratori (art. 4 L. 300/1970, GDPR). Verificare con il DPO "
                                       "informativa, regolamento informatico ed eventuale accordo sindacale.",
            "controlli_lavoratori_nota": "Es. «Regolamento IT rev. 3 del 10/11/2026, parere DPO».",
            "account_raccoglitori": "Es. svc-businesslog, svc-registro (separati da virgola). Sono i programmi che leggono "
                                    "i registri di tutti i server ogni pochi minuti: i loro accessi restano nell'archivio "
                                    "ma non riempiono gli «accessi degli amministratori», e lo svuotamento del registro fatto "
                                    "da loro non è un allarme. L'account con cui gira questo raccoglitore vale già.",
        }
        widgets = {"orario_inizio": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
                   "orario_fine": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}

    def clean_conservazione_mesi(self):
        mesi = self.cleaned_data["conservazione_mesi"]
        if mesi < 6:
            raise forms.ValidationError("Il provvedimento del Garante chiede almeno 6 mesi.")
        if mesi > 120:
            raise forms.ValidationError("Al massimo 120 mesi.")
        return mesi

    def clean_syslog_indirizzo(self):
        v = (self.cleaned_data.get("syslog_indirizzo") or "0.0.0.0").strip()
        try:
            ipaddress.ip_address(v)
        except ValueError as exc:
            raise forms.ValidationError("Serve un indirizzo IP del server (0.0.0.0 = tutte le schede di rete).") from exc
        return v

    def clean_syslog_porta(self):
        p = self.cleaned_data["syslog_porta"]
        if not 1 <= p <= 65535:
            raise forms.ValidationError("Porta non valida.")
        return p


class FonteForm(forms.ModelForm):
    class Meta:
        model = FonteLog
        fields = ["nome", "tipo", "ruolo", "host", "ou_pc", "indirizzi_ip", "canali", "eventi", "silenzio_max_ore", "attiva",
                  "audit_file", "cartelle_file", "audit_stampe", "stampe_nomi", "audit_usb"]
        labels = {
            "nome": "Nome", "tipo": "Come arrivano i log", "ruolo": "Che cos'è", "host": "Server da leggere",
            "ou_pc": "Unità organizzativa dei PC", "indirizzi_ip": "Indirizzi da cui arrivano i messaggi",
            "canali": "Registri da leggere", "eventi": "Cosa leggere", "silenzio_max_ore": "Avvisa se muta per più di (ore)",
            "attiva": "Attiva", "audit_file": "Accessi ai file", "cartelle_file": "Cartelle sorvegliate",
            "audit_stampe": "Stampe", "stampe_nomi": "Registra anche il nome del documento", "audit_usb": "Dispositivi USB",
        }
        help_texts = {
            "host": "Solo per «Server Windows»: nome (es. DC01) o indirizzo IP.",
            "ou_pc": "Solo per «Tutti i PC del dominio»: es. OU=Computer,DC=azienda,DC=local. Vuota = tutto il dominio "
                     "(senza i server già aggiunti come fonte a sé).",
            "indirizzi_ip": "Solo per «Syslog»: uno o più IP separati da virgola. Gli altri indirizzi vengono ignorati.",
            "canali": "Server e PC Windows: di solito Security,System.",
            "silenzio_max_ore": "0 = non avvisare. Un controller di dominio non resta mai muto per un'ora; un NAS anche per un giorno.",
            "audit_file": "File server: eventi 4663/4670 delle cartelle che hanno la voce di controllo (la stessa che usa "
                          "BusinessLog). «Anche le letture» registra ogni apertura.",
            "cartelle_file": "Come «Controllo files» di BusinessLog: una cartella per riga, con il percorso sul file server. "
                             "Dopo una barra si può scegliere cosa registrare, es. «D:\\Dati\\Progetti | letture, scritture, "
                             "eliminazioni». Vuoto = tutte le cartelle con la voce di controllo.",
            "audit_stampe": "Registro PrintService/Operational, evento 307: sul server di stampa e, per le stampanti "
                            "collegate direttamente, sui PC.",
            "stampe_nomi": "Spento = il titolo del documento non viene salvato nemmeno nell'archivio.",
            "audit_usb": "Chiavette e dischi collegati (6416, Partition/Diagnostic 1006) e file copiati, aperti o "
                         "eliminati sulle unità rimovibili (4663, «Controlla Archivio rimovibile»).",
        }
        widgets = {"cartelle_file": forms.Textarea(attrs={"rows": 3, "placeholder": "D:\\Dati\\Progetti | letture, scritture, eliminazioni"})}

    def clean(self):
        dati = super().clean()
        tipo = dati.get("tipo")
        riservati = dati.get("audit_file") or dati.get("audit_stampe") or dati.get("audit_usb")
        if riservati and not Impostazioni.corrente().controlli_lavoratori_ok:
            raise forms.ValidationError(
                "Accessi ai file, stampe e USB si accendono solo dopo la conferma «Informativa ai dipendenti e accordi "
                "verificati» nelle Impostazioni (sotto).")
        if tipo == FonteLog.TIPO_WINDOWS and not (dati.get("host") or "").strip():
            self.add_error("host", "Indicare il server da leggere.")
        if tipo == FonteLog.TIPO_DOMINIO:
            from . import ad

            if not ad.configurato():
                self.add_error("tipo", "L'elenco dei PC si legge da Active Directory: serve la connessione LDAP del portale "
                                       "(Setup Wizard › LDAP).")
            ou = (dati.get("ou_pc") or "").strip()
            if ou and "dc=" not in ou.lower():
                self.add_error("ou_pc", "Scrivere il percorso completo, es. OU=Computer,DC=azienda,DC=local.")
        for errore in regole.errori_cartelle(dati.get("cartelle_file") or ""):
            self.add_error("cartelle_file", errore)
        if tipo == FonteLog.TIPO_SYSLOG:
            ips = [x.strip() for x in (dati.get("indirizzi_ip") or "").replace(";", ",").split(",") if x.strip()]
            if not ips:
                self.add_error("indirizzi_ip", "Indicare almeno un indirizzo IP.")
            for ip in ips:
                try:
                    ipaddress.ip_address(ip)
                except ValueError:
                    self.add_error("indirizzi_ip", f"«{ip}» non è un indirizzo IP.")
            dati["indirizzi_ip"] = ", ".join(ips)
        return dati


class AmministratoreForm(forms.ModelForm):
    class Meta:
        model = AmministratoreSistema
        fields = ["nome", "tipo", "societa", "account", "ambito", "nominato_il", "documento_nomina", "prossima_revisione",
                  "revocato_il", "note"]
        labels = {
            "nome": "Nome e cognome", "tipo": "Tipo", "societa": "Società (se esterno)", "account": "Account usati",
            "ambito": "Sistemi che amministra", "nominato_il": "Nominato il", "documento_nomina": "Lettera di nomina (PDF)",
            "prossima_revisione": "Prossima revisione", "revocato_il": "Revocato il", "note": "Note",
        }
        help_texts = {"account": "Es. mrossi, adm-mrossi, root su ESXi. Servono a riconoscere i suoi accessi nel registro."}
        widgets = {"nominato_il": _Data(), "prossima_revisione": _Data(), "revocato_il": _Data(),
                   "ambito": forms.Textarea(attrs={"rows": 2}), "note": forms.Textarea(attrs={"rows": 2})}

    def clean_documento_nomina(self):
        f = self.cleaned_data.get("documento_nomina")
        if f and hasattr(f, "content_type"):
            if not str(f.name).lower().endswith(".pdf"):
                raise forms.ValidationError("Caricare la nomina in PDF.")
            if f.size > 10 * 1024 * 1024:
                raise forms.ValidationError("File troppo grande (massimo 10 MB).")
        return f


class ApparatoForm(forms.ModelForm):
    password = forms.CharField(label="Password", required=False, widget=forms.PasswordInput(render_value=False),
                               help_text="Lasciare vuoto per tenere quella salvata.")

    class Meta:
        model = ApparatoInfra
        fields = ["nome", "tipo", "indirizzo", "porta", "utente", "verifica_certificato", "attivo"]
        labels = {"nome": "Nome", "tipo": "Tipo", "indirizzo": "Indirizzo (nome o IP)", "porta": "Porta",
                  "utente": "Utente in sola lettura", "verifica_certificato": "Verifica il certificato HTTPS", "attivo": "Attivo"}
        help_texts = {"verifica_certificato": "Lasciare spento per i certificati autofirmati di ESXi e iLO."}

    field_order = ["nome", "tipo", "indirizzo", "porta", "utente", "password", "verifica_certificato", "attivo"]


class IndagineForm(forms.ModelForm):
    class Meta:
        model = Indagine
        fields = ["motivo", "riferimento", "account", "dal", "al", "filtro_testo"]
        labels = {"motivo": "Motivo", "riferimento": "Riferimento", "account": "Persone (account)", "dal": "Dal",
                  "al": "Al", "filtro_testo": "Cerca nel percorso, stampante o dispositivo"}
        help_texts = {"motivo": "Cosa è stato rilevato e perché serve guardare questi dati (es. sospetto furto di "
                                "disegni del cliente X segnalato il …). Resta nell'audit."}
        widgets = {"dal": _Data(), "al": _Data(), "motivo": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        dati = super().clean()
        if dati.get("dal") and dati.get("al") and dati["al"] < dati["dal"]:
            self.add_error("al", "La fine viene prima dell'inizio.")
        if len((dati.get("motivo") or "").strip()) < 20:
            self.add_error("motivo", "Scrivere il motivo in modo comprensibile (almeno una frase).")
        return dati


class VerificaForm(forms.ModelForm):
    class Meta:
        model = VerificaAnnuale
        fields = ["eseguita_il", "eseguita_da", "esito", "rilievi", "azioni"]
        labels = {"eseguita_il": "Verifica eseguita il", "eseguita_da": "Da (nome e ruolo)", "esito": "Esito",
                  "rilievi": "Rilievi", "azioni": "Azioni decise"}
        widgets = {"eseguita_il": _Data(), "rilievi": forms.Textarea(attrs={"rows": 3}), "azioni": forms.Textarea(attrs={"rows": 3})}
