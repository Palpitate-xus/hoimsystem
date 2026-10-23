<template>
  <div v-if="allowed" class="task-technical-directory">
    <p>此处查看全院任务技术状态；来源与执行溯源在“任务与反馈”按原权限核验。未核验的用量不会计为零。</p>
    <form class="page-toolbar" @submit.prevent="load(true)">
      <el-select v-model="filters.feature_key" clearable filterable placeholder="全部功能" aria-label="技术目录功能" style="width:220px"><el-option v-for="feature in features" :key="feature.key" :label="feature.name" :value="feature.key" /></el-select>
      <el-select v-model="filters.status" clearable placeholder="全部状态" aria-label="技术目录状态" style="width:130px"><el-option v-for="(label,value) in states" :key="value" :label="label" :value="value" /></el-select>
      <el-input-number v-model="filters.requested_by" :min="1" :max="2147483647" :precision="0" :controls="false" placeholder="申请人ID" aria-label="技术目录申请人ID" />
      <el-button type="primary" native-type="submit">查询技术任务</el-button><el-button @click="load()">刷新技术任务</el-button>
    </form>
    <el-table v-loading="loading" :data="rows" empty-text="暂无技术任务">
      <el-table-column v-for="column in columns" :key="column[0]" :label="column[1]" :min-width="column[2]" show-overflow-tooltip><template #default="{row}">{{ cell(row,column[0]) }}</template></el-table-column>
      <el-table-column label="操作" width="125"><template #default="{row}"><el-button size="small" @click="selected=row">技术详情</el-button></template></el-table-column>
    </el-table>
    <el-pagination :current-page="page" :page-size="30" :total="total" layout="total, prev, pager, next" class="pagination-wrapper" @current-change="changePage" />
    <el-dialog :model-value="selected!==null" title="任务技术信息" width="760px" destroy-on-close @close="selected=null"><pre v-if="selected">{{ JSON.stringify(selected,null,2) }}</pre><p>技术归属记录不授予来源正文或模型执行权限；用量尚未核验。</p></el-dialog>
  </div>
</template>

<script setup>
import {computed,onActivated,onBeforeUnmount,onDeactivated,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {ElMessage} from 'element-plus';
import {readTechnicalTasks} from '@/api/ai/taskDirectory';
const props=defineProps({features:{type:Array,default:()=>[]},active:{type:Boolean,default:false}});
const store=useStore(),deactivated=ref(false),roles=computed(()=>store.getters['user/permissions']||store.state.user.permissions);
const allowed=computed(()=>props.active&&!deactivated.value&&typeof store.state.user.accessToken==='string'&&store.state.user.accessToken.trim().length>0&&typeof store.state.user.username==='string'&&store.state.user.username.trim().length>0&&Array.isArray(roles.value)&&roles.value.every(role=>typeof role==='string')&&roles.value.includes('super_admin'));
const identity=computed(()=>allowed.value?JSON.stringify([store.state.user.accessToken,store.state.user.username,roles.value]):'');
const filters=ref({feature_key:'',status:'',requested_by:undefined}),rows=ref([]),total=ref(0),page=ref(1),loading=ref(false),selected=ref(null);
const states={queued:'排队中',running:'执行中',succeeded:'已完成',failed:'失败',cancelled:'已取消'},identities={unique:'唯一原生锚点',unproven:'旧记录或缺少证明',conflicting:'原生锚点冲突',invalid:'原生归属异常'};
const columns=[['run_id','任务ID',230],['feature','功能',180],['native_identity_state','技术归属',150],['status','状态',100],['requested_by','申请人ID',110],['provider_id','模型ID',95],['feedback_count','反馈数',90],['create_time','创建时间',180]];
let alive=true,version=0;
function clear(){rows.value=[];total.value=0;selected.value=null;loading.value=false;}
function cell(row,key){if(key==='feature')return (props.features.find(feature=>feature.key===(row.native_feature_key||row.feature_key))?.name||row.native_feature_key||row.feature_name||'未登记功能')+(row.feature_matches_native_contract===false?'（功能标记不一致）':'');if(key==='native_identity_state')return identities[row[key]];if(key==='status')return states[row[key]]||'状态异常';return row[key]??'未记录';}
function changePage(value){if(value!==page.value){page.value=value;load();}}
async function load(reset=false){
 const requestVersion=++version,key=identity.value;if(!alive||!allowed.value){clear();return;}rows.value=[];selected.value=null;if(reset)page.value=1;
 const current=()=>alive&&allowed.value&&identity.value===key&&version===requestVersion;
 const params={page:page.value,page_size:30};for(const name of ['feature_key','status','requested_by'])if(filters.value[name]!==''&&filters.value[name]!==null&&filters.value[name]!==undefined)params[name]=filters.value[name];
 loading.value=true;
 try{const response=await readTechnicalTasks(params,{current});if(current()&&response){rows.value=response.data;total.value=response.total;}}
 catch{if(current()){clear();ElMessage.warning('当前技术目录无法核验，旧记录已清除');}}
 finally{if(current())loading.value=false;}
}
watch(identity,()=>{version++;clear();if(allowed.value)load(true);},{immediate:true,flush:'sync'});
onDeactivated(()=>{deactivated.value=true;version++;clear();});onActivated(()=>{deactivated.value=false;});onBeforeUnmount(()=>{alive=false;version++;clear();});
</script>
