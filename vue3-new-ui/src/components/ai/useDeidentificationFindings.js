import{computed,onActivated,onBeforeUnmount,onDeactivated,ref,watch}from'vue';import{useStore}from'vuex';
import{deidentificationPolicy}from'@/api/ai/deidentificationSources';
import{deidentificationCanonical as canonical}from'@/api/ai/deidentificationCore';
import{verifyDeidentificationRun,verifyDeidentificationResultPart,verifyDeidentificationTrace,verifyDeidentificationTechnical}from'@/api/ai/deidentificationResults';
import{deidentificationWireValue}from'@/api/ai/deidentificationWire';
const clone=v=>JSON.parse(JSON.stringify(v));
export function useDeidentificationFindings(props,emit){const store=useStore(),kept=ref(true),busy=ref(false),proof=ref(null),safe=ref(null),error=ref(''),originalOpen=ref(false),privateOpen=ref(false),quote=ref(null),page=ref(1);let epoch=0,alive=true;
 const token=computed(()=>store.state.user?.accessToken||''),roles=computed(()=>store.state.user?.permissions),username=computed(()=>store.state.user?.username||''),allowed=computed(()=>alive&&props.active&&kept.value&&!!token.value&&Array.isArray(roles.value)&&roles.value.every(x=>typeof x==='string')&&roles.value.some(x=>deidentificationPolicy.source_roles.includes(x))),isSuper=computed(()=>Array.isArray(roles.value)&&roles.value.includes('super_admin'));
 const boundary=()=>canonical([props.scope,props.patientId,props.references,props.expectedRunId,props.auditOnly,props.configRevision,props.active,token.value,roles.value,username.value]),current=t=>allowed.value&&t.epoch===epoch&&t.boundary===boundary();
 function clear(notify=true){epoch++;busy.value=false;proof.value=null;safe.value=null;originalOpen.value=false;privateOpen.value=false;quote.value=null;page.value=1;if(notify)emit('invalidate');}
 const expected=()=>({...(props.scope===null?{}:{scope:props.scope}),...(props.patientId===null?{}:{patientId:props.patientId}),...(props.references===null?{}:{references:props.references}),...(props.expectedRunId===null?{}:{runId:props.expectedRunId})});
 async function inspect(){clear(false);error.value='';if(!allowed.value||props.auditOnly&&!isSuper.value)return;const t={epoch:++epoch,boundary:boundary()};busy.value=true;try{
  const options={current:()=>current(t),auditOnly:props.auditOnly};if(!await verifyDeidentificationRun(props.run,props.sourcePart,props.technical,expected(),options))throw new Error('完整来源与任务不一致');
  if(props.resultPart!==null&&!await verifyDeidentificationResultPart(props.resultPart,props.run,props.sourcePart,props.technical,expected(),options))throw new Error('拆分结果不一致');
  if(props.trace!==null&&(!isSuper.value||!await verifyDeidentificationTrace(props.trace,props.run,props.sourcePart,props.technical,expected(),{...options,allowAudit:true})))throw new Error('原始任务审计不一致');
  if(!current(t))return;proof.value=clone({run:deidentificationWireValue(props.run).data,body:deidentificationWireValue(props.sourcePart).data.source_artifact,traceVerified:props.trace!==null});
 }catch{if(current(t)){clear(false);error.value='当前完整来源、任务或逐字候选无法核对；旧全文和候选已清除。';emit('invalidate');}}finally{if(current(t))busy.value=false;}}
 function inspectTechnical(){clear(false);error.value='';if(!allowed.value||!verifyDeidentificationTechnical(props.technical,props.expectedRunId===null?{}:{runId:props.expectedRunId})){error.value='技术状态或用量回执无法核对。';return;}safe.value=clone(deidentificationWireValue(props.technical).data);}
 const run=computed(()=>proof.value?.run||null),source=computed(()=>proof.value?.body.public_source||null),result=computed(()=>run.value?.result||null),candidates=computed(()=>result.value?.draft.candidates||[]),visibleCandidates=computed(()=>candidates.value.slice((page.value-1)*10,page.value*10).map((x,i)=>({...x,ordinal:(page.value-1)*10+i}))),usage=computed(()=>run.value?.usage_receipt||safe.value?.usage_receipt||null);
 function inspectQuote(row){if(!allowed.value||!proof.value)return;const actual=candidates.value[row.ordinal];if(actual){quote.value=clone(actual);emit('inspect',{document_source_id:actual.document_source_id,start:actual.start,end:actual.end});}}
 watch([()=>props.scope,()=>props.patientId,()=>props.references,()=>props.expectedRunId,()=>props.auditOnly,()=>props.configRevision,()=>props.active,()=>props.run,()=>props.sourcePart,()=>props.resultPart,()=>props.technical,()=>props.trace,token,roles,username,kept],()=>{clear(false);error.value='';},{deep:true,flush:'sync'});
 onDeactivated(()=>{kept.value=false;});onActivated(()=>{kept.value=true;});onBeforeUnmount(()=>{alive=false;clear(false);});
 return{allowed,isSuper,busy,proof,safe,error,run,source,result,candidates,visibleCandidates,usage,originalOpen,privateOpen,quote,page,inspect,inspectTechnical,inspectQuote,close:()=>{clear();error.value='';}};
}
