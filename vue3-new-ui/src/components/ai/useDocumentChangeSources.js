import {computed,onActivated,onBeforeUnmount,onDeactivated,ref,reactive,watch} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical as canonical,supportDigest as digest,supportId} from '@/api/inpatientSupport';
import {documentBasis,documentCodepointSlice,documentUtf8,getDocumentOriginal} from '@/api/ai/documentEvidence';
import * as api from '@/api/ai/documentChanges';
const key=t=>t.kind+':'+String(t.target_id),cas=v=>({expected_revision:v.governance.revision,expected_content_hash:v.content_hash,expected_governance_hash:v.governance_hash});
const initial=()=>({relationship:'',family:'unknown',relationshipBasis:'',coverage:'unknown',declarationBasis:'',targetKind:'',targetId:'',side:'',start:'',end:'',dependency:'',linkBasis:''});
const reviewInitial=()=>({decision:'',privacy_review:'',faithfulness_review:'',dependency_review:'',basis_note:'',revokeBasis:''});
export function useDocumentChangeSources(props){
 const store=useStore(),roles=computed(()=>store.getters['user/permissions']),allowed=computed(()=>props.active&&typeof store.state.user.accessToken==='string'&&store.state.user.accessToken.length>0&&Array.isArray(roles.value)&&roles.value.includes('super_admin'));
 const auth=()=>canonical([props.active,store.state.user.accessToken,store.state.user.username,roles.value]);
 const form=reactive(initial()),review=reactive(reviewInitial()),baseline=ref(null),candidate=ref(null),declared=ref([]),target=ref(null),capture=ref(null),detail=ref(null),rawOpen=ref(false),error=ref(''),notice=ref(''),busy=ref(false),listsBusy=ref(false),optionsReady=ref(false),directories=reactive({links:null,scopes:null});
 let alive=true,deactivated=false,activated=false,epoch=0,workVersion=0,detailVersion=0,operation=0,listVersion=0;
 const available=()=>alive&&!deactivated&&allowed.value;
 function invalidateWork(){++workVersion;capture.value=null;}
 function clearDetail(){++detailVersion;detail.value=null;rawOpen.value=false;Object.assign(review,reviewInitial());}
 function clear(){++epoch;++operation;++listVersion;invalidateWork();clearDetail();baseline.value=candidate.value=target.value=null;declared.value=[];Object.assign(form,initial());directories.links=directories.scopes=null;optionsReady.value=false;busy.value=listsBusy.value=false;error.value=notice.value='';}
 function ticket(domain){return {key:auth(),epoch,domain,version:domain==='work'?workVersion:detailVersion};}
 const current=t=>available()&&t.key===auth()&&t.epoch===epoch&&t.version===(t.domain==='work'?workVersion:detailVersion);
 async function perform(domain,callback){
  if(!available()||!optionsReady.value||busy.value)return;error.value=notice.value='';const t=ticket(domain),id=++operation;busy.value=true;
  try{await callback(t,()=>current(t));}catch{if(current(t)){invalidateWork();if(domain==='detail')clearDetail();error.value='完整原件、声明、当前依赖或CAS无法核对；未自动重发，请刷新后人工核对';}}
  finally{if(id===operation)busy.value=false;}
 }
 async function loadDirectory(kind,page=1){
  if(!available())return;clearDetail();const t={key:auth(),epoch,version:++listVersion};listsBusy.value=true;
  try{const response=await (kind==='links'?api.getDocumentChangeLinks:api.getDocumentChangeScopes)({page,page_size:20});if(!available()||t.key!==auth()||t.epoch!==epoch||t.version!==listVersion)return;if(!api.documentChangeDirectoryValid(kind,response.data)||response.data.page!==page)throw new Error();directories[kind]=response.data;}
  catch{if(available()&&t.key===auth()&&t.epoch===epoch&&t.version===listVersion){directories[kind]=null;clearDetail();error.value='当前目录无法核对，旧私有详情已清除';}}
  finally{if(t.version===listVersion)listsBusy.value=false;}
 }
 async function refresh(){
  if(!available())return;const t={key:auth(),epoch,version:++listVersion};clearDetail();listsBusy.value=true;optionsReady.value=false;
  try{const values=await Promise.all([api.getDocumentChangeOptions(),api.getDocumentChangeLinks({page:1,page_size:20}),api.getDocumentChangeScopes({page:1,page_size:20})]);if(!available()||t.key!==auth()||t.epoch!==epoch||t.version!==listVersion)return;if(!api.documentChangeOptionsValid(values[0].data)||!api.documentChangeDirectoryValid('links',values[1].data)||!api.documentChangeDirectoryValid('scopes',values[2].data))throw new Error();directories.links=values[1].data;directories.scopes=values[2].data;optionsReady.value=true;}
  catch{if(available()&&t.key===auth()&&t.epoch===epoch&&t.version===listVersion){directories.links=directories.scopes=null;clearDetail();error.value='当前来源合同或目录无法核对，未开放写入';}}
  finally{if(t.version===listVersion)listsBusy.value=false;}
 }
 function selectOriginal(side,value){if(!available())return;(side==='baseline'?baseline:candidate).value=value?.ready===true?value.original:null;invalidateWork();clearDetail();target.value=null;}
 const pairValid=computed(()=>!!baseline.value&&!!candidate.value&&baseline.value.snapshot.original_id!==candidate.value.snapshot.original_id);
 function targetReference(){if(form.targetKind==='risk_rule_profile'&&supportId(form.targetId))return {kind:form.targetKind,target_id:form.targetId};if(form.targetKind==='clinical_pathway'&&/^[1-9][0-9]*$/.test(form.targetId)&&Number.isSafeInteger(Number(form.targetId))&&Number(form.targetId)<=2147483647)return {kind:form.targetKind,target_id:Number(form.targetId)};throw new Error();}
 async function readTarget(){await perform('work',async(t,valid)=>{const reference=targetReference(),response=await api.getDocumentChangeTarget(reference);if(!valid())return;const value=response.data;if(!api.documentChangeTargetValid(value.snapshot)||await digest(value.snapshot)!==value.snapshot_hash||!valid())throw new Error();if(canonical(value.snapshot.target)!==canonical(reference))throw new Error();target.value=value;});}
 function addTarget(){if(!available()||!target.value||!target.value.snapshot.exists||declared.value.length>=256)return;const value=target.value.snapshot.target;if(!declared.value.some(v=>key(v)===key(value)))declared.value=[...declared.value,value].sort((a,b)=>key(a)<key(b)?-1:key(a)>key(b)?1:0);invalidateWork();}
 function removeTarget(index){declared.value=declared.value.filter((_,i)=>i!==index);invalidateWork();}
 const originalRef=o=>({original_id:o.snapshot.original_id,content_hash:o.content_hash,governance_hash:o.governance_hash});
 function scopeBody(){if(!pairValid.value)throw new Error();return {baseline_original:originalRef(baseline.value),candidate_original:originalRef(candidate.value),relationship:{kind:form.relationship,same_guideline_family:form.family,basis_note:form.relationshipBasis},declared_targets:declared.value,rule_link_coverage:form.coverage,declaration_basis_note:form.declarationBasis};}
 const quote=computed(()=>{const o=form.side==='baseline'?baseline.value:form.side==='candidate'?candidate.value:null;if(!o||!/^(0|[1-9][0-9]*)$/.test(form.start)||!/^[1-9][0-9]*$/.test(form.end))return null;const start=Number(form.start),end=Number(form.end);if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start>=end||end>o.snapshot.codepoint_length||end-start>65535)return null;const text=documentCodepointSlice(o.snapshot.text,start,end);return documentUtf8(text).length<=65535?{start,end,quote:text}:null;});
 async function enrollLink(){await perform('work',async(t,valid)=>{
  const original=form.side==='baseline'?baseline.value:form.side==='candidate'?candidate.value:null;if(!original||!quote.value||!target.value)throw new Error();const body={original:originalRef(original),span:quote.value,target:target.value.snapshot.target,expected_target_hash:target.value.snapshot_hash,dependency_kind:form.dependency,basis_note:form.linkBasis,provenance:'unverified_human_submission'};
  const response=await api.createDocumentChangeLink(body);if(!valid())return;const row=response.data;if(!await api.verifyDocumentChangeLink(row,{original,target:target.value.snapshot,current:valid})||!valid()||canonical(row.snapshot.proposal)!==canonical(body)||row.governance.status!=='draft')throw new Error();Object.assign(review,reviewInitial());detail.value={kind:'links',value:row,original,target:target.value.snapshot};rawOpen.value=false;notice.value='关联仅登记为待审核人工声明，没有自动发布或修改目标';await refreshDirectories(valid);
 });}
 async function captureScope(){await perform('work',async(t,valid)=>{const body=scopeBody(),response=await api.captureDocumentChangeScope(body);if(!valid())return;if(!await api.verifyDocumentChangeCapture(response.data,body,{current:valid})||!valid())throw new Error();capture.value=response.data;});}
 async function enrollScope(){await perform('work',async(t,valid)=>{const saved=capture.value;if(!saved||canonical(scopeBody())!==canonical(saved.request))throw new Error();const response=await api.createDocumentChangeScope({...saved.request,expected_inventory_hash:saved.inventory_hash});if(!valid())return;const row=response.data;if(!await api.verifyDocumentChangeScope(row,{current:valid})||!valid()||canonical(row.snapshot.request)!==canonical(saved.request)||canonical(row.snapshot.inventory)!==canonical(saved.inventory)||row.governance.status!=='draft')throw new Error();Object.assign(review,reviewInitial());detail.value={kind:'scopes',value:row};rawOpen.value=false;capture.value=null;notice.value='有限比较范围已登记为草稿，须独立完成三项人工审核';await refreshDirectories(valid);});}
 async function refreshDirectories(valid){const values=await Promise.all([api.getDocumentChangeLinks({page:1,page_size:20}),api.getDocumentChangeScopes({page:1,page_size:20})]);if(!valid())return;if(!api.documentChangeDirectoryValid('links',values[0].data)||!api.documentChangeDirectoryValid('scopes',values[1].data))throw new Error();directories.links=values[0].data;directories.scopes=values[1].data;}
 async function inspectRecord(kind,metadata){clearDetail();await perform('detail',async(t,valid)=>{
  const id=metadata[kind==='links'?'link_id':'scope_id'],response=await(kind==='links'?api.getDocumentChangeLink:api.getDocumentChangeScope)(id);if(!valid())return;const value=response.data;if(!api.documentChangeMetadataMatches(kind,value,metadata))throw new Error();let original=null,parent=null;
  if(kind==='links'){const p=value.snapshot.proposal;[original,parent]=await Promise.all([getDocumentOriginal(p.original.original_id),api.getDocumentChangeTarget(p.target)]);if(!valid())return;original=original.data;parent=parent.data;if(!api.documentChangeTargetValid(parent.snapshot)||await digest(parent.snapshot)!==parent.snapshot_hash||!await api.verifyDocumentChangeLink(value,{original,target:parent.snapshot,current:valid})||!valid())throw new Error();parent=parent.snapshot;}
  else if(!await api.verifyDocumentChangeScope(value,{current:valid})||!valid())throw new Error();
  detail.value={kind,value,original,target:parent};rawOpen.value=false;
 });}
 async function mutate(revoke=false){await perform('detail',async(t,valid)=>{
  const selected=detail.value;if(!selected)throw new Error();const before=selected.value,body=revoke?{...cas(before),basis_note:review.revokeBasis}:{...cas(before),decision:review.decision,privacy_review:review.privacy_review,faithfulness_review:review.faithfulness_review,dependency_review:review.dependency_review,basis_note:review.basis_note};
  const fn=selected.kind==='links'?(revoke?api.revokeDocumentChangeLink:api.reviewDocumentChangeLink):(revoke?api.revokeDocumentChangeScope:api.reviewDocumentChangeScope),id=before.snapshot[selected.kind==='links'?'link_id':'scope_id'];const response=await fn(id,body);if(!valid())return;const after=response.data;
  const checked=selected.kind==='links'?await api.verifyDocumentChangeLink(after,{original:selected.original,target:selected.target,current:valid}):await api.verifyDocumentChangeScope(after,{current:valid});
  if(!checked||!valid()||after.content_hash!==before.content_hash||canonical(after.snapshot)!==canonical(before.snapshot)||after.governance.revision!==before.governance.revision+1||after.audit_event_ids.created!==before.audit_event_ids.created)throw new Error();
  if(revoke){if(after.governance.status!=='revoked'||after.governance.revoke_reason!==body.basis_note||['privacy_review','faithfulness_review','dependency_review','reviewed_by','reviewed_at','review_basis_note'].some(k=>after.governance[k]!==before.governance[k])||after.audit_event_ids.reviewed!==before.audit_event_ids.reviewed)throw new Error();}
  else if(after.governance.status!==(body.decision==='approve'?'published':'rejected')||['privacy_review','faithfulness_review','dependency_review'].some(k=>after.governance[k]!==body[k])||after.governance.review_basis_note!==body.basis_note)throw new Error();
  detail.value={...selected,value:after};notice.value=revoke?'已明确撤销；旧范围可能已失效，未自动修改任何目标':'审核已保存；发布只表示本次明确人工声明，不表示临床验证';rawOpen.value=false;await refreshDirectories(valid);
 });}
 watch(()=>canonical(form),()=>{invalidateWork();},{flush:'sync'});
 watch(()=>canonical(review),()=>{++detailVersion;},{flush:'sync'});
 watch(()=>[form.targetKind,form.targetId],()=>{target.value=null;},{flush:'sync'});
 watch(auth,()=>{clear();if(available())refresh();},{immediate:true,flush:'sync'});
 onActivated(()=>{if(!activated){activated=true;return;}deactivated=false;clear();if(available())refresh();});onDeactivated(()=>{deactivated=true;clear();});onBeforeUnmount(()=>{alive=false;clear();});
 return {allowed,form,review,baseline,candidate,declared,target,capture,detail,rawOpen,error,notice,busy,listsBusy,optionsReady,directories,pairValid,quote,states:api.documentChangeStates,canonical,documentBasis,refresh,loadDirectory,selectOriginal,readTarget,addTarget,removeTarget,enrollLink,captureScope,enrollScope,inspectRecord,mutate,clearDetail};
}
