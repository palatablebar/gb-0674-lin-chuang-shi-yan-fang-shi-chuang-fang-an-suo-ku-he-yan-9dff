const visitUi={busy:false};const feedback=document.querySelector('#feedback');document.querySelector('#source').value=new URL(location.href).searchParams.get('dataset')||document.querySelector('#source').value;document.querySelector('#run').addEventListener('click',async()=>{if(visitUi.busy)return;visitUi.busy=true;feedback.textContent='核验中…';try{const dataset=document.querySelector('#source').value;const r=await fetch(dataset===document.body.dataset.source?'/api/runs/'+document.body.dataset.runId+'/rerun':'/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset})});const data=await r.json();if(!r.ok)throw Error(data.detail);const url=new URL(location.href);url.searchParams.set('dataset',dataset);url.searchParams.set('run_id',data.manifest.run_id);location.href=url;}catch(e){feedback.textContent=e.message;}finally{visitUi.busy=false;}});
const filePicker=document.querySelector('#csv-file');
if(filePicker){
 const editor=document.querySelector('#csv-text');
 filePicker.addEventListener('change',async()=>{const file=filePicker.files[0];if(!file)return;if(file.size>2000000){editor.value='';alert('文件超过2MB，请缩小后导入');return;}const bytes=await file.arrayBuffer();try{editor.value=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch(e){editor.value=new TextDecoder('gb18030',{fatal:true}).decode(bytes);}});
 document.querySelector('#import-csv').addEventListener('click',async event=>{event.target.disabled=true;try{const response=await fetch('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csv_text:editor.value})});const data=await response.json();if(!response.ok)throw Error(data.detail);location.href=location.pathname+'?run_id='+data.manifest.run_id;}catch(e){editor.setCustomValidity(e.message);editor.reportValidity();}finally{event.target.disabled=false;}});
 editor.addEventListener('input',()=>editor.setCustomValidity(''));
}
const versionBox=document.querySelector('#version-list');
if(versionBox){
 const runId=versionBox.dataset.runId;
 const digest=versionBox.dataset.digest;
 const renderVersions=(items)=>{
  if(!items.length){versionBox.innerHTML='<div class="vrow">尚未发布成员版本</div>';return;}
  versionBox.innerHTML=items.map(v=>`<div class="vrow ${v.status}"><span>${v.version_id}</span><span>${v.status==='current'?'当前':'已失效'}</span><span>${v.digest.slice(0,10)}</span><span>${v.created_at.slice(0,19)}</span></div>`).join('');
 };
 const loadVersions=async()=>{
  const r=await fetch(`/api/runs/${runId}/membership`);
  if(r.ok)renderVersions(await r.json());
 };
 loadVersions();
 document.querySelector('#publish-membership').addEventListener('click',async(e)=>{
  e.target.disabled=true;
  try{
   const r=await fetch(`/api/runs/${runId}/membership/publish`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({digest})});
   const data=await r.json();
   if(!r.ok)throw Error(data.detail);
   feedback.textContent='成员版本 '+data.version_id+'（'+data.status+'）已发布';
   await loadVersions();
  }catch(err){feedback.textContent=err.message;}
  finally{e.target.disabled=false;}
 });
}
const lockBtn=document.querySelector('#lock-scope');
if(lockBtn){
 lockBtn.addEventListener('click',async()=>{
  lockBtn.disabled=true;
  const fb=document.querySelector('#lock-feedback');
  const runId=lockBtn.dataset.runId,digest=lockBtn.dataset.digest;
  try{
   let pr=await fetch(`/api/runs/${runId}/membership/publish`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({digest})});
   let pv=await pr.json();if(!pr.ok)throw Error(pv.detail);
   const lr=await fetch(`/api/runs/${runId}/lock`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version_id:pv.version_id})});
   const lv=await lr.json();if(!lr.ok)throw Error(lv.detail);
   fb.textContent='锁库范围已绑定成员版本 '+lv.locked_membership;
   feedback.textContent='冻结成功，可前往冻结归档下载凭证';
  }catch(e){fb.textContent='冻结失败，保留旧版：'+e.message;}
  finally{lockBtn.disabled=false;}
 });
}
