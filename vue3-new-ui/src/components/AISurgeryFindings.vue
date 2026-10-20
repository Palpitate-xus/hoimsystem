<template>
  <section aria-label="完整手术排程候选核对">
    <p v-if="error" role="alert">{{ error }}</p><p v-if="checking" role="status">正在核对完整手术原件与结果绑定。</p>
    <template v-if="accepted">
      <p>病例与资源范围来自本次冻结声明。登记标签仅帮助定位原资源；岗位资格、时长估计与未核清资料另行保留。</p>
      <p>场景 {{ source.source_id }}；科室 #{{ scope.department_id }}。原截止 UTC {{ source.as_of }}，原捕获 UTC {{ source.captured_at }}。</p>
      <p>原业务时区 {{ source.period.business_timezone }}；{{ source.period.date_from }} 至 {{ source.period.date_to }}。全部 {{ scope.snapshot.request.cases.length }} 件病例声明、{{ scope.snapshot.request.resources.length }} 项物理资源及 {{ source.manifest.length }} 件来源。</p>
      <p>目标：{{ source.objective_mode==='all_required_then_min_declared_cost'?'满足全部必排声明后最小化明确惩罚':'先最大化可选病例排入数量，再最小化明确惩罚' }}。未声明临床优先级，不按问题或 Prompt 改写目标。</p>
      <el-button @click="emit('inspect',source.source_id)">核对本次完整场景证据</el-button>
      <template v-if="analysis">
        <el-alert :closable="false" :type="analysis.solve_status==='optimal_proven'?'success':'info'" :title="solveLabels[analysis.solve_status]" />
        <p>{{ analysis.scope_status==='closed_declared_problem'?'本次明确声明范围闭合':'本次明确声明范围仍有缺口' }}；时长、资格、全地点占用及政策仍按原声明解释。本结果不自动预约、锁定资源或写入排台。</p>
        <p>已知可行目标 {{ objective(analysis.feasible_incumbent_objective) }}；乐观界 {{ objective(analysis.optimistic_objective_bound) }}。可选病例数量间隙 {{ analysis.optional_count_gap??'不可报告' }}；数量界闭合时的惩罚间隙 {{ analysis.penalty_gap_when_count_bound_closed??'不可报告' }}。</p>
        <el-table :data="proofs" aria-label="手术排程两图搜索证明"><el-table-column prop="label" label="搜索图" /><el-table-column label="终止原因"><template #default="{row}">{{ terminationLabels[row.termination] }}</template></el-table-column><el-table-column prop="expanded_nodes" label="实际展开节点" /><el-table-column prop="primitive_operations" label="实际原子操作" /><el-table-column prop="frontier_nodes" label="保留前沿节点" /><el-table-column label="原搜索上限"><template #default="{row}">操作 {{ row.work_limits.operation_limit }}；节点 {{ row.work_limits.node_limit }}；前沿 {{ row.work_limits.frontier_limit }}</template></el-table-column></el-table>
        <template v-if="analysis.solution">
          <p>{{ analysis.solution.status==='feasible_under_declared_scope'?'候选通过本次声明约束核对':'候选仍有未知约束，不能当作可执行排台' }}。排入 {{ analysis.solution.scheduled_count }} 件，其中可选 {{ analysis.solution.optional_scheduled_count }} 件；精确惩罚 {{ analysis.solution.exact_penalty_points??'未知' }}，已知惩罚下界 {{ analysis.solution.penalty_lower_bound }}。</p>
          <p>时长条件：{{ durationLabels[analysis.solution.duration_condition] }}。阶段时长为原审核估计，不保证实际手术结束时刻。</p>
          <el-table :data="assignmentPage" aria-label="手术候选逐病例排程"><el-table-column label="原申请" min-width="240"><template #default="{row}">{{ caseLabel(row.case_id) }}</template></el-table-column><el-table-column prop="start_at" label="候选开始 UTC" min-width="235" /><el-table-column label="原手术室" min-width="200"><template #default="{row}">{{ resourceLabel(row.room_id) }}</template></el-table-column><el-table-column label="角色槽与自然人" min-width="280"><template #default="{row}"><p v-for="role in row.roles" :key="role.slot_id">{{ demandLabel(row.case_id,role.slot_id) }}：{{ resourceLabel(role.person_id) }}；原职责 {{ dutyLabel(role.duty_id) }}</p></template></el-table-column><el-table-column label="具体设备槽" min-width="240"><template #default="{row}"><p v-for="item in row.equipment" :key="item.slot_id">{{ demandLabel(row.case_id,item.slot_id) }}：{{ resourceLabel(item.equipment_id) }}</p></template></el-table-column></el-table>
          <el-pagination v-if="analysis.solution.assignments.length>20" v-model:current-page="assignmentIndex" :page-size="20" :total="analysis.solution.assignments.length" layout="prev,pager,next,total" />
          <p v-if="analysis.solution.deferred_case_ids.length">原声明中未排入的病例：{{ analysis.solution.deferred_case_ids.map(caseLabel).join('；') }}。</p>
          <p>完整核对：满足 {{ analysis.solution.check_summary.counts.satisfied }}；违反 {{ analysis.solution.check_summary.counts.violated }}；未知 {{ analysis.solution.check_summary.counts.unknown }}；明确不适用 {{ analysis.solution.check_summary.counts.not_applicable }}。各计数按原核对定义，不能相加解释为病例人数。</p>
        </template>
        <p v-else>本次没有可展示候选；保留完整输入缺口及实际搜索终止原因。</p>
        <el-table v-if="witnesses.length" :data="witnessPage" aria-label="手术已知违反与未知依据"><el-table-column label="类别"><template #default="{row}">{{ row.group }}</template></el-table-column><el-table-column prop="status" label="原核对状态" /><el-table-column prop="code" label="原核对代码" /><el-table-column label="涉及原申请"><template #default="{row}">{{ row.case_ids.map(caseLabel).join('；')||'全域或原资源' }}</template></el-table-column><el-table-column label="涉及原资源"><template #default="{row}">{{ row.resource_ids.map(resourceLabel).join('；')||'原范围' }}</template></el-table-column></el-table>
        <el-pagination v-if="witnesses.length>20" v-model:current-page="witnessIndex" :page-size="20" :total="witnesses.length" layout="prev,pager,next,total" />
      </template><p v-else>此处仅核对来源与声明；尚未显示固定优化计算结果。</p>
      <el-collapse><el-collapse-item title="查看完整冻结原件、公开投影与计算记录"><p>院内原件和身份映射包含当前获准核对的真实标识；独立计算服务只接收匿名公开投影。</p><el-button @click="showPrivate=!showPrivate">{{ showPrivate?'收起':'展开' }}完整院内原件</el-button><pre v-if="showPrivate" aria-label="完整院内手术场景">{{ JSON.stringify(scope.snapshot,null,2) }}</pre><el-button @click="showPublic=!showPublic">{{ showPublic?'收起':'展开' }}匿名公开投影</el-button><pre v-if="showPublic" aria-label="匿名手术公开投影">{{ JSON.stringify(source,null,2) }}</pre><el-button v-if="analysis" @click="showAnalysis=!showAnalysis">{{ showAnalysis?'收起':'展开' }}完整固定计算记录</el-button><pre v-if="showAnalysis&&analysis" aria-label="完整手术固定计算记录">{{ JSON.stringify(analysis,null,2) }}</pre></el-collapse-item></el-collapse>
    </template>
  </section>
</template>

<script setup>
import {computed,onActivated,onBeforeUnmount,onDeactivated,ref,shallowRef,watch} from 'vue';
import {useStore} from 'vuex';
import {verifySurgeryContext,verifySurgeryRun} from '@/api/ai/surgeryScenarios';
import {supportCanonical} from '@/api/inpatientSupport';
const props=defineProps({run:{type:Object,default:null},context:{type:Object,default:null},expectedDepartmentId:{type:Number,default:null},expectedPoolId:{type:String,default:null},references:{type:Object,default:null},active:{type:Boolean,default:true}}),emit=defineEmits(['inspect']),store=useStore();
const accepted=shallowRef(null),error=ref(''),checking=ref(false),assignmentIndex=ref(1),witnessIndex=ref(1),showPrivate=ref(false),showPublic=ref(false),showAnalysis=ref(false);
let epoch=0,alive=true,paused=false;
const roles=computed(()=>store.getters['user/permissions']||[]),allowed=computed(()=>props.active&&!!store.state.user.accessToken&&roles.value.some(role=>['admin','super_admin','director'].includes(role)));
const auth=()=>supportCanonical([props.active,props.expectedDepartmentId,props.expectedPoolId,props.references,store.state.user.accessToken,store.state.user.username,roles.value]);
const packet=computed(()=>accepted.value?.run?.surgery_findings||accepted.value?.context),source=computed(()=>packet.value?.surgery_source),scope=computed(()=>packet.value?.surgery_scenario),analysis=computed(()=>accepted.value?.run?.result?.surgery_analysis||null);
const resolution=computed(()=>scope.value?.local_resolution),caseMap=computed(()=>new Map((resolution.value?.cases||[]).map(item=>[item.case_token,item]))),resourceMap=computed(()=>new Map((resolution.value?.resources||[]).map(item=>[item.resource_token,item])));
const caseLabel=token=>caseMap.value.get(token)?.application_id||token,resourceLabel=token=>{const item=resourceMap.value.get(token);return item?item.label+' · '+item.resource_id:token;};
const demandLabel=(caseToken,token)=>resolution.value?.demands.find(item=>item.case_token===caseToken&&item.demand_token===token)?.original_slot_id||token;
const dutyLabel=token=>token===null?'未核清':resolution.value?.duties.find(item=>item.duty_token===token)?.source_record_id||token;
const objective=value=>value===null?'未取得':(value.optional_scheduled_count===null?'':'可选数量 '+value.optional_scheduled_count+'；')+'惩罚 '+value.penalty_points;
const solveLabels={optimal_proven:'在明确声明范围内已证最优',feasible_not_proven:'已有可行候选，尚未证最优',infeasible_proven:'在明确声明范围内已证不可行',feasibility_unknown:'可行性未知',input_unknown:'资料不足，不能给出完整排程结论'};
const terminationLabels={exhausted:'完整搜索已耗尽',bound_closed:'当前数学界已闭合',operation_limit:'达到原子操作预算',node_limit:'达到节点预算',frontier_limit:'达到前沿预算',input_unknown:'输入资料未知'};
const durationLabels={declared_upper_bounds:'明确阶段时长上界',declared_point_durations:'明确阶段时长点估计',mixed:'混合原估计条件',unknown:'原时长条件未知'};
const proofs=computed(()=>analysis.value?[{...analysis.value.definite_search,label:'确定约束图'},{...analysis.value.optimistic_search,label:'显式松弛乐观图'}]:[]),assignmentPage=computed(()=>analysis.value?.solution?.assignments.slice((assignmentIndex.value-1)*20,assignmentIndex.value*20)||[]);
const witnesses=computed(()=>analysis.value?[...analysis.value.input_issues.map(item=>({...item,group:'输入缺口'})),...(analysis.value.solution?.violations||[]).map(item=>({...item,group:'候选已知违反'})),...(analysis.value.solution?.unknowns||[]).map(item=>({...item,group:'候选未知'}))]:[]),witnessPage=computed(()=>witnesses.value.slice((witnessIndex.value-1)*20,witnessIndex.value*20));
function reset(){epoch++;accepted.value=null;checking.value=false;error.value='';assignmentIndex.value=witnessIndex.value=1;showPrivate.value=showPublic.value=showAnalysis.value=false;}
async function verify(){
  reset();const version=epoch,key=auth();if(!alive||paused||!allowed.value||!props.run&&!props.context)return;checking.value=true;
  try{
    if(!!props.run===!!props.context)throw new Error('必须分别核对一件完整任务或本次资料预览');
    const value=JSON.parse(JSON.stringify(props.run?{run:props.run}:{context:props.context})),expected={departmentId:props.expectedDepartmentId,poolId:props.expectedPoolId,references:props.references};
    const valid=value.run?await verifySurgeryRun(value.run,expected):await verifySurgeryContext(value.context,expected);
    if(!alive||paused||!allowed.value||version!==epoch||key!==auth())return;
    if(!valid)throw new Error('手术场景、身份映射或完整结果绑定无法核对，暂不展示旧资料');accepted.value=value;
  }catch(failure){if(alive&&!paused&&version===epoch&&key===auth())error.value=failure.message||'手术完整原件无法核对';}finally{if(version===epoch)checking.value=false;}
}
watch([()=>props.run,()=>props.context,auth],verify,{deep:true,immediate:true,flush:'sync'});
onDeactivated(()=>{paused=true;reset();});onActivated(()=>{if(paused){paused=false;verify();}});onBeforeUnmount(()=>{alive=false;reset();});
</script>

<style scoped>
p{line-height:1.7}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:550px;overflow:auto}.el-button{margin:6px 8px 6px 0}.el-alert,.el-table{margin:12px 0}
</style>
