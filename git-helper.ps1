param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("start-feature", "start-fix", "start-hotfix", "commit", "push", "release-start", "release-finish")]
    [string]$Action,

    [string]$Name,
    [string]$Message,
    [string]$Version
)

function Fail($msg) {
    Write-Error $msg
    exit 1
}

function Ensure-GitRepo {
    git rev-parse --is-inside-work-tree *> $null
    if ($LASTEXITCODE -ne 0) {
        Fail "Cartella non valida: non sei dentro un repository git."
    }
}

function Ensure-CleanEnough {
    git status --short
}

Ensure-GitRepo

switch ($Action) {
    "start-feature" {
        if (-not $Name) { Fail "Specifica -Name per il branch feature." }
        git checkout develop
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile fare checkout develop." }

        git pull origin develop
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile aggiornare develop." }

        git checkout -b "feature/$Name"
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile creare il branch feature/$Name." }

        Write-Host "Creato branch feature/$Name"
    }

    "start-fix" {
        if (-not $Name) { Fail "Specifica -Name per il branch fix." }
        git checkout develop
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile fare checkout develop." }

        git pull origin develop
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile aggiornare develop." }

        git checkout -b "fix/$Name"
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile creare il branch fix/$Name." }

        Write-Host "Creato branch fix/$Name"
    }

    "start-hotfix" {
        if (-not $Name) { Fail "Specifica -Name per il branch hotfix." }
        git checkout main
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile fare checkout main." }

        git pull origin main
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile aggiornare main." }

        git checkout -b "hotfix/$Name"
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile creare il branch hotfix/$Name." }

        Write-Host "Creato branch hotfix/$Name"
    }

    "commit" {
        if (-not $Message) { Fail "Specifica -Message per il commit." }
        git add .
        if ($LASTEXITCODE -ne 0) { Fail "git add fallito." }

        git commit -m $Message
        if ($LASTEXITCODE -ne 0) { Fail "git commit fallito." }

        Write-Host "Commit creato: $Message"
    }

    "push" {
        $branch = git branch --show-current
        if (-not $branch) { Fail "Impossibile determinare il branch corrente." }

        git push -u origin $branch
        if ($LASTEXITCODE -ne 0) { Fail "git push fallito." }

        Write-Host "Push completato su $branch"
    }

    "release-start" {
        if (-not $Version) { Fail "Specifica -Version es. 0.5.0" }

        git checkout develop
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile fare checkout develop." }

        git pull origin develop
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile aggiornare develop." }

        git checkout -b "release/$Version"
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile creare release/$Version." }

        Set-Content -Path "VERSION" -Value $Version
        git add VERSION
        git commit -m "docs(release): imposta versione $Version"
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile creare commit release." }

        Write-Host "Branch release/$Version creato e VERSION aggiornato."
    }

    "release-finish" {
        if (-not $Version) { Fail "Specifica -Version es. 0.5.0" }

        git checkout main
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile fare checkout main." }

        git pull origin main
        if ($LASTEXITCODE -ne 0) { Fail "Impossibile aggiornare main." }

        git merge "release/$Version"
        if ($LASTEXITCODE -ne 0) { Fail "Merge release/$Version -> main fallito." }

        git tag -a "v$Version" -m "Release $Version"
        if ($LASTEXITCODE -ne 0) { Fail "Tag release fallito." }

        Write-Host "Release completata localmente. Esegui push di main e del tag dopo verifica."
    }
}