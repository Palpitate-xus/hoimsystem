import {computed,onActivated,onBeforeUnmount,onDeactivated,onMounted,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {supportId} from '@/api/inpatientSupport';
import {getDocumentOriginal} from '@/api/ai/documentEvidence';
import {getDocumentExtractionTrace,saveDocumentDraftCandidate,verifyDocumentDraftCandidate,verifyDocumentExtractionContext,verifyDocumentExtractionRun} from '@/api/ai/documentExtractionResults';
const clone=v=>JSON.parse(JSON.stringify(v));
export function useDocumentExtractionFindings(props,emit){
 const store=useStore(),keptActive=ref(true),closed=ref(false),proof=ref(null),busy=ref(false),error=ref(''),rawOpen=ref(false),saved=ref({});
 const token=computed(()=>store.state.user?.accessToken),roles=computed(()=>JSON.stringify(store.state.user?.permissions)),username=computed(()=>store.state.user?.username||'');
 const sessionAllowed=computed(()=>props.active===true&&keptActive.value&&typeof token.value==='string'&&token.value.length>0&&Array.isArray(store.state.user?.permissions)&&store.state.user.permissions.includes('super_admin'));
 const authorized=computed(()=>sessionAllowed.value&&!closed.value);
 const runId=computed(()=>props.expectedRunId||props.run?.run_id||null),canSave=computed(()=>authorized.value&&!props.auditOnly&&proof.value?.run.status==='succeeded'&&proof.value.run.document_original.eligible);
 let mounted=false,epoch=0;
 const ticket=()=>({epoch:++epoch,token:token.value,roles:roles.value,username:username.value,runId:runId.value,auditOnly:props.auditOnly});
 const current=t=>mounted&&authorized.value&&t.epoch===epoch&&t.token===token.value&&t.roles===roles.value&&t.username===username.value&&t.runId===runId.value&&t.auditOnly===props.auditOnly;
 function clear(){epoch++;proof.value=null;saved.value={};rawOpen.value=false;busy.value=false;error.value='';}
 function close(){closed.value=true;clear();emit('cleared');}
 function fail(cause,t){if(!current(t))return;clear();const code=cause?.response?.status;error.value=code===401||code===403?'当前登录或超级管理员权限已失效，原文与草稿已清除。':code===409?'原任务、原件或该条保存状态已改变；未自动重试，请重新核对。':'完整原文、冻结Prompt、SQL摘要或逐字草稿无法核对，未展示结果。';}
 async function load(forceFresh=false){if(!authorized.value||!supportId(runId.value))return;clear();const t=ticket();busy.value=true;try{const run=clone(props.run);if(run?.run_id!==t.runId||props.expectedOriginalId&&run.document_original_id!==props.expectedOriginalId)throw new Error('请求任务或原件范围不一致');const trace=!forceFresh&&props.trace?clone(props.trace):(await getDocumentExtractionTrace(t.runId)).data;if(!current(t))return;if(!await verifyDocumentExtractionRun(run,trace,{runId:t.runId,originalId:props.expectedOriginalId||null,auditOnly:props.auditOnly,current:()=>current(t)}))throw new Error('完整冻结证据核对失败');if(current(t))proof.value={run,trace};}catch(cause){fail(cause,t);}finally{if(current(t))busy.value=false;}}
 async function save(ordinal){if(!canSave.value||busy.value||Object.hasOwn(saved.value,ordinal))return;const checked=proof.value,t=ticket();busy.value=true;error.value='';try{
  const original=(await getDocumentOriginal(checked.run.document_original_id)).data;if(!current(t))return;
  if(!await verifyDocumentExtractionContext(checked.run.document_extraction_findings,original,{auditOnly:false,current:()=>current(t)}))throw new Error('原件已失效');
  const candidate=(await saveDocumentDraftCandidate(t.runId,ordinal)).data;if(!current(t))return;
  if(!await verifyDocumentDraftCandidate(candidate,checked.run,ordinal,original,{current:()=>current(t)}))throw new Error('保存回执不一致');
  if(!current(t))return;saved.value={...saved.value,[ordinal]:candidate};emit('candidate-saved',clone(candidate));
 }catch(cause){fail(cause,t);}finally{if(current(t))busy.value=false;}}
 function reopen(){if(!sessionAllowed.value)return;closed.value=false;load(true);}
 watch([token,roles,username,()=>props.active,keptActive],()=>{closed.value=true;clear();},{flush:'sync'});
 watch([()=>props.run,()=>props.trace,()=>props.expectedRunId,()=>props.expectedOriginalId,()=>props.auditOnly],()=>{closed.value=false;clear();if(mounted&&authorized.value)load();},{deep:true,flush:'sync'});
 onMounted(()=>{mounted=true;load();});onActivated(()=>{keptActive.value=true;});onDeactivated(()=>{keptActive.value=false;});onBeforeUnmount(()=>{mounted=false;clear();});
 return {authorized,sessionAllowed,closed,reopen,proof,busy,error,rawOpen,saved,canSave,close,save,load};
}
