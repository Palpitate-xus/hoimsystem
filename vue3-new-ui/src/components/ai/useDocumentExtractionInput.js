import {computed,onActivated,onBeforeUnmount,onDeactivated,onMounted,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical,supportId} from '@/api/inpatientSupport';
import {documentDirectoryValid,documentMetadataMatches,getDocumentOriginal,getDocumentOriginals,verifyDocumentOriginal} from '@/api/ai/documentEvidence';

export function useDocumentExtractionInput(props,emit){
 const store=useStore(),keptActive=ref(true),blocked=ref(false),directory=ref(null),original=ref(null),busy=ref(false),error=ref(''),rawOpen=ref(false);
 const token=computed(()=>store.state.user?.accessToken||''),roles=computed(()=>JSON.stringify(store.state.user?.permissions||[])),username=computed(()=>store.state.user?.username||'');
 const referencesValid=computed(()=>{const value=props.initialReferences;if(!value||typeof value!=='object'||Array.isArray(value)||![Object.prototype,null].includes(Object.getPrototypeOf(value)))return false;const keys=Object.keys(value);return !keys.length||keys.length===1&&keys[0]==='document_original_id'&&supportId(value.document_original_id);});
 const referenceKey=computed(()=>{try{return supportCanonical(props.initialReferences);}catch{return 'invalid references';}});
 const preset=computed(()=>referencesValid.value?props.initialReferences.document_original_id||null:null);
 const authorized=computed(()=>props.active&&keptActive.value&&!blocked.value&&referencesValid.value&&typeof token.value==='string'&&token.value.length>0&&Array.isArray(store.state.user?.permissions)&&store.state.user.permissions.includes('super_admin'));
 const largeOriginal=computed(()=>original.value!==null&&original.value.snapshot.raw_bytes_length>=65535);
 let mounted=false,version=0;
 const ticket=()=>({version:++version,token:token.value,roles:roles.value,username:username.value,references:referenceKey.value});
 const current=t=>mounted&&authorized.value&&t.version===version&&t.token===token.value&&t.roles===roles.value&&t.username===username.value&&t.references===referenceKey.value;
 function clear(){version++;busy.value=false;original.value=null;rawOpen.value=false;emit('selection-change',null);}
 function reset(){clear();directory.value=null;error.value='';}
 function failed(cause,t){if(!current(t))return;clear();const status=cause?.response?.status;if(status===401||status===403){blocked.value=true;directory.value=null;error.value='当前登录或权限已失效，原件与选择已清除。';}else error.value=status===409?'原件或审核版本已变化，请重新选择；未自动重试。':'完整原文、当前审核或字节身份无法核对，本次没有建立选择。';}
 async function loadPage(page=1){if(!authorized.value)return;clear();const t=ticket();busy.value=true;error.value='';try{const row=(await getDocumentOriginals({page,page_size:20})).data;if(!current(t))return;if(!documentDirectoryValid('originals',row)||row.page!==page||row.page_size!==20)throw new Error('原文目录分页合同不一致');directory.value=row;}catch(cause){failed(cause,t);}finally{if(current(t))busy.value=false;}}
 function metadataMatches(row,metadata){if(!metadata)return true;const s=row.snapshot,m=s.metadata;return documentMetadataMatches('originals',row,metadata)&&metadata.title===m.title&&metadata.version===m.version&&metadata.document_kind===m.document_kind&&metadata.raw_bytes_hash===s.raw_bytes_hash&&metadata.raw_bytes_length===s.raw_bytes_length&&metadata.codepoint_length===s.codepoint_length&&metadata.recorded_at===s.recorded_at;}
 async function select(id,metadata=null){if(!authorized.value||!supportId(id))return;clear();const t=ticket();busy.value=true;error.value='';try{const row=(await getDocumentOriginal(id)).data;if(!current(t))return;if(!await verifyDocumentOriginal(row,{current:()=>current(t)})||row.snapshot.original_id!==id||!metadataMatches(row,metadata)||!row.eligible||row.governance.status!=='published'||row.governance.privacy_review!=='confirmed'||row.governance.faithfulness_review!=='confirmed')throw new Error('当前原文、明确双审核或选择身份无法核对');if(!current(t))return;original.value=row;emit('selection-change',{ready:true,references:{document_original_id:id},original:JSON.parse(JSON.stringify(row))});}catch(cause){failed(cause,t);}finally{if(current(t))busy.value=false;}}
 function selectPreset(){if(preset.value)select(preset.value);}
 watch([token,roles,username,()=>props.active,keptActive,referenceKey],()=>{blocked.value=false;reset();if(mounted&&authorized.value)loadPage();},{flush:'sync'});
 onMounted(()=>{mounted=true;if(authorized.value)loadPage();else clear();});
 onActivated(()=>{keptActive.value=true;});onDeactivated(()=>{keptActive.value=false;});onBeforeUnmount(()=>{mounted=false;reset();});
 return {authorized,referencesValid,preset,directory,original,busy,error,rawOpen,largeOriginal,loadPage,select,selectPreset,clear};
}
