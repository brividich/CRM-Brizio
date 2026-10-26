from __future__ import annotations

import ipaddress

from django import forms

from .models import AmministratoreSistema, ApparatoInfra, FonteLog, Impostazioni, VerificaAnnuale


class _Data(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class ImpostazioniForm(forms.ModelForm):
    class Meta:
        model = Impostazioni
        fields = ["attivo", "conservazione_mesi", "cartella_archivio", "copia_cartella", "copia_sharepoint",
                  "syslog_attivo", "syslog_indirizzo", "syslog_porta", "syslog_tcp", "orario_inizio", "orario_fine"]
        labels = {
            "attivo": "Raccolta accesa",
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
        }
        help_texts = {
            "conservazione_mesi": "Minimo 6 mesi (Garante). Consigliati 12: coprono la verifica annuale.",
            "cartella_archivio": "Vuota = cartella privata del portale. Su un altro disco del server, non su una share.",
            "copia_cartella": "Es. \\\\nas\\registro-log. L'account del raccoglitore deve poterci scrivere.",
            "orario_fine": "Gli accessi degli amministratori fuori da questo orario (e nel fine settimana) vengono evidenziati.",
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
        fields = ["nome", "tipo", "ruolo", "host", "indirizzi_ip", "canali", "eventi", "silenzio_max_ore", "attiva"]
        labels = {
            "nome": "Nome", "tipo": "Come arrivano i log", "ruolo": "Che cos'è", "host": "Server da leggere",
            "indirizzi_ip": "Indirizzi da cui arrivano i messaggi", "canali": "Registri da leggere",
            "eventi": "Cosa leggere", "silenzio_max_ore": "Avvisa se muta per più di (ore)", "attiva": "Attiva",
        }
        help_texts = {
            "host": "Solo per «Server Windows»: nome (es. DC01) o indirizzo IP.",
            "indirizzi_ip": "Solo per «Syslog»: uno o più IP separati da virgola. Gli altri indirizzi vengono ignorati.",
            "canali": "Solo per «Server Windows»: di solito Security,System.",
            "silenzio_max_ore": "0 = non avvisare. Un controller di dominio non resta mai muto per un'ora; un NAS anche per un giorno.",
        }

    def clean(self):
        dati = super().clean()
        tipo = dati.get("tipo")
        if tipo == FonteLog.TIPO_WINDOWS and not (dati.get("host") or "").strip():
            self.add_error("host", "Indicare il server da leggere.")
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


class VerificaForm(forms.ModelForm):
    class Meta:
        model = VerificaAnnuale
        fields = ["eseguita_il", "eseguita_da", "esito", "rilievi", "azioni"]
        labels = {"eseguita_il": "Verifica eseguita il", "eseguita_da": "Da (nome e ruolo)", "esito": "Esito",
                  "rilievi": "Rilievi", "azioni": "Azioni decise"}
        widgets = {"eseguita_il": _Data(), "rilievi": forms.Textarea(attrs={"rows": 3}), "azioni": forms.Textarea(attrs={"rows": 3})}
