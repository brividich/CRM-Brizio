<#
.SYNOPSIS
    Health-check dell'assistente AI (Ollama + RAG citabile SGI) in produzione.

.DESCRIPTION
    Verifica in un colpo solo i punti che fanno la differenza tra "l'AI risponde"
    e "l'AI sfrutta tutta la potenza" (chat + RAG citabile):

      1. Settings AI EFFETTIVI (post-dotenv, via Django): modello chat/embed,
         base URL, RAG SGI on, sorgenti RAG (deve includere la KB curata).
      2. Chiavi DUPLICATE nel .env grezzo (es. OLLAMA_EMBED_MODEL ripetuto) -> in
         dotenv vince l'ultima, ma la duplicazione e' un bug latente: la segnala.
      3. Ollama raggiungibile + modello chat ED embed PRESENTI (api/tags).
      4. RAG SGI indicizzato: sgi_chunks > 0 e recall (ai_eval --rag-sgi / --rag).
      5. Schedule django-q presenti (ai_warmup_ollama, ai_index_sgi_documents)
         + cluster vivo (heartbeat).
      6. Procedure su file server: source_path in UNC e leggibile dal processo.

    Read-only: non scrive nulla, non modifica .env ne' DB. Esegui SUL server
    di prod (pclogsys) con l'identita' giusta; per il check 6 conta l'identita'
    dell'app pool IIS e del Task Scheduler QCluster_PROD (vedi note a fine run).

.EXAMPLE
    .\tools\ai_healthcheck_prod.ps1
    .\tools\ai_healthcheck_prod.ps1 -SkipSgiEval   # salta l'eval pesante (PDF/embeddings)
#>
[CmdletBinding()]
param(
    [string]   $AppRoot  = 'C:\PortaleNovicrom\prod\current',
    [string]   $PyExe    = 'C:\PortaleNovicrom\prod\venv\Scripts\python.exe',
    [string]   $Settings = 'config.settings.prod',
    [string[]] $EnvCandidates = @(
        'C:\PortaleNovicrom\prod\config\.env',
        'C:\PortaleNovicrom\prod\current\django_app\.env'
    ),
    [switch]   $SkipSgiEval
)

$ErrorActionPreference = 'Continue'
$ManagePy = Join-Path $AppRoot 'django_app\manage.py'

# ---- helpers -------------------------------------------------------------
$script:rows = @()
function Add-Result([string]$Name, [string]$State, [string]$Detail) {
    # State: PASS | WARN | FAIL
    $script:rows += [pscustomobject]@{ Check = $Name; State = $State; Detail = $Detail }
    $color = switch ($State) { 'PASS' { 'Green' } 'WARN' { 'Yellow' } default { 'Red' } }
    Write-Host ("[{0,-4}] {1,-22} {2}" -f $State, $Name, $Detail) -ForegroundColor $color
}

function Get-EmbeddedJson([string]$Text, [string]$Marker) {
    if ($Marker) {
        $line = ($Text -split "`r?`n") | Where-Object { $_ -like "$Marker*" } | Select-Object -First 1
        if (-not $line) { return $null }
        return ($line.Substring($Marker.Length) | ConvertFrom-Json)
    }
    $start = $Text.IndexOf('{'); $end = $Text.LastIndexOf('}')
    if ($start -lt 0 -or $end -le $start) { return $null }
    return ($Text.Substring($start, $end - $start + 1) | ConvertFrom-Json)
}

function Invoke-DjangoShell([string]$Code) {
    # NB: niente 2>&1 sui nativi (corrompe l'output in WinPS 5.1). stderr va a video.
    $out = & $PyExe $ManagePy shell -c $Code --settings=$Settings
    return ($out -join "`n")
}

Write-Host ''
Write-Host '=== AI HEALTHCHECK PROD - NOVICROM HUB ===' -ForegroundColor Cyan
Write-Host ("AppRoot : {0}" -f $AppRoot)
Write-Host ("Python  : {0}" -f $PyExe)
Write-Host ("Settings: {0}" -f $Settings)
Write-Host ''

# ---- pre-flight ----------------------------------------------------------
if (-not (Test-Path $PyExe))    { Add-Result 'preflight' 'FAIL' "Python venv assente: $PyExe"; return }
if (-not (Test-Path $ManagePy)) { Add-Result 'preflight' 'FAIL' "manage.py assente: $ManagePy"; return }

# ---- 1+5+6: fatti lato Django (settings, schedule, cluster, procedure) ---
$pyFacts = @'
import json, os
from django.conf import settings as s
out = {}
keys = ['OLLAMA_API_PROVIDER','OLLAMA_BASE_URL','OLLAMA_CHAT_MODEL','OLLAMA_CHAT_ENABLED',
        'OLLAMA_EMBED_ENABLED','OLLAMA_EMBED_MODEL','RAG_EMBED_BACKEND',
        'RAG_EMBED_OPENAI_BASE_URL','RAG_EMBED_OPENAI_MODEL','OLLAMA_RAG_ENABLED',
        'OLLAMA_RAG_SGI_ENABLED','OLLAMA_RAG_STEMMING_ENABLED','OLLAMA_RAG_SOURCE_PATHS',
        'OLLAMA_KEEP_ALIVE']
out['settings'] = {k: getattr(s, k, None) for k in keys}
try:
    from django_q.models import Schedule
    names = ['ai_warmup_ollama', 'ai_index_sgi_documents']
    found = {sc.name: {'func': sc.func, 'next_run': str(sc.next_run),
                       'schedule_type': sc.schedule_type}
             for sc in Schedule.objects.filter(name__in=names)}
    out['schedules'] = found
    out['schedules_missing'] = [n for n in names if n not in found]
except Exception as e:
    out['schedules_error'] = str(e)
try:
    from django_q.models import Stat
    out['qcluster_alive'] = bool(list(Stat.get_all()))
except Exception as e:
    out['qcluster_error'] = str(e)
try:
    from procedure_refresh.models import ProcedureRevision as P
    sample = []
    for r in P.objects.all().iterator():
        try:
            if getattr(r, 'source_type', '') != 'fileserver':
                continue
            if not getattr(r, 'is_current', False):
                continue
        except Exception:
            continue
        p = getattr(r, 'source_path', '') or ''
        unc = p.startswith('\\\\')
        try:
            readable = bool(p) and os.path.isfile(p) and os.access(p, os.R_OK)
        except Exception:
            readable = False
        sample.append({'path': p, 'unc': unc, 'readable': readable})
        if len(sample) >= 300:
            break
    out['procedures'] = {
        'count': len(sample),
        'non_unc': [x['path'] for x in sample if not x['unc']][:10],
        'unreadable': [x['path'] for x in sample if x['unc'] and not x['readable']][:10],
    }
except Exception as e:
    out['procedures_error'] = str(e)
print('@@FACTS@@' + json.dumps(out, default=str))
'@

$factsRaw = Invoke-DjangoShell $pyFacts
$facts = Get-EmbeddedJson $factsRaw '@@FACTS@@'

if (-not $facts) {
    Add-Result 'django-facts' 'FAIL' 'Django non avviato o output non parsabile (vedi stderr sopra).'
} else {
    $cfg = $facts.settings

    # 1. Settings AI effettivi
    $baseUrl    = [string]$cfg.OLLAMA_BASE_URL
    $chatModel  = [string]$cfg.OLLAMA_CHAT_MODEL
    $embOn      = [bool]$cfg.OLLAMA_EMBED_ENABLED
    $sgiOn      = [bool]$cfg.OLLAMA_RAG_SGI_ENABLED
    $embBackend = ([string]$cfg.RAG_EMBED_BACKEND).Trim().ToLower()
    if (-not $embBackend) { $embBackend = 'ollama' }
    $teiBase    = [string]$cfg.RAG_EMBED_OPENAI_BASE_URL
    $teiModel   = [string]$cfg.RAG_EMBED_OPENAI_MODEL
    # modello embed "effettivo" per il backend attivo (TEI usa RAG_EMBED_OPENAI_MODEL)
    $embModel   = if ($embBackend -eq 'openai') { $teiModel } else { [string]$cfg.OLLAMA_EMBED_MODEL }
    Add-Result 'settings.chat' 'PASS' ("model={0} base={1} provider={2}" -f $chatModel, $baseUrl, $cfg.OLLAMA_API_PROVIDER)
    Add-Result 'settings.embed' ($(if ($embOn) {'PASS'} else {'WARN'})) ("enabled={0} backend={1} model={2}" -f $embOn, $embBackend, $embModel)
    Add-Result 'settings.rag_sgi' ($(if ($sgiOn) {'PASS'} else {'WARN'})) ("enabled={0} stemming={1}" -f $sgiOn, $cfg.OLLAMA_RAG_STEMMING_ENABLED)

    # 1b. sorgenti RAG: la KB curata deve esserci, altrimenti in prod resta solo README
    $srcs = @($cfg.OLLAMA_RAG_SOURCE_PATHS)
    $hasKb = ($srcs -join '|') -match 'ai_assistant/knowledge'
    if ($hasKb) {
        Add-Result 'settings.rag_src' 'PASS' ("sorgenti={0}" -f ($srcs -join ', '))
    } else {
        Add-Result 'settings.rag_src' 'FAIL' ("KB curata ASSENTE dalle sorgenti -> RAG quasi muto. sorgenti={0}" -f ($srcs -join ', '))
    }

    # 5. schedule + cluster
    if ($facts.PSObject.Properties.Name -contains 'schedules_error') {
        Add-Result 'q.schedules' 'WARN' ("non leggibili: {0}" -f $facts.schedules_error)
    } else {
        $missing = @($facts.schedules_missing)
        if ($missing.Count -eq 0) {
            $nr = ($facts.schedules.PSObject.Properties | ForEach-Object { "{0}@{1}" -f $_.Name, $_.Value.next_run }) -join ' | '
            Add-Result 'q.schedules' 'PASS' $nr
        } else {
            Add-Result 'q.schedules' 'WARN' ("mancanti: {0} -> lancia 'manage.py setup_q_schedules'" -f ($missing -join ', '))
        }
    }
    if ($facts.PSObject.Properties.Name -contains 'qcluster_alive') {
        Add-Result 'q.cluster' ($(if ($facts.qcluster_alive) {'PASS'} else {'WARN'})) ("heartbeat attivo={0} (serve per warmup/indicizzazione notturna)" -f $facts.qcluster_alive)
    }

    # 6. procedure su file server
    if ($facts.PSObject.Properties.Name -contains 'procedures_error') {
        Add-Result 'sgi.procedures' 'WARN' ("non valutabili: {0}" -f $facts.procedures_error)
    } elseif ($facts.procedures.count -eq 0) {
        Add-Result 'sgi.procedures' 'WARN' 'nessuna ProcedureRevision corrente di tipo fileserver (solo metadati/SharePoint)'
    } else {
        $nonUnc = @($facts.procedures.non_unc)
        $unread = @($facts.procedures.unreadable)
        if ($nonUnc.Count -eq 0 -and $unread.Count -eq 0) {
            Add-Result 'sgi.procedures' 'PASS' ("{0} procedure fileserver: tutte UNC e leggibili" -f $facts.procedures.count)
        } else {
            $msg = "su {0} procedure: non-UNC={1} non-leggibili={2}" -f $facts.procedures.count, $nonUnc.Count, $unread.Count
            if ($nonUnc.Count -gt 0) { $msg += " | es. non-UNC: " + ($nonUnc[0]) }
            if ($unread.Count -gt 0) { $msg += " | es. non-leggibile: " + ($unread[0]) }
            Add-Result 'sgi.procedures' 'FAIL' $msg
        }
    }
}

# ---- 2: chiavi duplicate nel .env grezzo ---------------------------------
$envFile = $EnvCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $envFile) {
    Add-Result 'env.dupes' 'WARN' ("nessun .env trovato tra: {0}" -f ($EnvCandidates -join ', '))
} else {
    $aiKeys = Get-Content $envFile | Where-Object { $_ -match '^\s*(OLLAMA_|RAG_|AI_|EMBED_|TEI_)\w+\s*=' } |
              ForEach-Object { ($_ -split '=', 2)[0].Trim() }
    $dupes = $aiKeys | Group-Object | Where-Object { $_.Count -gt 1 } | ForEach-Object { "{0}(x{1})" -f $_.Name, $_.Count }
    if ($dupes) {
        Add-Result 'env.dupes' 'WARN' ("{0} : chiavi AI duplicate -> {1}. Vince l'ultima; ripulisci il .env persistente." -f (Split-Path $envFile -Leaf), ($dupes -join ', '))
    } else {
        Add-Result 'env.dupes' 'PASS' ("{0}: nessuna chiave AI duplicata" -f (Split-Path $envFile -Leaf))
    }
}

# ---- 3: Ollama raggiungibile + modelli presenti --------------------------
if ($facts -and $baseUrl) {
    try {
        $tags = Invoke-RestMethod -Uri ("{0}/api/tags" -f $baseUrl.TrimEnd('/')) -TimeoutSec 15 -Method Get
        $names = @($tags.models | ForEach-Object { $_.name })
        $base = { param($m) ($m -split ':')[0] }
        $haveChat = $names | Where-Object { $_ -eq $chatModel -or (& $base $_) -eq (& $base $chatModel) }
        Add-Result 'ollama.reach' 'PASS' ("{0} modelli su {1}" -f $names.Count, $baseUrl)
        Add-Result 'ollama.chat'  ($(if ($haveChat) {'PASS'} else {'FAIL'})) ("modello chat '{0}' {1}" -f $chatModel, $(if ($haveChat) {'presente'} else {"ASSENTE -> ollama pull $chatModel"}))
        # Il modello embed va cercato in Ollama SOLO col backend nativo: con TEI
        # (backend openai) gli embeddings stanno su TEI, non in Ollama (check 3b).
        if ($embOn -and $embBackend -eq 'ollama') {
            $embBase  = [string]$cfg.OLLAMA_EMBED_MODEL
            $haveEmb  = $names | Where-Object { $_ -eq $embBase -or (& $base $_) -eq (& $base $embBase) }
            Add-Result 'ollama.embed' ($(if ($haveEmb) {'PASS'} else {'FAIL'})) ("modello embed '{0}' {1}" -f $embBase, $(if ($haveEmb) {'presente'} else {"ASSENTE -> ollama pull $embBase"}))
        }
    } catch {
        Add-Result 'ollama.reach' 'FAIL' ("{0} irraggiungibile: {1}" -f $baseUrl, $_.Exception.Message)
    }
}

# ---- 3b: TEI (backend embeddings OpenAI-compatibile) ---------------------
if ($facts -and $embOn -and $embBackend -eq 'openai') {
    if (-not $teiBase)  { Add-Result 'tei.config' 'FAIL' 'RAG_EMBED_BACKEND=openai ma RAG_EMBED_OPENAI_BASE_URL vuota' }
    elseif (-not $teiModel) { Add-Result 'tei.config' 'FAIL' 'RAG_EMBED_BACKEND=openai ma RAG_EMBED_OPENAI_MODEL vuoto' }
    else {
        $teiRoot = $teiBase.TrimEnd('/')
        $health = $false
        try { Invoke-RestMethod -Uri ("{0}/health" -f $teiRoot) -TimeoutSec 10 -Method Get | Out-Null; $health = $true } catch { $health = $false }
        try {
            $body = @{ model = $teiModel; input = @('ping') } | ConvertTo-Json
            $resp = Invoke-RestMethod -Uri ("{0}/v1/embeddings" -f $teiRoot) -TimeoutSec 20 -Method Post -ContentType 'application/json' -Body $body
            $dim = 0
            if ($resp.data -and $resp.data[0].embedding) { $dim = @($resp.data[0].embedding).Count }
            $dimWarn = if ($dim -gt 0 -and $dim -ne 1024) { " (atteso 1024 per bge-m3!)" } else { "" }
            Add-Result 'tei.embed' 'PASS' ("TEI ok su {0} | modello={1} | dim={2}{3} | health={4}" -f $teiRoot, $teiModel, $dim, $dimWarn, $health)
        } catch {
            Add-Result 'tei.embed' 'FAIL' ("TEI {0} non risponde su /v1/embeddings: {1} (TEI su per docker? porta 8081?)" -f $teiRoot, $_.Exception.Message)
        }
    }
}

# ---- 4: RAG SGI indicizzato (ai_eval) ------------------------------------
if (-not $SkipSgiEval) {
    Write-Host ''
    Write-Host '... ai_eval --rag-sgi (la prima build legge i PDF/embeddings: puo richiedere minuti)' -ForegroundColor DarkGray
    $sgiRaw = & $PyExe $ManagePy ai_eval --rag-sgi --json --settings=$Settings
    $sgi = Get-EmbeddedJson (($sgiRaw -join "`n")) $null
    if ($sgi -and $sgi.summary) {
        $sm = $sgi.summary
        $st = if ([int]$sm.sgi_chunks -gt 0) { 'PASS' } else { 'FAIL' }
        Add-Result 'rag.sgi_chunks' $st ("sgi_chunks={0} chunk_totali={1} recall={2}/{3} mrr={4} retrieval={5}" -f `
            $sm.sgi_chunks, $sm.chunks_indexed, $sm.recall_hits, $sm.cases, $sm.mrr, $(if ($sm.embeddings_enabled) {'ibrido'} else {'BM25'}))
    } else {
        Add-Result 'rag.sgi_chunks' 'WARN' 'ai_eval --rag-sgi non parsabile (Ollama offline o eval fallito)'
    }

    $ragRaw = & $PyExe $ManagePy ai_eval --rag --json --settings=$Settings
    $rag = Get-EmbeddedJson (($ragRaw -join "`n")) $null
    if ($rag -and $rag.summary) {
        $rm = $rag.summary
        Add-Result 'rag.kb' 'PASS' ("KB curata: recall@{0}={1}/{2} mrr={3}" -f $rm.top_k, $rm.recall_hits, $rm.cases, $rm.mrr)
    } else {
        Add-Result 'rag.kb' 'WARN' 'ai_eval --rag non parsabile'
    }
} else {
    Add-Result 'rag.sgi_chunks' 'WARN' 'saltato (-SkipSgiEval)'
}

# ---- riepilogo -----------------------------------------------------------
Write-Host ''
Write-Host '=== RIEPILOGO ===' -ForegroundColor Cyan
$script:rows | Format-Table -AutoSize Check, State, Detail | Out-String | Write-Host
$fail = @($script:rows | Where-Object { $_.State -eq 'FAIL' })
$warn = @($script:rows | Where-Object { $_.State -eq 'WARN' })
Write-Host ("FAIL: {0}  WARN: {1}  PASS: {2}" -f $fail.Count, $warn.Count, @($script:rows | Where-Object { $_.State -eq 'PASS' }).Count)
Write-Host ''
Write-Host 'NOTE:' -ForegroundColor DarkGray
Write-Host '  - Il check 6 (procedure) usa l''identita di chi lancia lo script. In prod' -ForegroundColor DarkGray
Write-Host '    la lettura reale la fanno l''APP POOL IIS e il Task Scheduler QCluster_PROD:' -ForegroundColor DarkGray
Write-Host '    se hanno identita diverse, verifica che ANCHE loro abbiano Read sulla share.' -ForegroundColor DarkGray
Write-Host '  - Cambiare modello di embedding richiede di rigenerare l''indice:' -ForegroundColor DarkGray
Write-Host '    python django_app\manage.py index_sgi_documents --json --settings=config.settings.prod' -ForegroundColor DarkGray
if ($fail.Count -gt 0) { exit 1 } else { exit 0 }
