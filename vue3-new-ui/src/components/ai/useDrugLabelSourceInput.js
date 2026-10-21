import {computed,onActivated,onBeforeUnmount,onDeactivated,onMounted,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical,supportId} from '@/api/inpatientSupport';
import {getDrugLabelOptions,getDrugLabelSource,drugLabelOptionsValid,verifyDrugLabelSource} from '@/api/ai/drugLabelSources';

export function drugLabelReferencesValid(value){
 if(value===null||value===undefined)return true;
 if(typeof value!=='object'||Array.isArray(value)||![Object.prototype,null].includes(Object.getPrototypeOf(value)))return false;
 const keys=Object.keys(value);return keys.length===0||keys.length===1&&keys[0]==='drug_label_source_binding_id'&&supportId(value.drug_label_source_binding_id);
}
const anchors=row=>({source_binding_id:row.snapshot.source_binding_id,source_id:row.source_id,content_hash:row.content_hash,governance_hash:row.governance_hash,identity_hash:row.snapshot.identity_hash,identity:structuredClone(row.snapshot.identity),original:{original_id:row.snapshot.original.snapshot.original_id,content_hash:row.snapshot.original.content_hash,governance_hash:row.snapshot.original.governance_hash,raw_bytes_hash:row.snapshot.original.snapshot.raw_bytes_hash},professional:{professional_review_id:row.professional_review.snapshot.professional_review_id,content_hash:row.professional_review.content_hash,governance_hash:row.professional_review.governance_hash}});
export function useDrugLabelSourceInput(props,emit){
 const store=useStore(),kept=ref(true),blocked=ref(false),selected=ref(null),open=ref(false),busy=ref(false),error=ref(''),options=ref(null);
 const token=computed(()=>store.state.user?.accessToken||''),roles=computed(()=>JSON.stringify(store.state.user?.permissions||[])),username=computed(()=>store.state.user?.username||''),role=computed(()=>{const r=store.state.user?.permissions||[];return r.includes('super_admin')?'super_admin':r.includes('pharmacist')?'pharmacist':null;});
 const referencesValid=computed(()=>drugLabelReferencesValid(props.initialReferences)),referenceKey=computed(()=>{try{return supportCanonical(props.initialReferences??null);}catch{return 'invalid';}}),scopeValid=computed(()=>props.pharmaceuticalId===null||Number.isSafeInteger(props.pharmaceuticalId)&&props.pharmaceuticalId>0&&props.pharmaceuticalId<=2147483647),authorized=computed(()=>props.active&&kept.value&&!blocked.value&&!!token.value&&!!role.value&&referencesValid.value&&scopeValid.value);
 const preset=computed(()=>referencesValid.value?props.initialReferences?.drug_label_source_binding_id||null:null),panelPharmaceuticalId=computed(()=>props.pharmaceuticalId??selected.value?.identity.pharmaceutical_id??null);
 let mounted=false,version=0;
 const ticket=()=>({version:++version,token:token.value,roles:roles.value,username:username.value,ref:referenceKey.value,sku:props.pharmaceuticalId}),current=t=>mounted&&authorized.value&&t.version===version&&t.token===token.value&&t.roles===roles.value&&t.username===username.value&&t.ref===referenceKey.value&&t.sku===props.pharmaceuticalId;
 function clear({close=false,invalidate=true}={}){version++;selected.value=null;busy.value=false;if(close)open.value=false;emit('availability',false);if(invalidate)emit('invalidate');}
 function failed(cause,t){if(!current(t))return;clear({close:true});const status=cause?.response?.status;if([401,403].includes(status)){blocked.value=true;options.value=null;error.value='当前会话或权限已失效，来源选择已清除。';}else error.value=status===409?'来源或签署已改变，请显式重读；旧选择未恢复。':'完整来源、当前签署或药品范围无法核对，未建立选择。';}
 async function read(id,candidate=null){if(!authorized.value||!supportId(id))return;clear();const t=ticket();busy.value=true;error.value='';try{
  const capability=(await getDrugLabelOptions()).data;if(!current(t))return;if(!drugLabelOptionsValid(capability,{role:role.value}))throw new Error('当前角色能力不符');options.value=capability;
  const row=(await getDrugLabelSource(id,{auditOnly:false})).data;if(!await verifyDrugLabelSource(row,{pharmaceuticalId:props.pharmaceuticalId,role:role.value,actorId:capability.professional_signer_user_id,execution:true,current:()=>current(t)})||row.snapshot.source_binding_id!==id||candidate&&supportCanonical(anchors(candidate))!==supportCanonical(anchors(row)))throw new Error('已选来源与当前完整原件不符');if(!current(t))return;
  selected.value=anchors(row);open.value=false;emit('scope-change',{pharmaceuticalId:row.snapshot.identity.pharmaceutical_id});emit('selection',{drug_label_source_binding_id:id});emit('availability',true);
 }catch(cause){failed(cause,t);}finally{if(current(t))busy.value=false;}}
 function select(row){if(!authorized.value||row?.eligible!==true||row.audit_only!==false)return;read(row.snapshot.source_binding_id,row);}
 function showSources(){if(!authorized.value)return;clear();error.value='';open.value=true;}
 function closeSources(){clear({close:true});}
 function sourceChanged(){clear();}
 function invalidate(){clear();}
 function reread(){const id=selected.value?.source_binding_id||preset.value;if(id)read(id);}
 watch([token,roles,username,referenceKey,()=>props.pharmaceuticalId,()=>props.active,kept],()=>{blocked.value=false;options.value=null;error.value='';clear({close:true});emit('scope-change',{pharmaceuticalId:props.pharmaceuticalId});},{flush:'sync'});
 onMounted(()=>{mounted=true;clear();});onActivated(()=>{kept.value=true;});onDeactivated(()=>{kept.value=false;});onBeforeUnmount(()=>{mounted=false;options.value=null;clear({close:true});});
 return {authorized,referencesValid,scopeValid,preset,panelPharmaceuticalId,selected,open,busy,error,read,select,showSources,closeSources,sourceChanged,invalidate,reread,clear};
}
