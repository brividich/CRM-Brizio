/* NOVICROM HUB — da anomalie/pages/anomalie_configurazione.html (blocco 2), spostato dall'inline il 12/11/2026: stesso punto, ora in cache. */
// ── Logo Menu ──────────────────────────────────────────────────────────────
(function () {
  const previewImg = document.getElementById('logo-preview');
  const placeholder = document.getElementById('logo-placeholder');
  const fileInput  = document.getElementById('logo-file-input');
  const btnUpload  = document.getElementById('btn-logo-upload');
  const btnReset   = document.getElementById('btn-logo-reset');
  const statusEl   = document.getElementById('logo-status');
  if (!btnUpload) return; // non siamo nella tab config
  const getCsrf = () => (document.cookie.split(';').find(c => c.trim().startsWith('csrftoken=')) || '').split('=')[1] || '';

  function showLogo(url) {
    if (url) {
      previewImg.src = url + '?t=' + Date.now();
      previewImg.style.display = 'block';
      placeholder.style.display = 'none';
    } else {
      previewImg.style.display = 'none';
      placeholder.style.display = '';
    }
  }

  function setStatus(ok, msg) {
    statusEl.className = 'status ' + (ok ? 'ok' : 'err');
    statusEl.textContent = msg;
  }

  fetch('/api/anomalie/config/liste')
    .then(r => r.json())
    .then(d => showLogo(d.menu_logo || ''))
    .catch(() => {});

  fileInput.addEventListener('change', function () {
    const file = this.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = e => showLogo(e.target.result);
    reader.readAsDataURL(file);
  });

  btnUpload.addEventListener('click', async function () {
    const file = fileInput.files[0];
    if (!file) { setStatus(false, 'Seleziona prima un file.'); return; }
    const fd = new FormData();
    fd.append('logo', file);
    btnUpload.disabled = true;
    try {
      const r = await fetch('/api/anomalie/config/logo', { method: 'POST', headers: { 'X-CSRFToken': getCsrf() }, body: fd });
      const d = await r.json();
      if (d.success) { showLogo(d.url); setStatus(true, 'Logo salvato. Ricarica il menu per vederlo.'); fileInput.value = ''; }
      else setStatus(false, d.error || 'Errore upload');
    } catch (e) { setStatus(false, e.message); }
    btnUpload.disabled = false;
  });

  btnReset.addEventListener('click', async function () {
    if (!(await hubConfirm('Ripristinare il logo di default?'))) return;
    btnReset.disabled = true;
    try {
      const r = await fetch('/api/anomalie/config/logo/reset', { method: 'POST', headers: { 'X-CSRFToken': getCsrf() } });
      const d = await r.json();
      if (d.success) { showLogo(''); setStatus(true, 'Logo ripristinato al default.'); }
      else setStatus(false, d.error || 'Errore');
    } catch (e) { setStatus(false, e.message); }
    btnReset.disabled = false;
  });
})();
