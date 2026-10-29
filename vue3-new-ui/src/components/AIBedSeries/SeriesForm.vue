<template>
  <section aria-label="完整床位序列逐日逐件审核">
    <p>完整 {{ days.length }} 天、{{ members.length }} 件相关原件、{{ preview.bed_cohort.length }} 个稳定床位身份。床位配置数量 {{ preview.ward_capture_evidence.configured_bed_count??'未知' }} 是独立原元数据，不补成历史占床数或容量。</p>
    <p class="hash">本次完整集合 {{ preview.collection_digest }}</p>
    <p>分页只影响展示，捕获提交全部日期、全部相关成员和五个目标声明。四类物理事件只选择同一整件 flow 原件。未核实保持待填，不补零。</p>
    <details><summary>明确批量动作（作用于整个冻结候选集合）</summary>
      <p>这些按钮按上述全部 {{ days.length }} 天或 {{ members.length }} 件执行，每次保存所选记录及审核版本。请核实候选后提交。</p>
      <el-input v-model="batchBasis" aria-label="床位序列批量核实依据" type="textarea" placeholder="逐日、逐件采用共同依据时明确填写，至少20个非空白字符" :disabled="disabled" />
      <el-button :disabled="disabled||!bedBasisValid(batchBasis)" @click="uniqueDaily">明确采用每种仅一件合格兼容来源的日期</el-button>
      <el-button :disabled="disabled||!bedBasisValid(batchBasis)" @click="missingDaily">明确将尚未选择的日期记为缺失</el-button>
      <el-button :disabled="disabled||!bedBasisValid(batchBasis)" @click="days.forEach(d=>d.selection_basis_note=batchBasis)">明确将共同依据应用全部日期</el-button>
      <el-select v-model="remainingReview" aria-label="其余非容量原件批量用途" :disabled="disabled" placeholder="明确其余原件用途"><el-option label="明确排除其余原件" value="excluded" /><el-option label="其余原件用途未知" value="unknown" /></el-select>
      <el-button :disabled="disabled||!bedBasisValid(batchBasis)||!remainingReview" @click="reviewDaily">确认已选整件；按所选用途审核其余全部非容量原件</el-button>
      <el-select v-model="capacityReview" aria-label="全部容量原件批量用途" :disabled="disabled" placeholder="容量必须明确纳入或排除"><el-option label="明确纳入全部治理合格容量原件" value="confirmed" /><el-option label="明确排除全部容量原件" value="excluded" /></el-select>
      <el-button :disabled="disabled||!bedBasisValid(batchBasis)||!capacityReview" @click="reviewCapacity">明确审核全部历史容量与未来场景</el-button>
      <p v-if="batchNotice" role="status">{{ batchNotice }}</p>
    </details>
    <h3>每日整件来源选择</h3>
    <p>已填完整日期 {{ completeDays }} / {{ days.length }}。原业务时区 {{ period.business_timezone }}；原日界 UTC 与原实际观察、登记时刻分别保留。</p>
    <article v-for="(day,index) in visibleDays" :key="day.business_date" :aria-label="`床位序列日期 ${day.business_date}`">
      <p>{{ day.business_date }} · [{{ group(day).day_start_at }}, {{ group(day).day_end_at }})</p>
      <div v-for="prefix in ['census','flow']" :key="prefix">
        <el-select :model-value="choice(day,prefix)" :aria-label="`${day.business_date} ${prefix}整件来源`" :disabled="disabled" placeholder="明确整件来源或缺失原因" @update:model-value="chooseDay(day,prefix,$event)">
          <el-option label="明确无可选原件（missing）" value="missing" /><el-option label="明确冲突尚未解决（unresolved_conflict）" value="unresolved_conflict" />
          <el-option v-for="row in group(day)[prefix+'_candidates']" :key="row.source_record_id" :value="row.source_record_id" :disabled="!row.eligible||!row.compatible" :label="`${row.source_record_id} · ${row.eligible&&row.compatible?'治理合格且日界兼容':'不可选：'+row.exclusion_reasons.join('；')}`" />
        </el-select>
        <el-button v-if="day[prefix+'_source_record_id']" @click="inspect(day[prefix+'_source_record_id'])">核对该{{ prefix==='census'?'占床':'整件事件' }}原件</el-button>
      </div>
      <el-input v-model="days[(dayPage-1)*20+index].selection_basis_note" :aria-label="`${day.business_date}整件选择依据`" type="textarea" :disabled="disabled" placeholder="明确本日整件选择或缺失/冲突依据" />
    </article>
    <el-pagination v-model:current-page="dayPage" :total="days.length" :page-size="20" layout="prev,pager,next" aria-label="床位序列日期分页" />
    <h3>五个独立目标的覆盖声明</h3>
    <article v-for="row in coverage" :key="row.target" :aria-label="bedTargets[row.target]+'覆盖'">
      <p>{{ bedTargets[row.target] }} · {{ row.definition }}</p>
      <el-select v-for="[key,label] in reviewFields" :key="key" v-model="row[key]" :aria-label="`${bedTargets[row.target]}${label}`" :disabled="disabled" placeholder="明确本目标原声明"><el-option v-for="(text,value) in declarationLabels" :key="value" :label="text" :value="value" /></el-select>
      <el-input v-model="row.basis_note" :aria-label="`${bedTargets[row.target]}覆盖依据`" type="textarea" :disabled="disabled" />
    </article>
    <h3>全部相关原件逐件用途</h3>
    <p>已填原件 {{ completeMembers }} / {{ members.length }}。已发布原件的数量、覆盖或准备条件仍可未知；不能通过择优拼接或遗漏其他成员制造完整资料。</p>
    <article v-for="row in visibleMembers" :key="row.source_record_id" :aria-label="`床位成员 ${row.source_record_id}`">
      <p>{{ bedSourceKinds[row.kind].label }} · {{ row.source_record_id }}<br />{{ source(row).status }} · {{ source(row).eligible?'原治理当前合格':'原治理或范围不可用' }}<br /><span class="hash">内容 {{ row.expected_content_hash }}<br />治理 {{ row.expected_governance_hash }}</span></p>
      <el-button @click="inspect(row.source_record_id)">核对完整原件或当前红化元数据</el-button>
      <el-select v-model="row.selection" :aria-label="`${row.source_record_id}原件用途`" :disabled="disabled" placeholder="明确本条用途"><el-option label="明确纳入（confirmed）" value="confirmed" :disabled="!source(row).eligible" /><el-option label="明确排除（excluded）" value="excluded" /><el-option v-if="row.kind!=='capacity_interval'" label="用途未知（unknown）" value="unknown" /></el-select>
      <el-input v-model="row.basis_note" :aria-label="`${row.source_record_id}原件用途依据`" type="textarea" :disabled="disabled" />
    </article>
    <el-pagination v-if="members.length>20" v-model:current-page="memberPage" :total="members.length" :page-size="20" layout="prev,pager,next" aria-label="床位原件分页" />
    <p role="status">{{ valid?'全部日期、目标声明和完整成员用途已填写，仍须服务器重核全集合后捕获。':'尚有未填、原件选择或集合绑定不一致，不能捕获。' }}</p>
  </section>
</template>

<script setup>
import {computed,ref,watch} from 'vue';
import {bedBasisValid,bedSourceKinds} from '@/api/bedSources';
import {bedSeriesRequestValid,bedTargetDefinition,bedTargets} from '@/api/bedSeries';
const props=defineProps({preview:{type:Object,required:true},period:{type:Object,required:true},disabled:Boolean}),emit=defineEmits(['validity','inspect']);
const days=ref([]),coverage=ref([]),members=ref([]),dayPage=ref(1),memberPage=ref(1),batchBasis=ref(''),remainingReview=ref(''),capacityReview=ref(''),batchNotice=ref('');
const declarationLabels={confirmed:'明确已确认（confirmed）',not_confirmed:'明确未确认（not_confirmed）',unknown:'声明未知（unknown）'},reviewFields=[['same_scope_confirmed','同一病区范围声明'],['same_definition_confirmed','同一物理定义声明'],['same_method_confirmed','同一采集方法声明']];
const group=day=>props.preview.day_groups.find(g=>g.business_date===day.business_date),source=row=>props.preview.fact_manifest.find(m=>m.source_record_id===row.source_record_id),choice=(day,prefix)=>day[prefix+'_source_record_id']||day[prefix+'_selection_reason'];
const visibleDays=computed(()=>days.value.slice((dayPage.value-1)*20,dayPage.value*20)),visibleMembers=computed(()=>members.value.slice((memberPage.value-1)*20,memberPage.value*20));
const completeDays=computed(()=>days.value.filter(d=>bedBasisValid(d.selection_basis_note)&&d.census_selection_reason&&d.flow_selection_reason).length),completeMembers=computed(()=>members.value.filter(r=>r.selection&&bedBasisValid(r.basis_note)).length);
function build(){return JSON.parse(JSON.stringify({...props.period,days:days.value,target_coverage:coverage.value,member_reviews:members.value}));}
const valid=computed(()=>bedSeriesRequestValid(build(),props.preview));watch(valid,value=>emit('validity',value),{immediate:true});
function chooseDay(day,prefix,value){day[prefix+'_source_record_id']=['missing','unresolved_conflict'].includes(value)?null:value;day[prefix+'_selection_reason']=['missing','unresolved_conflict'].includes(value)?value:'confirmed';}
function inspect(id){const m=props.preview.fact_manifest.find(x=>x.source_record_id===id);if(m)emit('inspect',m);}
function uniqueDaily(){if(props.disabled||!bedBasisValid(batchBasis.value))return;let count=0;for(const d of days.value)for(const p of ['census','flow']){const rows=group(d)[p+'_candidates'].filter(x=>x.eligible&&x.compatible);if(rows.length===1){chooseDay(d,p,rows[0].source_record_id);d.selection_basis_note=batchBasis.value;count++;}}batchNotice.value=`已按明确动作选择 ${count} 个唯一合格整件；其余日期仍须明确核实。`;}
function missingDaily(){if(props.disabled||!bedBasisValid(batchBasis.value))return;for(const d of days.value){for(const p of ['census','flow'])if(!choice(d,p))chooseDay(d,p,'missing');d.selection_basis_note=batchBasis.value;}batchNotice.value='已按明确动作将尚未选择的日期登记为缺失；保留已有整件选择。';}
function reviewDaily(){if(props.disabled||!bedBasisValid(batchBasis.value)||!remainingReview.value)return;const ids=new Set(days.value.flatMap(d=>[d.census_source_record_id,d.flow_source_record_id]).filter(Boolean));for(const r of members.value)if(r.kind!=='capacity_interval'){r.selection=ids.has(r.source_record_id)?'confirmed':remainingReview.value;r.basis_note=batchBasis.value;}batchNotice.value='已明确审核全部非容量成员；全部 UUID 与两种摘要保持绑定。';}
function reviewCapacity(){if(props.disabled||!bedBasisValid(batchBasis.value)||!capacityReview.value)return;for(const r of members.value)if(r.kind==='capacity_interval'&&(capacityReview.value!=='confirmed'||source(r).eligible)){r.selection=capacityReview.value;r.basis_note=batchBasis.value;}batchNotice.value='已按明确动作审核全部可处理容量成员；不合格原件不会被批量确认。';}
watch(()=>props.preview,()=>{days.value=props.preview.day_groups.map(g=>({business_date:g.business_date,census_source_record_id:null,census_selection_reason:null,census_group_digest:g.census_group_digest,flow_source_record_id:null,flow_selection_reason:null,flow_group_digest:g.flow_group_digest,selection_basis_note:''}));coverage.value=Object.keys(bedTargets).map(target=>({target,definition:bedTargetDefinition(target),same_scope_confirmed:null,same_definition_confirmed:null,same_method_confirmed:null,basis_note:''}));members.value=props.preview.fact_manifest.map(m=>({source_record_id:m.source_record_id,kind:m.kind,expected_content_hash:m.content_hash,expected_governance_hash:m.governance_hash,selection:null,basis_note:''}));dayPage.value=memberPage.value=1;batchBasis.value=remainingReview.value=capacityReview.value=batchNotice.value='';},{immediate:true});
defineExpose({build});
</script>

<style scoped>
p{line-height:1.7}.hash{overflow-wrap:anywhere}article{border:1px solid var(--el-border-color);padding:12px;margin:10px 0}.el-select{min-width:260px;margin:5px 10px 5px 0;max-width:100%}.el-button{margin:6px 8px 6px 0}details{padding:10px;border:1px solid var(--el-border-color)}
</style>
