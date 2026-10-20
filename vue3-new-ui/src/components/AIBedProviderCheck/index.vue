<template>
  <el-dialog :model-value="!!target&&allowed" title="本地床位固定预测服务核对" width="min(850px,95vw)" @update:model-value="value=>!value&&close()">
    <div v-loading="loading"><p>核对已保存服务 {{ target?.name }}。平台仅鉴权 GET 服务 /capabilities，不发送病区原件或问题，不创建预测任务。</p><p v-if="error" role="alert">{{ error }}</p>
      <template v-if="result"><el-alert :type="result.compatible?'success':'warning'" :closable="false" :title="result.compatible?'服务声明与登记配置匹配，实际运营适用性及效果仍须验证':'已保存配置与服务实际声明存在差异'" /><p v-for="issue in result.issues" :key="issue">{{ issue }}</p>
        <el-descriptions :column="1" border><el-descriptions-item v-for="[label,value] in rows" :key="label" :label="label"><span class="hash">{{ value }}</span></el-descriptions-item></el-descriptions><p>{{ result.scope_note }}</p>
        <p>能力核对不改变验证状态或启用配置。填写实际模型仅回填编辑表单，仍须用户核对并保存当前版本。</p>
      </template>
    </div><template #footer><el-button @click="close">关闭</el-button><el-button v-if="result&&target?.model!==result.capabilities.model_version" @click="editModel">填写实际模型，待保存</el-button></template>
  </el-dialog>
</template>

<script setup>
import {computed,onBeforeUnmount,onDeactivated,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {checkBedProvider,verifyBedCapabilities} from '@/api/bedForecast';
const props=defineProps({target:{type:Object,default:null},providers:{type:Array,default:()=>[]}}),emit=defineEmits(['close','edit-model']),store=useStore(),result=ref(null),loading=ref(false),error=ref('');let epoch=0,session=null,alive=true;
const roles=computed(()=>store.getters['user/permissions']||[]),allowed=computed(()=>!!store.state.user.accessToken&&roles.value.includes('super_admin'));
const rows=computed(()=>{const c=result.value?.capabilities;return c?[
 ['实际模型',c.model_version],['服务范围','单一受审病区的物理占床与四类实际事件；未来容量为明确审核场景。'],['固定方法','四周同星期均值；保留七日季节朴素、七日及二十八日滚动均值三基线。'],['校准及回测','此前已观察残差校准；28个origin、196/392对与34/41个唯一目标日期分开，当前冻结资料回顾不构成历史可得性重放。'],['原量与容量','未知不补零；历史容量积分按实际日长与准备声明，未来日界按半开场景，不替代即时可收治名额。'],['真实运行环境',`Python ${c.python_version}；${Object.entries(c.engine_versions).map(([key,value])=>key+' '+value).join('；')}`],['四核心文件',Object.entries(c.core_sha256).map(([key,value])=>key+': '+value).join('；')],['时区库',c.timezone_database_digest],['固定限制',`请求 ${c.max_request_bytes} 字节；响应 ${c.max_response_bytes} 字节；服务时限 ${c.timeout_seconds} 秒。`],['原规则及输入政策',c.recipe_digest+'；'+c.input_policy_digest],['实际运行摘要',c.runtime_digest],['验证与保证',`运营 ${c.operational_validation}；临床 ${c.clinical_validation}；覆盖保证 ${c.coverage_guarantee}。`],['Prompt','只作溯源，不改变固定原量、方法、约束或结果。'],
 ]:[];});
function current(){const row=props.providers.find(p=>p.provider_id===props.target?.provider_id);return alive&&allowed.value&&session===store.state.user.accessToken&&props.target?.session===session&&row&&row.revision===props.target.revision&&row.model===props.target.model&&row.kind==='specialist'&&row.supported_features?.includes('bed_forecast')?row:null;}
function close(){epoch++;result.value=null;loading.value=false;error.value='';session=null;emit('close');}
watch(()=>props.target,async target=>{const ticket=++epoch;result.value=null;loading.value=false;error.value='';session=target?.session;if(!target||!current())return;loading.value=true;try{const response=await checkBedProvider(target.provider_id,target.revision),data=response.data;if(ticket!==epoch||!current())return;if(!data||Object.keys(data).sort().join(',')!=='capabilities,compatible,configured_model,issues,provider_id,provider_revision,scope_note'||data.provider_id!==target.provider_id||data.provider_revision!==target.revision||data.configured_model!==target.model||typeof data.compatible!=='boolean'||data.compatible&&(data.configured_model!==data.capabilities?.model_version||data.issues?.length!==0)||!Array.isArray(data.issues)||data.issues.length>32||data.issues.some(s=>typeof s!=='string'||s.length>4000)||typeof data.scope_note!=='string'||data.scope_note.length>8000||!await verifyBedCapabilities(data.capabilities))throw new Error('核对回执与当前已保存床位服务或完整能力声明不一致，请刷新重试');if(ticket===epoch&&current())result.value=data;}catch(f){if(ticket===epoch&&current())error.value=f?.message||'床位服务能力核对失败';}finally{if(ticket===epoch)loading.value=false;}},{immediate:true,deep:true});
watch([()=>store.state.user.accessToken,()=>JSON.stringify(roles.value)],close,{flush:'sync'});watch(()=>JSON.stringify(props.providers.map(p=>[p.provider_id,p.revision,p.model,p.kind,p.supported_features])),()=>{if(props.target&&!current())close();},{flush:'sync'});
function editModel(){const row=current(),checked=result.value;if(!row||!checked||checked.provider_id!==row.provider_id||checked.provider_revision!==row.revision||checked.configured_model!==row.model){close();return;}emit('edit-model',{provider_id:row.provider_id,revision:row.revision,configured_model:row.model,model:checked.capabilities.model_version,session});close();}
onDeactivated(close);onBeforeUnmount(()=>{alive=false;close();});
</script>

<style scoped>
p{line-height:1.7}.hash{overflow-wrap:anywhere}.el-descriptions{margin:12px 0}
</style>
