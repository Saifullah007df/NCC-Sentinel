for(const el of document.querySelectorAll('.local-time')){const ts=Number(el.dataset.ts);el.textContent=new Date(ts*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short'});} 
const panel=document.getElementById('challenge-panel');
if(panel){
 let challenge=null,serverOffset=0,busy=false;
 const feedback=document.getElementById('challenge-feedback');
 async function post(url,obj){const resp=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({...obj,csrf:panel.dataset.csrf})});const data=await resp.json();if(!resp.ok)throw new Error(data.detail||'Request failed');return data;}
 async function refresh(){
  try{const resp=await fetch('/api/challenge',{cache:'no-store'});if(!resp.ok)return;const data=await resp.json();serverOffset=data.server_time-Date.now()/1000;
  if(!data.challenge){panel.classList.add('hidden');challenge=null;return;}
  const fresh=!challenge||challenge.id!==data.challenge.id;challenge=data.challenge;
  panel.classList.remove('hidden');document.getElementById('challenge-duty').textContent='Duty: '+challenge.title;
  document.getElementById('captcha-question').textContent=challenge.captcha_text;
  if(fresh){if(document.getElementById('captcha-answer'))document.getElementById('captcha-answer').value='';document.getElementById('duty-otp').value='';feedback.textContent='';}
  document.getElementById('captcha-area').classList.toggle('hidden',!!challenge.captcha_passed);
  document.getElementById('otp-area').classList.toggle('hidden',!challenge.captcha_passed);
  }catch(e){feedback.textContent='Connection issue. Trying to reconnect.';}
 }
 document.getElementById('captcha-form').addEventListener('submit',async e=>{e.preventDefault();if(!challenge||busy)return;busy=true;try{const data=await post('/api/challenge/captcha',{id:challenge.id,answer:document.getElementById('captcha-answer')?.value||'',turnstile_token:document.querySelector('[name=cf-turnstile-response]')?.value||''});feedback.textContent=data.ok?'CAPTCHA accepted. Enter SMS OTP.':'Incorrect CAPTCHA. Try again.';await refresh();}catch(err){feedback.textContent=err.message;}finally{busy=false;}});
 document.getElementById('otp-form').addEventListener('submit',async e=>{e.preventDefault();if(!challenge||busy)return;busy=true;try{const data=await post('/api/challenge/otp',{id:challenge.id,code:document.getElementById('duty-otp').value});feedback.textContent=data.ok?'OTP verified. Complete the GPS check if one is assigned.':'Invalid OTP.';if(data.ok&&data.location)window.dispatchEvent(new CustomEvent('ncc:location-created',{detail:data.location}));if(data.ok){panel.classList.add('hidden');challenge=null;setTimeout(()=>location.reload(),1200);}}catch(err){feedback.textContent=err.message;}finally{busy=false;}});
 setInterval(()=>{if(!challenge)return;const remain=Math.max(0,Math.ceil(challenge.deadline-(Date.now()/1000+serverOffset)));document.getElementById('seconds').textContent=remain+'s';if(remain===0)refresh();},250);
 setInterval(refresh,3000);refresh();
}
// A location challenge is issued only after a successful CAPTCHA+OTP check.
const locationPanel=document.getElementById('location-panel');
if(locationPanel){
 let currentLocation=null,offset=0,processing=false;
 const info=document.getElementById('gps-status');
 const status=document.getElementById('gps-checkpoint');
 const startButton=document.getElementById('gps-start');
 async function refreshLocation(){
  try{const r=await fetch('/api/location/challenge',{cache:'no-store'});if(!r.ok)return;
    const v=await r.json();offset=v.server_time-Date.now()/1000;const lc=v.challenge;
    if(!lc){locationPanel.classList.add('hidden');return;}
    if(!currentLocation||currentLocation.id!==lc.id){currentLocation=lc;info.textContent='GPS verification is required after your duty OTP.';}
    locationPanel.classList.remove('hidden');status.textContent=`Checkpoint: ${lc.checkpoint_name} · Radius: ${lc.radius_m} metres`;
  }catch(e){info.textContent='Unable to reach the server for location verification.';}
 }
 async function submitLocation(samples){
   const token=sessionStorage.getItem('ncc_gps_nonce_'+currentLocation.id);
   if(!token)throw new Error('Location security token not available. Re-login/ask admin to review the missed check.');
   const r=await fetch('/api/location/submit',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:currentLocation.id,nonce:token,csrf:locationPanel.dataset.csrf,samples})});
   const body=await r.json();if(!r.ok)throw new Error(body.detail||'Location validation failed');
   if(body.status!=='accuracy_insufficient')sessionStorage.removeItem('ncc_gps_nonce_'+currentLocation.id);
   return body;
 }
 startButton.addEventListener('click',()=>{
  if(processing||!currentLocation)return;
  if(!navigator.geolocation){info.textContent='Geolocation is not supported by this browser.';return;}
  processing=true;startButton.disabled=true;info.textContent='Collecting 3 fresh location fixes. Keep this page open...';
  const fixes=[];let watchId=null;let timeoutId=null;let done=false;
  const stop=()=>{if(watchId!==null)navigator.geolocation.clearWatch(watchId);if(timeoutId!==null)clearTimeout(timeoutId);processing=false;startButton.disabled=false;};
  watchId=navigator.geolocation.watchPosition(async p=>{
   if(done)return;
   const ts=p.timestamp;
   if(!fixes.some(f=>f.timestamp===ts))fixes.push({latitude:p.coords.latitude,longitude:p.coords.longitude,accuracy:p.coords.accuracy,timestamp:ts});
   info.textContent=`Collected ${fixes.length}/3 GPS readings · latest reported accuracy ${p.coords.accuracy.toFixed(1)} m`;
   if(fixes.length>=3){done=true;stop();try{const result=await submitLocation(fixes);info.textContent=`${result.status.replaceAll('_',' ').toUpperCase()} — distance ${result.distance_m} m, accuracy ${result.accuracy_m} m. ${result.status==='accuracy_insufficient'?'Move to open sky and retry before expiration.':'Device estimate only.'}`;setTimeout(refreshLocation,4000);}catch(e){info.textContent=e.message;}}
  },err=>{if(done)return;done=true;stop();info.textContent='Location failed: '+err.message+' (permission or signal issue).';fetch('/api/location/report-error',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:currentLocation.id,reason:err.code===1?'permission_denied':'location_unavailable',csrf:locationPanel.dataset.csrf})}).catch(()=>{});},{enableHighAccuracy:true,maximumAge:0,timeout:15000});
  timeoutId=setTimeout(()=>{if(!done){done=true;stop();info.textContent='Not enough distinct GPS readings. Retry in an open location before the deadline.';}},27000);
 });
 setInterval(()=>{if(currentLocation&&!locationPanel.classList.contains('hidden'))document.getElementById('gps-timer').textContent=Math.max(0,Math.ceil(currentLocation.expires_at-(Date.now()/1000+offset)))+'s';},250);
 setInterval(refreshLocation,3500);refreshLocation();
 // Duty OTP handler dispatches this after the server issues location challenge.
 window.addEventListener('ncc:location-created',evt=>{const loc=evt.detail;if(loc){sessionStorage.setItem('ncc_gps_nonce_'+loc.id,loc.nonce);refreshLocation();}});
}
