<template>
  <section class="document-change-input" aria-label="双原文比较范围选择">
    <el-alert title="只选择已审核的有限比较范围，生成结果仍是未核实的问题草稿" type="info" :closable="false" />
    <p class="note">两件原文、已登记关联和直接知识发布都保留原样。版本关系是人工声明，不自动替代原文、修改规则或证明临床影响。</p>
    <el-alert v-if="!allowed" title="仅当前超级管理员可以读取和选择完整原文范围" type="warning" :closable="false" />
    <el-alert v-else-if="!referencesValid" title="比较范围引用须仅含规范的 document_change_scope_id，不接受患者、就诊或其它输入" type="warning" :closable="false" />
    <template v-else>
      <div class="actions"><el-button :loading="loading" @click="loadPage">刷新比较范围目录</el-button><el-button v-if="record" @click="clearSelection">清除所选范围</el-button></div>
      <el-alert v-if="error" :title="error" type="warning" :closable="false" />
      <el-table :data="items" row-key="scope_id" empty-text="当前页无比较范围，不会自动选择首项">
        <el-table-column prop="scope_id" label="范围标识" min-width="260" />
        <el-table-column label="审核状态" width="130"><template #default="{row}">{{ states[row.status] }}</template></el-table-column>
        <el-table-column prop="revision" label="版本" width="70" />
        <el-table-column label="操作" width="150"><template #default="{row}"><el-button :disabled="row.status!=='published'||selecting" @click="choose(row.scope_id,row)">读取完整件并选择</el-button></template></el-table-column>
      </el-table>
      <div class="actions"><el-button :disabled="page===1||loading" @click="changePage(-1)">上一页</el-button><span>第 {{ page }} 页 · {{ total }} 件</span><el-button :disabled="page*20>=total||loading" @click="changePage(1)">下一页</el-button></div>
      <div v-if="record&&publicSource" class="chosen" aria-label="已核对完整双原文范围">
        <p>基线：{{ record.snapshot.inventory.baseline_original.snapshot.metadata.title }} · {{ record.snapshot.inventory.baseline_original.snapshot.metadata.version }}</p>
        <p>候选：{{ record.snapshot.inventory.candidate_original.snapshot.metadata.title }} · {{ record.snapshot.inventory.candidate_original.snapshot.metadata.version }}</p>
        <p>完整依赖 {{ publicSource.member_count }} 项；关联 {{ publicSource.rule_links.length }} 条；直接知识发布 {{ publicSource.publications.length }} 项。</p>
        <p>声明范围内目标 {{ publicSource.targets.filter(t=>t.within_declared_scope).length }} 项，范围外保留目标 {{ publicSource.targets.filter(t=>!t.within_declared_scope).length }} 项；全院盘点未提供。</p>
        <p>完整私有原件及公开投影已逐字段核对。登记容量不保证完整模型报文可装入预算，生成前仍需服务器另检。</p>
      </div>
    </template>
  </section>
</template>
<script setup>
import {computed,onActivated,onBeforeUnmount,onDeactivated,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical} from '@/api/inpatientSupport';
import {documentChangeReferenceValid,documentChangeDirectoryValid,documentChangeMetadataMatches,documentChangeStates,getDocumentChangeScopes,getDocumentChangeScope,getDocumentChangePublicSource,verifyDocumentChangeScope,verifyDocumentChangeSource} from '@/api/ai/documentChanges';
const props=defineProps({active:{type:Boolean,default:true},initialReferences:{type:Object,default:()=>({})}}),emit=defineEmits(['selection-change']),store=useStore();
const roles=computed(()=>store.getters['user/permissions']),allowed=computed(()=>props.active&&typeof store.state.user.accessToken==='string'&&store.state.user.accessToken.length>0&&Array.isArray(roles.value)&&roles.value.includes('super_admin'));
const referencesValid=computed(()=>props.initialReferences!==null&&typeof props.initialReferences==='object'&&!Array.isArray(props.initialReferences)&&(Object.keys(props.initialReferences).length===0||documentChangeReferenceValid(props.initialReferences)));
const auth=()=>supportCanonical([props.active,store.state.user.accessToken,store.state.user.username,roles.value]),initialAuth=auth(),initiallyAllowed=allowed.value;
const items=ref([]),page=ref(1),total=ref(0),record=ref(null),publicSource=ref(null),loading=ref(false),selecting=ref(false),error=ref(''),states=documentChangeStates;
let alive=true,deactivated=false,activationSeen=false,epoch=0,listVersion=0,detailVersion=0,initialSeed=true;
const current=(key,version)=>alive&&!deactivated&&allowed.value&&referencesValid.value&&key===auth()&&version===epoch;
function clearSelection(){++detailVersion;record.value=publicSource.value=null;selecting.value=false;error.value='';emit('selection-change',null);}
function clear(){++epoch;++listVersion;clearSelection();items.value=[];page.value=1;total.value=0;loading.value=false;}
async function loadPage(){
 if(!alive||deactivated||!allowed.value||!referencesValid.value)return;
 const key=auth(),version=epoch,ticket=++listVersion;loading.value=true;
 try{const response=await getDocumentChangeScopes({page:page.value,page_size:20});if(!current(key,version)||ticket!==listVersion)return;if(!documentChangeDirectoryValid('scopes',response.data))throw new Error();items.value=response.data.items;total.value=response.data.total;}
 catch{if(current(key,version)&&ticket===listVersion){clearSelection();items.value=[];total.value=0;error.value='当前比较范围目录无法核对，旧私有原件已清除';}}
 finally{if(current(key,version)&&ticket===listVersion)loading.value=false;}
}
async function choose(id,metadata=null){
 if(!alive||deactivated||!allowed.value||!referencesValid.value)return;
 clearSelection();const key=auth(),version=epoch,ticket=detailVersion;selecting.value=true;const valid=()=>current(key,version)&&ticket===detailVersion;
 try{
  const response=await getDocumentChangeScope(id);if(!valid())return;const full=response.data;
  if(full?.snapshot?.scope_id!==id||!await verifyDocumentChangeScope(full,{current:valid})||!valid()||!documentChangeMetadataMatches('scopes',full,metadata)||full.eligible!==true||full.inventory_current!==true||full.governance.status!=='published')throw new Error();
  const projected=await getDocumentChangePublicSource(id);if(!valid())return;
  if(!await verifyDocumentChangeSource(projected.data,{scope:full,current:valid})||!valid())throw new Error();
  record.value=full;publicSource.value=projected.data;
  emit('selection-change',{ready:true,references:{document_change_scope_id:id},scope:full,publicSource:projected.data});
 }catch{if(valid()){clearSelection();error.value='当前完整原文、关联、目标集合或审核状态无法核对，请重新选择';}}
 finally{if(valid())selecting.value=false;}
}
function changePage(delta){page.value+=delta;loadPage();}
watch([auth,()=>props.active],()=>{initialSeed=false;clear();if(allowed.value&&referencesValid.value)loadPage();},{flush:'sync'});
watch(()=>supportCanonical(props.initialReferences),()=>{
 const seed=initialSeed;initialSeed=false;clear();if(!allowed.value||!referencesValid.value||deactivated||!alive)return;
 loadPage();if(Object.keys(props.initialReferences).length&&(seed?initiallyAllowed&&auth()===initialAuth:true))choose(props.initialReferences.document_change_scope_id);
},{immediate:true,flush:'sync'});
onActivated(()=>{if(!activationSeen){activationSeen=true;return;}deactivated=false;clear();if(allowed.value&&referencesValid.value)loadPage();});
onDeactivated(()=>{deactivated=true;initialSeed=false;clear();});
onBeforeUnmount(()=>{alive=false;clear();});
</script>
<style scoped>
.document-change-input{display:grid;gap:12px}.actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.note,.chosen{line-height:1.6;overflow-wrap:anywhere}.chosen{padding:12px;background:var(--el-fill-color-light);border-radius:6px}
</style>
