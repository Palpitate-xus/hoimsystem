import {computed,onActivated,onBeforeUnmount,onDeactivated,onMounted,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical} from '@/api/inpatientSupport';
import {verifyDrugLabelContext,verifyDrugLabelRun,verifyDrugLabelTrace,drugLabelTaskProofScope} from '@/api/ai/drugLabelResults';
export function useDrugLabelFindings(props,emit){
 const store=useStore(),kept=ref(true),closed=ref(false),proof=ref(null),busy=ref(false),error=ref(''),rawOpen=ref(false),privateOpen=ref(false),quote=ref(null),page=ref(1);
 const token=computed(()=>store.state.user?.accessToken||''),roles=computed(()=>JSON.stringify(store.state.user?.permissions||[])),username=computed(()=>store.state.user?.username||''),role=computed(()=>{const r=store.state.user?.permissions||[];return r.includes('super_admin')?'super_admin':r.includes('pharmacist')?'pharmacist':null;}),sessionAllowed=computed(()=>!!token.value&&!!role.value&&(!props.auditOnly||role.value==='super_admin')),authorized=computed(()=>sessionAllowed.value&&props.active&&kept.value&&!closed.value);
 const referenceKey=computed(()=>{try{return supportCanonical(props.references??null);}catch{return 'invalid';}}),boundary=computed(()=>JSON.stringify([token.value,roles.value,username.value,props.active,props.auditOnly,props.pharmaceuticalId,props.expectedRunId,referenceKey.value,props.configRevision]));
 let version=0,mounted=false,activated=false;
 const expected=()=>({references:props.references,pharmaceuticalId:props.pharmaceuticalId,runId:props.expectedRunId});
 function clear({close=false,invalidate=false}={}){version++;proof.value=null;busy.value=false;rawOpen.value=false;privateOpen.value=false;quote.value=null;page.value=1;if(close)closed.value=true;if(invalidate)emit('invalidate');}
 function close(){clear({close:true,invalidate:true});error.value='';}
 function reread(){if(!sessionAllowed.value||!props.active||!kept.value)return;clear();closed.value=false;error.value='';emit('reload');}
 async function verify(){clear();if(!mounted||!authorized.value||!props.run&&!props.preview)return;const t=version,b=boundary.value,current=()=>mounted&&authorized.value&&version===t&&boundary.value===b;busy.value=true;error.value='';try{
  const options={current,auditOnly:props.auditOnly,allowFrozenAudit:role.value==='super_admin'};
  if(props.run){if(!await verifyDrugLabelRun(props.run,expected(),options)||props.trace!==null&&(role.value!=='super_admin'||!await verifyDrugLabelTrace(props.trace,props.run,expected(),options)))throw new Error('完整任务、来源或冻结原字节无法核对');}
  else if(props.trace!==null||!await verifyDrugLabelContext(props.preview,expected(),options))throw new Error('完整预览来源无法核对');
  if(current())proof.value=JSON.parse(JSON.stringify({run:props.run,trace:props.trace,preview:props.preview}));
 }catch{if(current()){clear();error.value='完整任务、原件、逐字位置或当前范围无法核对；旧正文和草稿已清除。';emit('invalidate');}}finally{if(current())busy.value=false;}}
 const findings=computed(()=>proof.value?.run?.drug_label_findings||null),source=computed(()=>findings.value?.drug_label_source||proof.value?.preview?.context.drug_label_source||null),record=computed(()=>findings.value?.drug_label_source_record||proof.value?.preview?.drug_label_source_record||null),result=computed(()=>proof.value?.run?.result||null),receipt=computed(()=>proof.value?.run?.usage_receipt||null),rows=computed(()=>result.value?.drug_label_extraction.fields.flatMap((f,fieldIndex)=>f.spans.map((span,spanIndex)=>({...span,field:f.field,review_question:f.review_question,fieldIndex,spanIndex})))||[]),visibleRows=computed(()=>rows.value.slice((page.value-1)*10,page.value*10)),proofNote=computed(()=>proof.value?.trace?drugLabelTaskProofScope.trace:drugLabelTaskProofScope.ordinary);
 function inspect(row){if(!authorized.value||!proof.value||!source.value)return;quote.value={...row};emit('inspect',{field_index:row.fieldIndex,span_index:row.spanIndex,source_id:source.value.source_id,source_projection_hash:findings.value?.drug_label_binding.source_projection_hash||proof.value.preview.context.drug_label_binding.source_projection_hash,start:row.start,end:row.end,quote:row.quote});}
 function showOriginal(){if(authorized.value&&proof.value)rawOpen.value=!rawOpen.value;}
 function showPrivate(){if(authorized.value&&proof.value)privateOpen.value=!privateOpen.value;}
 watch([()=>props.run,()=>props.trace,()=>props.preview],()=>{if(mounted&&!closed.value)verify();else if(mounted)clear();},{deep:true,flush:'sync'});
 watch(boundary,()=>{if(!mounted)return;error.value='';clear({close:true,invalidate:true});},{flush:'sync'});
 onMounted(()=>{mounted=true;verify();});onActivated(()=>{kept.value=true;if(activated)clear({close:true,invalidate:true});activated=true;});onDeactivated(()=>{kept.value=false;clear({close:true,invalidate:true});});onBeforeUnmount(()=>{mounted=false;clear({close:true});});
 return {sessionAllowed,authorized,closed,proof,busy,error,source,record,result,receipt,rows,visibleRows,page,rawOpen,privateOpen,quote,proofNote,close,reread,verify,inspect,showOriginal,showPrivate};
}
