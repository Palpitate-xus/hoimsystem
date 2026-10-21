import {computed,onActivated,onBeforeUnmount,onDeactivated,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical as canonical} from '@/api/inpatientSupport';
import {verifySatisfactionContext,verifySatisfactionFindings,verifySatisfactionResult,resolveSatisfactionEvidence} from '@/api/ai/satisfactionResults';

export function useSatisfactionFindings(props,emit){
 const store=useStore(),roles=computed(()=>store.getters['user/permissions']||[]),allowed=computed(()=>props.active&&!!store.state.user.accessToken&&roles.value.some(r=>['admin','director','super_admin'].includes(r))&&(!props.auditOnly||roles.value.includes('super_admin')));
 const source=ref(null),result=ref(null),findings=ref(null),checking=ref(false),error=ref(''),themeIndex=ref(0),evidence=ref(null),evidenceChecking=ref(false),excerptPage=ref(0);
 let version=0,evidenceVersion=0,alive=true,paused=false;
 const current=token=>alive&&!paused&&allowed.value&&version===token;
 function closeEvidence(){evidenceVersion++;evidence.value=null;evidenceChecking.value=false;excerptPage.value=0;}
 function clear(){version++;source.value=null;result.value=null;findings.value=null;checking.value=false;error.value='';themeIndex.value=0;closeEvidence();}
 async function load(){clear();if(!alive||paused||!allowed.value||props.packet===null)return;const token=version;checking.value=true;error.value='';try{const packet=props.packet,expanded=Object.hasOwn(packet,'snapshot_time'),valid=expanded?await verifySatisfactionContext(packet,{references:props.references,auditOnly:props.auditOnly}):await verifySatisfactionFindings(packet,{references:props.references,auditOnly:props.auditOnly});if(!current(token))return;if(!valid)throw new Error('完整安全来源、原发布绑定或当前入口引用无法核对。');const value=props.result,hasResult=value!==null&&!(typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===0);if(hasResult&&!await verifySatisfactionResult(packet.satisfaction_source,value))throw new Error('固定统计、完整部分主题或逐字码点引文无法核对。');if(!current(token))return;source.value=JSON.parse(canonical(packet.satisfaction_source));result.value=hasResult?JSON.parse(canonical(value)):null;findings.value=JSON.parse(canonical({satisfaction_source:packet.satisfaction_source,satisfaction_case:packet.satisfaction_case,satisfaction_binding:packet.satisfaction_binding}));}catch(e){if(current(token)){source.value=null;result.value=null;findings.value=null;closeEvidence();error.value=e.message||'完整评价结果无法核对，旧正文已清除。';emit('invalidate');}}finally{if(current(token))checking.value=false;}}
 async function openEvidence(){if(!source.value||!findings.value||!allowed.value)return;closeEvidence();const token=version,dialog=++evidenceVersion;evidenceChecking.value=true;const binding=findings.value.satisfaction_binding,value={source_id:binding.source_id,kind:'operational_record',title:'完整评价与明确选择人工摘录的安全冻结依据',content:canonical({satisfaction_binding:binding})};
  try{const opened=await resolveSatisfactionEvidence(value,findings.value,{references:props.references,auditOnly:props.auditOnly});if(!current(token)||dialog!==evidenceVersion)return;if(!opened)throw new Error('安全冻结依据无法核对。');evidence.value=opened;}catch(e){if(current(token)&&dialog===evidenceVersion){evidence.value=null;error.value=e.message;emit('invalidate');}}finally{if(current(token)&&dialog===evidenceVersion)evidenceChecking.value=false;}}
 watch(()=>[props.packet,props.result,props.references],load,{immediate:true,deep:true,flush:'sync'});
 // A new login/role/config activation cannot re-authorize retained props.
 // The parent must obtain a fresh authorized packet before they are shown.
 watch(()=>[props.active,props.auditOnly,store.state.user.accessToken,store.state.user.username,roles.value],()=>{const hadView=source.value!==null||checking.value;clear();if(hadView)emit('invalidate');},{deep:true,flush:'sync'});
 onDeactivated(()=>{paused=true;clear();});onActivated(()=>{if(paused){paused=false;clear();if(props.packet!==null)emit('invalidate');}});onBeforeUnmount(()=>{alive=false;clear();});
 return{allowed,source,result,checking,error,themeIndex,evidence,evidenceChecking,excerptPage,closeEvidence,openEvidence};
}
