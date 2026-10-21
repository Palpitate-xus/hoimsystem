import{computed,onActivated,onBeforeUnmount,onDeactivated,ref,watch}from'vue';
import{useStore}from'vuex';
import{supportCanonical as canonical}from'@/api/inpatientSupport';
import * as api from '@/api/ai/chargeReconciliationSources';
const clone=v=>JSON.parse(canonical(v));
export function useChargeReconciliationSources(props,emit){
 const store=useStore(),roles=computed(()=>store.getters['user/permissions']||[]),allowed=computed(()=>props.active&&!!store.state.user.accessToken&&roles.value.some(r=>['admin','super_admin','cashier','director'].includes(r))&&(!props.auditOnly||roles.value.includes('super_admin')));
 const scope=computed(()=>({patient_id:props.patientId,admission_id:props.admissionId})),scopeReady=computed(()=>api.chargeScopeValid(scope.value));
 const options=ref(null),directory=ref(null),detail=ref(null),preview=ref(null),loading=ref(false),inspecting=ref(false),creating=ref(false),previewing=ref(false),saving=ref(false),governing=ref(false),error=ref(''),notice=ref(''),note=ref(''),basis=ref(''),page=ref(1),showRaw=ref(false),group=ref('charges'),memberPage=ref(0);
 let epoch=0,loadVersion=0,inspectVersion=0,createVersion=0,governVersion=0,alive=true,paused=false,initialized=false;
 const identity=()=>JSON.stringify([props.patientId,props.admissionId,props.auditOnly,props.active,store.state.user.accessToken,store.state.user.username,roles.value]);
 const ticket=()=>({epoch,identity:identity()}),current=t=>alive&&!paused&&allowed.value&&t.epoch===epoch&&t.identity===identity();
 function closeCreate(){createVersion++;creating.value=false;previewing.value=false;saving.value=false;preview.value=null;note.value='';}
 function clearDetail(notify=false){inspectVersion++;detail.value=null;inspecting.value=false;basis.value='';showRaw.value=false;group.value='charges';memberPage.value=0;if(notify)emit('invalidate');}
 function clear(notify=true){epoch++;loadVersion++;governVersion++;options.value=null;directory.value=null;loading.value=false;governing.value=false;error.value='';notice.value='';clearDetail();closeCreate();if(notify)emit('invalidate');}
 function fail(message){clear();error.value=message||'当前账目原件或完整授权已无法核对，旧正文已清除。';}
 async function load(){clearDetail();closeCreate();directory.value=null;options.value=null;const t=ticket(),version=++loadVersion;if(!current(t)||!scopeReady.value&&!props.auditOnly)return;loading.value=true;error.value='';
  try{const params=scopeReady.value?scope.value:{},value=(await api.getChargeReconciliationOptions(params)).data;if(!current(t)||version!==loadVersion)return;if(!api.chargeSourceOptionsValid(value,params))throw new Error('账目来源的实际范围或能力回执不一致。');options.value=value;
   const query={...params,audit_only:props.auditOnly,page:page.value,page_size:20},rows=(await api.getChargeReconciliationCases(query)).data;if(!current(t)||version!==loadVersion)return;if(!api.chargeSourceDirectoryValid(rows,query))throw new Error('账目元数据目录范围或完整分页无法核对。');directory.value=rows;
  }catch(e){if(current(t)&&version===loadVersion)fail(e.message);}finally{if(current(t)&&version===loadVersion)loading.value=false;}}
 async function inspect(row){clearDetail(true);const t=ticket(),version=inspectVersion;inspecting.value=true;error.value='';notice.value='';
  try{const value=(await api.getChargeReconciliationCase(row.case_snapshot_id,{auditOnly:props.auditOnly})).data;if(!current(t)||version!==inspectVersion)return;
   if(!await api.verifyChargeReconciliationCase(value,{patientId:props.patientId,admissionId:props.admissionId,auditOnly:props.auditOnly})||value.case_snapshot_id!==row.case_snapshot_id||value.content_hash!==row.content_hash||value.collection_digest!==row.collection_digest||value.status!==row.status||value.revision!==row.revision)throw new Error('原件完整证明、治理或实际住院与所选目录不一致。');
   if(!current(t)||version!==inspectVersion)return;detail.value=clone(value);
  }catch(e){if(current(t)&&version===inspectVersion)fail(e.message);}finally{if(current(t)&&version===inspectVersion)inspecting.value=false;}}
 async function selectDetail(){const before=detail.value;if(!before||props.auditOnly||!before.eligible||!scopeReady.value)return;const t=ticket(),version=++inspectVersion;inspecting.value=true;
  try{const value=(await api.getChargeReconciliationCase(before.case_snapshot_id)).data;if(!current(t)||version!==inspectVersion)return;if(!await api.verifyChargeReconciliationCase(value,{patientId:props.patientId,admissionId:props.admissionId})||!value.eligible||value.case_snapshot_id!==before.case_snapshot_id||value.content_hash!==before.content_hash||value.governance_hash!==before.governance_hash)throw new Error('选择前原件或治理已改变，请重新核对。');if(!current(t)||version!==inspectVersion)return;detail.value=clone(value);emit('select',clone(value));
  }catch(e){if(current(t)&&version===inspectVersion)fail(e.message);}finally{if(current(t)&&version===inspectVersion)inspecting.value=false;}}
 function openCreate(){if(!scopeReady.value||!options.value?.can_record)return;closeCreate();emit('invalidate');creating.value=true;error.value='';notice.value='';}
 async function capture(){if(!creating.value||!scopeReady.value)return;const body=clone(scope.value),expected=canonical(body),t=ticket(),version=++createVersion;preview.value=null;previewing.value=true;error.value='';
  try{const value=(await api.previewChargeReconciliationCase(body)).data;if(!current(t)||version!==createVersion||!creating.value||canonical(scope.value)!==expected)return;if(!await api.verifyChargeReconciliationCapture(value,body))throw new Error('完整账目捕获的逐件SHA、成员关系或范围不一致。');if(!current(t)||version!==createVersion||!creating.value||canonical(scope.value)!==expected)return;preview.value=clone(value);
  }catch(e){if(current(t)&&version===createVersion&&creating.value)fail(e.message);}finally{if(current(t)&&version===createVersion&&creating.value)previewing.value=false;}}
 const createBody=computed(()=>preview.value?{request:scope.value,expected_collection_digest:preview.value.collection_digest,note:note.value}:null);
 const createValid=computed(()=>creating.value&&scopeReady.value&&!!createBody.value&&canonical(preview.value.request)===canonical(scope.value)&&api.chargeSourceRequestValid('CaseCreate',createBody.value));
 async function save(){if(!createValid.value||saving.value)return;const body=clone(createBody.value),expected=canonical(body),t=ticket(),version=++createVersion;saving.value=true;
  try{const value=(await api.createChargeReconciliationCase(body)).data;if(!current(t)||version!==createVersion||!creating.value||canonical(createBody.value)!==expected)return;
   if(!await api.verifyChargeReconciliationCase(value,{patientId:props.patientId,admissionId:props.admissionId})||value.status!=='draft'||value.collection_digest!==body.expected_collection_digest||value.snapshot.note!==body.note||canonical(value.snapshot.collection.request)!==canonical(body.request))throw new Error('登记回执未绑定本次完整捕获、说明或原件SHA。');
   if(!current(t)||version!==createVersion||!creating.value||canonical(createBody.value)!==expected)return;closeCreate();emit('source-changed');await load();if(current(t))notice.value='完整账目已登记为草稿，发布需要单独审核。';
  }catch(e){if(current(t)&&version===createVersion&&creating.value)fail(e.message);}finally{if(current(t)&&version===createVersion)saving.value=false;}}
 async function govern(action){const before=detail.value;if(!before||governing.value||!['publish','reject','revoke'].includes(action))return;if(action==='revoke'?!before.can_revoke||!api.chargeSourceRevokeBasis(basis.value):!before.can_review||!api.chargeSourceBasis(basis.value))return;
  const body={expected_revision:before.revision,expected_content_hash:before.content_hash,expected_governance_hash:before.governance_hash,...(action==='revoke'?{}:{decision:action}),basis_note:basis.value},t=ticket(),version=++governVersion;governing.value=true;error.value='';emit('invalidate');
  try{const fn=action==='revoke'?api.revokeChargeReconciliationCase:api.reviewChargeReconciliationCase,value=(await fn(before.case_snapshot_id,body)).data;if(!current(t)||version!==governVersion)return;
   const metadataOnly=action==='revoke'&&before.snapshot===null,valid=metadataOnly?await api.verifyChargeReconciliationMetadataRevoke(value,before,body):await api.verifyChargeReconciliationTransition(value,before,action,body);
   if(!valid)throw new Error('治理回执与本次CAS、原件或明确依据不一致。');if(!current(t)||version!==governVersion)return;emit('source-changed');await load();if(current(t))notice.value=metadataOnly?'撤销状态已更新；隐藏的治理正文保持不可读，未作完整哈希重建。':'本次原件治理已完成。';
  }catch(e){if(current(t)&&version===governVersion)fail(e.message);}finally{if(current(t)&&version===governVersion)governing.value=false;}}
 function reload(){emit('invalidate');load();}
 function changePage(delta){page.value+=delta;emit('invalidate');load();}
 watch(identity,()=>{clear(initialized);initialized=true;page.value=1;load();},{immediate:true,flush:'sync'});
 onDeactivated(()=>{paused=true;clear();});onActivated(()=>{if(paused){paused=false;clear(false);load();}});onBeforeUnmount(()=>{alive=false;clear(false);});
 return{allowed,scope,scopeReady,options,directory,detail,preview,loading,inspecting,creating,previewing,saving,governing,error,notice,note,basis,page,showRaw,group,memberPage,createValid,closeCreate,clearDetail,load,reload,inspect,selectDetail,openCreate,capture,save,govern,changePage,api};
}
