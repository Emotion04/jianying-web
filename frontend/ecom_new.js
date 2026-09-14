// ── 电商状态 ──
let ecomVideoPaths = [], ecomVideoMeta = null, ecomSubSource = 'asr';
let ecomSrtContent = '', ecomPlans = null, ecomMixMode = 'random';
let ecomSelectedPlan = 0;

// ── 上传视频 ──
(function(){
  const dz = document.getElementById('ecomDz'), inp = document.getElementById('ecomInp');
  if (!dz || !inp) return;
  inp.setAttribute('multiple','');
  dz.addEventListener('click',()=>inp.click());
  inp.addEventListener('change',async()=>{
    const files=Array.from(inp.files);if(!files.length)return;
    const icon=$('#ecomDzIcon'),text=$('#ecomDzText');let up=0;
    for(let i=0;i<files.length;i++){
      const f=files[i];
      if(icon)icon.textContent='...';if(text)text.textContent='Uploading '+(i+1)+'/'+files.length+': '+f.name;
      dz.style.borderColor='var(--primary)';
      const fd=new FormData();fd.append('files',f);
      try{
        const r=await fetch('/api/media/upload',{method:'POST',body:fd});const d=await r.json();
        if(d.files&&d.files[0]){ecomVideoPaths.push({name:f.name,path:d.files[0].saved_path,size:f.size});up++;
          if(up===1){const fi=new FormData();fi.append('files',f);try{const ir=await fetch('/api/media/info',{method:'POST',body:fi});const id=await ir.json();if(id.files&&id.files[0])ecomVideoMeta=id.files[0];}catch(e){}}
        }
      }catch(e){}
    }
    if(icon)icon.textContent=up>0?'Done':'Drop';if(text)text.textContent=up>0?'Uploaded '+up+' videos':'Drop videos or click';
    dz.style.borderColor=up>0?'var(--success)':'';
    const vi=$('#ecomVideoInfo');if(vi&&ecomVideoMeta)vi.textContent=up+' videos | '+(ecomVideoMeta.aspect||'')+' | '+(ecomVideoMeta.duration_seconds||0).toFixed(1)+'s';
    if(up>0)toast('success','Uploaded '+up+' videos');
  });
  dz.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('drag-over');});
  dz.addEventListener('dragleave',()=>dz.classList.remove('drag-over'));
  dz.addEventListener('drop',e=>{e.preventDefault();dz.classList.remove('drag-over');inp.files=e.dataTransfer.files;inp.dispatchEvent(new Event('change'));});
})();
