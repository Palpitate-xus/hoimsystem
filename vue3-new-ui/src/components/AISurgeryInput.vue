<template>
  <section aria-label="受审手术排程入口">
    <p v-if="!allowed">当前身份或会话不能读取手术排程场景。</p>
    <template v-else>
      <p>明确实际资源池并选择一件当前已发布的完整场景。病例队列、阶段时长、有限开始时刻和目标均来自原审核声明。</p>
      <el-form inline @submit.prevent="refresh">
        <el-form-item label="明确手术排程资源池"><el-select v-model="pool" clearable aria-label="明确手术排程资源池" placeholder="明确选择，不默认首项"><el-option v-for="item in pools" :key="item.pool_id" :value="item.pool_id" :label="item.name+' · 科室 #'+item.department_id" /></el-select></el-form-item>
        <el-button native-type="submit" :loading="loading">重新核对手术排程范围</el-button><el-button v-if="chosen" @click="invalidate">清除所选手术场景</el-button>
      </el-form>
      <p v-if="error" role="alert">{{ error }}</p><p v-if="checking" role="status">正在重新核对完整场景、当前来源与治理。</p>
      <p v-if="chosen" aria-label="已绑定手术排程场景" class="hash">原场景 {{ chosen.source_id }}；科室 #{{ chosen.department_id }}。完整 {{ chosen.snapshot.request.cases.length }} 件病例声明、{{ chosen.snapshot.request.resources.length }} 项资源；原件 {{ chosen.content_hash }}。</p>
      <SurgeryScenarios v-if="scopeReady" :key="childKey" :pool-id="pool" :application-ids="applicationIds" :active="active" @select="selectScenario" @scenario-changed="changed" @invalidate="unavailable" />
      <p v-else>先核对当前授权资源池，再读取完整场景。专业病例原件从实际申请入口登记。</p>
    </template>
  </section>
</template>

<script setup>
import {computed,defineAsyncComponent,onActivated,onBeforeUnmount,onDeactivated,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {getSurgerySourceOptions,surgeryPositive,surgerySourceKinds} from '@/api/ai/surgerySources';
import {getSurgeryScenario,surgeryReferencesValid,verifySurgeryScenario} from '@/api/ai/surgeryScenarios';
import {supportCanonical,supportHash,supportId} from '@/api/inpatientSupport';

const SurgeryScenarios=defineAsyncComponent(()=>import('./AISurgeryScenarios.vue'));
const props=defineProps({departmentId:{type:Number,default:null},poolId:{type:String,default:null},applicationIds:{type:Array,default:null},initialReferences:{type:Object,default:null},active:{type:Boolean,default:true}});
const emit=defineEmits(['department-change','pool-change','selection','availability','invalidate']),store=useStore();
const roles=computed(()=>store.getters['user/permissions']||[]),allowed=computed(()=>props.active&&!!store.state.user.accessToken&&roles.value.some(role=>['super_admin','admin','director'].includes(role)));
const pool=ref(props.poolId),pools=ref([]),chosen=ref(null),error=ref(''),loading=ref(false),checking=ref(false),childKey=ref(0);
let epoch=0,catalogSeq=0,selectionSeq=0,alive=true,paused=false;
const identity=()=>supportCanonical([props.departmentId,props.poolId,props.applicationIds,props.initialReferences,props.active,pool.value,store.state.user.accessToken,store.state.user.username,roles.value]);
const ticket=()=>({epoch,key:identity()}),current=t=>alive&&!paused&&allowed.value&&t.epoch===epoch&&t.key===identity();
const scopeReady=computed(()=>allowed.value&&supportId(pool.value)&&pools.value.some(item=>item.pool_id===pool.value&&(props.departmentId===null||item.department_id===props.departmentId)));
function invalidate(){selectionSeq++;chosen.value=null;checking.value=false;emit('selection',null);emit('availability',false);emit('invalidate');}
function reset(){epoch++;catalogSeq++;pools.value=[];loading.value=false;error.value='';childKey.value++;invalidate();}
function unavailable(message){invalidate();error.value=typeof message==='string'?message:'当前场景或来源无法核对，旧选择已清除。';}
function optionsValid(value){return value?.provider_required===false&&value.can_record_operational===true&&supportCanonical([...value.source_kinds||[]].sort())===supportCanonical(Object.keys(surgerySourceKinds).sort())&&Array.isArray(value.pools)&&value.pools.length<=2000&&new Set(value.pools.map(item=>item.pool_id)).size===value.pools.length&&value.pools.every(item=>supportId(item.pool_id)&&surgeryPositive(item.department_id)&&typeof item.name==='string'&&Array.from(item.name).length<=80&&supportHash(item.content_hash)&&supportHash(item.governance_hash));}
async function refresh(){
  invalidate();pools.value=[];childKey.value++;const t=ticket(),seq=++catalogSeq;if(!current(t))return;loading.value=true;error.value='';
  try{
    const value=(await getSurgerySourceOptions()).data;if(!current(t)||seq!==catalogSeq)return;
    if(!optionsValid(value))throw new Error('当前实际资源池目录或运营权限无法核对');pools.value=value.pools.filter(item=>props.departmentId===null||item.department_id===props.departmentId);
    if(pool.value!==null&&!pools.value.some(item=>item.pool_id===pool.value))throw new Error('明确资源池不属于当前授权科室范围');
    if(props.initialReferences!==null){
      if(!surgeryReferencesValid(props.initialReferences))throw new Error('原引用必须是一件明确的规范手术场景标识');
      const row=(await getSurgeryScenario(props.initialReferences.surgery_scenario_id,{audit_only:false})).data;if(!current(t)||seq!==catalogSeq)return;
      if(!await verifySurgeryScenario(row,{departmentId:props.departmentId,auditOnly:false})||!row.eligible||row.scenario_id!==props.initialReferences.surgery_scenario_id||!pools.value.some(item=>item.pool_id===row.pool_id))throw new Error('原场景当前已失效或完整来源无法核对');
      if(!current(t)||seq!==catalogSeq)return;
      if(pool.value===null){pool.value=row.pool_id;return;}
      if(pool.value!==row.pool_id)throw new Error('原场景不属于明确选择的资源池');
      await selectScenario(row);
    }
  }catch(failure){if(current(t)&&seq===catalogSeq){pools.value=[];unavailable(failure.message);}}finally{if(current(t)&&seq===catalogSeq)loading.value=false;}
}
function cohortMatches(row){return props.applicationIds===null||Array.isArray(props.applicationIds)&&props.applicationIds.length>0&&Array.isArray(row?.snapshot?.request?.cases)&&supportCanonical(row.snapshot.request.cases.map(item=>item.application_id).sort())===supportCanonical([...props.applicationIds].sort());}
async function selectScenario(original){
  invalidate();const t=ticket(),seq=selectionSeq;if(!current(t)||!scopeReady.value)return;checking.value=true;error.value='';
  try{
    const expected={poolId:pool.value,departmentId:props.departmentId,auditOnly:false};
    if(!await verifySurgeryScenario(original,expected)||!cohortMatches(original)||!original.eligible||!original.public_source)throw new Error('请选择当前已发布且完整来源一致的场景');
    if(!current(t)||seq!==selectionSeq)return;
    const row=(await getSurgeryScenario(original.scenario_id,{audit_only:false})).data;if(!current(t)||seq!==selectionSeq)return;
    if(!await verifySurgeryScenario(row,expected)||!cohortMatches(row)||!row.eligible||!row.public_source||['scenario_id','pool_id','department_id','content_hash','governance_hash','projection_hash','collection_digest'].some(key=>row[key]!==original[key]))throw new Error('原件或当前治理已经变化，请重新读取完整场景');
    if(current(t)&&seq===selectionSeq){chosen.value=row;emit('selection',{surgery_scenario_id:row.scenario_id});emit('availability',true);}
  }catch(failure){if(current(t)&&seq===selectionSeq)unavailable(failure.message);}finally{if(current(t)&&seq===selectionSeq)checking.value=false;}
}
function changed(){invalidate();error.value='场景或原来源已经变化，须重新核对后选择。';}
watch(()=>props.poolId,value=>{pool.value=value;},{flush:'sync'});
watch(pool,value=>{const selected=pools.value.find(item=>item.pool_id===value);emit('pool-change',value??null);if(selected)emit('department-change',selected.department_id);else if(!value)emit('department-change',null);},{flush:'sync'});
watch(identity,()=>{reset();refresh();},{immediate:true,flush:'sync'});
onDeactivated(()=>{paused=true;reset();});onActivated(()=>{if(paused){paused=false;reset();refresh();}});onBeforeUnmount(()=>{alive=false;reset();});
</script>

<style scoped>
p{line-height:1.7}.hash{overflow-wrap:anywhere}.el-select{min-width:260px}.el-button{margin:6px 8px 6px 0}
</style>
