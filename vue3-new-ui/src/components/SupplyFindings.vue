<template>
  <section v-if="allowed&&(checking||error||accepted)" aria-label="完整物资数量预测核对">
    <p v-if="checking">正在核对完整原件、单位、原任务绑定和精确回顾计算……</p>
    <el-alert v-else-if="error" type="error" :closable="false" :title="error" />
    <template v-else-if="accepted">
      <el-alert type="info" :closable="false" title="三种已记录数量分别预测；不自动选最优，不推断潜在需求或生成采购指令。" />
      <p>院内物资 {{ local.item_kind }} · {{ local.item_id }}；原计量单位 {{ local.original_unit_text }}；范围 hospital_inventory。</p>
      <p>历史 {{ source.date_from }} 至 {{ source.date_to }}，{{ source.days.length }} 个闭合业务日；预测 {{ packet.supply_binding.horizon_days }} 日。资料截止 {{ source.as_of }}；IANA 时区 {{ source.timezone }}。</p>
      <p>参数为明确审核分数：数量 α {{ exact(source.parameters.alpha_size) }}；间隔 α {{ exact(source.parameters.alpha_interval) }}；发生概率 β {{ exact(source.parameters.beta_occurrence) }}。Prompt仅作溯源。</p>
      <el-button @click="emit('inspect',source.source_id)">核对本次完整物资原量依据</el-button>
      <template v-if="analysis">
        <p>每种完整回测使用28个滚动原点，{{ analysis.planned_pair_count }} 个重叠原点—步长误差，涉及 {{ analysis.distinct_planned_target_dates }} 个不同目标日期，部分日期对应多个预测起点。</p>
        <el-tabs v-model="targetIndex" aria-label="三个独立已记录数量目标">
          <el-tab-pane v-for="(t,i) in analysis.targets" :key="t.target" :name="String(i)" :label="targetNames[t.target]">
            <p>{{ targetNames[t.target] }}：{{ t.status==='complete'?'完整原量':'资料未知，未生成该目标预测' }}；符合原目标的日原件 {{ t.eligible_day_count }}/{{ source.days.length }}。</p>
            <p>完整目标原量总和 {{ exact(t.observed_sum) }}；同审核单位的已知部分和 {{ exact(t.known_observed_sum) }}；末日原量 {{ raw(t.last_day_value) }}。</p>
            <p v-if="t.last_eligible_observation">最近符合目标的原量 {{ t.last_eligible_observation.date }}：{{ t.last_eligible_observation.value }}（{{ t.last_eligible_observation.source_id }}）。</p>
            <p>已选原件中，明确部分或全日供应约束标记 {{ t.stock_constrained_days }} 日，显式 unknown 供应约束标记 {{ t.stock_constraint_unknown_days }} 日。</p>
            <p v-if="t.target_gate_reasons.length">目标级缺项：{{ t.target_gate_reasons.join('；') }}。</p>
            <el-table v-if="t.missing_days.length" :data="t.missing_days.slice((missingPage-1)*20,missingPage*20)" aria-label="物资目标逐日缺项"><el-table-column prop="date" label="日期"/><el-table-column prop="source_id" label="原件引用"/><el-table-column label="缺项"><template #default="{row}">{{ row.reasons.join('；') }}</template></el-table-column></el-table>
            <el-pagination v-if="t.missing_days.length>20" v-model:current-page="missingPage" :page-size="20" :total="t.missing_days.length" layout="prev,pager,next,total" />
            <el-table :data="t.models" aria-label="六种固定物资预测方法">
              <el-table-column label="方法"><template #default="{row}">{{ modelNames[row.model] }}</template></el-table-column>
              <el-table-column label="原状态"><template #default="{row}">{{ statusNames[row.status] }}</template></el-table-column>
              <el-table-column label="预测期总量"><template #default="{row}">{{ exact(row.horizon_forecast_sum) }}</template></el-table-column>
              <el-table-column label="实际回顾原点"><template #default="{row}">{{ row.eligible_origin_count }}/28；{{ row.eligible_pair_count }} 对</template></el-table-column>
              <el-table-column label="相同比较域"><template #default="{row}">{{ row.directly_comparable?'28原点均可用，仍不自动排名':'原点不全，不直接与28原点成绩排名' }}</template></el-table-column>
              <el-table-column label="核对"><template #default="{row}"><el-button @click="modelKey=row.model">查看原点与误差 {{ modelNames[row.model] }}</el-button></template></el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
        <template v-if="selectedModel">
          <h4>{{ modelNames[selectedModel.model] }} · {{ targetNames[selectedTarget.target] }}</h4>
          <p v-if="selectedModel.prediction">未来原量表示 {{ selectedModel.prediction.representation==='constant_rate'?'固定原点的每日常数率':'重复末周7个已观测日值' }}：{{ selectedModel.prediction.values.map(exact).join('；') }}。预测日期 {{ selectedModel.forecast_dates.join('、') }}；不按库存截断。</p>
          <p v-else>没有该方法的数值预测；正值不足属于明确软件可用性门槛，不把未知正值大小补成零。</p>
          <p>总体日误差 MAE {{ exact(selectedModel.metrics?.mae) }}；MSE {{ exact(selectedModel.metrics?.mse) }}；ME（预测−实际）{{ exact(selectedModel.metrics?.me) }}；WAPE {{ exact(selectedModel.metrics?.wape) }}；MASE {{ exact(selectedModel.metrics?.mase) }}。</p>
          <p v-if="selectedModel.metrics">未定义原因：WAPE {{ selectedModel.metrics.wape_undefined_reason||'无' }}；MASE {{ selectedModel.metrics.mase_undefined_reason||'无' }}；保留零训练尺度误差 {{ selectedModel.metrics.zero_scale_count }} 对。</p>
          <p>累计整段误差 MAE {{ exact(selectedModel.cumulative_horizon_metrics?.mae) }}；MSE {{ exact(selectedModel.cumulative_horizon_metrics?.mse) }}；ME {{ exact(selectedModel.cumulative_horizon_metrics?.me) }}。累计误差不提供日级 MASE。</p>
          <el-table :data="selectedModel.by_lead" aria-label="物资逐预测步长误差"><el-table-column prop="lead_days" label="提前日数"/><el-table-column label="误差对数"><template #default="{row}">{{ row.metrics?.count??'未定义' }}</template></el-table-column><el-table-column label="MAE"><template #default="{row}">{{ exact(row.metrics?.mae) }}</template></el-table-column><el-table-column label="MSE"><template #default="{row}">{{ exact(row.metrics?.mse) }}</template></el-table-column><el-table-column label="ME"><template #default="{row}">{{ exact(row.metrics?.me) }}</template></el-table-column></el-table>
          <el-table :data="selectedModel.rolling_origins.slice((originPage-1)*10,originPage*10)" aria-label="物资28滚动原点评价"><el-table-column prop="origin_date" label="原点"/><el-table-column prop="training_days" label="前缀日数"/><el-table-column prop="status" label="原点状态"/><el-table-column label="原点尺度"><template #default="{row}">{{ exact(row.origin_scale) }}</template></el-table-column><el-table-column label="实际期总量"><template #default="{row}">{{ exact(row.horizon_actual_sum) }}</template></el-table-column><el-table-column label="预测期总量"><template #default="{row}">{{ exact(row.horizon_forecast_sum) }}</template></el-table-column><el-table-column label="累计误差"><template #default="{row}">{{ exact(row.horizon_error) }}</template></el-table-column></el-table>
          <el-pagination v-if="selectedModel.rolling_origins.length" v-model:current-page="originPage" :page-size="10" :total="selectedModel.rolling_origins.length" layout="prev,pager,next,total" />
        </template>
      </template>
      <p v-else>已核对本次完整来源；尚无成功计算结果，不显示预测量。</p>
      <el-collapse><el-collapse-item title="查看完整院内原件与公开计算证明"><p>院内原件仅在当前获准会话中展开；服务只接收公开量、受控标记与匿名标识。</p><el-button @click="showPrivate=!showPrivate">{{ showPrivate?'收起':'展开' }}完整院内原件</el-button><pre v-if="showPrivate" aria-label="完整院内物资原件">{{ JSON.stringify(packet.supply_series.snapshot,null,2) }}</pre><el-button @click="showPublic=!showPublic">{{ showPublic?'收起':'展开' }}公开物资原量</el-button><pre v-if="showPublic" aria-label="公开物资原量">{{ JSON.stringify(source,null,2) }}</pre><el-button v-if="analysis" @click="showProof=!showProof">{{ showProof?'收起':'展开' }}完整精确计算</el-button><pre v-if="showProof&&analysis" aria-label="完整物资计算证明">{{ JSON.stringify(analysis,null,2) }}</pre></el-collapse-item></el-collapse>
    </template>
  </section>
</template>
<script setup>
import {computed,onActivated,onBeforeUnmount,onDeactivated,ref,shallowRef,watch} from 'vue';
import {useStore} from 'vuex';
import {verifySupplyContext,verifySupplyRun,verifySupplyReceipt,supplyExactText,supplyAnalysisVersionSupported} from '@/api/ai/supplyResults';
import {supportCanonical} from '@/api/inpatientSupport';
const emit=defineEmits(['inspect']);
const props=defineProps({run:{type:Object,default:null},context:{type:Object,default:null},receipt:{type:Object,default:null},expectedItemKind:{type:String,default:null},expectedItemId:{type:Number,default:null},expectedSeriesId:{type:String,default:null},horizonDays:{type:Number,default:null},references:{type:Object,default:null},active:{type:Boolean,default:true},auditOnly:{type:Boolean,default:false}}),store=useStore(),accepted=shallowRef(null),checking=ref(false),error=ref(''),targetIndex=ref('0'),modelKey=ref('croston'),originPage=ref(1),missingPage=ref(1),showPrivate=ref(false),showPublic=ref(false),showProof=ref(false);let version=0,alive=true,paused=false;const blocked=new WeakSet();
const roles=computed(()=>Array.isArray(store.getters['user/permissions'])?store.getters['user/permissions']:[]),allowed=computed(()=>props.active&&!!store.state.user.accessToken&&roles.value.some(r=>['admin','director','pharmacist','super_admin'].includes(r))),auth=()=>supportCanonical([props.active,props.auditOnly,props.expectedItemKind,props.expectedItemId,props.expectedSeriesId,props.horizonDays,props.references,store.state.user.accessToken,store.state.user.username,roles.value]),packet=computed(()=>accepted.value?.run?.supply_findings||accepted.value?.run?.frozen_request?.payload?.context||accepted.value?.context),source=computed(()=>packet.value?.supply_source),analysis=computed(()=>accepted.value?.run?.result?.supply_analysis||null),local=computed(()=>{const s=packet.value?.supply_series.snapshot;return s?{item_kind:s.item_kind,item_id:s.item_id,original_unit_text:s.collection.unit_definitions.find(r=>r.source.source_record_id===s.request.unit_definition_id)?.source.payload.original_unit_text}:{};}),selectedTarget=computed(()=>analysis.value?.targets[Number(targetIndex.value)]),selectedModel=computed(()=>selectedTarget.value?.models.find(m=>m.model===modelKey.value)),exact=supplyExactText,raw=v=>v===null||v===undefined?'未知（null）':v;
const targetNames={recorded_request_quantity:'已记录请求量',gross_fulfilled_issue_quantity:'实际毛发出量',confirmed_consumed_quantity:'确认实耗量'},modelNames={croston:'Croston',sba:'SBA',tsb:'TSB',prefix_mean:'全前缀均值',last28_mean:'末28日均值',seasonal_naive7:'末周季节朴素'},statusNames={complete:'完整',partial_backtest:'回顾原点不全',insufficient_positive_observations:'正值观测不足',input_unknown:'资料未知'};
function invalidate(){for(const value of [props.run,props.context])if(value&&typeof value==='object')blocked.add(value);reset();}
function reset(){version++;accepted.value=null;checking.value=false;error.value='';targetIndex.value='0';modelKey.value='croston';originPage.value=missingPage.value=1;showPrivate.value=showPublic.value=showProof.value=false;}
async function verify(){reset();const ticket=version,key=auth(),current=()=>alive&&!paused&&allowed.value&&ticket===version&&key===auth();if(!current()||!props.run&&!props.context)return;if(blocked.has(props.run||props.context)){error.value='会话或页面已变化，请重新读取完整受审物资序列和任务';return;}checking.value=true;try{if(!!props.run===!!props.context)throw new Error('须分别核对一件完整任务或资料预览');const value=JSON.parse(JSON.stringify(props.run?{run:props.run}:{context:props.context})),expected={itemKind:props.expectedItemKind,itemId:props.expectedItemId,seriesId:props.expectedSeriesId,horizonDays:props.horizonDays,references:props.references},options={current,auditOnly:props.auditOnly&&roles.value.includes('super_admin')};if(props.receipt&&(!value.run||!verifySupplyReceipt(props.receipt,value.run)))throw new Error('任务回执与完整结果标识或上下文不同');if(value.run?.result?.supply_analysis&&!supplyAnalysisVersionSupported(value.run.result.supply_analysis))throw new Error('原运行版本当前无法重算，不能将旧原数作为当前版本预测展示；超级管理员可保留原冻结件作技术审计');const valid=value.run?await verifySupplyRun(value.run,expected,options):await verifySupplyContext(value.context,expected,options);if(!current())return;if(!valid)throw new Error('物资完整原件、单位、原任务或精确计算绑定无法核对，暂不展示');accepted.value=value;}catch(failure){if(current())error.value=failure.message||'完整物资证明无法核对';}finally{if(ticket===version)checking.value=false;}}
watch(()=>supportCanonical([store.state.user.accessToken,store.state.user.username,roles.value]),invalidate,{flush:'sync'});watch(()=>props.active,v=>{if(!v)invalidate();},{flush:'sync'});
watch([()=>props.run,()=>props.context,()=>props.receipt,auth],verify,{deep:true,immediate:true,flush:'sync'});watch([targetIndex,modelKey],()=>{originPage.value=missingPage.value=1;});onDeactivated(()=>{paused=true;invalidate();});onActivated(()=>{if(paused){paused=false;verify();}});onBeforeUnmount(()=>{alive=false;reset();});
</script>
<style scoped>
p{line-height:1.7}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:500px;overflow:auto}.el-button{margin:6px 8px 6px 0}.el-table,.el-alert{margin:12px 0}
</style>
