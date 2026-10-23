import {computed,onActivated,onBeforeUnmount,onDeactivated,ref,shallowRef,watch} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical} from '@/api/inpatientSupport';
import {parseResearchVariableJson,researchVariableWhole} from '@/api/ai/researchVariableProofs';
import {verifyResearchVariableRun} from '@/api/ai/researchVariableTasks';

const allowed=['super_admin','admin','director','doctor','pharmacist'];
const snapshot=value=>{researchVariableWhole(value);return parseResearchVariableJson(supportCanonical(value));};
export function useResearchVariableFindings(props,emit){
 const store=useStore(),proof=shallowRef(null),busy=ref(false),error=ref(''),closed=ref(false),live=ref(true),originalOpen=ref(false),selectedOriginal=ref(null),recordPage=ref(1);
 let version=0,blockedRun=null;
 const roles=computed(()=>store.getters['user/permissions']),token=computed(()=>store.state.user.accessToken),username=computed(()=>store.state.user.username);
 const sessionAllowed=computed(()=>Array.isArray(roles.value)&&roles.value.every(role=>typeof role==='string')&&roles.value.some(role=>allowed.includes(role))&&typeof token.value==='string'&&token.value.trim().length>0&&typeof username.value==='string'&&username.value.trim().length>0&&(!props.auditOnly||roles.value.includes('super_admin'))&&(props.trace===null||roles.value.includes('super_admin')));
 const authorized=computed(()=>sessionAllowed.value&&props.active&&live.value&&!closed.value),sessionKey=computed(()=>JSON.stringify([token.value,username.value,roles.value]));
 function clear({block=false,notify=false}={}){version++;proof.value=null;busy.value=false;error.value='';originalOpen.value=false;selectedOriginal.value=null;recordPage.value=1;if(block){blockedRun=props.run;closed.value=true;}if(notify)emit('cleared');}
 async function verify(){
  clear();if(!authorized.value||props.run===null||props.parts===null||props.run===blockedRun)return;if(props.auditOnly&&props.trace===null){error.value='明确冻结审计须同时核对原始Trace，未展示部分原件。';return;}
  const ticket=version,current=()=>version===ticket&&authorized.value&&props.run!==blockedRun;busy.value=true;
  try{
   const run=snapshot(props.run),parts=Object.fromEntries(Object.entries(props.parts).map(([name,value])=>[name,snapshot(value)])),trace=props.trace===null?null:snapshot(props.trace);
   const checked=await verifyResearchVariableRun(run,parts,{runId:props.expectedRunId||run.run_id,batchId:props.expectedBatchId,auditOnly:props.auditOnly,trace,current});
   if(!current())return;if(!checked){error.value='完整科研变量来源、原字面值、任务锚或回执无法核对，未显示部分结果。';return;}
   proof.value={run,parts,trace,checked};
  }catch{if(current())error.value='完整科研变量分件无效或超出预算，未截断显示。';}
  finally{if(current())busy.value=false;}
 }
 watch(()=>[sessionKey.value,props.active,props.auditOnly,props.run,props.parts,props.trace,props.expectedRunId,props.expectedBatchId],(next,previous)=>{
  const changed=previous&&(next[0]!==previous[0]||next[1]!==previous[1]||next[2]!==previous[2]);
  if(changed){clear({block:true,notify:true});return;}
  if(props.run!==blockedRun)closed.value=false;verify();
 },{deep:true,flush:'sync',immediate:true});
 function close(){clear({block:true,notify:true});emit('close-requested');}
 function requestReload(){emit('reload-requested');}
 onDeactivated(()=>{live.value=false;clear({block:true,notify:true});});onActivated(()=>{live.value=true;});onBeforeUnmount(()=>clear({block:true,notify:true}));
 const source=computed(()=>proof.value?.parts.source.source||null),candidates=computed(()=>proof.value?.parts.result?.result.research_variable_extraction.literal_draft.candidates||[]),records=computed(()=>proof.value?.parts.scope.private_scope.snapshot.capture.records||[]);
 const visibleRecords=computed(()=>records.value.slice((recordPage.value-1)*20,recordPage.value*20));
 const original=computed(()=>selectedOriginal.value===null?null:records.value[selectedOriginal.value]||null);
 function selectOriginal(index){if(!proof.value||!authorized.value)return;selectedOriginal.value=index;}
 function variable(key){return source.value?.variables.find(row=>row.variable_key===key)||null;}
 return {proof,busy,error,closed,sessionAllowed,authorized,close,requestReload,source,candidates,records,visibleRecords,original,originalOpen,recordPage,selectOriginal,variable};
}
