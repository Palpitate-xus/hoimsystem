<template>
  <el-dialog :model-value="!!target&&allowed" title="本地物资数量预测服务核对" width="min(850px,95vw)" @update:model-value="value=>!value&&close()">
    <div v-loading="loading">
      <p>核对已保存服务 {{ target?.name }}。平台仅鉴权 GET 服务 /capabilities，不发送物资原件、处方或问题，不创建预测任务。</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <template v-if="result">
        <el-alert :type="result.compatible?'success':'warning'" :closable="false" :title="result.compatible?'服务声明与登记配置匹配，实际运营适用性及效果仍须验证':'已保存配置与服务实际声明存在差异'" />
        <p v-for="issue in result.issues" :key="issue">{{ issue }}</p>
        <el-descriptions :column="1" border><el-descriptions-item v-for="[label,value] in rows" :key="label" :label="label"><span class="hash">{{ value }}</span></el-descriptions-item></el-descriptions>
        <p v-if="noticeText(result.scope_note)">{{ noticeText(result.scope_note) }}</p><p>仅预测已记录数量，不输出潜在需求、采购量或缺货概率。能力核对不改变验证状态或启用配置。</p>
        <p>填写实际模型只回填编辑表单，仍须用户核对并保存当前版本。</p>
      </template>
    </div>
    <template #footer><el-button @click="close">关闭</el-button><el-button v-if="result&&target?.model!==result.capabilities.model_version" @click="editModel">填写实际模型，待保存</el-button></template>
  </el-dialog>
</template>

<script setup>
import { noticeText, noticeList } from "@/utils/noticeText.cjs";
import {computed,onBeforeUnmount,onDeactivated,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {checkSupplyProvider,verifySupplyProviderCheck} from '@/api/ai/supplyProvider';

const props=defineProps({target:{type:Object,default:null},providers:{type:Array,default:()=>[]}}),emit=defineEmits(['close','edit-model']),store=useStore();
const result=ref(null),loading=ref(false),error=ref('');let epoch=0,session=null,alive=true;
const roles=computed(()=>store.getters['user/permissions']||[]),allowed=computed(()=>!!store.state.user.accessToken&&roles.value.includes('super_admin'));
const rows=computed(()=>{const c=result.value?.capabilities;return c?[
 ['实际模型',c.model_version],['声明范围','单物资、明确库存范围及一个受审核单位；请求、毛实发和确认实耗三个目标独立。'],
 ['六种固定方法','Croston、SBA、TSB、全前缀均值、末28日均值和末周季节朴素；不自动选最优。'],
 ['原始边界','分别记录零值、未知、单位冲突和缺项。'],
 ['真实运行环境',`Python ${c.python_version}；${Object.entries(c.engine_versions).map(([k,v])=>k+' '+v).join('；')}`],
 ['四核心文件',Object.entries(c.core_sha256).map(([k,v])=>k+': '+v).join('；')],['时区库',c.timezone_database_digest],
 ['固定限制',`请求 ${c.max_request_bytes} 字节；响应 ${c.max_response_bytes} 字节；服务时限 ${c.timeout_seconds} 秒。`],
 ['原规则及输入政策',c.recipe_digest+'；'+c.input_policy_digest],['实际运行摘要',c.runtime_digest],
 ['验证',`运营 ${c.operational_validation}；临床 ${c.clinical_validation}。`],['Prompt','只作溯源，不改变原量、参数、预算或预测结果。'],
 ]:[];});
function current(){const row=props.providers.find(p=>p.provider_id===props.target?.provider_id);return alive&&allowed.value&&session===store.state.user.accessToken&&props.target?.session===session&&row&&row.revision===props.target.revision&&row.model===props.target.model&&row.kind==='specialist'&&row.supported_features?.includes('supply_forecast')?row:null;}
function close(){epoch++;result.value=null;loading.value=false;error.value='';session=null;emit('close');}
watch(()=>props.target,async target=>{
 const ticket=++epoch;result.value=null;loading.value=false;error.value='';session=target?.session;
 if(!target||!current())return;loading.value=true;
 try{
  const response=await checkSupplyProvider(target.provider_id,target.revision);
  if(ticket!==epoch||!current())return;
  if(!await verifySupplyProviderCheck(response.data,target))throw new Error('核对回执与当前已保存物资服务或完整能力声明不一致，请刷新重试');
  if(ticket===epoch&&current())result.value=response.data;
 }catch(failure){if(ticket===epoch&&current())error.value=failure?.message||'物资服务能力核对失败';}
 finally{if(ticket===epoch)loading.value=false;}
},{immediate:true,deep:true});
watch([()=>store.state.user.accessToken,()=>JSON.stringify(roles.value)],close,{flush:'sync'});
watch(()=>JSON.stringify(props.providers.map(p=>[p.provider_id,p.revision,p.model,p.kind,p.supported_features])),()=>{if(props.target&&!current())close();},{flush:'sync'});
function editModel(){const row=current(),checked=result.value;if(!row||!checked||checked.provider_id!==row.provider_id||checked.provider_revision!==row.revision||checked.configured_model!==row.model){close();return;}emit('edit-model',{provider_id:row.provider_id,revision:row.revision,configured_model:row.model,model:checked.capabilities.model_version,session});close();}
onDeactivated(close);onBeforeUnmount(()=>{alive=false;close();});
</script>

<style scoped>
p{line-height:1.7}.hash{overflow-wrap:anywhere}.el-descriptions{margin:12px 0}
</style>
