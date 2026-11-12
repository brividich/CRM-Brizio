/* NOVICROM HUB — da tickets/pages/gestione_detail.html (blocco 1), spostato dall'inline il 12/11/2026: stesso punto, ora in cache. */
/* Copilota AI di triage (Ondata 3.1): proposta read-only. Pre-compila i campi
   esistenti ma NON salva: il gestore conferma con i pulsanti gia' presenti. */
(function(){
  const btn=document.getElementById("copilota-run");
  if(!btn)return;
  const statusEl=document.getElementById("copilota-status");
  const resEl=document.getElementById("copilota-result");
  function setAssegnatario(nome){
    const sel=document.getElementById("assign-membro");
    if(!sel||!nome)return false;
    let found=false;
    Array.from(sel.options).forEach(o=>{if(o.value===nome){sel.value=nome;found=true;}});
    return found;
  }
  btn.addEventListener("click",async function(){
    btn.disabled=true;statusEl.textContent="Analisi in corso...";resEl.style.display="none";
    try{
      const r=await fetch(this.dataset.url,{method:"POST",headers:{"Content-Type":"application/json","X-CSRFToken":CSRF},body:JSON.stringify({ticket_id:TICKET_ID})});
      const d=await r.json();
      if(!r.ok||!d.ok){statusEl.textContent=(d&&d.error)||"Errore.";btn.disabled=false;return;}
      const p=d.proposta||{};
      if(!p.ai_disponibile){statusEl.textContent="AI non disponibile al momento. Riprova piu tardi.";btn.disabled=false;return;}
      statusEl.textContent="Proposta pronta (rivedi e firma):";
      const prio=p.incide_sicurezza?((p.priorita||"")+" (sicurezza)"):(p.priorita||"");
      let html='<div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;padding:10px 12px;">';
      html+='<div><strong>Categoria:</strong> '+(escapeHtml(p.categoria)||"&mdash;")+'</div>';
      html+='<div><strong>Priorita:</strong> '+(escapeHtml(prio)||"&mdash;")+'</div>';
      html+='<div><strong>Sicurezza:</strong> '+(p.incide_sicurezza?"si":"no")+'</div>';
      html+='<div><strong>Assegnatario:</strong> '+(p.assegnatario?escapeHtml(p.assegnatario.nome):"&mdash;")+'</div>';
      if(p.motivazione)html+='<div style="margin-top:6px;color:#475569;"><em>'+escapeHtml(p.motivazione)+'</em></div>';
      if(p.bozza_risoluzione)html+='<div style="margin-top:8px;"><strong>Bozza risoluzione:</strong><br>'+escapeHtml(p.bozza_risoluzione).replace(/\n/g,"<br>")+'</div>';
      html+='<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;">';
      if(p.assegnatario)html+='<button type="button" class="tkt-btn-sm tkt-btn-gray" id="copilota-use-assegna">Usa assegnatario</button>';
      if(p.bozza_risoluzione)html+='<button type="button" class="tkt-btn-sm tkt-btn-gray" id="copilota-use-bozza">Usa bozza nel commento</button>';
      html+='</div><div id="copilota-apply-status" style="font-size:11px;color:#16a34a;margin-top:6px;"></div></div>';
      resEl.innerHTML=html;resEl.style.display="";
      const applyStatus=document.getElementById("copilota-apply-status");
      const ua=document.getElementById("copilota-use-assegna");
      if(ua)ua.addEventListener("click",function(){
        const ok=setAssegnatario(p.assegnatario&&p.assegnatario.nome);
        applyStatus.textContent=ok?"Assegnatario impostato: premi 'Salva assegnazione' per confermare.":"Assegnatario non in elenco: selezionalo a mano.";
      });
      const ub=document.getElementById("copilota-use-bozza");
      if(ub)ub.addEventListener("click",function(){
        const ta=document.getElementById("commento-testo");
        if(ta){ta.value=p.bozza_risoluzione;applyStatus.textContent="Bozza inserita nel commento: rivedila e premi 'Aggiungi commento'.";ta.scrollIntoView({behavior:"smooth",block:"center"});}
      });
    }catch(e){statusEl.textContent="Errore di rete.";}
    btn.disabled=false;
  });
})();
