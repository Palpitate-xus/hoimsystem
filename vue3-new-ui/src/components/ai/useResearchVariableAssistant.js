import {computed,onActivated,onBeforeUnmount,onDeactivated,ref,shallowRef,watch} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical as canonical,supportId as uuid} from '@/api/inpatientSupport';
import {researchVariableFixed as fixed,researchVariableBytes as bytes,researchVariableWhole as whole} from '@/api/ai/researchVariableProofs';
import {researchVariableSelectionValid,researchVariableTaskReceiptValid,createResearchVariableTask,cancelResearchVariableTask,feedbackResearchVariableTask} from '@/api/ai/researchVariableTasks';
import {readVerifiedResearchVariablePreview,readVerifiedResearchVariableTask,readResearchVariableHistory} from '@/api/ai/researchVariableTaskFlow';

const rolesAllowed=['super_admin','admin','director','doctor','pharmacist'];
const own=(value,key)=>Object.hasOwn(value,key),object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value),positive=value=>Number.isSafeInteger(value)&&value>0;
function validInitial(value){try{
 return object(value)&&whole(value,fixed.max_run_text_bytes)&&Object.keys(value).every(key=>[fixed.reference_key,'question'].includes(key))&&(!own(value,fixed.reference_key)||uuid(value[fixed.reference_key]))&&(!own(value,'question')||value.question===null||typeof value.question==='string'&&Array.from(value.question).length<=2000&&bytes(value.question)<=8000);
}catch{return false;}}
const fingerprint=value=>{try{return canonical(value);}catch{return 'invalid';}};

export function useResearchVariableAssistant(props,emit){
 const store=useStore(),batchId=ref(''),question=ref(''),questionPresent=ref(false),previewMode=ref(false),busy=ref(false),error=ref(''),notice=ref(''),preview=shallowRef(null),bundle=shallowRef(null),history=shallowRef([]),evidenceOpen=ref(false),closed=ref(false),live=ref(true),feedbackOutcome=ref('accepted'),feedbackComment=ref('');
 let version=0,timer=null,mutating=false,initialSeedAllowed=true,receipt=null,expectedSelection=null,expectedPreview=null;
 const token=computed(()=>store.state.user.accessToken),username=computed(()=>store.state.user.username),roles=computed(()=>store.getters['user/permissions']);
 const sessionKey=computed(()=>fingerprint([token.value,username.value,roles.value]));
 const sessionAllowed=computed(()=>typeof token.value==='string'&&token.value.trim().length>0&&typeof username.value==='string'&&username.value.trim().length>0&&Array.isArray(roles.value)&&roles.value.every(role=>typeof role==='string')&&roles.value.some(role=>rolesAllowed.includes(role)));
 const isSuper=computed(()=>sessionAllowed.value&&roles.value.includes('super_admin'));
 const initialValid=computed(()=>validInitial(props.initialInput));
 const modeReady=computed(()=>sessionAllowed.value&&props.featureKey===fixed.feature_key&&props.feature?.key===fixed.feature_key&&props.feature.input_mode===fixed.input_mode&&typeof props.feature.enabled==='boolean'&&typeof props.feature.provider_configured==='boolean'&&Array.isArray(props.feature.allowed_roles)&&props.feature.allowed_roles.every(role=>typeof role==='string')&&(isSuper.value||roles.value.some(role=>rolesAllowed.includes(role)&&props.feature.allowed_roles.includes(role))));
 const scopeValid=computed(()=>props.patientId===null&&props.encounterRef===''&&initialValid.value);
 const available=computed(()=>sessionAllowed.value&&modeReady.value&&scopeValid.value&&props.active&&live.value&&!closed.value);
 const selection=computed(()=>({research_variable_batch_id:batchId.value,...(questionPresent.value?{question:question.value}:{})}));
 const selectionValid=computed(()=>researchVariableSelectionValid(selection.value));
 const queueAllowed=computed(()=>available.value&&selectionValid.value&&preview.value!==null&&props.feature.provider_configured&&(props.feature.enabled||isSuper.value&&previewMode.value)&&(!previewMode.value||isSuper.value));
 const polling=computed(()=>bundle.value!==null&&(['queued','running'].includes(bundle.value.run.status)||bundle.value.run.status==='cancelled'&&bundle.value.run.usage_receipt_status==='pending'));

 function stopPolling(){if(timer!==null){clearTimeout(timer);timer=null;}}
 function clear({wipeInputs=false,notify=false}={}){
  version++;stopPolling();busy.value=false;error.value='';notice.value='';preview.value=null;bundle.value=null;history.value=[];evidenceOpen.value=false;feedbackComment.value='';receipt=null;expectedSelection=null;expectedPreview=null;
  if(wipeInputs){mutating=true;batchId.value='';question.value='';questionPresent.value=false;previewMode.value=false;mutating=false;}
  if(notify)emit('cleared');
 }
 function seedInitial(){
  if(!scopeValid.value||!available.value)return;mutating=true;batchId.value=props.initialInput.research_variable_batch_id??'';question.value=own(props.initialInput,'question')?props.initialInput.question:'';questionPresent.value=own(props.initialInput,'question');mutating=false;
 }
 const configKey=computed(()=>fingerprint(props.feature)),initialKey=computed(()=>fingerprint(props.initialInput));
 watch(()=>[sessionKey.value,props.active,props.featureKey,configKey.value,props.patientId,props.encounterRef,initialKey.value],(next,previous)=>{
  const changed=previous!==undefined,authChanged=changed&&next[0]!==previous[0],initialChanged=changed&&next[6]!==previous[6];
  const firstConfiguration=initialSeedAllowed&&modeReady.value&&!authChanged;
  clear({wipeInputs:true,notify:changed});
  if(authChanged||!props.active||props.patientId!==null||props.encounterRef!=='')initialSeedAllowed=false;
  if(firstConfiguration&&initialSeedAllowed||initialChanged&&!authChanged&&available.value){closed.value=false;seedInitial();}
  if(modeReady.value)initialSeedAllowed=false;
 },{immediate:true,flush:'sync'});
 watch(question,()=>{if(!mutating){questionPresent.value=true;clear({notify:true});}},{flush:'sync'});
 watch(()=>[batchId.value,previewMode.value],()=>{if(!mutating)clear({notify:true});},{flush:'sync'});
 const currentFor=ticket=>()=>ticket===version&&available.value;
 function fail(message){clear({wipeInputs:true,notify:true});error.value=message;}

 async function inspect(){
  if(!available.value||!selectionValid.value||busy.value)return;clear();const ticket=version,current=currentFor(ticket),input=structuredClone(selection.value);busy.value=true;
  try{const value=await readVerifiedResearchVariablePreview(input,{current});if(!current())return;if(value!==null&&!roles.value.includes(value.preview.research_variable_binding.request_authorization.actor_role))throw new Error('role');preview.value=value;}
  catch{if(current())fail('当前批次、完整原件或逐患者用途无法核对，请重新选择；未显示部分原件。');}
  finally{if(current())busy.value=false;}
 }
 function schedule(identifier){
  stopPolling();if(!polling.value||!available.value)return;const ticket=version;
  timer=setTimeout(()=>{timer=null;if(currentFor(ticket)())loadTask(identifier,{ticket});},2000);
 }
 async function loadTask(identifier,{ticket=version}={}){
  const current=currentFor(ticket);if(!current())return;bundle.value=null;busy.value=true;
  try{
   const value=await readVerifiedResearchVariableTask(identifier,{batchId:batchId.value,receipt,selection:expectedSelection,preview:expectedPreview,current});
   if(!current())return;if(value!==null&&!roles.value.includes(value.run.research_variable_artifact.actor_role))throw new Error('role');bundle.value=value;if(value!==null){receipt=structuredClone(value.run);schedule(identifier);}
  }catch{if(current())fail('完整任务与原批次、问题或实际回执无法核对，请明确重新读取；未回退为通用结果。');}
  finally{if(current())busy.value=false;}
 }
 async function submit(){
  if(!queueAllowed.value||busy.value)return;stopPolling();version++;bundle.value=null;history.value=[];error.value='';notice.value='';evidenceOpen.value=false;
  const ticket=version,current=currentFor(ticket),input=structuredClone(selection.value),mode=previewMode.value,reference=structuredClone(preview.value.bindingReference);busy.value=true;
  try{
   const reply=await createResearchVariableTask(input,{preview:mode});if(!current())return;
   if(!researchVariableTaskReceiptValid(reply,{batchId:input.research_variable_batch_id,preview:mode,bindingReference:reference}))throw new Error('receipt');
   receipt=reply;expectedSelection=input;expectedPreview=mode;await loadTask(reply.run_id,{ticket});
  }catch{if(current())fail('入队回执未闭合或请求失败；未自动重试提交，请明确核对历史。');}
  finally{if(current())busy.value=false;}
 }
 async function loadHistory(){
  if(!available.value||!selectionValid.value||busy.value)return;stopPolling();version++;bundle.value=null;evidenceOpen.value=false;history.value=[];error.value='';notice.value='';receipt=null;expectedSelection=null;expectedPreview=null;
  const ticket=version,current=currentFor(ticket);busy.value=true;
  try{const rows=await readResearchVariableHistory(batchId.value,{current});if(!current())return;if(rows?.some(row=>!roles.value.includes(row.research_variable_artifact.actor_role)))throw new Error('role');history.value=rows??[];}
  catch{if(current())fail('当前批次历史无法核对，未显示其他范围或通用结果。');}
  finally{if(current())busy.value=false;}
 }
 async function openHistory(row){
  if(!available.value||busy.value||!history.value.includes(row)||row.research_variable_batch_id!==batchId.value)return;version++;stopPolling();error.value='';notice.value='';bundle.value=null;evidenceOpen.value=false;receipt=structuredClone(row);expectedSelection=null;expectedPreview=null;await loadTask(row.run_id);
 }
 async function refresh(){if(!available.value||busy.value||bundle.value===null)return;const id=bundle.value.run.run_id;version++;error.value='';notice.value='';stopPolling();await loadTask(id);}
 async function cancel(){
  if(!available.value||busy.value||bundle.value===null||!['queued','running'].includes(bundle.value.run.status))return;
  const identifier=bundle.value.run.run_id;version++;stopPolling();bundle.value=null;evidenceOpen.value=false;error.value='';notice.value='';const ticket=version,current=currentFor(ticket);busy.value=true;
  try{
   const ack=await cancelResearchVariableTask(identifier);if(!current())return;
   if(!object(ack)||fingerprint(Object.keys(ack).sort())!==fingerprint(['schema_version','run_id','status','cancel_event_id','usage_event_id','receipt_pending','automatic_clinical_write','automatic_export'].sort())||ack.schema_version!=='research_variable_cancel_ack_v1'||ack.run_id!==identifier||ack.status!=='cancelled'||!positive(ack.cancel_event_id)||typeof ack.receipt_pending!=='boolean'||ack.receipt_pending!==(ack.usage_event_id===null)||ack.usage_event_id!==null&&!positive(ack.usage_event_id)||ack.automatic_clinical_write!==false||ack.automatic_export!==false)throw new Error('cancel');
   notice.value=ack.receipt_pending?'已停止接收结果；在途调用的实际用量尚待原交付结算。':'取消已记录；未调用时保留明确零用量。';await loadTask(identifier,{ticket});
  }catch{if(current())fail('取消回执无法核对；未恢复旧原件，请明确重新读取当前任务。');}
  finally{if(current())busy.value=false;}
 }
 async function feedback(){
  if(!available.value||busy.value||bundle.value?.run.status!=='succeeded')return;const identifier=bundle.value.run.run_id,ticket=version,current=currentFor(ticket);busy.value=true;notice.value='';error.value='';
  try{const ack=await feedbackResearchVariableTask(identifier,{outcome:feedbackOutcome.value,comment:feedbackComment.value});if(!current())return;if(!object(ack)||!uuid(ack.feedback_id)||!positive(ack.audit_event_id)||ack.automatic_clinical_write!==false||ack.automatic_export!==false||Object.keys(ack).length!==4)throw new Error('feedback');notice.value='人工复核已记录；未生成已审核矩阵、导出或临床写入。';feedbackComment.value='';}
  catch{if(current())fail('复核回执无法核对；未自动重试或发布。');}
  finally{if(current())busy.value=false;}
 }
 function close(){initialSeedAllowed=false;closed.value=true;clear({wipeInputs:true,notify:true});}
 function reopen(){closed.value=false;clear({wipeInputs:true,notify:true});}
 function childCleared(){bundle.value=null;stopPolling();}
 function closeEvidence(done){evidenceOpen.value=false;done?.();}
 onDeactivated(()=>{initialSeedAllowed=false;live.value=false;close();});onActivated(()=>{live.value=true;});onBeforeUnmount(()=>{live.value=false;close();});
 return {batchId,question,previewMode,busy,error,notice,preview,bundle,history,evidenceOpen,closed,sessionAllowed,isSuper,modeReady,scopeValid,available,selectionValid,queueAllowed,polling,feedbackOutcome,feedbackComment,inspect,submit,loadHistory,openHistory,refresh,cancel,feedback,close,reopen,childCleared,closeEvidence};
}
