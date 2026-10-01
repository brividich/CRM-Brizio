#Requires -Version 5.1
# Execute only the installer's credential guard, never its task mutations.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$path=Join-Path $PSScriptRoot '..\scripts\install-qcluster-watchdog.ps1'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Installer parse error' }
$guard=$ast.Find({param($node)
    $node -is [Management.Automation.Language.IfStatementAst] -and
    $node.Extent.Text.StartsWith("if (`$logon -eq 'Password')")
},$false)
$code=[scriptblock]::Create($guard.Extent.Text)
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$script:testSid=$identity.User.Value
$worker=[pscustomobject]@{Principal=[pscustomobject]@{UserId='abbreviated-display-name'}}
$taskPath='\Synthetic\'; $workerName='Synthetic'; $logon='Password'
function Export-ScheduledTask { param($TaskPath,$TaskName)
    "<Task><Principals><Principal><UserId>$script:testSid</UserId></Principal></Principals></Task>"
}
$Credential=[PSCredential]::new($identity.Name,(ConvertTo-SecureString 'synthetic-unused' -AsPlainText -Force))
& $code
Write-Host 'PASS: matching SID despite different display name'
$script:testSid='S-1-5-18'
if ($identity.User.Value -eq $script:testSid) { $script:testSid='S-1-5-19' }
$failed=$false
try { & $code } catch { $failed=$_.Exception.Message -like '*SID diverso*' }
if (-not $failed) { throw 'Different account accepted' }
Write-Host 'PASS: different SID rejected'
$script:testSid='S-1-invalid'
$failed=$false
try { & $code } catch { $failed=$_.Exception.Message -like '*Impossibile risolvere*' }
if (-not $failed) { throw 'Unresolvable account accepted' }
Write-Host 'PASS: unresolvable identity rejected'
$Credential=$null
$failed=$false
try { & $code } catch { $failed=$_.Exception.Message -like '*Passare -Credential*' }
if (-not $failed) { throw 'Missing credentials accepted' }
Write-Host 'PASS: missing credentials rejected'
$logon='Interactive'
$failed=$false
try { & $code } catch { $failed=$_.Exception.Message -like '*non interattivo*' }
if (-not $failed) { throw 'Interactive account accepted' }
Write-Host 'PASS: interactive logon rejected'

. (Join-Path $PSScriptRoot '..\scripts\qcluster-console.ps1') -Environment test
$script:testSid=$identity.User.Value
$resolved=Get-QCWorkerAccount
if ($resolved -ne $identity.Name) { throw 'Console did not resolve canonical account from task SID' }
Write-Host 'PASS: console resolves full account from task SID'
$script:testSid='S-1-invalid'
$failed=$false
try { Get-QCWorkerAccount } catch { $failed=$_.Exception.Message -like '*Impossibile risolvere*' }
if (-not $failed) { throw 'Console accepted unresolvable account' }
Write-Host 'PASS: console refuses unresolvable task account'
