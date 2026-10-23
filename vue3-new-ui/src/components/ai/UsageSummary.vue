<template>
 <section v-if="allowed" aria-label="AI调用统计">
  <p>按任务绑定的具体用量审计记录核对身份、租约与计数；来源正文和结果内容由原业务权限另行核验。历史未核验记录保留为未知。</p>
  <el-button :loading="loading" @click="load">刷新调用统计</el-button>
  <p v-if="summary">本次完整覆盖 {{ summary.coverage.scanned }} 项任务；输入和输出用量分别计数。</p>
  <p v-if="error" role="alert">{{ error }}</p>
  <el-table :data="summary?.data||[]" empty-text="暂无已核对统计">
   <el-table-column v-for="column in columns" :key="column[0]" :label="column[1]" :min-width="column[2]"><template #default="{row}">{{ cell(row,column[0]) }}</template></el-table-column>
  </el-table>
  <p>本地计算的外部模型Token与计算耗时分别记录；未知耗时不计入已知毫秒合计。</p>
 </section>
</template>

<script setup>
import {computed,onActivated,onBeforeUnmount,onDeactivated,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {readUsageSummary,usageCountLabel} from '@/api/ai/usageSummary';
const props=defineProps({features:{type:Array,default:()=>[]},active:{type:Boolean,default:false}}),store=useStore(),deactivated=ref(false);
const roles=computed(()=>store.getters['user/permissions']||store.state.user.permissions),allowed=computed(()=>props.active&&!deactivated.value&&typeof store.state.user.accessToken==='string'&&!!store.state.user.accessToken.trim()&&typeof store.state.user.username==='string'&&!!store.state.user.username.trim()&&Array.isArray(roles.value)&&roles.value.every(role=>typeof role==='string')&&roles.value.includes('super_admin'));
const identity=computed(()=>allowed.value?JSON.stringify([store.state.user.accessToken,store.state.user.username,roles.value]):''),summary=ref(null),loading=ref(false),error=ref('');
const states={queued:'排队中',running:'执行中',succeeded:'已完成',failed:'失败',cancelled:'已取消',invalid:'状态异常'},columns=[['feature','功能',180],['status','状态',90],['count','任务数',80],['receipts','回执状态',230],['input_tokens','输入Token',180],['output_tokens','输出Token',180],['attempts','外部模型调用',230],['local','本地计算',250]];
let alive=true,version=0;
function clear(){summary.value=null;loading.value=false;error.value='';}
function cell(row,key){if(key==='feature')return props.features.find(feature=>feature.key===row.feature_key)?.name||row.feature_key||'未登记或归属冲突';if(key==='status')return states[row.status];if(key==='receipts')return `记录${row.recorded_count} / 待结算${row.pending_count} / 异常${row.invalid_count} / 未核验${row.unverified_count}`;if(key==='attempts')return `已调用${row.model_call_attempted_count} / 未调用${row.model_call_unattempted_count} / 未知${row.model_call_unknown_count}`;if(key==='local')return row.local_calculation_count?`已计算${row.local_calculation_attempted_count} / 未计算${row.local_calculation_unattempted_count} / 未知${row.local_calculation_unknown_count}；已知${row.local_calculation_ms_known_count}项共${row.local_calculation_ms_known_sum}毫秒`:'无本地计算任务';return ['input_tokens','output_tokens'].includes(key)?usageCountLabel(row,key):row[key];}
async function load(){const requestVersion=++version,key=identity.value;clear();if(!alive||!allowed.value)return;const current=()=>alive&&allowed.value&&identity.value===key&&version===requestVersion;loading.value=true;try{const value=await readUsageSummary({current});if(current()&&value)summary.value=value;}catch{if(current()){clear();error.value='当前调用统计无法核验，旧统计已清除';}}finally{if(current())loading.value=false;}}
watch(identity,()=>{version++;clear();if(allowed.value)load();},{immediate:true,flush:'sync'});
onDeactivated(()=>{deactivated.value=true;version++;clear();});onActivated(()=>{deactivated.value=false;});onBeforeUnmount(()=>{alive=false;version++;clear();});
</script>
