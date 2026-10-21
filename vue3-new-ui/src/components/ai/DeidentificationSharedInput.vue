<template>
 <section aria-label="病例去标识项目与患者来源入口">
  <p>只读取明确项目中的单个实际患者；项目技术候选不授予研究、外发或导出权限。</p>
  <p v-if="!allowed" role="status">当前会话不能选择病例去标识来源。</p>
  <p v-else-if="!validProps" role="alert">业务患者、项目三锚或唯一Case引用无效，未读取来源。</p>
  <template v-else>
   <el-button :disabled="busy" @click="loadScopes(1)">读取当前项目技术候选</el-button>
   <el-select v-if="scopes.length" :model-value="selectedScope?.scope_id??null" aria-label="明确病例去标识项目" :disabled="scope!==null||busy" clearable @update:model-value="selectScope">
    <el-option v-for="row in scopes" :key="row.scope_id" :value="row.scope_id" :label="row.scope_id+' / '+row.status"/>
   </el-select>
   <template v-if="total>100"><el-button :disabled="busy||page===1" @click="loadScopes(page-1)">上一页项目</el-button><span>第{{ page }}页，共{{ total }}个技术候选</span><el-button :disabled="busy||page*100>=total" @click="loadScopes(page+1)">下一页项目</el-button></template>
   <p v-if="selectedScope" aria-label="明确项目技术三锚">项目 {{ selectedScope.scope_id }}；SHA只绑定该原件版本，不代表当前用途权限。</p>
   <p v-if="patientId!==null" aria-label="业务绑定真实患者">已绑定业务患者 {{ patientId }}，不可切换为其他患者。</p>
   <template v-else-if="isSuper&&selectedScope">
    <el-button :disabled="busy" @click="readDeclaredPatients">显式读取本项目声明的有限患者集合</el-button>
    <el-select v-if="declaredPatients.length" v-model="selectedPatient" aria-label="明确项目已声明患者" :disabled="busy" clearable @change="scopeChanged"><el-option v-for="id in declaredPatients" :key="id" :value="id" :label="'项目声明患者 '+id"/></el-select>
    <p>这只是项目原件声明的有限集合，逐患者用途与模型许可仍由当前Case读取重新核验。</p>
   </template>
   <p v-else-if="selectedPatient===null" role="status">缺少实际授权患者入口。请从真实患者业务行进入，或显式读取已有Case；不提供全院患者目录。</p>
   <el-button v-if="pending" :disabled="busy" @click="readInitial">按当前用途重读明确Case引用</el-button>
   <p v-if="chosen" aria-label="当前已核对去标识Case">已核对当前普通来源 {{ chosen }}。本地选择不授予模型外发、人工复核或导出资格。</p>
   <el-button @click="clearSelection">清除病例去标识选择</el-button>
   <DeidentificationInput v-if="selectedScope&&positive(selectedPatient)&&chosen===null" :scope="selectedScope" :patient-id="selectedPatient" :active="active" @selection="choose" @availability="value=>emit('availability',value)" @invalidate="invalidate"/>
  </template>
  <p v-if="busy" role="status">正在按当前授权核对完整原件…</p><p v-if="error" role="alert">{{ error }}</p>
 </section>
</template>
<script setup>
import{computed,onActivated,onBeforeUnmount,onDeactivated,ref,watch}from'vue';import{useStore}from'vuex';
import DeidentificationInput from'./DeidentificationInput.vue';
import{getResearchScopes,getResearchScope}from'@/api/ai/researchCohortSources';
import{researchRegistryDirectoryValid,researchRegistryMetadataMatches}from'@/api/ai/researchCohortDirectory';
import{verifyResearchRegistryRecord}from'@/api/ai/researchCohortProofs';
import{getDeidentificationCase,verifyDeidentificationSource,deidentificationPolicy,deidentificationScopeValid}from'@/api/ai/deidentificationSources';
import{deidentificationReferencesValid}from'@/api/ai/deidentificationTasks';
import{deidentificationCanonical as canonical,keys,pick,same,positive}from'@/api/ai/deidentificationCore';
const props=defineProps({scope:{type:Object,default:null},patientId:{type:Number,default:null},initialReferences:{type:Object,default:null},active:{type:Boolean,default:true},configRevision:{type:[Number,String],default:null}}),emit=defineEmits(['scope-change','selection','availability','invalidate']),store=useStore(),kept=ref(true),busy=ref(false),scopes=ref([]),page=ref(1),total=ref(0),selectedScope=ref(null),selectedPatient=ref(null),declaredPatients=ref([]),chosen=ref(null),error=ref('');let epoch=0,alive=true;
const roles=computed(()=>store.state.user?.permissions),isSuper=computed(()=>Array.isArray(roles.value)&&roles.value.includes('super_admin')),allowed=computed(()=>alive&&props.active&&kept.value&&!!store.state.user?.accessToken&&Array.isArray(roles.value)&&roles.value.every(x=>typeof x==='string')&&roles.value.some(x=>deidentificationPolicy.source_roles.includes(x)));
const scopeValid=value=>keys(value,['scope_id','scope_content_hash','scope_governance_hash'])&&deidentificationScopeValid({...value,patient_id:1}),validProps=computed(()=>(props.patientId===null||positive(props.patientId))&&(props.scope===null||scopeValid(props.scope))&&(props.initialReferences===null||deidentificationReferencesValid(props.initialReferences))),pending=computed(()=>deidentificationReferencesValid(props.initialReferences)?props.initialReferences.deidentification_case_id:null);
const identity=()=>canonical([props.scope,props.patientId,props.initialReferences,props.active,props.configRevision,store.state.user?.accessToken,store.state.user?.username,roles.value]),current=t=>allowed.value&&validProps.value&&t.epoch===epoch&&t.identity===identity();
function clearSelection(){epoch++;busy.value=false;chosen.value=null;emit('selection',null);emit('availability',false);emit('invalidate');}
function publishScope(){emit('scope-change',{scope:selectedScope.value,patientId:selectedPatient.value});}
function reset(){clearSelection();scopes.value=[];total.value=0;declaredPatients.value=[];selectedScope.value=props.scope&&scopeValid(props.scope)?{...props.scope}:null;selectedPatient.value=positive(props.patientId)?props.patientId:null;error.value='';publishScope();}
function scopeChanged(){clearSelection();publishScope();}
async function loadScopes(selected=1){if(!allowed.value||!validProps.value)return;clearSelection();scopes.value=[];error.value='';const t={epoch:++epoch,identity:identity()};busy.value=true;try{const value=(await getResearchScopes({page:selected,size:100})).data;if(!current(t))return;if(!researchRegistryDirectoryValid(value,'scope',{page:selected,size:100}))throw new Error();scopes.value=value.items;page.value=selected;total.value=value.total;}catch{if(current(t)){scopes.value=[];error.value='当前项目技术目录无法读取或核对，未选择首项。';}}finally{if(current(t))busy.value=false;}}
function selectScope(id){clearSelection();declaredPatients.value=[];if(props.scope!==null)return;const row=scopes.value.find(x=>x.scope_id===id);selectedScope.value=row?{scope_id:row.scope_id,scope_content_hash:row.content_hash,scope_governance_hash:row.governance_hash}:null;selectedPatient.value=props.patientId;publishScope();}
async function readDeclaredPatients(){if(!allowed.value||!isSuper.value||!selectedScope.value)return;clearSelection();declaredPatients.value=[];error.value='';const t={epoch:++epoch,identity:identity()},scope={...selectedScope.value};busy.value=true;try{const row=(await getResearchScope(scope.scope_id,{auditOnly:false})).data;if(!current(t)||!same(scope,selectedScope.value))return;const listed=scopes.value.find(x=>x.scope_id===scope.scope_id);if(!await verifyResearchRegistryRecord(row,{kind:'scope',expectedId:scope.scope_id,auditOnly:false,current:()=>current(t)})||row.original===null||row.content_hash!==scope.scope_content_hash||row.governance_hash!==scope.scope_governance_hash||listed&&!researchRegistryMetadataMatches(row,listed,'scope'))throw new Error();if(!current(t))return;declaredPatients.value=[...row.original.payload.patient_ids];}catch{if(current(t))error.value='项目原件当前不可读；未显示或推断任何患者。';}finally{if(current(t))busy.value=false;}}
async function readInitial(){if(!allowed.value||!validProps.value||!pending.value)return;clearSelection();const t={epoch:++epoch,identity:identity()},id=pending.value;busy.value=true;error.value='';try{const row=(await getDeidentificationCase(id,{audit_only:false})).data;if(!current(t))return;if(!await verifyDeidentificationSource(row,{auditOnly:false,current:()=>current(t)})||!row.eligible||row.snapshot===null||row.case_id!==id)throw new Error();const request=row.snapshot.capture.request,scope=pick(request,['scope_id','scope_content_hash','scope_governance_hash']);if(props.patientId!==null&&row.snapshot.patient_id!==props.patientId||props.scope!==null&&!same(props.scope,scope))throw new Error();if(!current(t))return;selectedScope.value=scope;selectedPatient.value=row.snapshot.patient_id;chosen.value=id;publishScope();emit('selection',{deidentification_case_id:id});emit('availability',true);}catch{if(current(t)){clearSelection();error.value='当前Case、项目、实际患者或用途不符，未保留旧选择。';}}finally{if(current(t))busy.value=false;}}
function choose(value){chosen.value=deidentificationReferencesValid(value)?value.deidentification_case_id:null;emit('selection',value);}
function invalidate(){chosen.value=null;emit('selection',null);emit('availability',false);emit('invalidate');}
watch([()=>props.scope,()=>props.patientId,()=>props.initialReferences,()=>props.active,()=>props.configRevision,()=>store.state.user?.accessToken,()=>store.state.user?.username,roles,kept],reset,{deep:true,flush:'sync',immediate:true});
onActivated(()=>{kept.value=true;});onDeactivated(()=>{kept.value=false;});onBeforeUnmount(()=>{alive=false;reset();});defineExpose({clear:reset});
</script>
