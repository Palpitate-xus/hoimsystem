import {computed,onActivated,onBeforeUnmount,onDeactivated,onMounted,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {readVerifiedResearchVariableBatch} from '@/api/ai/researchVariableSources';
import {supportCanonical as canonical,supportId as uuid} from '@/api/inpatientSupport';
const clone=v=>JSON.parse(JSON.stringify(v)),allowed=['super_admin','admin','director','doctor','pharmacist'];
export function researchVariableReferencesValid(value){return value!==null&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===1&&Object.hasOwn(value,'research_variable_batch_id')&&uuid(value.research_variable_batch_id);}
export function useResearchVariableInput(props,emit){
 const store=useStore(),kept=ref(true),panelOpen=ref(false),selected=ref(null),reading=ref(false),error=ref(''),manualId=ref('');let epoch=0,mounted=false;
 const token=computed(()=>store.state.user?.accessToken||''),roles=computed(()=>canonical(store.state.user?.permissions??null)),username=computed(()=>store.state.user?.username||''),references=computed(()=>{try{return canonical(props.initialReferences);}catch{return 'invalid';}}),initialValid=computed(()=>props.initialReferences!==null&&typeof props.initialReferences==='object'&&!Array.isArray(props.initialReferences)&&(Object.keys(props.initialReferences).length===0||researchVariableReferencesValid(props.initialReferences))),authorized=computed(()=>{const r=store.state.user?.permissions;return !!token.value.trim()&&!!username.value.trim()&&props.active&&kept.value&&initialValid.value&&Array.isArray(r)&&r.length>0&&new Set(r).size===r.length&&r.every(v=>allowed.includes(v));}),pendingId=computed(()=>researchVariableReferencesValid(props.initialReferences)?props.initialReferences.research_variable_batch_id:null);
 function clear({close=true}={}){epoch++;reading.value=false;selected.value=null;if(close)panelOpen.value=false;emit('selection-change',null);}
 const ticket=()=>({epoch:++epoch,token:token.value,roles:roles.value,username:username.value,refs:references.value}),current=t=>mounted&&authorized.value&&t.epoch===epoch&&t.token===token.value&&t.roles===roles.value&&t.username===username.value&&t.refs===references.value;
 async function read(id){if(!authorized.value||reading.value||!uuid(id))return;clear({close:false});const t=ticket();reading.value=true;error.value='';try{const batch=await readVerifiedResearchVariableBatch(id,{current:()=>current(t)});if(!current(t))return;if(!batch||batch.metadata.record_id!==id||batch.currentValidation.eligible!==true||batch.metadata.status!=='published')throw Error('来源不满足当前完整批次条件');selected.value=clone(batch);panelOpen.value=false;emit('selection-change',{ready:true,references:{research_variable_batch_id:id},batch:clone(batch)});}catch(cause){if(!current(t))return;clear();error.value=[401,403].includes(cause?.response?.status)?'当前项目或逐患者研究授权不足，旧来源已清除。':'当前完整批次、治理关系或用途无法核对；请显式重读。';}finally{if(current(t))reading.value=false;}}
 function open(){if(!authorized.value||reading.value)return;clear();error.value='';panelOpen.value=true;}
 function choose(bundle){if(!authorized.value||!panelOpen.value||bundle?.metadata?.record_kind!=='batch'||bundle.currentValidation?.eligible!==true)return;read(bundle.metadata.record_id);}
 function invalidate(){clear({close:false});}
 function close(){clear();manualId.value='';error.value='';}
 watch([token,roles,username,references,()=>props.active,kept],()=>{clear();manualId.value='';error.value='';},{flush:'sync'});
 watch(manualId,()=>{clear({close:false});error.value='';},{flush:'sync'});
 onMounted(()=>{mounted=true;emit('selection-change',null);});onActivated(()=>{kept.value=true;});onDeactivated(()=>{kept.value=false;});onBeforeUnmount(()=>{mounted=false;epoch++;selected.value=null;panelOpen.value=false;emit('selection-change',null);});
 return {authorized,initialValid,pendingId,panelOpen,selected,reading,error,manualId,manualValid:computed(()=>uuid(manualId.value)),open,read,choose,invalidate,close};
}
