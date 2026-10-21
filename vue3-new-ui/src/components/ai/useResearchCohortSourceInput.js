import {computed,onActivated,onBeforeUnmount,onDeactivated,onMounted,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical as canonical,supportId as uuid} from '@/api/inpatientSupport';
import {getResearchCase} from '@/api/ai/researchCohortSources';
import {verifyResearchCase,researchCaseAnchors,researchCaseAnchorsValid} from '@/api/ai/researchCohortCases';
export function researchCohortReferencesValid(value){if(value===null||value===undefined)return true;if(typeof value!=='object'||Array.isArray(value)||![Object.prototype,null].includes(Object.getPrototypeOf(value)))return false;const names=Object.keys(value);return names.length===0||names.length===1&&names[0]==='research_cohort_case_id'&&uuid(value.research_cohort_case_id);}
export function useResearchCohortSourceInput(props,emit){
 const store=useStore(),kept=ref(true),blocked=ref(false),selected=ref(null),open=ref(false),busy=ref(false),error=ref(''),token=computed(()=>store.state.user?.accessToken||''),roles=computed(()=>JSON.stringify(store.state.user?.permissions??null)),username=computed(()=>store.state.user?.username||''),role=computed(()=>{const r=store.state.user?.permissions;if(!Array.isArray(r)||!r.length||new Set(r).size!==r.length||r.some(v=>typeof v!=='string'||!['super_admin','admin','director','doctor'].includes(v)))return null;return r.includes('super_admin')?'super_admin':r[0];}),referencesValid=computed(()=>researchCohortReferencesValid(props.initialReferences)),referenceKey=computed(()=>{try{return canonical(props.initialReferences??null);}catch{return 'invalid';}}),preset=computed(()=>referencesValid.value?props.initialReferences?.research_cohort_case_id??null:null),authorized=computed(()=>props.active&&kept.value&&!blocked.value&&!!token.value&&!!role.value&&referencesValid.value);
 let mounted=false,version=0;
 const ticket=()=>({version:++version,token:token.value,roles:roles.value,username:username.value,ref:referenceKey.value}),current=t=>mounted&&authorized.value&&t.version===version&&t.token===token.value&&t.roles===roles.value&&t.username===username.value&&t.ref===referenceKey.value;
 function clear({close=false,invalidate=true}={}){version++;selected.value=null;busy.value=false;if(close)open.value=false;emit('availability',false);if(invalidate)emit('invalidate');}
 function failed(cause,t){if(!current(t))return;const status=cause?.response?.status;clear({close:true});if([401,403].includes(status)){blocked.value=true;error.value='当前会话或项目逐患者授权已失效，旧来源选择已清除。';}else error.value=status===409?'病例来源、成员或授权已变化，请明确重读。':'完整病例来源或本地条件结果无法核对，未建立选择。';}
 async function read(id,candidate=null){if(!authorized.value||!uuid(id)||candidate&&!researchCaseAnchorsValid(candidate))return;clear();error.value='';const t=ticket();busy.value=true;try{const value=(await getResearchCase(id,{auditOnly:false})).data,proof=await verifyResearchCase(value,{caseId:id,auditOnly:false,execution:true,current:()=>current(t)});if(!proof?.selectable)throw new Error('当前完整病例未满足选件条件');const anchors=researchCaseAnchors(value);if(candidate&&canonical(candidate)!==canonical(anchors))throw new Error('当前来源已不同于明确选择');if(!current(t))return;selected.value={anchors,externalModelUse:value.public_source.external_model_use};open.value=false;emit('scope-change',{scopeId:value.scope_id});emit('selection',{research_cohort_case_id:id});emit('availability',true);}catch(cause){failed(cause,t);}finally{if(current(t))busy.value=false;}}
 function select(candidate){if(!authorized.value||!researchCaseAnchorsValid(candidate))return;return read(candidate.case_id,candidate);}
 function showSources(){if(!authorized.value)return;clear();error.value='';open.value=true;}
 function closeSources(){clear({close:true});}
 function invalidate(){clear();}
 function sourceChanged(){clear();}
 function reread(){const id=selected.value?.anchors.case_id||preset.value;if(id)read(id);}
 watch([token,roles,username,referenceKey,()=>props.active,kept],()=>{blocked.value=false;error.value='';clear({close:true});emit('scope-change',{scopeId:null});},{flush:'sync'});
 onMounted(()=>{mounted=true;clear();});onActivated(()=>{kept.value=true;});onDeactivated(()=>{kept.value=false;});onBeforeUnmount(()=>{mounted=false;clear({close:true});});
 return {authorized,referencesValid,preset,selected,open,busy,error,read,select,showSources,closeSources,invalidate,sourceChanged,reread,clear};
}
