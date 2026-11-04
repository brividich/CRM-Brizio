<?php
// =============================================
// public/admin/sso.php  —  Accesso automatico da NOVICROM HUB
//
// L'HUB (fornitori/guestportal.py) reindirizza qui con ?t=<token>:
//   token = base64url(payload JSON) . "." . base64url(HMAC-SHA256(payload, segreto))
//   payload = {u: username dominio, iat, exp (iat+60), n: nonce, iss: "novicrom-hub"}
//
// Regole:
// - segreto condiviso in config/sso.php (GP_SSO_SECRET), mai nel codice;
// - token valido 60 secondi e usabile UNA volta (nonce registrato in AuditLog);
// - chi entra lo decide sempre AdminUsers (presente e attivo), come il login LDAP;
// - l'account master non entra mai da qui;
// - qualsiasi errore riporta al login normale (index.php), senza dettagli.
// Nessun file esistente è stato modificato: se questo file viene rimosso il
// pannello funziona come prima.
// =============================================

// Stesso log degli altri endpoint: senza file, error_log() scrive su stderr e
// IIS/FastCGI risponde 500 invece del redirect al login.
ini_set('error_log', 'C:\\Windows\\Temp\\guestportal.log');
ini_set('log_errors', '1');
ini_set('display_errors', '0');

require_once dirname(dirname(__DIR__)) . '/bootstrap.php';

header('Cache-Control: no-store');
header('Referrer-Policy: no-referrer');
header('X-Content-Type-Options: nosniff');

function gp_sso_fallisci(string $motivo): void {
    error_log('[SSO] accesso rifiutato: ' . $motivo);
    header('Location: index.php', true, 302);
    exit;
}

function gp_sso_b64dec(string $s) {
    if ($s === '' || preg_match('/[^A-Za-z0-9_-]/', $s)) {
        return false;
    }
    $pad = strlen($s) % 4;
    if ($pad) {
        $s .= str_repeat('=', 4 - $pad);
    }
    return base64_decode(strtr($s, '-_', '+/'), true);
}

$cfgFile = APP_ROOT . '/config/sso.php';
if (!is_file($cfgFile)) {
    gp_sso_fallisci('config/sso.php assente');
}
require_once $cfgFile;
if (!defined('GP_SSO_SECRET') || strlen(GP_SSO_SECRET) < 32) {
    gp_sso_fallisci('segreto non configurato');
}
$maxSkew = defined('GP_SSO_MAX_SKEW') ? (int) GP_SSO_MAX_SKEW : 30;

// Già dentro: niente da fare.
AdminAuth::startSession();
if (AdminAuth::isAuthenticated()) {
    header('Location: dashboard.php', true, 302);
    exit;
}

// ─── Verifica token ─────────────────────────
$token = isset($_GET['t']) ? (string) $_GET['t'] : '';
if ($token === '' || strlen($token) > 2048 || substr_count($token, '.') !== 1) {
    gp_sso_fallisci('token mancante o malformato');
}
list($corpo, $firma) = explode('.', $token, 2);

$attesa = rtrim(strtr(base64_encode(hash_hmac('sha256', $corpo, GP_SSO_SECRET, true)), '+/', '-_'), '=');
if (!hash_equals($attesa, $firma)) {
    gp_sso_fallisci('firma non valida');
}

$json = gp_sso_b64dec($corpo);
$p = $json === false ? null : json_decode($json, true);
if (!is_array($p)) {
    gp_sso_fallisci('payload non leggibile');
}

$adesso = time();
$utente = isset($p['u']) ? strtolower(trim((string) $p['u'])) : '';
$iat    = isset($p['iat']) ? (int) $p['iat'] : 0;
$exp    = isset($p['exp']) ? (int) $p['exp'] : 0;
$nonce  = isset($p['n']) ? (string) $p['n'] : '';

if (($p['iss'] ?? '') !== 'novicrom-hub') {
    gp_sso_fallisci('emittente non valido');
}
if (!preg_match('/^[a-z0-9._-]{1,100}$/', $utente)) {
    gp_sso_fallisci('username non valido');
}
if (!preg_match('/^[a-f0-9]{16,64}$/', $nonce)) {
    gp_sso_fallisci('nonce non valido');
}
if ($exp <= $iat || ($exp - $iat) > 120) {
    gp_sso_fallisci('durata token non valida');
}
if ($iat > $adesso + $maxSkew || $exp + $maxSkew < $adesso) {
    gp_sso_fallisci('token scaduto o orologi non allineati');
}
if (strtolower(ADMIN_MASTER_USER) === $utente) {
    gp_sso_fallisci('account master escluso');
}

try {
    $db = Database::getInstance();

    // ─── Uso singolo: il nonce si "brucia" in AuditLog prima di tutto ──
    $dettaglio = json_encode(['nonce' => $nonce]);
    $usato = $db->fetchOne($db->query(
        "SELECT LogID FROM AuditLog
         WHERE TableName = 'SSO' AND Action = 'SSO_LOGIN' AND Details = ?
         LIMIT 1",
        [$dettaglio]
    ));
    if ($usato) {
        gp_sso_fallisci('token già usato');
    }
    $ip = isset($_SERVER['REMOTE_ADDR']) ? substr((string) $_SERVER['REMOTE_ADDR'], 0, 45) : null;
    $db->query(
        "INSERT INTO AuditLog (TableName, RecordID, Action, PerformedBy, PerformedAt, IPAddress, Details)
         VALUES ('SSO', 0, 'SSO_LOGIN', ?, NOW(), ?, ?)",
        [$utente . ' (HUB)', $ip, $dettaglio]
    );

    // ─── Autorizzazione: stessa regola del login LDAP ──
    $row = $db->fetchOne($db->query(
        "SELECT AdminID, DisplayName, IsActive FROM AdminUsers WHERE Username = ?",
        [$utente]
    ));
    if (!$row || !$row['IsActive']) {
        gp_sso_fallisci('utente non abilitato in AdminUsers');
    }
    $db->query("UPDATE AdminUsers SET LastLoginAt = NOW() WHERE AdminID = ?", [$row['AdminID']]);

} catch (\Throwable $e) {
    gp_sso_fallisci('errore DB: ' . $e->getMessage());
}

// ─── Sessione: stessi campi di AdminAuth::createSession ──
session_regenerate_id(true);
$_SESSION['admin_user']    = $utente;
$_SESSION['admin_display'] = $row['DisplayName'];
$_SESSION['admin_master']  = false;
$_SESSION['admin_expires'] = time() + 3600;

header('Location: dashboard.php', true, 302);
exit;
