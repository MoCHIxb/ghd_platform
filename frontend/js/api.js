const BASE='/api';
function getToken(){return localStorage.getItem('token')||''}
async function request(method,path,data=null){
  const headers={}; if(getToken())headers.Authorization='Bearer '+getToken();
  const opts={method,headers}; if(data!==null){if(data instanceof FormData){opts.body=data}else{headers['Content-Type']='application/json';opts.body=JSON.stringify(data)}}
  try{const res=await fetch(BASE+path,opts);return{status:res.status,data:await res.json().catch(()=>({}))}}
  catch(error){return{status:0,data:{msg:'无法连接服务器，请确认后端已启动'},error}}
}
const API={
  login:d=>request('POST','/auth/login',d),profile:()=>request('GET','/auth/profile'),updateProfile:d=>request('PUT','/auth/profile',d),
  overview:()=>request('GET','/club/overview'),departments:()=>request('GET','/club/departments'),members:()=>request('GET','/club/members'),
  activities:(status='')=>request('GET','/club/activities'+(status?'?status='+encodeURIComponent(status):'')),createActivity:d=>request('POST','/club/activities',d),activity:id=>request('GET',`/club/activities/${id}`),transferActivity:(id,d)=>request('PUT',`/club/activities/${id}/transfer`,d),updateParticipant:(id,d)=>request('PUT',`/club/activities/${id}/participants`,d),saveSummary:(id,d)=>request('PUT',`/club/activities/${id}/summary`,d),
  equipment:()=>request('GET','/club/equipment'),createEquipment:d=>request('POST','/club/equipment',d),equipmentCategories:()=>request('GET','/club/equipment/categories'),createEquipmentCategory:d=>request('POST','/club/equipment/categories',d),updateEquipmentCategory:(id,d)=>request('PUT',`/club/equipment/categories/${id}`,d),deleteEquipmentCategory:id=>request('DELETE',`/club/equipment/categories/${id}`),borrow:(id,d)=>request('POST',`/club/equipment/${id}/borrow`,d),usages:()=>request('GET','/club/equipment/usages?active=1'),returnEquipment:id=>request('PUT',`/club/equipment/usages/${id}/return`,{}),
  socials:()=>request('GET','/club/office/socials'),createSocial:d=>request('POST','/club/office/socials',d),archives:()=>request('GET','/club/office/archives'),createArchive:d=>request('POST','/club/office/archives',d),mediaQueue:()=>request('GET','/club/office/media'),reviewMedia:(id,d)=>request('PUT',`/club/office/media/${id}/review`,d)
};
