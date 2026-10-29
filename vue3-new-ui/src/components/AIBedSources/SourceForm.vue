<template>
  <el-form label-position="top" :disabled="disabled" @submit.prevent>
    <p>以下填写原件声明。数量、覆盖和确认状态都须明确选择；保存草稿或超级管理员发布不会把未知变成已核实。</p>
    <template v-if="kind!=='capacity_interval'">
      <el-form-item label="原业务日期"><el-input v-model="draft.business_date" aria-label="原业务日期" placeholder="YYYY-MM-DD，原已闭合业务日" /></el-form-item>
      <el-form-item label="原业务IANA时区"><el-input v-model="draft.business_timezone" aria-label="原业务IANA时区" placeholder="明确原时区，例如 Asia/Shanghai" /></el-form-item>
      <el-form-item label="原采集方法"><el-select v-model="draft.method" aria-label="原采集方法" placeholder="明确原方法，不由当前床位状态补历史"><el-option label="原直接盘点（direct_tally）" value="direct_tally" /><el-option label="原外部登记（external_register）" value="external_register" /></el-select></el-form-item>
      <el-form-item label="原外部登记键状态"><el-select v-model="draft.external_state" aria-label="原外部登记键状态" placeholder="明确原登记键或其缺项"><el-option label="明确存在原登记键" value="known" /><el-option label="原登记键未知" value="unknown" /><el-option label="明确无适用外部登记键" value="not_applicable" /></el-select></el-form-item>
      <el-form-item v-if="draft.external_state==='known'" label="院内原外部登记键"><el-input v-model="draft.external_record_key" aria-label="院内原外部登记键" placeholder="原文仅院内核对，不发送预测服务" /></el-form-item>
    </template>
    <template v-if="kind==='census'">
      <p>固定口径：原业务日次日当地零点的物理占床状态。服务端按明确IANA时区核对真实日界；原盘点完成钟点另存，不强迫两钟相等。</p>
      <el-form-item label="原占床状态日界UTC"><el-input v-model="draft.census_at" aria-label="原占床状态日界UTC" :placeholder="clockHint" /></el-form-item>
      <el-form-item label="原盘点实际观察完成UTC"><el-input v-model="draft.observed_at" aria-label="原盘点实际观察完成UTC" :placeholder="clockHint" /></el-form-item>
      <el-form-item label="原日界状态确认"><el-select v-model="draft.boundary_state_confirmed" aria-label="原日界状态确认" placeholder="明确原协议与依据支持的状态"><el-option v-for="(label,key) in reviews" :key="key" :label="label" :value="key" /></el-select></el-form-item>
      <count-field v-model="counts.occupied_beds" label="原物理占床数" :disabled="disabled" />
    </template>
    <template v-else-if="kind==='flow_day'">
      <p>固定口径：同一原病区的物理日事件，使用半开日窗口。四种原计数分别保留；不从今日入院记录推算，不强迫与日界占床数守恒。</p>
      <el-form-item v-for="[key,label] in [['day_start_at','原物理事件日开始UTC'],['day_end_at','原物理事件日结束UTC'],['observed_at','原物理事件实际核对完成UTC']]" :key="key" :label="label"><el-input v-model="draft[key]" :aria-label="label" :placeholder="clockHint" /></el-form-item>
      <count-field v-for="[key,label] in flowCounts" :key="key" v-model="counts[key]" :label="label" unit="次" :disabled="disabled" />
      <el-form-item label="原物理日事件定义依据"><el-input v-model="draft.event_definition_basis_note" aria-label="原物理日事件定义依据" type="textarea" :rows="3" placeholder="至少20个非空白字符；明确原登记的纳入、排除、转入转出及其他离开原因；同病区换床不自动作为转病区事件" /></el-form-item>
    </template>
    <template v-else-if="kind==='capacity_interval'">
      <el-form-item label="原容量依据类型"><el-select v-model="draft.basis_kind" aria-label="原容量依据类型" placeholder="明确已观察原区间或独立未来场景"><el-option label="已观察的原可运营容量区间" value="observed_operational_capacity" /><el-option label="明确待审核的未来容量场景" value="reviewed_future_scenario" /></el-select></el-form-item>
      <el-form-item v-for="[key,label] in [['start_at','原容量区间开始UTC'],['end_at','原容量区间结束UTC']]" :key="key" :label="label"><el-input v-model="draft[key]" :aria-label="label" :placeholder="clockHint" /></el-form-item>
      <el-form-item v-if="draft.basis_kind==='observed_operational_capacity'" label="原容量实际观察完成UTC"><el-input v-model="draft.observed_at" aria-label="原容量实际观察完成UTC" :placeholder="clockHint" /></el-form-item>
      <p v-if="draft.basis_kind==='reviewed_future_scenario'">未来容量采用情景值，请填写准备条件；观察时间留空。</p>
      <count-field v-model="counts.operational_total_beds" label="原可运营物理总床数" :disabled="disabled" />
      <p>总床数包含已占用的可运营床。即时可收治名额请另行填写观察时间和准备条件。</p>
      <count-field v-model="counts.immediate_admittable_slots" label="原即时可收治空余名额" :allow-known="draft.basis_kind==='observed_operational_capacity'" :disabled="disabled" />
      <el-form-item v-if="counts.immediate_admittable_slots.state==='known'&&draft.basis_kind==='observed_operational_capacity'" label="原即时名额实际观察UTC"><el-input v-model="draft.immediate_slots_observed_at" aria-label="原即时名额实际观察UTC" :placeholder="clockHint" /></el-form-item>
      <el-form-item v-for="[key,label] in [['staff_readiness','本来源原人员就绪声明'],['equipment_readiness','本来源原设备就绪声明'],['isolation_applicability','本来源原隔离适用声明']]" :key="key" :label="label"><el-select v-model="draft[key]" :aria-label="label" placeholder="保留原confirmed/not_confirmed/unknown"><el-option v-for="(text,state) in reviews" :key="state" :label="text" :value="state" /></el-select></el-form-item>
      <el-form-item label="原容量及场景依据"><el-input v-model="draft.capacity_basis_note" aria-label="原容量及场景依据" type="textarea" :rows="3" placeholder="至少20个非空白字符；明确原可运营总量、原观察或未来场景区间，以及准备条件依据" /></el-form-item>
    </template>
    <el-form-item label="原来源覆盖状态"><el-select v-model="draft.coverage" aria-label="原来源覆盖状态" placeholder="明确原完整性，不根据数据库有记录默认完整"><el-option label="明确核实原覆盖完整" value="attested_complete" /><el-option label="明确原覆盖不完整" value="incomplete" /><el-option label="原覆盖未知" value="unknown" /></el-select></el-form-item>
    <el-form-item v-if="kind!=='capacity_interval'" label="原来源覆盖依据"><el-input v-model="draft.coverage_basis_note" aria-label="原来源覆盖依据" type="textarea" :rows="3" placeholder="至少20个非空白字符、最多4000个Unicode字符；明确原病区物理人口、覆盖范围和原采集依据" /></el-form-item>
    <p v-if="!valid" role="status">尚有原字段、时刻关系或明确状态未通过核对。系统登记时刻由服务器生成，不回填为历史可用时刻；所有自由依据仅院内保留。</p>
  </el-form>
</template>

<script setup>
import {computed,reactive,watch} from 'vue';
import CountField from './CountField.vue';
import {bedPayloadValid} from '@/api/bedSources';
const props=defineProps({kind:{type:String,required:true},disabled:{type:Boolean,default:false}}),emit=defineEmits(['validity','change']);
const clockHint='YYYY-MM-DDTHH:mm:ss.ffffffZ，原明确UTC六位微秒',reviews={confirmed:'原明确已确认（confirmed）',not_confirmed:'原明确未确认（not_confirmed）',unknown:'原声明未知（unknown）'},flowCounts=[['admission_events','原物理入病区事件数'],['discharge_events','原物理出院离开事件数'],['transfer_in_events','原物理转入病区事件数'],['transfer_out_events','原物理转出病区事件数']];
const blank=()=>({business_date:'',business_timezone:'',method:'',external_state:'',external_record_key:'',coverage:'',coverage_basis_note:'',census_at:'',observed_at:'',boundary_state_confirmed:'',day_start_at:'',day_end_at:'',event_definition_basis_note:'',basis_kind:'',start_at:'',end_at:'',immediate_slots_observed_at:'',staff_readiness:'',equipment_readiness:'',isolation_applicability:'',capacity_basis_note:''}),draft=reactive(blank()),counts=reactive({});
function reset(){Object.assign(draft,blank());for(const key of ['occupied_beds',...flowCounts.map(row=>row[0]),'operational_total_beds','immediate_admittable_slots'])counts[key]={state:'',value:''};}
function quantity(key){const row=counts[key];if(['unknown','not_recorded'].includes(row.state))return{value:null,absent_reason:row.state};if(row.state!=='known'||typeof row.value!=='string'||!/^(?:0|[1-9]\d{0,9})$/.test(row.value)||Number(row.value)>2147483647)throw new Error('原数量须明确已知整数或原缺项状态');return{value:Number(row.value),absent_reason:null};}
function build(){
  const common={coverage:draft.coverage};
  if(props.kind==='capacity_interval')return{...common,schema_version:'bed_capacity_interval_v1',start_at:draft.start_at,end_at:draft.end_at,basis_kind:draft.basis_kind,operational_total_beds:quantity('operational_total_beds'),capacity_definition:'total_operational_physical_beds_v1',capacity_basis_note:draft.capacity_basis_note,observed_at:draft.basis_kind==='reviewed_future_scenario'?null:draft.observed_at,staff_readiness:draft.staff_readiness,equipment_readiness:draft.equipment_readiness,isolation_applicability:draft.isolation_applicability,immediate_admittable_slots:quantity('immediate_admittable_slots'),immediate_slots_observed_at:counts.immediate_admittable_slots.state==='known'?draft.immediate_slots_observed_at:null};
  Object.assign(common,{business_date:draft.business_date,business_timezone:draft.business_timezone,method:draft.method,external_record_key:draft.external_state==='known'?draft.external_record_key:null,external_record_key_absent_reason:draft.external_state==='known'?null:draft.external_state,coverage_basis_note:draft.coverage_basis_note,observed_at:draft.observed_at});
  if(props.kind==='census')return{...common,schema_version:'bed_census_observation_v1',census_at:draft.census_at,definition:'occupied_physical_beds_at_boundary_v1',boundary_state_confirmed:draft.boundary_state_confirmed,occupied_beds:quantity('occupied_beds')};
  if(props.kind==='flow_day')return{...common,schema_version:'bed_flow_day_v1',day_start_at:draft.day_start_at,day_end_at:draft.day_end_at,definition:'ward_physical_day_events_v1',...Object.fromEntries(flowCounts.map(([key])=>[key,quantity(key)])),event_definition_basis_note:draft.event_definition_basis_note};
  throw new Error('原来源类型不支持');
}
const valid=computed(()=>{try{return bedPayloadValid(props.kind,build());}catch{return false;}});
watch(()=>props.kind,reset,{immediate:true,flush:'sync'});
watch(()=>draft.basis_kind,()=>{counts.immediate_admittable_slots={state:'',value:''};draft.immediate_slots_observed_at='';});
watch(valid,value=>emit('validity',value),{immediate:true});watch([draft,counts],()=>emit('change'),{deep:true});
defineExpose({build});
</script>
