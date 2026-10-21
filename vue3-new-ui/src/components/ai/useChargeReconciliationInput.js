import{computed,onActivated,onBeforeUnmount,onDeactivated,ref,watch}from'vue';
import{useStore}from'vuex';
import{getChargeReconciliationCase,verifyChargeReconciliationCase,chargeCaseReferencesValid,chargeScopeValid}from'@/api/ai/chargeReconciliationSources';
import{supportCanonical as canonical}from'@/api/inpatientSupport';
const empty=v=>v===null||v!==null&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length===0;
export function useChargeReconciliationInput(props,emit){
 const store=useStore(),roles=computed(()=>store.getters['user/permissions']||[]),allowed=computed(()=>props.active&&!!store.state.user.accessToken&&roles.value.some(r=>['admin','super_admin','cashier','director'].includes(r)));
 const scope=computed(()=>({patient_id:props.patientId,admission_id:props.admissionId})),scopeReady=computed(()=>allowed.value&&chargeScopeValid(scope.value));
 const selected=ref(null),checking=ref(false),error=ref(''),childKey=ref(0);let epoch=0,sequence=0,alive=true,paused=false,initialConsumed=false;
 const identity=()=>JSON.stringify([props.patientId,props.admissionId,props.initialReferences,props.active,store.state.user.accessToken,store.state.user.username,roles.value]),ticket=()=>({epoch,identity:identity()}),current=t=>alive&&!paused&&allowed.value&&t.epoch===epoch&&t.identity===identity();
 function invalidate(notify=true){sequence++;selected.value=null;checking.value=false;emit('selection',null);emit('availability',false);if(notify)emit('invalidate');}
 function reset(notify=true){epoch++;childKey.value++;error.value='';invalidate(notify);emit('scope-change',null);}
 function clearSelection(){initialConsumed=true;childKey.value++;invalidate();}
 function fail(message){invalidate();error.value=message||'当前完整账目或真实住院已无法核对，旧选择已清除。';}
 async function select(value){invalidate();const t=ticket(),version=sequence;if(!current(t)||!scopeReady.value)return;checking.value=true;error.value='';initialConsumed=true;
  try{const refs=value?.case_snapshot_id?{charge_case_id:value.case_snapshot_id}:value;if(!chargeCaseReferencesValid(refs))throw new Error('账目引用须只包含一个规范完整账目原件标识。');
   const row=(await getChargeReconciliationCase(refs.charge_case_id,{auditOnly:false})).data;if(!current(t)||version!==sequence)return;
   if(row.case_snapshot_id!==refs.charge_case_id||row.audit_only!==false||!row.eligible||!await verifyChargeReconciliationCase(row,{patientId:props.patientId,admissionId:props.admissionId,auditOnly:false})||value?.case_snapshot_id&&(row.content_hash!==value.content_hash||row.governance_hash!==value.governance_hash))throw new Error('所选完整账目、真实患者住院或当前治理已无法核对。');
   if(!current(t)||version!==sequence)return;selected.value=JSON.parse(canonical(row));emit('selection',{charge_case_id:row.case_snapshot_id});emit('availability',true);
  }catch(e){if(current(t)&&version===sequence)fail(e.message);}finally{if(current(t)&&version===sequence)checking.value=false;}}
 function unavailable(){const had=selected.value!==null||checking.value;initialConsumed=true;invalidate();if(had)error.value='当前账目原件或授权已变化，旧选择已清除。';}
 function sourceChanged(){initialConsumed=true;invalidate();error.value='账目或原件治理已变化，请重新核对并明确选择。';}
 async function refresh(){childKey.value++;invalidate();error.value='';if(!scopeReady.value)return;if(!empty(props.initialReferences)&&!chargeCaseReferencesValid(props.initialReferences)){fail('账目引用须只包含一个规范完整账目原件标识。');return;}emit('scope-change',JSON.parse(canonical(scope.value)));if(!initialConsumed&&!empty(props.initialReferences))await select(props.initialReferences);}
 watch(()=>JSON.stringify([props.patientId,props.admissionId,props.initialReferences]),()=>{initialConsumed=false;},{flush:'sync'});
 let started=false;watch(identity,()=>{if(started)initialConsumed=true;started=true;reset();refresh();},{immediate:true,flush:'sync'});
 // An explicit new business reference may be loaded once. Session/role/active
 // changes never replay a previously consumed private reference.
 watch(()=>JSON.stringify([props.patientId,props.admissionId,props.initialReferences]),()=>{initialConsumed=false;refresh();},{flush:'post'});
 onDeactivated(()=>{paused=true;initialConsumed=true;reset();});onActivated(()=>{if(paused){paused=false;reset();refresh();}});onBeforeUnmount(()=>{alive=false;reset(false);});
 return{allowed,scopeReady,selected,checking,error,childKey,select,refresh,clearSelection,sourceChanged,unavailable};
}
