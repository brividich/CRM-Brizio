import React, { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Users,
  UserPlus,
  CalendarDays,
  ShieldCheck,
  FileWarning,
  GraduationCap,
  BriefcaseBusiness,
  Search,
  Filter,
  Bell,
  ChevronRight,
  Clock3,
  HeartPulse,
  BadgeCheck,
  AlertTriangle,
  Building2,
  ClipboardCheck,
  FileText,
  KeyRound,
  UserCheck,
  FolderArchive,
  ClipboardList,
  Award,
  CalendarCheck,
  Eye,
  Download,
  Plus,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const people = [
  { id: 1, name: "Marco Rossi", dept: "Produzione", role: "Saldatore", status: "Attivo", risk: "Doc. in scadenza", score: 82, contract: "Tempo indeterminato", manager: "L. Verdi", site: "Sede / Officina" },
  { id: 2, name: "Giulia Bianchi", dept: "Amministrazione", role: "Impiegata", status: "Attivo", risk: "OK", score: 96, contract: "Tempo indeterminato", manager: "Direzione", site: "Sede" },
  { id: 3, name: "Luca Verdi", dept: "Cantiere", role: "Preposto", status: "Attivo", risk: "Formazione", score: 74, contract: "Tempo indeterminato", manager: "Direzione Tecnica", site: "Cantieri" },
  { id: 4, name: "Sara Neri", dept: "HR", role: "HR Specialist", status: "Onboarding", risk: "Contratto da firmare", score: 68, contract: "Nuova assunzione", manager: "Direzione", site: "Sede" },
  { id: 5, name: "Francesco Conti", dept: "Magazzino", role: "Addetto logistica", status: "Attivo", risk: "DPI", score: 79, contract: "Tempo determinato", manager: "M. Rossi", site: "Magazzino" },
];

const absences = [
  { person: "Marco Rossi", type: "Ferie", period: "22/05 → 24/05", status: "In approvazione", tone: "warning" },
  { person: "Giulia Bianchi", type: "Permesso", period: "23/05 · mattina", status: "Approvata", tone: "ok" },
  { person: "Luca Verdi", type: "Malattia", period: "20/05 → 21/05", status: "Registrata", tone: "blue" },
  { person: "Francesco Conti", type: "ROL", period: "27/05 · pomeriggio", status: "Da validare", tone: "warning" },
];

const training = [
  { course: "Sicurezza generale lavoratori", audience: "Tutti", coverage: 94, missing: 8, due: "30 giorni", mandatory: true, owner: "HR / RSPP", risk: "Basso", hours: 4, format: "E-learning + test" },
  { course: "Preposto", audience: "Capi reparto / cantiere", coverage: 71, missing: 4, due: "15 giorni", mandatory: true, owner: "RSPP", risk: "Alto", hours: 8, format: "Aula" },
  { course: "Antincendio", audience: "Squadra emergenza", coverage: 88, missing: 2, due: "60 giorni", mandatory: true, owner: "HSE", risk: "Medio", hours: 8, format: "Aula + prova pratica" },
  { course: "Carrelli elevatori", audience: "Magazzino", coverage: 76, missing: 3, due: "45 giorni", mandatory: true, owner: "Logistica", risk: "Medio", hours: 12, format: "Aula + pratica" },
  { course: "Privacy e trattamento dati HR", audience: "HR / Amministrazione", coverage: 67, missing: 5, due: "20 giorni", mandatory: true, owner: "IT / HR", risk: "Alto", hours: 2, format: "E-learning" },
  { course: "Qualità e non conformità", audience: "Produzione / Cantiere", coverage: 58, missing: 11, due: "90 giorni", mandatory: false, owner: "Qualità", risk: "Medio", hours: 3, format: "Workshop" },
];

const trainingSessions = [
  { title: "Preposto - aggiornamento", date: "24 maggio", time: "09:00 - 13:00", location: "Sala riunioni", seats: "6/10", status: "Da confermare", tone: "warning" },
  { title: "Carrelli elevatori - pratica", date: "28 maggio", time: "08:30 - 12:30", location: "Magazzino", seats: "8/8", status: "Completa", tone: "ok" },
  { title: "Privacy HR", date: "03 giugno", time: "14:00 - 15:30", location: "Online", seats: "12/20", status: "Aperta", tone: "blue" },
  { title: "Antincendio prova pratica", date: "10 giugno", time: "09:00 - 17:00", location: "Campo prova", seats: "4/12", status: "Da riempire", tone: "warning" },
];

const competencyMatrix = [
  { role: "Saldatore", required: ["Sicurezza", "DPI", "Qualità", "Antincendio"], coverage: 78, gaps: 5, critical: "Qualità" },
  { role: "Preposto cantiere", required: ["Preposto", "Sicurezza", "Antincendio", "Primo soccorso"], coverage: 71, gaps: 4, critical: "Preposto" },
  { role: "Addetto logistica", required: ["Carrelli", "DPI", "Sicurezza", "Movimentazione"], coverage: 83, gaps: 3, critical: "Carrelli" },
  { role: "HR / Amministrazione", required: ["Privacy", "Cyber awareness", "Procedure HR"], coverage: 67, gaps: 5, critical: "Privacy" },
];

const trainingRisks = [
  { person: "Luca Verdi", role: "Preposto", issue: "Aggiornamento preposto in scadenza", due: "15 giorni", severity: "Alto", tone: "danger" },
  { person: "Francesco Conti", role: "Addetto logistica", issue: "Modulo carrelli da rinnovare", due: "45 giorni", severity: "Medio", tone: "warning" },
  { person: "Sara Neri", role: "HR Specialist", issue: "Privacy HR non completata", due: "20 giorni", severity: "Alto", tone: "danger" },
  { person: "Marco Rossi", role: "Saldatore", issue: "Qualità e non conformità mancante", due: "90 giorni", severity: "Medio", tone: "warning" },
];

const documents = [
  { id: 1, title: "Carta identità", owner: "Marco Rossi", ownerType: "Lavoratore", category: "Personali", area: "Anagrafica", status: "In scadenza", tone: "danger", expiry: "12/06/2026", access: "HR", retention: "Fascicolo personale", tags: ["Identità", "Documento personale"] },
  { id: 2, title: "Codice fiscale / tessera sanitaria", owner: "Giulia Bianchi", ownerType: "Lavoratore", category: "Personali", area: "Anagrafica", status: "Valido", tone: "ok", expiry: "-", access: "HR", retention: "Fascicolo personale", tags: ["Anagrafica", "Dati personali"] },
  { id: 3, title: "Contratto di lavoro", owner: "Sara Neri", ownerType: "Lavoratore", category: "Contratti", area: "Rapporto di lavoro", status: "Firma mancante", tone: "warning", expiry: "Da firmare", access: "HR riservato", retention: "Rapporto di lavoro", tags: ["Contratto", "Assunzione"] },
  { id: 4, title: "Proroga contratto TD", owner: "Francesco Conti", ownerType: "Lavoratore", category: "Contratti", area: "Rapporto di lavoro", status: "Da predisporre", tone: "warning", expiry: "30/06/2026", access: "HR riservato", retention: "Rapporto di lavoro", tags: ["Proroga", "Scadenza"] },
  { id: 5, title: "Scheda mansione", owner: "Luca Verdi", ownerType: "Lavoratore", category: "Mansioni", area: "Organizzazione", status: "Aggiornata", tone: "ok", expiry: "Revisione annuale", access: "HR + Responsabili", retention: "Fascicolo personale", tags: ["Mansione", "Preposto"] },
  { id: 6, title: "Attestato formazione sicurezza", owner: "Marco Rossi", ownerType: "Lavoratore", category: "Formazione", area: "Sicurezza lavoro", status: "Valido", tone: "ok", expiry: "18/11/2027", access: "HR + HSE", retention: "Sicurezza", tags: ["Formazione", "Sicurezza"] },
  { id: 7, title: "Idoneità sanitaria", owner: "Luca Verdi", ownerType: "Lavoratore", category: "Sicurezza", area: "Sorveglianza sanitaria", status: "In scadenza", tone: "danger", expiry: "05/06/2026", access: "HR + Medico competente", retention: "Sanitario riservato", tags: ["Idoneità", "Medicina lavoro"] },
  { id: 8, title: "Consegna DPI", owner: "Francesco Conti", ownerType: "Lavoratore", category: "Sicurezza", area: "DPI", status: "Firma richiesta", tone: "warning", expiry: "Aperta", access: "HR + HSE + Responsabile", retention: "Sicurezza", tags: ["DPI", "Consegna"] },
  { id: 9, title: "Cedolino paga", owner: "Giulia Bianchi", ownerType: "Lavoratore", category: "Retribuzione", area: "Amministrazione personale", status: "Riservato", tone: "blue", expiry: "Maggio 2026", access: "Solo HR autorizzato", retention: "Riservato", tags: ["Retribuzione", "Payroll"] },
  { id: 10, title: "Organigramma aziendale", owner: "Costruzioni Novicrom", ownerType: "Azienda", category: "Aziendali", area: "Organizzazione", status: "Pubblicato", tone: "ok", expiry: "Revisione Q3", access: "Direzione + HR + Responsabili", retention: "Archivio aziendale", tags: ["Organigramma", "Ruoli"] },
  { id: 11, title: "Procedura ferie e permessi", owner: "Costruzioni Novicrom", ownerType: "Azienda", category: "Aziendali", area: "Procedure HR", status: "Pubblicato", tone: "ok", expiry: "Revisione annuale", access: "Tutti i dipendenti", retention: "Archivio procedure", tags: ["Procedure", "Assenze"] },
  { id: 12, title: "Policy privacy dipendenti", owner: "Costruzioni Novicrom", ownerType: "Azienda", category: "Aziendali", area: "Privacy", status: "Da revisionare", tone: "warning", expiry: "31/07/2026", access: "Tutti + HR", retention: "Archivio compliance", tags: ["Privacy", "GDPR"] },
  { id: 13, title: "DVR - Documento Valutazione Rischi", owner: "Costruzioni Novicrom", ownerType: "Azienda", category: "Sicurezza", area: "Sicurezza lavoro", status: "Aggiornato", tone: "ok", expiry: "Revisione 2026", access: "Direzione + HSE + Responsabili", retention: "Archivio sicurezza", tags: ["DVR", "Rischi"] },
];

const safetyItems = [
  { area: "Sorveglianza sanitaria", open: 7, ok: 141, note: "Visite da pianificare" },
  { area: "DPI", open: 9, ok: 132, note: "Consegne da confermare" },
  { area: "Idoneità mansione", open: 4, ok: 144, note: "Cambio mansione / rinnovi" },
  { area: "Abilitazioni operative", open: 6, ok: 118, note: "Patenti, carrelli, piattaforme" },
];

const tabs = [
  { name: "Dashboard", icon: Building2 },
  { name: "Persone", icon: Users },
  { name: "Assenze", icon: CalendarDays },
  { name: "Formazione", icon: GraduationCap },
  { name: "Documenti", icon: FolderArchive },
  { name: "Sicurezza", icon: ShieldCheck },
];

const documentViews = ["Panoramica", "Lavoratori", "Aziendali", "Contratti", "Sicurezza", "Scadenze", "Riservati"];

function Pill({ children, tone = "neutral" }) {
  const tones = {
    neutral: "bg-slate-100 text-slate-700 border-slate-200",
    ok: "bg-emerald-50 text-emerald-700 border-emerald-200",
    warning: "bg-amber-50 text-amber-700 border-amber-200",
    danger: "bg-red-50 text-red-700 border-red-200",
    blue: "bg-blue-50 text-blue-700 border-blue-200",
  };
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${tones[tone]}`}>{children}</span>;
}

function ProgressBar({ value }) {
  return <div className="h-1.5 rounded-full bg-slate-100"><div className="h-1.5 rounded-full bg-slate-900" style={{ width: `${value}%` }} /></div>;
}

function MetricCard({ icon: Icon, label, value, sub, tone = "blue", onClick }) {
  const accents = {
    blue: "text-blue-700 bg-blue-50",
    green: "text-emerald-700 bg-emerald-50",
    amber: "text-amber-700 bg-amber-50",
    red: "text-red-700 bg-red-50",
  };
  return (
    <button onClick={onClick} className="w-full text-left">
      <Card className="rounded-2xl border-slate-200 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
        <CardContent className="px-3 py-2.5">
          <div className="flex items-center gap-3">
            <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${accents[tone]}`}><Icon className="h-4 w-4" /></div>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <p className="truncate text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
                <div className="shrink-0 text-xl font-bold tracking-tight text-slate-950">{value}</div>
              </div>
              <p className="truncate text-xs text-slate-500">{sub}</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </button>
  );
}

function PageHeader({ eyebrow, title, description, actionLabel, actionIcon: ActionIcon = Plus, onAction }) {
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm lg:flex-row lg:items-center lg:justify-between">
      <div className="min-w-0">
        <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#1f5c91]">{eyebrow}</div>
        <h2 className="mt-1 truncate text-xl font-bold tracking-tight text-[#12395f] md:text-2xl">{title}</h2>
        <p className="mt-1 max-w-5xl text-xs leading-5 text-slate-500 md:text-sm">{description}</p>
      </div>
      {actionLabel && <Button onClick={onAction} className="h-9 shrink-0 rounded-xl bg-[#12395f] px-3 text-sm hover:bg-[#0e2d4b]"><ActionIcon className="mr-2 h-4 w-4" /> {actionLabel}</Button>}
    </div>
  );
}

function InfoCell({ label, value, muted }) {
  return (
    <div className="rounded-2xl bg-white p-3">
      <div className="text-[11px] font-bold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate font-semibold text-slate-900">{value}</div>
      {muted && <div className="truncate text-xs text-slate-500">{muted}</div>}
    </div>
  );
}

function DashboardPage({ filteredPeople, setActiveTab }) {
  const expiring = [
    { label: "Visite mediche", value: 7, tone: "danger", target: "Sicurezza" },
    { label: "Formazione sicurezza", value: 12, tone: "warning", target: "Formazione" },
    { label: "Contratti / proroghe", value: 3, tone: "warning", target: "Documenti" },
    { label: "DPI da consegnare", value: 9, tone: "danger", target: "Sicurezza" },
  ];
  const activities = [
    { icon: UserPlus, title: "Nuovo onboarding creato", meta: "Sara Neri · HR · oggi 09:12", target: "Persone" },
    { icon: ClipboardCheck, title: "Corso sicurezza aggiornato", meta: "Produzione · 8 partecipanti · ieri", target: "Formazione" },
    { icon: FileText, title: "Documento caricato", meta: "Contratto apprendistato · Marco Rossi", target: "Documenti" },
  ];

  return (
    <>
      <section className="overflow-hidden rounded-[2rem] bg-gradient-to-br from-[#12395f] via-[#1f5c91] to-[#12395f] p-5 text-white shadow-xl shadow-slate-900/10">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="inline-flex rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white/85">Console HR aziendale</div>
            <h2 className="mt-3 max-w-3xl text-3xl font-bold tracking-tight md:text-4xl">Persone, contratti, assenze e compliance in un’unica dashboard operativa.</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-white/80">Vista compatta per Direzione, HR e responsabili reparto.</p>
          </div>
          <div className="grid min-w-[280px] grid-cols-2 gap-2">
            <button onClick={() => setActiveTab("Sicurezza")} className="rounded-2xl border border-white/15 bg-white/10 p-3 text-left backdrop-blur transition hover:bg-white/15"><div className="text-2xl font-bold">86%</div><div className="text-xs uppercase tracking-wide text-white/70">Compliance HR</div></button>
            <button onClick={() => setActiveTab("Documenti")} className="rounded-2xl border border-white/15 bg-white/10 p-3 text-left backdrop-blur transition hover:bg-white/15"><div className="text-2xl font-bold">21</div><div className="text-xs uppercase tracking-wide text-white/70">Azioni aperte</div></button>
          </div>
        </div>
      </section>

      <section className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard onClick={() => setActiveTab("Persone")} icon={Users} label="Dipendenti attivi" value="148" sub="+4 nel mese" tone="blue" />
        <MetricCard onClick={() => setActiveTab("Assenze")} icon={CalendarDays} label="Assenze oggi" value="11" sub="7 ferie · 4 malattia" tone="amber" />
        <MetricCard onClick={() => setActiveTab("Sicurezza")} icon={ShieldCheck} label="Idoneità valide" value="93%" sub="7 visite da pianificare" tone="green" />
        <MetricCard onClick={() => setActiveTab("Documenti")} icon={FileWarning} label="Scadenze HR" value="31" sub="10 priorità alta" tone="red" />
      </section>

      <section className="mt-3 grid gap-3 xl:grid-cols-[1.25fr_0.75fr]">
        <Card className="rounded-2xl border-slate-200 shadow-sm">
          <CardContent className="p-3">
            <div className="flex items-center justify-between gap-3"><div><h3 className="text-lg font-bold text-[#12395f]">Persone da presidiare</h3><p className="text-sm text-slate-500">Priorità documenti, formazione e sicurezza.</p></div><Button onClick={() => setActiveTab("Persone")} variant="ghost" className="rounded-xl text-[#12395f]">Apri elenco <ChevronRight className="ml-1 h-4 w-4" /></Button></div>
            <div className="mt-3 overflow-hidden rounded-2xl border border-slate-200">
              <div className="grid grid-cols-[1.3fr_0.9fr_0.9fr_0.8fr] bg-slate-50 px-3 py-2 text-xs font-bold uppercase tracking-wide text-slate-500"><div>Persona</div><div>Reparto</div><div>Stato</div><div>HR score</div></div>
              {filteredPeople.map((person) => (
                <button key={person.name} onClick={() => setActiveTab("Persone")} className="grid w-full grid-cols-[1.3fr_0.9fr_0.9fr_0.8fr] items-center border-t border-slate-200 px-3 py-2 text-left text-sm transition hover:bg-slate-50">
                  <div><div className="font-semibold text-slate-950">{person.name}</div><div className="text-xs text-slate-500">{person.role}</div></div>
                  <div className="text-slate-600">{person.dept}</div>
                  <div><Pill tone={person.risk === "OK" ? "ok" : person.status === "Onboarding" ? "blue" : "warning"}>{person.risk}</Pill></div>
                  <div><div className="mb-1 text-xs font-semibold text-slate-600">{person.score}%</div><ProgressBar value={person.score} /></div>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-3">
          <Card className="rounded-2xl border-slate-200 shadow-sm"><CardContent className="p-3"><div className="flex items-center justify-between"><div><h3 className="text-lg font-bold text-[#12395f]">Scadenze critiche</h3><p className="text-sm text-slate-500">Da trasformare in task HR.</p></div><Bell className="h-5 w-5 text-amber-600" /></div><div className="mt-3 grid gap-2">{expiring.map((item) => <button key={item.label} onClick={() => setActiveTab(item.target)} className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white p-3 text-left transition hover:bg-slate-50"><div className="font-semibold text-slate-700">{item.label}</div><Pill tone={item.tone}>{item.value}</Pill></button>)}</div></CardContent></Card>
          <Card className="rounded-2xl border-slate-200 shadow-sm"><CardContent className="p-3"><h3 className="text-lg font-bold text-[#12395f]">Timeline attività HR</h3><div className="mt-3 grid gap-2">{activities.map((activity) => <button key={activity.title} onClick={() => setActiveTab(activity.target)} className="flex items-start gap-3 rounded-2xl border border-slate-200 bg-white p-3 text-left transition hover:bg-slate-50"><activity.icon className="h-4 w-4 text-[#12395f]" /><div><div className="font-semibold text-slate-900">{activity.title}</div><div className="text-sm text-slate-500">{activity.meta}</div></div></button>)}</div></CardContent></Card>
        </div>
      </section>
    </>
  );
}

function PeoplePage({ filteredPeople, setActiveTab }) {
  const [expandedPersonId, setExpandedPersonId] = useState(null);
  const [personSection, setPersonSection] = useState("Riepilogo");
  const personSections = ["Riepilogo", "Anagrafica civile", "Contratto & riservati", "Ferie", "Corsi", "Documenti", "DPI", "Visite mediche", "Asset"];

  const getPersonDocuments = (person) => documents.filter((doc) => doc.owner === person.name);
  const getPersonAbsences = (person) => absences.filter((absence) => absence.person === person.name);
  const getPersonCourses = (person) => {
    const text = `${person.role} ${person.dept}`.toLowerCase();
    return training.filter((course) => course.audience.toLowerCase().includes("tutti") || text.includes("preposto") && course.course === "Preposto" || text.includes("magazzino") && course.course.includes("Carrelli") || text.includes("hr") && course.course.includes("Privacy") || text.includes("produzione") && course.course.includes("Qualità")).slice(0, 4);
  };
  const buildPersonData = (person) => ({
    company: { matricola: `NV-${String(person.id).padStart(4, "0")}`, badge: `B-${1200 + person.id}`, email: `${person.name.toLowerCase().replaceAll(" ", ".")}@costruzioninovicrom.it`, reparto: person.dept, mansione: person.role, sede: person.site, responsabile: person.manager, rischio: person.risk === "OK" ? "Allineato" : person.risk },
    civil: { cf: `${person.name.split(" ").map((x) => x[0]).join("")}RSS80A01G702X`, nascita: person.id % 2 ? "Pisa, 14/03/1986" : "Pontedera, 22/09/1991", residenza: person.id % 2 ? "Via Roma 18, Santa Maria a Monte" : "Via Tosco Romagnola 44, Pontedera", domicilio: "Coincide con residenza", telefono: `+39 333 45${person.id} 77${person.id}2`, emergenza: person.id % 2 ? "Anna Rossi · moglie" : "Mario Bianchi · padre" },
    reserved: { contratto: person.contract, assunzione: person.id === 4 ? "01/06/2026" : "03/04/2021", livello: person.dept === "Produzione" ? "C2 Metalmeccanico" : person.dept === "Cantiere" ? "C3 Edile" : "B2 Impiegato", retribuzione: "Visibile solo HR/Payroll", iban: "IT** **** **** **** 1289", note: person.risk === "Contratto da firmare" ? "Documentazione assunzione da completare" : "Nessuna nota critica" },
    ferie: { ferieResidue: person.id % 2 ? "72 h" : "48 h", rolResidui: person.id % 2 ? "18 h" : "26 h", exFestivita: "8 h", ultimoPeriodo: getPersonAbsences(person)[0]?.period || "Nessuna richiesta recente", statoRichieste: getPersonAbsences(person)[0]?.status || "Nessuna richiesta aperta" },
    dpi: [{ item: "Scarpe antinfortunistiche", consegna: "12/01/2026", stato: person.risk === "DPI" ? "Firma richiesta" : "Consegnato", tone: person.risk === "DPI" ? "warning" : "ok" }, { item: "Casco protettivo", consegna: "12/01/2026", stato: "Consegnato", tone: "ok" }, { item: "Guanti da lavoro", consegna: "10/04/2026", stato: "Da rinnovare", tone: "warning" }],
    medical: [{ visita: "Idoneità mansione", data: "05/06/2026", esito: person.risk === "Doc. in scadenza" ? "In scadenza" : "Idoneo", tone: person.risk === "Doc. in scadenza" ? "danger" : "ok" }, { visita: "Sorveglianza sanitaria", data: "18/11/2026", esito: "Programmabile", tone: "blue" }],
    assets: [{ tag: `NB-${220 + person.id}`, type: "Notebook", status: "Assegnato" }, { tag: `TEL-${310 + person.id}`, type: "Smartphone", status: person.dept === "Produzione" ? "Non assegnato" : "Assegnato" }, { tag: `BADGE-${1200 + person.id}`, type: "Badge accesso", status: "Attivo" }],
  });

  const rowList = (rows, renderRow) => <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">{rows.map(renderRow)}</div>;

  const PersonMiniPage = ({ person }) => {
    const data = buildPersonData(person);
    const personDocuments = getPersonDocuments(person);
    const personCourses = getPersonCourses(person);
    const personAbsences = getPersonAbsences(person);
    const contractDocs = personDocuments.filter((doc) => doc.category === "Contratti");

    const renderSection = () => {
      if (personSection === "Anagrafica civile") return <div className="grid gap-2 md:grid-cols-3 xl:grid-cols-6"><InfoCell label="Codice fiscale" value={data.civil.cf} /><InfoCell label="Nascita" value={data.civil.nascita} /><InfoCell label="Residenza" value={data.civil.residenza} /><InfoCell label="Domicilio" value={data.civil.domicilio} /><InfoCell label="Telefono" value={data.civil.telefono} /><InfoCell label="Emergenza" value={data.civil.emergenza} /></div>;
      if (personSection === "Contratto & riservati") return <div className="grid gap-2 xl:grid-cols-[1.1fr_0.9fr]"><div className="grid gap-2 md:grid-cols-3"><InfoCell label="Contratto" value={data.reserved.contratto} /><InfoCell label="Assunzione" value={data.reserved.assunzione} /><InfoCell label="Livello / CCNL" value={data.reserved.livello} /><InfoCell label="Retribuzione" value={data.reserved.retribuzione} /><InfoCell label="IBAN" value={data.reserved.iban} /><InfoCell label="Note riservate" value={data.reserved.note} /></div>{rowList(contractDocs.length ? contractDocs : [{ id: "empty", title: "Nessun documento contrattuale collegato", expiry: "-", status: "N/D", tone: "neutral" }], (doc) => <div key={doc.id} className="flex items-center justify-between border-t border-slate-200 px-3 py-2 text-sm first:border-t-0"><div><div className="font-semibold text-[#12395f]">{doc.title}</div><div className="text-xs text-slate-500">{doc.expiry}</div></div><Pill tone={doc.tone}>{doc.status}</Pill></div>)}</div>;
      if (personSection === "Ferie") return <div className="grid gap-2 md:grid-cols-5"><InfoCell label="Ferie residue" value={data.ferie.ferieResidue} /><InfoCell label="ROL residui" value={data.ferie.rolResidui} /><InfoCell label="Ex festività" value={data.ferie.exFestivita} /><InfoCell label="Ultimo periodo" value={data.ferie.ultimoPeriodo} /><InfoCell label="Stato richieste" value={data.ferie.statoRichieste} /></div>;
      if (personSection === "Corsi") return rowList(personCourses, (course) => <button key={course.course} onClick={() => setActiveTab("Formazione")} className="grid w-full gap-2 border-t border-slate-200 px-3 py-2 text-left text-sm first:border-t-0 hover:bg-slate-50 lg:grid-cols-[1.4fr_0.9fr_0.8fr_0.7fr_auto] lg:items-center"><div><div className="font-semibold text-[#12395f]">{course.course}</div><div className="text-xs text-slate-500">{course.owner}</div></div><div>{course.format} · {course.hours}h</div><div className="flex items-center gap-2"><div className="h-1.5 flex-1 rounded-full bg-slate-100"><div className="h-1.5 rounded-full bg-slate-900" style={{ width: `${course.coverage}%` }} /></div><Pill tone={course.coverage >= 85 ? "ok" : course.coverage >= 75 ? "warning" : "danger"}>{course.coverage}%</Pill></div><div className="text-xs text-slate-500">{course.due}</div><div className="text-right text-xs font-semibold text-[#12395f]">Apri</div></button>);
      if (personSection === "Documenti") return rowList(personDocuments, (doc) => <button key={doc.id} onClick={() => setActiveTab("Documenti")} className="flex w-full items-center justify-between border-t border-slate-200 px-3 py-2 text-left first:border-t-0 hover:bg-slate-50"><div><div className="font-semibold text-[#12395f]">{doc.title}</div><div className="text-xs text-slate-500">{doc.category} · {doc.expiry}</div></div><Pill tone={doc.tone}>{doc.status}</Pill></button>);
      if (personSection === "DPI") return rowList(data.dpi, (dpi) => <div key={dpi.item} className="grid gap-2 border-t border-slate-200 px-3 py-2 text-sm first:border-t-0 lg:grid-cols-3"><div className="font-semibold text-[#12395f]">{dpi.item}</div><div>{dpi.consegna}</div><div><Pill tone={dpi.tone}>{dpi.stato}</Pill></div></div>);
      if (personSection === "Visite mediche") return rowList(data.medical, (visit) => <div key={visit.visita} className="grid gap-2 border-t border-slate-200 px-3 py-2 text-sm first:border-t-0 lg:grid-cols-3"><div className="font-semibold text-[#12395f]">{visit.visita}</div><div>{visit.data}</div><div><Pill tone={visit.tone}>{visit.esito}</Pill></div></div>);
      if (personSection === "Asset") return rowList(data.assets, (asset) => <div key={asset.tag} className="grid gap-2 border-t border-slate-200 px-3 py-2 text-sm first:border-t-0 lg:grid-cols-3"><div className="font-semibold text-[#12395f]">{asset.tag}</div><div>{asset.type}</div><div><Pill tone={asset.status === "Assegnato" || asset.status === "Attivo" ? "ok" : "neutral"}>{asset.status}</Pill></div></div>);
      return <div className="grid gap-2 md:grid-cols-4 xl:grid-cols-8"><InfoCell label="Matricola" value={data.company.matricola} /><InfoCell label="Badge" value={data.company.badge} /><InfoCell label="Email aziendale" value={data.company.email} /><InfoCell label="Reparto" value={data.company.reparto} /><InfoCell label="Mansione" value={data.company.mansione} /><InfoCell label="Sede" value={data.company.sede} /><InfoCell label="Responsabile" value={data.company.responsabile} /><InfoCell label="HR Score" value={`${person.score}%`} muted={data.company.rischio} /></div>;
    };

    return (
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="border-t border-slate-200 bg-slate-50/70 px-3 py-3">
        <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between"><div><div className="text-xs font-bold uppercase tracking-[0.18em] text-[#1f5c91]">Scheda dipendente</div><h4 className="mt-1 text-xl font-bold text-[#12395f]">{person.name}</h4><p className="text-sm text-slate-500">{person.role} · {person.dept} · {person.site}</p></div><div className="flex flex-wrap gap-2"><Button onClick={() => setActiveTab("Documenti")} variant="outline" className="h-9 rounded-xl border-slate-200 px-3 text-sm"><FileText className="mr-2 h-4 w-4" /> Documenti</Button><Button onClick={() => setActiveTab("Formazione")} variant="outline" className="h-9 rounded-xl border-slate-200 px-3 text-sm"><GraduationCap className="mr-2 h-4 w-4" /> Formazione</Button><Button onClick={() => setActiveTab("Sicurezza")} variant="outline" className="h-9 rounded-xl border-slate-200 px-3 text-sm"><ShieldCheck className="mr-2 h-4 w-4" /> Sicurezza</Button></div></div>
          <div className="mt-3 flex gap-1.5 overflow-x-auto rounded-xl border border-slate-200 bg-slate-50 p-1.5">{personSections.map((section) => <button key={section} onClick={() => setPersonSection(section)} className={`whitespace-nowrap rounded-lg px-2.5 py-1.5 text-xs font-semibold transition ${personSection === section ? "bg-[#12395f] text-white shadow-sm" : "text-slate-600 hover:bg-slate-100"}`}>{section}</button>)}</div>
          <div className="mt-3 rounded-2xl bg-slate-50 p-3">{renderSection()}</div>
        </div>
      </motion.div>
    );
  };

  return (
    <>
      <PageHeader eyebrow="Anagrafica personale" title="Persone e fascicolo HR" description="Cliccando sul nome del dipendente si apre sotto la riga una mini pagina personale con anagrafica aziendale, civile, contratto, retribuzione, dati riservati, ferie, corsi, documenti, DPI, visite mediche e asset assegnati." actionLabel="Nuovo dipendente" actionIcon={UserPlus} />
      <section className="mt-3 grid gap-2 md:grid-cols-3"><MetricCard icon={Users} label="Totale persone" value="148" sub="136 attivi · 12 esterni" tone="blue" /><MetricCard icon={UserCheck} label="Onboarding" value="5" sub="2 bloccati da documenti" tone="amber" /><MetricCard icon={BriefcaseBusiness} label="Cambi mansione" value="8" sub="Da validare questo mese" tone="green" /></section>
      <Card className="mt-3 rounded-2xl border-slate-200 shadow-sm"><CardContent className="p-3"><div className="overflow-hidden rounded-2xl border border-slate-200"><div className="grid grid-cols-[1.2fr_0.8fr_0.9fr_0.9fr_0.8fr_0.7fr] bg-slate-50 px-3 py-2 text-xs font-bold uppercase tracking-wide text-slate-500"><div>Dipendente</div><div>Reparto</div><div>Mansione</div><div>Contratto</div><div>Stato</div><div>Azioni</div></div>{filteredPeople.map((p) => <div key={p.id}><div className="grid grid-cols-[1.2fr_0.8fr_0.9fr_0.9fr_0.8fr_0.7fr] items-center border-t border-slate-200 px-3 py-2 text-sm"><div><button onClick={() => { setExpandedPersonId((current) => current === p.id ? null : p.id); setPersonSection("Riepilogo"); }} className="text-left"><div className="font-semibold text-slate-950 hover:text-[#12395f]">{p.name}</div><div className="text-xs text-slate-500">{p.site} · Resp. {p.manager}</div></button></div><div className="text-slate-600">{p.dept}</div><div className="text-slate-600">{p.role}</div><div className="text-slate-600">{p.contract}</div><div><Pill tone={p.risk === "OK" ? "ok" : p.status === "Onboarding" ? "blue" : "warning"}>{p.status}</Pill></div><div className="flex gap-2"><button onClick={() => setExpandedPersonId((current) => current === p.id ? null : p.id)} className="rounded-xl border border-slate-200 p-2 text-[#12395f] hover:bg-slate-50"><Eye className="h-4 w-4" /></button><button onClick={() => setActiveTab("Documenti")} className="rounded-xl border border-slate-200 p-2 text-[#12395f] hover:bg-slate-50"><FileText className="h-4 w-4" /></button></div></div>{expandedPersonId === p.id && <PersonMiniPage person={p} />}</div>)}</div></CardContent></Card>
    </>
  );
}

function AbsencesPage() {
  const [selectedAbsence, setSelectedAbsence] = useState(null);
  return (
    <>
      <PageHeader eyebrow="Presenze e assenze" title="Assenze, ferie, permessi e copertura reparti" description="Clicca una richiesta per aprire il dettaglio sotto la riga." actionLabel="Nuova richiesta" actionIcon={CalendarCheck} />
      <section className="mt-3 grid gap-2 md:grid-cols-4"><MetricCard icon={CalendarDays} label="Assenze oggi" value="11" sub="7 ferie · 4 malattia" tone="amber" /><MetricCard icon={ClipboardCheck} label="Da approvare" value="6" sub="Responsabili reparto" tone="red" /><MetricCard icon={CheckCircle2} label="Approvate mese" value="42" sub="Ferie / ROL / permessi" tone="green" /><MetricCard icon={XCircle} label="Scoperte reparto" value="2" sub="Produzione e magazzino" tone="red" /></section>
      <Card className="mt-3 rounded-2xl border-slate-200 shadow-sm"><CardContent className="p-3"><h3 className="text-lg font-bold text-[#12395f]">Richieste recenti</h3><div className="mt-3 overflow-hidden rounded-2xl border border-slate-200">{absences.map((a) => <div key={`${a.person}-${a.period}`}><button onClick={() => setSelectedAbsence((current) => current?.person === a.person && current?.period === a.period ? null : a)} className="flex w-full items-center justify-between border-t border-slate-200 bg-white p-3 text-left first:border-t-0 transition hover:bg-slate-50"><div><div className="font-semibold text-slate-900">{a.person}</div><div className="text-sm text-slate-500">{a.type} · {a.period}</div></div><Pill tone={a.tone}>{a.status}</Pill></button>{selectedAbsence?.person === a.person && selectedAbsence?.period === a.period && <div className="border-t border-slate-200 bg-slate-50/70 px-3 py-3"><div className="rounded-2xl border border-slate-200 bg-white p-3"><div className="grid gap-2 md:grid-cols-4"><InfoCell label="Tipo" value={a.type} /><InfoCell label="Periodo" value={a.period} /><InfoCell label="Stato" value={a.status} /><InfoCell label="Copertura" value="Verificata" /></div></div></div>}</div>)}</div></CardContent></Card>
    </>
  );
}

function TrainingPage() {
  const [trainingView, setTrainingView] = useState("Overview");
  const [selectedKey, setSelectedKey] = useState(null);
  const trainingViews = ["Overview", "Catalogo corsi", "Matrice competenze", "Sessioni", "Scadenze", "Gap persone"];
  const tabClass = (v) => `whitespace-nowrap rounded-lg px-2.5 py-1.5 text-xs font-semibold transition ${trainingView === v ? "bg-[#12395f] text-white shadow-sm" : "text-slate-600 hover:bg-slate-100"}`;

  const Detail = ({ children }) => <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="border-t border-slate-200 bg-slate-50/70 px-3 py-3"><div className="rounded-2xl border border-slate-200 bg-white p-3">{children}</div></motion.div>;

  const CourseDetail = ({ course }) => <Detail><div className="flex items-start justify-between gap-3"><div><div className="text-xs font-bold uppercase tracking-wide text-[#1f5c91]">Scheda corso</div><h4 className="text-lg font-bold text-[#12395f]">{course.course}</h4><p className="text-sm text-slate-500">{course.audience} · {course.owner}</p></div><Pill tone={course.risk === "Alto" ? "danger" : course.risk === "Medio" ? "warning" : "ok"}>{course.risk}</Pill></div><div className="mt-3 grid gap-2 md:grid-cols-4"><InfoCell label="Copertura" value={`${course.coverage}%`} /><InfoCell label="Mancanti" value={course.missing} /><InfoCell label="Formato" value={course.format} muted={`${course.hours} ore`} /><InfoCell label="Scadenza" value={course.due} /></div></Detail>;

  const renderCatalog = () => <Card className="mt-3 rounded-2xl border-slate-200 shadow-sm"><CardContent className="p-3"><h3 className="text-lg font-bold text-[#12395f]">Catalogo corsi</h3><div className="mt-3 overflow-hidden rounded-2xl border border-slate-200">{training.map((t) => <div key={t.course}><button onClick={() => setSelectedKey(selectedKey === t.course ? null : t.course)} className="grid w-full gap-2 border-t border-slate-200 px-3 py-2 text-left text-sm first:border-t-0 hover:bg-slate-50 lg:grid-cols-[1.3fr_0.9fr_0.7fr_0.7fr_0.7fr]"><div><div className="font-semibold text-[#12395f]">{t.course}</div><div className="text-xs text-slate-500">{t.audience}</div></div><div>{t.format}</div><div><Pill tone={t.coverage >= 85 ? "ok" : t.coverage >= 75 ? "warning" : "danger"}>{t.coverage}%</Pill></div><div>{t.owner}</div><div>{t.due}</div></button>{selectedKey === t.course && <CourseDetail course={t} />}</div>)}</div></CardContent></Card>;

  const renderMatrix = () => <div className="mt-3 grid gap-3 lg:grid-cols-2">{competencyMatrix.map((m) => <div key={m.role}><button onClick={() => setSelectedKey(selectedKey === m.role ? null : m.role)} className="w-full text-left"><Card className="rounded-2xl border-slate-200 shadow-sm"><CardContent className="p-3"><div className="flex items-start justify-between"><div><h3 className="font-bold text-[#12395f]">{m.role}</h3><p className="text-sm text-slate-500">Gap aperti: {m.gaps}</p></div><Pill tone={m.coverage >= 80 ? "ok" : "warning"}>{m.coverage}%</Pill></div><div className="mt-2"><ProgressBar value={m.coverage} /></div></CardContent></Card></button>{selectedKey === m.role && <Detail><div className="flex flex-wrap gap-2">{m.required.map((r) => <Pill key={r} tone={r === m.critical ? "danger" : "blue"}>{r}</Pill>)}</div><div className="mt-3 grid gap-2 md:grid-cols-3"><InfoCell label="Copertura" value={`${m.coverage}%`} /><InfoCell label="Gap" value={m.gaps} /><InfoCell label="Criticità" value={m.critical} /></div></Detail>}</div>)}</div>;

  const renderSessions = () => <Card className="mt-3 rounded-2xl border-slate-200 shadow-sm"><CardContent className="p-3"><h3 className="text-lg font-bold text-[#12395f]">Sessioni</h3><div className="mt-3 overflow-hidden rounded-2xl border border-slate-200">{trainingSessions.map((s) => <div key={s.title}><button onClick={() => setSelectedKey(selectedKey === s.title ? null : s.title)} className="grid w-full gap-2 border-t border-slate-200 px-3 py-2 text-left text-sm first:border-t-0 hover:bg-slate-50 md:grid-cols-[1fr_0.7fr_0.7fr_0.6fr_auto]"><div><div className="font-semibold text-[#12395f]">{s.title}</div><div className="text-xs text-slate-500">{s.location}</div></div><div>{s.date}</div><div>{s.time}</div><div>{s.seats}</div><Pill tone={s.tone}>{s.status}</Pill></button>{selectedKey === s.title && <Detail><div className="grid gap-2 md:grid-cols-4"><InfoCell label="Data" value={s.date} /><InfoCell label="Orario" value={s.time} /><InfoCell label="Luogo" value={s.location} /><InfoCell label="Posti" value={s.seats} /></div></Detail>}</div>)}</div></CardContent></Card>;

  const renderGaps = () => <Card className="mt-3 rounded-2xl border-slate-200 shadow-sm"><CardContent className="p-3"><h3 className="text-lg font-bold text-[#12395f]">Gap persone</h3><div className="mt-3 overflow-hidden rounded-2xl border border-slate-200">{trainingRisks.map((r) => <div key={r.person}><button onClick={() => setSelectedKey(selectedKey === r.person ? null : r.person)} className="flex w-full items-center justify-between border-t border-slate-200 px-3 py-2 text-left first:border-t-0 hover:bg-slate-50"><div><div className="font-semibold text-[#12395f]">{r.person}</div><div className="text-sm text-slate-500">{r.role} · {r.issue}</div></div><Pill tone={r.tone}>{r.severity}</Pill></button>{selectedKey === r.person && <Detail><div className="grid gap-2 md:grid-cols-3"><InfoCell label="Ruolo" value={r.role} /><InfoCell label="Scadenza" value={r.due} /><InfoCell label="Criticità" value={r.issue} /></div></Detail>}</div>)}</div></CardContent></Card>;

  const renderOverview = () => <><section className="mt-3 grid gap-2 md:grid-cols-4"><MetricCard icon={GraduationCap} label="Copertura media" value="82%" sub="Corsi obbligatori" tone="blue" onClick={() => setTrainingView("Catalogo corsi")} /><MetricCard icon={AlertTriangle} label="Scadenze 30 gg" value="12" sub="Priorità sicurezza" tone="red" onClick={() => setTrainingView("Scadenze")} /><MetricCard icon={Award} label="Abilitazioni" value="54" sub="Attive" tone="green" onClick={() => setTrainingView("Matrice competenze")} /><MetricCard icon={ClipboardList} label="Da pianificare" value="9" sub="Sessioni" tone="amber" onClick={() => setTrainingView("Sessioni")} /></section>{renderCatalog()}</>;

  return <><PageHeader eyebrow="Formazione e competenze" title="Training Center HR" description="Corsi, matrice competenze, sessioni, scadenze e gap formativi con dettaglio inline sotto elemento cliccato." actionLabel="Pianifica corso" actionIcon={GraduationCap} onAction={() => setTrainingView("Sessioni")} /><div className="mt-3 flex gap-1.5 overflow-x-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-sm">{trainingViews.map((v) => <button key={v} onClick={() => { setTrainingView(v); setSelectedKey(null); }} className={tabClass(v)}>{v}</button>)}</div>{trainingView === "Overview" && renderOverview()}{trainingView === "Catalogo corsi" && renderCatalog()}{trainingView === "Matrice competenze" && renderMatrix()}{trainingView === "Sessioni" && renderSessions()}{trainingView === "Scadenze" && renderCatalog()}{trainingView === "Gap persone" && renderGaps()}</>;
}

function DocumentsPage() {
  const [documentView, setDocumentView] = useState("Panoramica");
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [documentQuery, setDocumentQuery] = useState("");
  const filteredDocs = documents.filter((doc) => {
    const q = documentQuery.toLowerCase().trim();
    const matches = !q || `${doc.title} ${doc.owner} ${doc.category} ${doc.area} ${doc.tags.join(" ")}`.toLowerCase().includes(q);
    if (!matches) return false;
    if (documentView === "Lavoratori") return doc.ownerType === "Lavoratore";
    if (documentView === "Aziendali") return doc.ownerType === "Azienda";
    if (documentView === "Contratti") return doc.category === "Contratti";
    if (documentView === "Sicurezza") return doc.category === "Sicurezza";
    if (documentView === "Scadenze") return ["danger", "warning"].includes(doc.tone);
    if (documentView === "Riservati") return doc.access.toLowerCase().includes("riservato") || doc.category === "Retribuzione";
    return true;
  });

  return <><PageHeader eyebrow="Archivio anagrafico documentale" title="Documenti aziendali e fascicoli dei lavoratori" description="Archivio unico per documenti personali, contratti, sicurezza, procedure aziendali e dati riservati." actionLabel="Carica documento" actionIcon={FileText} /><div className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between"><div className="flex gap-1.5 overflow-x-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-sm">{documentViews.map((v) => <button key={v} onClick={() => { setDocumentView(v); setSelectedDocument(null); }} className={`whitespace-nowrap rounded-lg px-2.5 py-1.5 text-xs font-semibold transition ${documentView === v ? "bg-[#12395f] text-white shadow-sm" : "text-slate-600 hover:bg-slate-100"}`}>{v}</button>)}</div><div className="relative lg:w-96"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><input value={documentQuery} onChange={(e) => setDocumentQuery(e.target.value)} placeholder="Cerca documento..." className="h-9 w-full rounded-xl border border-slate-200 bg-white pl-9 pr-3 text-sm outline-none ring-[#12395f]/20 focus:ring-4" /></div></div><Card className="mt-3 rounded-2xl border-slate-200 shadow-sm"><CardContent className="p-3"><div className="overflow-hidden rounded-2xl border border-slate-200">{filteredDocs.map((doc) => <div key={doc.id}><button onClick={() => setSelectedDocument(selectedDocument?.id === doc.id ? null : doc)} className="grid w-full gap-2 border-t border-slate-200 px-3 py-2 text-left text-sm first:border-t-0 hover:bg-slate-50 lg:grid-cols-[1.3fr_0.9fr_0.7fr_0.7fr_0.7fr_auto]"><div><div className="font-semibold text-[#12395f]">{doc.title}</div><div className="text-xs text-slate-500">{doc.area}</div></div><div>{doc.owner}</div><div>{doc.category}</div><div>{doc.expiry}</div><div><Pill tone={doc.tone}>{doc.status}</Pill></div><div className="text-right text-xs font-semibold text-[#12395f]">Apri</div></button>{selectedDocument?.id === doc.id && <div className="border-t border-slate-200 bg-slate-50/70 px-3 py-3"><div className="rounded-2xl border border-slate-200 bg-white p-3"><div className="grid gap-2 md:grid-cols-4"><InfoCell label="Proprietario" value={doc.owner} muted={doc.ownerType} /><InfoCell label="Categoria" value={doc.category} muted={doc.area} /><InfoCell label="Accesso" value={doc.access} /><InfoCell label="Conservazione" value={doc.retention} /></div></div></div>}</div>)}</div></CardContent></Card></>;
}

function SafetyPage() {
  const [selectedSafety, setSelectedSafety] = useState(null);
  return <><PageHeader eyebrow="Sicurezza lavoro" title="Sorveglianza sanitaria, DPI, idoneità e abilitazioni" description="Clicca un’area per aprire il dettaglio sotto la card." actionLabel="Apri piano sicurezza" actionIcon={ShieldCheck} /><section className="mt-3 grid gap-2 md:grid-cols-4"><MetricCard icon={ShieldCheck} label="Idoneità valide" value="93%" sub="7 visite" tone="green" /><MetricCard icon={HeartPulse} label="Sorveglianza" value="7" sub="Scadenze" tone="red" /><MetricCard icon={BadgeCheck} label="DPI aperti" value="9" sub="Consegna / firma" tone="amber" /><MetricCard icon={Award} label="Abilitazioni" value="54" sub="Patenti" tone="blue" /></section><div className="mt-3 grid gap-3 lg:grid-cols-2">{safetyItems.map((s) => <div key={s.area}><button onClick={() => setSelectedSafety(selectedSafety?.area === s.area ? null : s)} className="w-full text-left"><Card className="rounded-2xl border-slate-200 shadow-sm"><CardContent className="p-3"><div className="flex items-start justify-between gap-4"><div><h3 className="font-bold text-[#12395f]">{s.area}</h3><p className="text-sm text-slate-500">{s.note}</p></div><Pill tone={s.open > 7 ? "danger" : s.open > 4 ? "warning" : "blue"}>{s.open} aperti</Pill></div><div className="mt-3 grid grid-cols-2 gap-2"><InfoCell label="OK" value={s.ok} /><InfoCell label="Da gestire" value={s.open} /></div></CardContent></Card></button>{selectedSafety?.area === s.area && <div className="mt-2 rounded-2xl border border-slate-200 bg-white p-3"><div className="grid gap-2 md:grid-cols-4"><InfoCell label="Area" value={s.area} /><InfoCell label="Owner" value="HR / HSE" /><InfoCell label="Priorità" value={s.open > 7 ? "Alta" : "Media"} /><InfoCell label="Azione" value="Crea attività" /></div></div>}</div>)}</div></>;
}

export default function AnagraficaHRDashboardNovicrom() {
  const [activeTab, setActiveTab] = useState("Dashboard");
  const [query, setQuery] = useState("");
  const filteredPeople = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return people;
    return people.filter((p) => `${p.name} ${p.dept} ${p.role} ${p.contract} ${p.site}`.toLowerCase().includes(q));
  }, [query]);

  const renderPage = () => {
    if (activeTab === "Persone") return <PeoplePage filteredPeople={filteredPeople} setActiveTab={setActiveTab} />;
    if (activeTab === "Assenze") return <AbsencesPage />;
    if (activeTab === "Formazione") return <TrainingPage />;
    if (activeTab === "Documenti") return <DocumentsPage />;
    if (activeTab === "Sicurezza") return <SafetyPage />;
    return <DashboardPage filteredPeople={filteredPeople} setActiveTab={setActiveTab} />;
  };

  return (
    <div className="min-h-screen bg-[#f4f7fb] text-slate-950">
      <div className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between px-4 py-3">
          <button onClick={() => setActiveTab("Dashboard")} className="flex items-center gap-3 text-left"><div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#12395f] text-white shadow-sm"><Building2 className="h-6 w-6" /></div><div><div className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Novicrom HUB</div><h1 className="text-xl font-bold text-[#12395f]">Anagrafica HR</h1></div></button>
          <div className="hidden items-center gap-2 md:flex"><Button onClick={() => setActiveTab("Documenti")} variant="outline" className="rounded-xl border-slate-200"><KeyRound className="mr-2 h-4 w-4" /> Permessi HR</Button><Button onClick={() => setActiveTab("Persone")} className="rounded-xl bg-[#12395f] hover:bg-[#0e2d4b]"><UserPlus className="mr-2 h-4 w-4" /> Nuovo dipendente</Button></div>
        </div>
      </div>
      <main className="mx-auto max-w-[1500px] px-4 py-4">
        <div className="mb-4 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex gap-1.5 overflow-x-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-sm">{tabs.map((tab) => { const Icon = tab.icon; return <button key={tab.name} onClick={() => setActiveTab(tab.name)} className={`inline-flex items-center whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-semibold transition ${activeTab === tab.name ? "bg-[#12395f] text-white shadow-sm" : "text-slate-600 hover:bg-slate-100"}`}><Icon className="mr-2 h-4 w-4" /> {tab.name}</button>; })}</div>
          <div className="flex gap-2"><div className="relative flex-1 lg:w-80"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cerca persona, reparto, mansione..." className="h-9 w-full rounded-xl border border-slate-200 bg-white pl-9 pr-3 text-sm outline-none ring-[#12395f]/20 focus:ring-4" /></div><Button variant="outline" className="h-9 rounded-xl border-slate-200 px-3 text-sm"><Filter className="mr-2 h-4 w-4" /> Filtri</Button></div>
        </div>
        <motion.div key={activeTab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22 }}>{renderPage()}</motion.div>
      </main>
    </div>
  );
}
