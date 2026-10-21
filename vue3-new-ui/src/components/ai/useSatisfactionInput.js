import {computed,onActivated,onBeforeUnmount,onDeactivated,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical as canonical,supportDigest as digest} from '@/api/inpatientSupport';
import {getSatisfactionCase,satisfactionPolicy,satisfactionReferencesValid,verifySatisfactionCase} from '@/api/ai/satisfactionSources';

export function useSatisfactionInput(props,emit){
 const store=useStore(),roles=computed(()=>store.getters['user/permissions']||[]);
 const allowed=computed(()=>props.active&&!!store.state.user.accessToken&&roles.value.some(r=>['admin','director','super_admin'].includes(r)));
 const initialMalformed=computed(()=>props.initialReferences!==null&&!satisfactionReferencesValid(props.initialReferences));
 const selected=ref(null),scope=ref(null),checking=ref(false),error=ref(''),childKey=ref(0);
 let epoch=0,selectionVersion=0,scopeVersion=0,alive=true,paused=false,initialAllowed=true,initialized=false;
 const identity=()=>canonical([props.active,props.initialReferences,store.state.user.accessToken,store.state.user.username,roles.value]);
 const ticket=()=>({epoch,identity:identity()}),current=t=>alive&&!paused&&allowed.value&&!initialMalformed.value&&t.epoch===epoch&&t.identity===identity();
 function invalidate(notify=true){selectionVersion++;selected.value=null;checking.value=false;emit('selection',null);emit('availability',false);if(notify)emit('invalidate');}
 function reset(notify=true){epoch++;scopeVersion++;scope.value=null;childKey.value++;error.value='';invalidate(notify);emit('scope-change',null);}
 function fail(message){invalidate();error.value=message||'当前完整来源或权限无法核对，旧引用已清除。';}
 async function selectCase(value,{initial=false,notify=true}={}){invalidate(notify);const t=ticket(),version=selectionVersion,s=scopeVersion;if(!current(t))return;if(!initial)initialAllowed=false;checking.value=true;error.value='';try{if(!satisfactionReferencesValid(value))throw new Error('评价输入必须仅含一个规范受审来源引用');const row=(await getSatisfactionCase(value.satisfaction_case_id,{auditOnly:false})).data;if(!current(t)||version!==selectionVersion||s!==scopeVersion)return;if(row.case_id!==value.satisfaction_case_id||!row.eligible||row.audit_only||!row.public_source||!await verifySatisfactionCase(row,{auditOnly:false})||row.safe_snapshot.policy_hash!==await digest(satisfactionPolicy))throw new Error('当前完整安全来源、发布投影或政策版本已无法核对');if(!current(t)||version!==selectionVersion||s!==scopeVersion)return;
 if(scope.value&&scope.value.doctor_ids!==null&&(row.scope_kind!==scope.value.scope_kind||row.date_from!==scope.value.date_from||row.date_to!==scope.value.date_to||row.safe_snapshot.doctor_cohort_size!==(scope.value.scope_kind==='hospital_reviews'?null:scope.value.doctor_ids.length)))throw new Error('所选原件与本次明确范围或日期不一致');
 if(initial){scope.value={scope_kind:row.scope_kind,doctor_ids:null,doctor_cohort_size:row.safe_snapshot.doctor_cohort_size,date_from:row.date_from,date_to:row.date_to};emit('scope-change',{...scope.value});}
 selected.value=row;emit('selection',{satisfaction_case_id:row.case_id});emit('availability',true);
 }catch(e){if(current(t)&&version===selectionVersion)fail(e.message);}finally{if(current(t)&&version===selectionVersion)checking.value=false;}}
 function scopeChanged(value){initialAllowed=false;scopeVersion++;scope.value=value;invalidate();emit('scope-change',value);}
 function sourceChanged(){initialAllowed=false;invalidate();error.value='原评价、任一摘录版本或治理已变化，请重新核对当前完整来源。';}
 function sourceUnavailable(){initialAllowed=false;invalidate();error.value='当前来源能力或安全原件不可用，旧选择已清除。';}
 function clearSelection(){initialAllowed=false;invalidate();}
 async function refresh(notify=true){invalidate(notify);if(!allowed.value||initialMalformed.value)return;if(initialAllowed&&props.initialReferences!==null)await selectCase(props.initialReferences,{initial:true,notify:false});}
 watch(()=>canonical(props.initialReferences),()=>{initialAllowed=true;},{flush:'sync'});
 watch(identity,()=>{reset(initialized);initialized=true;if(initialMalformed.value){error.value='引用须仅包含一个规范 satisfaction_case_id，不能混入患者、住院或其他来源。';return;}refresh();},{immediate:true,flush:'sync'});
 onDeactivated(()=>{paused=true;reset();});onActivated(()=>{if(paused){paused=false;reset();refresh();}});onBeforeUnmount(()=>{alive=false;reset(false);});
 return{allowed,initialMalformed,selected,scope,checking,error,childKey,selectCase,scopeChanged,sourceChanged,sourceUnavailable,clearSelection,refresh};
}
