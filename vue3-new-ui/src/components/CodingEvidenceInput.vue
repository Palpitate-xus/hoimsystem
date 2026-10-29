<template>
  <section aria-label="完整病案编码依据入口">
    <p v-if="!allowed">当前身份不能读取病案编码依据。</p>
    <template v-else>
      <p>核对本次真实住院的完整病案首页、全部编码绑定、对应字典与已记录分组。整理结果等待人工复核，不确认临床诊断，不自动写入编码或结算。</p>
      <p v-if="!scopeValid">请从已授权患者的真实住院记录进入，不能手工猜测病案标识。</p>
      <template v-else>
        <el-form inline @submit.prevent="refresh">
          <el-form-item label="实际病案首页"><el-select :model-value="home" @update:model-value="editHome" :disabled="homeId !== null || loading" clearable aria-label="实际病案首页" placeholder="明确实际病案首页，不默认首项"><el-option v-for="row in homes" :key="row.home_id" :value="row.home_id" :label="`病案首页 ${row.home_id} · ${row.status_text || '原记录'}`" /></el-select></el-form-item>
          <el-button native-type="submit" :loading="loading">重新核对病案范围</el-button><el-button v-if="selected" @click="clearSelection">清除编码依据选择</el-button>
        </el-form>
        <p v-if="error" role="alert">{{ error }}</p><p v-if="checking" role="status">正在核对完整病案、原件哈希及当前治理。</p>
        <p v-if="selected" aria-label="已选择完整编码依据">受审原件 {{ selected.source_id }}；{{ selected.public_source.code_bindings.length }} 条完整编码绑定；捕获时刻 {{ selected.snapshot.collection.captured_at }}。</p>
        <coding-evidence-sources v-if="homeReady" :key="childKey" :patient-id="patientId" :admission-id="admissionId" :home-id="home" :active="active" :audit-only="false" @select="selectCase" @source-changed="sourceChanged" @invalidate="sourceUnavailable" />
      </template>
    </template>
  </section>
</template>

<script setup>
import {computed,defineAsyncComponent,onActivated,onBeforeUnmount,onDeactivated,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical as canonical,supportId as uuid} from '@/api/inpatientSupport';
import {getCodingEvidenceHomes,getCodingEvidenceCase,verifyCodingEvidenceCase,codingCaseReferencesValid,codingEvidenceHomesValid} from '@/api/ai/codingEvidence';
const CodingEvidenceSources=defineAsyncComponent(()=>import('./CodingEvidenceSources.vue'));
const props=defineProps({patientId:{type:Number,default:null},admissionId:{type:String,default:null},homeId:{type:String,default:null},initialReferences:{type:Object,default:null},active:{type:Boolean,default:true}});
const emit=defineEmits(['scope-change','selection','availability','invalidate']),store=useStore(),roles=computed(()=>store.getters['user/permissions']||[]);
const positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647;
const allowed=computed(()=>props.active&&!!store.state.user.accessToken&&roles.value.some(r=>['admin','super_admin','director','doctor'].includes(r)));
const scopeValid=computed(()=>positive(props.patientId)&&uuid(props.admissionId)&&(props.homeId===null||uuid(props.homeId)));
const home=ref(props.homeId),homes=ref([]),selected=ref(null),loading=ref(false),checking=ref(false),error=ref(''),childKey=ref(0);
const homeReady=computed(()=>allowed.value&&scopeValid.value&&uuid(home.value)&&homes.value.some(r=>r.home_id===home.value));
let epoch=0,loadVersion=0,selectionVersion=0,alive=true,paused=false,initialAllowed=true;
const identity=()=>canonical([props.patientId,props.admissionId,props.homeId,props.initialReferences,props.active,home.value,store.state.user.accessToken,store.state.user.username,roles.value]);
const ticket=()=>({epoch,identity:identity()}),current=t=>alive&&!paused&&allowed.value&&t.epoch===epoch&&t.identity===identity();
function invalidate(notify=true){selectionVersion++;checking.value=false;selected.value=null;emit('selection',null);emit('availability',false);if(notify)emit('invalidate');}
function reset(notify=true){epoch++;loadVersion++;homes.value=[];loading.value=false;error.value='';childKey.value++;invalidate(notify);emit('scope-change',null);}
function fail(message){reset();error.value=message||'当前病案范围或完整原件已无法核对，旧选择已清除。';}
async function refresh(){
 invalidate();homes.value=[];emit('scope-change',null);const t=ticket(),version=++loadVersion;
 if(!current(t)||!scopeValid.value)return;
 loading.value=true;error.value='';
 try{
  if(props.initialReferences!==null&&!codingCaseReferencesValid(props.initialReferences))throw new Error('编码依据引用须仅包含一个规范编码快照标识。');
  const query={patient_id:props.patientId,admission_id:props.admissionId},value=(await getCodingEvidenceHomes(query)).data;
  if(!current(t)||version!==loadVersion)return;
  if(!codingEvidenceHomesValid(value,query))throw new Error('当前真实病案目录的患者与住院范围无法核对。');
  homes.value=value.items;
  if(home.value!==null){if(!homes.value.some(r=>r.home_id===home.value))throw new Error('业务病案首页已不属于当前授权住院。');emit('scope-change',{...query,home_id:home.value});}
  if(initialAllowed&&props.initialReferences!==null){
   if(home.value===null){const row=(await getCodingEvidenceCase(props.initialReferences.coding_case_id,{auditOnly:false})).data;
    if(!current(t)||version!==loadVersion)return;
    if(row.case_snapshot_id!==props.initialReferences.coding_case_id||!row.eligible||!await verifyCodingEvidenceCase(row,{patientId:props.patientId,admissionId:props.admissionId,auditOnly:false}))throw new Error('原编码快照当前不能用于本次住院。');
    if(!current(t)||version!==loadVersion)return;
    if(!homes.value.some(r=>r.home_id===row.home_id))throw new Error('原快照病案不在当前授权目录。');home.value=row.home_id;return;
   }
   await selectCase(props.initialReferences);
  }
 }catch(e){if(current(t)&&version===loadVersion)fail(e.message);}
 finally{if(current(t)&&version===loadVersion)loading.value=false;}
}
async function selectCase(refValue){
 invalidate();const t=ticket(),version=selectionVersion;if(!current(t)||!homeReady.value)return;checking.value=true;error.value='';
 try{if(!codingCaseReferencesValid(refValue))throw new Error('须明确选择一个规范编码依据快照。');
  const row=(await getCodingEvidenceCase(refValue.coding_case_id,{auditOnly:false})).data;
  if(!current(t)||version!==selectionVersion)return;
  if(row.case_snapshot_id!==refValue.coding_case_id||row.audit_only!==false||!row.eligible||!row.public_source||!await verifyCodingEvidenceCase(row,{patientId:props.patientId,admissionId:props.admissionId,homeId:home.value,auditOnly:false}))throw new Error('完整编码原件、实际病案或当前治理已无法核对。');
  if(!current(t)||version!==selectionVersion)return;
  selected.value=row;emit('selection',{coding_case_id:row.case_snapshot_id});emit('availability',true);
 }catch(e){if(current(t)&&version===selectionVersion)fail(e.message);}
 finally{if(current(t)&&version===selectionVersion)checking.value=false;}
}
function editHome(value){initialAllowed=false;home.value=value||null;}
function clearSelection(){initialAllowed=false;invalidate();}
function sourceChanged(){invalidate();childKey.value++;error.value='原病案、编码绑定或治理已变化，请重新核对完整快照。';}
function sourceUnavailable(){const had=selected.value!==null||checking.value;invalidate();if(had)error.value='当前原件无法核对，旧选择已清除。';}
watch(()=>canonical([props.patientId,props.admissionId,props.homeId,props.initialReferences]),()=>{initialAllowed=true;},{flush:'sync'});
watch(()=>[props.patientId,props.admissionId,props.homeId],values=>{home.value=values[2];},{flush:'sync'});
watch(identity,()=>{reset();refresh();},{immediate:true,flush:'sync'});
onDeactivated(()=>{paused=true;reset();});onActivated(()=>{if(paused){paused=false;reset();refresh();}});onBeforeUnmount(()=>{alive=false;reset(false);});
</script>
<style scoped>p{line-height:1.7;overflow-wrap:anywhere}.el-select{min-width:340px}.el-button{margin:6px}</style>
