window.addEventListener('load',()=>{
  const form=document.getElementById('link-checkpoint');
  if(form)form.addEventListener('submit',e=>{const id=document.getElementById('link-duty').value;if(!id){e.preventDefault();return;}form.action='/admin/duties/'+encodeURIComponent(id)+'/checkpoint';});
  const box=document.getElementById('checkpoint-map');if(!box)return;
  if(typeof L==='undefined'){box.textContent='Map unavailable offline. Enter the latitude and longitude manually.';return;}
  const map=L.map(box).setView([12.9716,79.1598],15);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors'}).addTo(map);
  let marker=null;
  function select(lat,lng){document.getElementById('cp-lat').value=lat.toFixed(7);document.getElementById('cp-lon').value=lng.toFixed(7);if(marker)map.removeLayer(marker);marker=L.marker([lat,lng]).addTo(map);}
  map.on('click',e=>select(e.latlng.lat,e.latlng.lng));
  document.getElementById('cp-lat').addEventListener('change',sync);
  document.getElementById('cp-lon').addEventListener('change',sync);
  function sync(){let lat=Number(document.getElementById('cp-lat').value),lon=Number(document.getElementById('cp-lon').value);if(Number.isFinite(lat)&&Number.isFinite(lon)&&Math.abs(lat)<=90&&Math.abs(lon)<=180){select(lat,lon);map.setView([lat,lon],17);}}
});
