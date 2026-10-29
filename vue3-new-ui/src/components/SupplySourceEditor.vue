<template>
  <el-form label-position="top" class="supply-editor" @submit.prevent>
    <p>单个真实品种 · 全院库存范围。原计数单位、三个数量口径与专业确认分别填写；这里不推断库存需求，也不改业务库存。</p>
    <template v-if="kind==='daily'">
      <el-form-item label="原数量口径"><el-select :model-value="payload.target" aria-label="原数量口径" @update:model-value="set('target',$event)"><el-option v-for="(label,key) in supplySourceTargets" :key="key" :value="key" :label="label" /></el-select></el-form-item>
      <el-form-item label="原业务日期"><el-input :model-value="payload.date" aria-label="原业务日期" placeholder="YYYY-MM-DD" @update:model-value="set('date',$event)" /></el-form-item>
      <el-form-item label="原业务时区"><el-input :model-value="payload.timezone" aria-label="原业务时区" placeholder="明确IANA时区，例如 Asia/Shanghai" @update:model-value="set('timezone',$event)" /></el-form-item>
      <el-form-item v-for="(label,key) in clockLabels" :key="key" :label="label"><el-input :model-value="payload[key]" :aria-label="label" placeholder="YYYY-MM-DDTHH:mm:ss.ffffffZ" @update:model-value="set(key,$event)" /></el-form-item>
      <el-form-item label="原数量记录状态"><el-select :model-value="quantityMode" aria-label="原数量记录状态" @update:model-value="quantityState"><el-option label="填写原十进制数值（可为零）" value="value" /><el-option label="原未知（unknown）" value="unknown" /><el-option label="原未记录（not_recorded）" value="not_recorded" /></el-select></el-form-item>
      <el-form-item v-if="quantityMode==='value'" label="原十进制数量"><el-input :model-value="payload.quantity?.value" aria-label="原十进制数量" placeholder="保留原文，最多18位整数/6位小数" @update:model-value="set('quantity',{value:$event,absent_reason:null})" /></el-form-item>
      <p v-if="quantityMode==='unknown'||quantityMode==='not_recorded'">原数量为 null，绝不补为 0。</p>
      <el-form-item label="明确单位原件"><el-select :model-value="modelValue?.unit_definition_id===null?'__none__':modelValue?.unit_definition_id" aria-label="明确单位原件" @update:model-value="emit('unit-change',$event)"><el-option :value="'__none__'" label="明确未绑定单位原件" /><el-option v-for="unit in units" :key="unit.source_record_id" :value="unit.source_record_id" :label="unit.source_record_id+' · '+unit.status+' · '+unit.professional_status" /></el-select></el-form-item>
      <p v-if="selectedUnit">已逐件核对单位：{{ selectedUnit.payload.original_unit_text }} · {{ selectedUnit.content_hash }}</p>
      <el-form-item label="原单位文字是否有记录"><el-select :model-value="unitTextMode" aria-label="原单位文字是否有记录" @update:model-value="set('original_unit_text',$event==='null'?null:'')"><el-option value="value" label="填写原单位文字" /><el-option value="null" label="明确原单位未知（null）" /></el-select></el-form-item>
    </template>
    <el-form-item v-if="kind==='unit'||unitTextMode==='value'" label="原库存计数单位文字"><el-input :model-value="payload.original_unit_text" aria-label="原库存计数单位文字" placeholder="原明确计数单位；不从剂量、规格或价格猜测" @update:model-value="set('original_unit_text',$event)" /></el-form-item>
    <template v-if="kind==='daily'">
      <el-form-item v-for="(field,key) in declarations" :key="key" :label="field.label"><el-select :model-value="payload[key]" :aria-label="field.label" @update:model-value="set(key,$event)"><el-option v-for="(label,value) in field.options" :key="value" :value="value" :label="label" /></el-select></el-form-item>
      <el-form-item v-if="payload.method==='external_register'" label="原外部登记引用键"><el-input :model-value="payload.external_record_key" aria-label="原外部登记引用键" @update:model-value="set('external_record_key',$event)" /></el-form-item>
      <el-form-item label="原日数量覆盖依据"><el-input type="textarea" :model-value="payload.coverage_basis_note" aria-label="原日数量覆盖依据" @update:model-value="set('coverage_basis_note',$event)" /></el-form-item>
      <el-form-item label="原供应约束核实依据"><el-input type="textarea" :model-value="payload.stock_constraint_basis_note" aria-label="原供应约束核实依据" @update:model-value="set('stock_constraint_basis_note',$event)" /></el-form-item>
    </template>
    <el-form-item label="原单位或数量口径依据"><el-input type="textarea" :model-value="payload.definition_basis_note" aria-label="原单位或数量口径依据" @update:model-value="set('definition_basis_note',$event)" /></el-form-item>
    <el-form-item label="实际专业确认"><el-select :model-value="payload.professional_attestation?.status" aria-label="实际专业确认" @update:model-value="signature"><el-option value="unknown" label="专业确认未知；仅登记原件" /><el-option v-if="canConfirmProfessional&&supplySourcePositive(professionalSignerUserId)" value="confirmed" :label="'由当前实际药师本人 #'+professionalSignerUserId+' 明确确认'" /></el-select></el-form-item>
    <p v-if="!canConfirmProfessional">当前技术身份可以登记未知、审核或治理。专业确认必须由实际药师本人完成；技术发布不改变其状态。</p>
    <el-form-item v-if="payload.professional_attestation?.status==='confirmed'" label="药师本人专业确认依据"><el-input type="textarea" :model-value="payload.professional_attestation.basis_note" aria-label="药师本人专业确认依据" @update:model-value="set('professional_attestation',{...payload.professional_attestation,basis_note:$event})" /></el-form-item>
    <template v-if="kind==='daily'">
      <fieldset><legend>可选旧台账审计引用</legend><p>以下为原台账审计记录。</p>
        <el-button v-if="!Array.isArray(payload.audit_refs)" @click="set('audit_refs',[])">本条不附旧台账审计引用</el-button>
        <el-button :disabled="payload.audit_refs?.length>=64" @click="addAudit">添加明确审计引用</el-button>
        <div v-for="(ref,index) in payload.audit_refs||[]" :key="index"><el-form-item :label="itemKind==='pharmaceutical'?'实际原台账编号':'实际原追溯UUID'"><el-input :model-value="String(itemKind==='pharmaceutical'?ref.ledger_id??'':ref.trace_id??'')" :aria-label="'原审计引用第'+(index+1)+'项'" @update:model-value="auditValue(index,$event)" /></el-form-item><el-button @click="set('audit_refs',payload.audit_refs.filter((_,i)=>i!==index))">移除此审计引用</el-button></div>
      </fieldset>
    </template>
    <p>依据至少 20 个非空白字符、最多 4000 UTF-8 字节。保存只创建待审核原件；未知或缺项不会自动变为已核实。</p>
  </el-form>
</template>

<script setup>
import {computed} from 'vue';
import {supplySourceTargets,supplySourcePositive} from '@/api/ai/supplySources';
const props=defineProps({kind:{type:String,required:true},itemKind:{type:String,required:true},modelValue:{type:Object,default:()=>({})},units:{type:Array,default:()=>[]},selectedUnit:{type:Object,default:null},canConfirmProfessional:Boolean,professionalSignerUserId:{type:Number,default:null}}),emit=defineEmits(['update:modelValue','unit-change']);
const payload=computed(()=>props.modelValue?.payload||{}),quantityMode=computed(()=>payload.value.quantity?.value===undefined?undefined:payload.value.quantity.value===null?payload.value.quantity.absent_reason:'value'),unitTextMode=computed(()=>payload.value.original_unit_text===undefined?undefined:payload.value.original_unit_text===null?'null':'value');
const clockLabels={day_start_at:'原日开始UTC6',day_end_at:'原日结束UTC6',observed_at:'原观察完成UTC6'};
const declarations={unit_review:{label:'原单位核实状态',options:{confirmed:'明确单位已核实',not_confirmed:'单位未核实',unknown:'单位核实未知'}},coverage:{label:'原日数量覆盖',options:{attested_complete:'药师明确核实完整',incomplete:'原覆盖不完整',unknown:'原覆盖未知'}},method:{label:'原登记方法',options:{direct_tally:'明确直接计数',external_register:'明确外部登记'}},stock_constraint:{label:'原供应约束状态',options:{none_observed:'未观察到供应约束',partial:'原部分受约束',full:'原完全受约束',unknown:'原供应约束未知'}}};
function set(key,value){const next={...payload.value,[key]:value};if(key==='method'&&value==='direct_tally')next.external_record_key=null;emit('update:modelValue',{...props.modelValue,payload:next});}
function quantityState(value){set('quantity',value==='value'?{value:'',absent_reason:null}:{value:null,absent_reason:value});}
function signature(status){set('professional_attestation',status==='confirmed'?{status,signer_user_id:props.professionalSignerUserId,basis_note:undefined}:{status,signer_user_id:null,basis_note:null});}
function addAudit(){set('audit_refs',[...(payload.value.audit_refs||[]),{kind:props.itemKind==='pharmaceutical'?'pharmaceutical_ledger':'consumable_trace',ledger_id:null,trace_id:null}]);}
function auditValue(index,value){const refs=payload.value.audit_refs.map((r,i)=>i!==index?r:props.itemKind==='pharmaceutical'?{...r,ledger_id:/^[1-9][0-9]*$/.test(value)&&supplySourcePositive(Number(value))?Number(value):null}:{...r,trace_id:value});set('audit_refs',refs);}
</script>

<style scoped>
.supply-editor{max-width:900px}.el-select{width:100%}fieldset{border:1px solid #dcdfe6;padding:12px;margin:12px 0}p{line-height:1.6;overflow-wrap:anywhere}
</style>
