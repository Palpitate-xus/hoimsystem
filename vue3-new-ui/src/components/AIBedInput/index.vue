<template>
  <section aria-label="受审床位预测入口">
    <p v-if="!allowed">当前身份无法访问此床位预测范围。</p>
    <template v-else>
      <p>明确科室、病区、完整受审序列与预测期限。五种历史物理目标分别核对，未来容量场景独立；不把即时可收治名额或今日床位状态当作历史资料。</p>
      <el-form inline @submit.prevent="refresh">
        <el-form-item label="床位预测科室"><el-select  :model-value="department" @update:model-value="department=$event||null" aria-label="床位预测科室" clearable placeholder="明确授权科室"><el-option v-for="d in departments" :key="d.department_id" :value="d.department_id" :label="`${d.name||'原科室'} · #${d.department_id}`" /></el-select></el-form-item>
        <el-form-item label="床位预测病区"><el-select  :model-value="ward" @update:model-value="ward=$event||null" aria-label="床位预测病区" clearable :disabled="!department" placeholder="明确当前实际病区"><el-option v-for="w in options?.wards||[]" :key="w.ward_id" :value="w.ward_id" :label="`${w.name||'原病区'} · #${w.ward_id}`" /></el-select></el-form-item>
        <el-form-item label="床位预测期限"><el-select v-model="horizon" aria-label="床位预测期限" clearable placeholder="明确7或14天，不默认"><el-option :value="7" label="完整7个业务日" /><el-option :value="14" label="完整14个业务日" /></el-select></el-form-item>
        <el-button native-type="submit" :loading="loading">重新核对床位预测范围</el-button><el-button v-if="chosen" @click="invalidate">清除所选床位序列</el-button>
      </el-form>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="checking" role="status">正在核对完整原件、公开投影与当前治理。</p>
      <p v-if="chosen" aria-label="已绑定床位预测序列" class="hash">原序列 {{ chosen.source_id }}；原科室 #{{ chosen.department_id }} · 病区 #{{ chosen.ward_id }}。完整 {{ chosen.snapshot.request.days.length }} 天、{{ chosen.snapshot.facts.length }} 件来源；明确预测 {{ horizon }} 天。完整原件 {{ chosen.content_hash }}；公开投影 {{ chosen.projection_hash }}。</p>
      <bed-series v-if="scopeReady" :key="childKey" :department-id="department" :ward-id="ward" :active="active" @select="selectSeries" @series-changed="seriesChanged" @invalidate="seriesUnavailable" />
      <p v-else>先明确当前授权科室与实际病区，再核对受审序列。原引用只按本入口的序列和期限核验。</p>
    </template>
  </section>
</template>

<script setup>
import {computed,defineAsyncComponent,onActivated,onBeforeUnmount,onDeactivated,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {bedPositive,getBedSourceOptions} from '@/api/bedSources';
import {getBedSeriesDetail,verifyBedSeries} from '@/api/bedSeries';
import {supportCanonical,supportId} from '@/api/inpatientSupport';
const BedSeries=defineAsyncComponent(()=>import('../AIBedSeries/index.vue'));
const props=defineProps({departmentId:{type:Number,default:null},wardId:{type:Number,default:null},initialReferences:{type:Object,default:null},active:{type:Boolean,default:true}}),emit=defineEmits(['department-change','ward-change','selection','availability','invalidate']),store=useStore();
const roles=computed(()=>store.getters['user/permissions']||[]),allowed=computed(()=>props.active&&!!store.state.user.accessToken&&roles.value.some(r=>['admin','director','super_admin'].includes(r)));
const department=ref(props.departmentId),ward=ref(props.wardId),horizon=ref(null),departments=ref([]),options=ref(null),chosen=ref(null),error=ref(''),loading=ref(false),checking=ref(false),childKey=ref(0);
let epoch=0,catalogSeq=0,selectionSeq=0,alive=true,paused=false;
const horizonValid=v=>Number.isInteger(v)&&(v===7||v===14),referencesValid=v=>v!==null&&typeof v==='object'&&!Array.isArray(v)&&supportCanonical(Object.keys(v).sort())===supportCanonical(['bed_series_id','horizon_days'])&&supportId(v.bed_series_id)&&horizonValid(v.horizon_days);
const identity=()=>supportCanonical([props.departmentId,props.wardId,department.value,ward.value,props.active,props.initialReferences,store.state.user.accessToken,store.state.user.username,roles.value]),ticket=()=>({epoch,key:identity()}),current=t=>alive&&!paused&&allowed.value&&t.epoch===epoch&&t.key===identity();
const scopeReady=computed(()=>allowed.value&&bedPositive(department.value)&&bedPositive(ward.value)&&departments.value.some(d=>d.department_id===department.value)&&options.value?.department_id===department.value&&options.value.wards.some(w=>w.ward_id===ward.value&&w.department_id===department.value));
function invalidate(){selectionSeq++;checking.value=false;chosen.value=null;emit('selection',null);emit('availability',false);emit('invalidate');}
function reset(){epoch++;catalogSeq++;departments.value=[];options.value=null;loading.value=false;error.value='';childKey.value++;invalidate();}
function unavailable(message){invalidate();options.value=null;childKey.value++;error.value=message||'当前病区或受审集合无法核对，旧选择已清除。';}
function optionsValid(d){return d?.provider_required===false&&supportCanonical(d.source_kinds)===supportCanonical(['census','flow_day','capacity_interval']);}
async function refresh(){
  const t=ticket(),n=++catalogSeq;invalidate();options.value=null;departments.value=[];childKey.value++;if(!current(t))return;loading.value=true;error.value='';
  try{
    const d=(await getBedSourceOptions()).data;if(!current(t)||n!==catalogSeq)return;
    if(!optionsValid(d)||!Array.isArray(d.departments)||d.departments.length>2000||new Set(d.departments.map(x=>x.department_id)).size!==d.departments.length||d.departments.some(x=>!bedPositive(x.department_id)||x.name!==null&&typeof x.name!=='string'))throw new Error('当前授权科室目录无法核对');departments.value=d.departments;
    if(department.value!==null){
      if(!bedPositive(department.value)||!d.departments.some(x=>x.department_id===department.value))throw new Error('明确科室不在当前授权目录');
      const o=(await getBedSourceOptions({department_id:department.value})).data;if(!current(t)||n!==catalogSeq)return;
      if(!optionsValid(o)||o.department_id!==department.value||o.schema_version!=='bed_source_private_v1'||typeof o.can_record!=='boolean'||!Array.isArray(o.wards)||o.wards.length>200000||new Set(o.wards.map(x=>x.ward_id)).size!==o.wards.length||o.wards.some(x=>!bedPositive(x.ward_id)||x.department_id!==department.value||x.name!==null&&typeof x.name!=='string')||ward.value!==null&&!o.wards.some(x=>x.ward_id===ward.value))throw new Error('当前病区归属与明确科室无法核对');options.value=o;
    }
    if(props.initialReferences!==null){
      if(!referencesValid(props.initialReferences))throw new Error('原引用须明确本入口的规范序列标识与整数7或14天期限');
      const row=(await getBedSeriesDetail(props.initialReferences.bed_series_id)).data;if(!current(t)||n!==catalogSeq)return;
      if(row.series_id!==props.initialReferences.bed_series_id||row.audit_only!==roles.value.includes('super_admin')||!await verifyBedSeries(row)||!row.eligible||!row.public_source)throw new Error('原绑定序列已失效或完整原件与投影无法核对');if(!current(t)||n!==catalogSeq)return;
      if(department.value===null){if(!departments.value.some(d=>d.department_id===row.department_id))throw new Error('原绑定科室当前未授权');department.value=row.department_id;ward.value=row.ward_id;return;}
      if(row.department_id!==department.value||ward.value!==null&&row.ward_id!==ward.value)throw new Error('原绑定序列与明确科室病区不一致');
      if(ward.value===null){ward.value=row.ward_id;return;}
      if(scopeReady.value&&horizonValid(horizon.value))await selectSeries(row);
    }
  }catch(f){if(current(t)&&n===catalogSeq)unavailable(f.message);}finally{if(current(t)&&n===catalogSeq)loading.value=false;}
}
async function selectSeries(original){
  invalidate();const t=ticket(),n=selectionSeq,days=horizon.value;
  if(!current(t)||!scopeReady.value)return;if(!horizonValid(days)){error.value='请明确选择整数7或14天期限，再选择受审序列。';return;}
  checking.value=true;error.value='';
  try{
    if(original?.department_id!==department.value||original.ward_id!==ward.value||!original.eligible||!original.public_source||original.audit_only!==roles.value.includes('super_admin')||!await verifyBedSeries(original,department.value,ward.value))throw new Error('所选完整序列与当前科室病区或治理不一致');
    if(!current(t)||n!==selectionSeq||days!==horizon.value)return;
    const row=(await getBedSeriesDetail(original.series_id)).data;if(!current(t)||n!==selectionSeq||days!==horizon.value)return;
    if(row.audit_only!==roles.value.includes('super_admin')||!await verifyBedSeries(row,department.value,ward.value)||!row.eligible||!row.public_source||['series_id','content_hash','governance_hash','projection_hash','collection_digest'].some(k=>row[k]!==original[k]))throw new Error('当前原件、公开投影或治理已变化，请重新读取完整序列');
    if(current(t)&&n===selectionSeq&&days===horizon.value){chosen.value=row;emit('selection',{bed_series_id:row.series_id,horizon_days:days});emit('availability',true);}
  }catch(f){if(current(t)&&n===selectionSeq){invalidate();error.value=f.message||'当前序列核对失败，旧选择已清除。';}}finally{if(current(t)&&n===selectionSeq)checking.value=false;}
}
function seriesChanged(){invalidate();error.value='原来源或序列治理已变化，须重新核对完整集合后选择。';}
function seriesUnavailable(){invalidate();error.value='当前序列访问或完整集合无法重新核对，旧选择已清除。';}
watch(()=>props.departmentId,v=>{department.value=v;},{flush:'sync'});watch(()=>props.wardId,v=>{ward.value=v;},{flush:'sync'});
watch(department,v=>{ward.value=null;emit('department-change',v??null);},{flush:'sync'});watch(ward,v=>emit('ward-change',v??null),{flush:'sync'});
watch(()=>supportCanonical(props.initialReferences),()=>{horizon.value=referencesValid(props.initialReferences)?props.initialReferences.horizon_days:null;},{immediate:true,flush:'sync'});
watch(horizon,()=>{const original=chosen.value;invalidate();if(original&&horizonValid(horizon.value))selectSeries(original);},{flush:'sync'});
watch(identity,()=>{reset();refresh();},{immediate:true,flush:'sync'});
onDeactivated(()=>{paused=true;reset();});onActivated(()=>{if(paused){paused=false;reset();refresh();}});onBeforeUnmount(()=>{alive=false;reset();});
</script>

<style scoped>
p{line-height:1.7}.hash{overflow-wrap:anywhere}.el-select{min-width:230px}.el-button{margin:6px 8px 6px 0}
</style>
