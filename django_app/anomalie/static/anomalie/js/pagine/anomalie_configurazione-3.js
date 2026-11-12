/* NOVICROM HUB — da anomalie/pages/anomalie_configurazione.html (blocco 3), spostato dall'inline il 12/11/2026: stesso punto, ora in cache. */
// ── Template Report Segnalazione ────────────────────────────────────────────
(function () {
  const badge      = document.getElementById('tpl-status-badge');
  const detail     = document.getElementById('tpl-status-detail');
  const btnReset   = document.getElementById('btn-tpl-reset');
  const fileInput  = document.getElementById('tpl-file-input');
  const btnUpload  = document.getElementById('btn-tpl-upload');
  const uploadSt   = document.getElementById('tpl-upload-status');
  const valResult  = document.getElementById('tpl-validation-result');
  if (!badge) return; // non siamo nella tab config
  const getCsrf = () => (document.cookie.split(';').find(c => c.trim().startsWith('csrftoken=')) || '').split('=')[1] || '';

  function setUploadStatus(ok, msg) {
    uploadSt.className = 'status ' + (ok ? 'ok' : 'err');
    uploadSt.textContent = msg;
  }

  function showValidation(errors) {
    if (!errors || !errors.length) {
      valResult.style.display = 'none';
      return;
    }
    valResult.style.display = 'block';
    valResult.style.background = 'var(--danger-bg)';
    valResult.style.border = '1px solid #fca5a5';
    valResult.style.color = 'var(--danger)';
    valResult.innerHTML = '<strong>Errori di validazione:</strong><ul style="margin:6px 0 0;padding-left:18px;">'
      + errors.map(e => `<li>${e}</li>`).join('') + '</ul>';
  }

  function refreshStatus() {
    fetch('/api/anomalie/config/report-template')
      .then(r => r.json())
      .then(d => {
        if (d.custom) {
          badge.textContent = 'Template personalizzato attivo';
          badge.style.background = 'var(--success-bg)';
          badge.style.color = 'var(--success)';
          badge.style.border = '1px solid #86efac';
          detail.textContent = d.filename ? `File: ${d.filename}` : '';
          btnReset.style.display = '';
        } else {
          badge.textContent = 'Template di default';
          badge.style.background = 'var(--bg)';
          badge.style.color = 'var(--text-mid)';
          badge.style.border = '1px solid var(--border)';
          detail.textContent = 'Nessun template personalizzato attivo.';
          btnReset.style.display = 'none';
        }
      })
      .catch(() => {
        badge.textContent = 'Errore caricamento stato';
        badge.style.color = 'var(--danger)';
      });
  }

  btnReset.addEventListener('click', async function () {
    if (!(await hubConfirm('Ripristinare il template di default? Il template personalizzato verrà eliminato.'))) return;
    btnReset.disabled = true;
    try {
      const fd = new FormData();
      fd.append('action', 'reset');
      const r = await fetch('/api/anomalie/config/report-template', { method: 'POST', headers: { 'X-CSRFToken': getCsrf() }, body: fd });
      const d = await r.json();
      if (d.success) { refreshStatus(); setUploadStatus(true, d.message); valResult.style.display = 'none'; }
      else setUploadStatus(false, d.error || 'Errore');
    } catch (e) { setUploadStatus(false, e.message); }
    btnReset.disabled = false;
  });

  btnUpload.addEventListener('click', async function () {
    const file = fileInput.files[0];
    if (!file) { setUploadStatus(false, 'Seleziona prima un file .html.'); return; }
    valResult.style.display = 'none';
    btnUpload.disabled = true;
    try {
      const fd = new FormData();
      fd.append('action', 'upload');
      fd.append('template', file);
      const r = await fetch('/api/anomalie/config/report-template', { method: 'POST', headers: { 'X-CSRFToken': getCsrf() }, body: fd });
      const d = await r.json();
      if (d.success) {
        refreshStatus();
        setUploadStatus(true, d.message);
        fileInput.value = '';
      } else {
        showValidation(d.errors);
        setUploadStatus(false, 'Validazione fallita. Correggi gli errori e ricarica.');
      }
    } catch (e) { setUploadStatus(false, e.message); }
    btnUpload.disabled = false;
  });

  refreshStatus();
})();
