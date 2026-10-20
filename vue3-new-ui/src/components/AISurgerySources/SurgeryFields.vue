<template>
  <div class="surgery-field">
    <template v-if="nullable&&modelValue===undefined&&!editing"><span>{{ label }}：未填写</span><el-button size="small" @click="change(null)">明确为空</el-button><el-button size="small" @click="startValue">填写原值</el-button></template>
    <template v-else-if="nullable&&modelValue===null"><span>{{ label }}：原明确为空（null）</span><el-button size="small" @click="startValue">改为填写原值</el-button></template>
    <template v-else-if="choices.length>1&&!selected">
      <el-form-item :label="label+'原类型'"><el-select :model-value="null" :aria-label="label+'原类型'" @update:model-value="selectVariant"><el-option v-for="(item,index) in choices" :key="index" :value="index" :label="variantLabel(item)" /></el-select></el-form-item>
    </template>
    <template v-else-if="effective?.type==='object'">
      <fieldset><legend>{{ label }}</legend><el-button v-if="choices.length>1" size="small" @click="resetVariant">重新选择原类型</el-button>
        <SurgeryFields v-for="[key,child] in Object.entries(effective.properties||{})" :key="key" :schema="child" :root="root" :label="fieldLabel(key)" :field-key="key" :lookups="lookups" :model-value="modelValue?.[key]" @update:model-value="value=>change({...modelValue,[key]:value})" />
      </fieldset>
    </template>
    <template v-else-if="effective?.type==='array'">
      <fieldset><legend>{{ label }} · {{ Array.isArray(modelValue)?modelValue.length+'条原件条目':'未填写' }}</legend>
        <el-button v-if="!Array.isArray(modelValue)" size="small" @click="change([])">明确空集合</el-button>
        <el-button size="small" :disabled="Array.isArray(modelValue)&&modelValue.length>=(effective.maxItems??Infinity)" @click="addItem">添加原条目</el-button>
        <template v-if="Array.isArray(modelValue)"><div v-for="index in visibleIndices" :key="index" class="array-item"><SurgeryFields :schema="effective.items" :root="root" :label="label+' 第'+(index+1)+'项'" :lookups="lookups" :model-value="modelValue[index]" @update:model-value="value=>replaceItem(index,value)" /><el-button size="small" @click="removeItem(index)">删除本条目</el-button></div>
          <el-pagination v-if="modelValue.length>20" v-model:current-page="page" :page-size="20" :total="modelValue.length" layout="prev,pager,next,total" /><p v-if="modelValue.length>20">分页仅控制显示，提交和完整性核对包含全部条目。</p>
        </template>
      </fieldset>
    </template>
    <template v-else-if="Object.hasOwn(effective||{},'const')">
      <p v-if="typeof effective.const==='string'">{{ label }}：{{ enumLabel(effective.const) }}</p>
      <el-form-item v-else :label="label"><el-select :model-value="modelValue" :aria-label="label" @update:model-value="change"><el-option :value="effective.const" :label="enumLabel(effective.const)" /></el-select></el-form-item>
    </template>
    <el-form-item v-else-if="Object.hasOwn(lookups,fieldKey)" :label="label"><el-select :model-value="modelValue" :aria-label="label" placeholder="选择已读取的真实身份" :disabled="!lookups[fieldKey].length" @update:model-value="change"><el-option v-for="item in lookups[fieldKey]" :key="item.value" :value="item.value" :label="item.label" /></el-select></el-form-item>
    <el-form-item v-else-if="effective?.enum||effective?.type==='boolean'" :label="label"><el-select :model-value="modelValue" :aria-label="label" placeholder="明确选择原声明" @update:model-value="change"><el-option v-for="value in effective.enum||(effective.type==='boolean'?[true,false]:[])" :key="String(value)" :value="value" :label="enumLabel(value)" /></el-select></el-form-item>
    <el-form-item v-else-if="effective?.type==='integer'" :label="label"><el-input :model-value="modelValue===undefined?'':String(modelValue)" :aria-label="label" inputmode="numeric" placeholder="原实际整数；空白不补零" @update:model-value="integerValue" /></el-form-item>
    <el-form-item v-else :label="label"><el-input :model-value="modelValue??''" :aria-label="label" :type="label.includes('依据')||label.includes('原文')?'textarea':'text'" :autosize="{minRows:2,maxRows:5}" placeholder="填写原值；原时刻须明确UTC六位微秒" @update:model-value="change" /></el-form-item>
  </div>
</template>

<script setup>
import {computed,ref,watch} from 'vue';
defineOptions({name:'SurgeryFields'});
const props=defineProps({schema:{type:[Object,Boolean],required:true},root:{type:Object,required:true},modelValue:{default:undefined},label:{type:String,required:true},fieldKey:{type:String,default:''},lookups:{type:Object,default:()=>({})}}),emit=defineEmits(['update:modelValue']),page=ref(1),editing=ref(false),variant=ref(null);
const labels={kind:'原件类型',basis_note:'原明确依据',record_type:'原记录类型',policy_type:'原政策类型',name:'原资源池名称',label:'原资源名称',department_id:'原科室标识',resource_id:'明确原物理资源标识',resource_kind:'原物理资源种类',user_id:'原真实用户账号标识',doctor_id:'原医师别名标识',equipment_id:'原Equipment资产标识',cssd_instrument_id:'原CSSD器械资产标识',pool_id:'原资源池标识',alias_scope:'原别名范围',alias_namespace:'原别名命名空间',legacy_schedule_id:'原执行记录标识',raw_original_text:'原未修剪手术室文字',application_id:'原手术申请标识',procedure_group_key:'原术式分组键',procedure_group_absent_reason:'原术式分组缺项原因',required:'原是否必须安排',required_absent_reason:'原必须性缺项原因',release:'原可开始界限',deadline:'原结束期限',patient_segment_ids:'原患者在场阶段键',patient_occupation_mode:'原患者在场范围',room:'原房间需求',roles:'原岗位需求',equipment:'原具体设备需求',other_requirements_status:'原其他需求完整性',slot_id:'原需求槽键',capability_keys:'原岗位或设备能力键',occupation:'原资源占用依据',segment_ids:'原占用阶段键',occupation_mode:'原占用范围',transition_class_key:'原转换类别键',transition_class_absent_reason:'原转换类别缺项原因',counted_as_work:'原是否计工时',counted_as_work_absent_reason:'原计工时缺项原因',role_kind:'原岗位',other_role_key:'原其他岗位键',observed_start_at:'原实际开始UTC',observed_end_at:'原实际结束UTC',observed_at:'原观察完成UTC',clock_interpretation:'原时钟解释依据',method:'原时长方法',semantics:'原时长语义',segments:'原阶段估计',segment_id:'原阶段键',start_offset_us:'原开始偏移微秒',end_offset_us:'原结束偏移微秒',value:'原值（十进制原文）',absent_reason:'原缺项原因',identity_status:'原身份核实状态',capability_status:'原能力核实状态',qualification_status:'原岗位资格核实状态',valid_from_at:'原效期开始UTC',valid_until:'原效期结束依据',at:'原明确UTC时刻',start_at:'原区间开始UTC',end_at:'原区间结束UTC',state:'原可用性',accounting:'原工时核算声明',breaks:'原明确休息区间',breaks_complete:'原休息记录是否完整',time_accounting_status:'原计时核算状态',effective_from_at:'原政策效期开始UTC',effective_until:'原政策效期结束依据',pairs:'原有向转换对',pair_coverage:'原转换对覆盖',from_class_key:'原前项类别键',to_class_key:'原后项类别键',minimum_gap_us:'原最小转换间隔微秒',penalty:'原声明成本',max_single_presence:'原单次职责最大跨度',max_work_rolling_24h:'原滚动24小时工时上限',max_work_rolling_7d:'原滚动7日工时上限',minimum_rest:'原不同职责最短休息',fixed_windows:'原固定工时窗口',minimum_work:'原窗口工时下限',maximum_work:'原窗口工时上限',unit:'原单位',policy_reference:'院内原政策引用原文'};
const enums={true:'原明确是（true）',false:'原明确否（false）',unknown:'原未知（unknown）',not_recorded:'原未记录（not_recorded）',not_applicable:'原不适用（not_applicable）',verified:'原已核实（verified）',not_verified:'原未核实（not_verified）',available:'原可用（available）',unavailable:'原不可用（unavailable）',attested_complete:'原明确核实完整（attested_complete）',incomplete:'原不完整（incomplete）',attested_not_required:'原明确不需要其他要求',all_required_modeled:'原全部其他要求已建模',segments:'原逐阶段占用',envelope:'原完整包络占用',room:'房间',person:'自然人',equipment:'具体设备',availability:'原可用区间',duty:'原明确职责区间',busy_capsule:'受控安全忙时',transition:'原转换政策',work:'原工时政策',surgeon:'术者',anesthesia:'麻醉',assistant:'助手',scrub_nurse:'器械护士',circulating_nurse:'巡回护士',other:'其他明确岗位',reviewed_case_estimate:'原病例审核估计',declared_upper_bounds:'原声明时长上界',declared_point_durations:'原声明点时长',explicit_original_utc:'明确原始UTC',reviewed_legacy_clock_mapping:'经审核旧时钟映射',namespace:'明确命名空间',legacy_schedule:'明确原执行记录',us:'原微秒（us）',min:'原分钟（min）'};
const fieldLabel=key=>labels[key]||`原${key}`,enumLabel=value=>enums[String(value)]??String(value);
function resolve(v){let result=v;for(let i=0;i<20&&result?.$ref;i++){const m=/^#\/\$defs\/([A-Za-z][A-Za-z0-9_]*)$/.exec(result.$ref);if(!m||!Object.hasOwn(props.root.$defs||{},m[1]))return null;result=props.root.$defs[m[1]];}return result;}
const declared=computed(()=>resolve(props.schema)),nullable=computed(()=>declared.value?.anyOf?.some(v=>resolve(v)?.type==='null')||false);
function flatten(v){const s=resolve(v);return s?.oneOf?s.oneOf.flatMap(flatten):[s];}
const choices=computed(()=>{const s=nullable.value?declared.value.anyOf.filter(v=>resolve(v)?.type!=='null'):declared.value?.anyOf||[declared.value];return s.flatMap(flatten).filter(Boolean);});
const selected=computed(()=>{if(choices.value.length===1)return choices.value[0];if(variant.value!==null&&choices.value[variant.value])return choices.value[variant.value];if(!props.modelValue||typeof props.modelValue!=='object')return null;const matches=choices.value.filter(s=>Object.entries(s.properties||{}).every(([key,value])=>{const field=resolve(value)||{};return Object.hasOwn(field,'const')?props.modelValue[key]===field.const:['kind','record_type','policy_type'].includes(key)&&field.enum?field.enum.includes(props.modelValue[key]):true;}));return matches.length===1?matches[0]:null;});
const effective=computed(()=>selected.value||choices.value[0]);
const visibleIndices=computed(()=>Array.isArray(props.modelValue)?props.modelValue.map((_,index)=>index).slice((page.value-1)*20,page.value*20):[]);
function seed(schema){const s=resolve(schema);return s?.type==='object'?Object.fromEntries(Object.entries(s.properties||{}).filter(([,v])=>typeof resolve(v)?.const==='string').map(([key,value])=>[key,resolve(value).const])):undefined;}
function change(value){emit('update:modelValue',value);}
function startValue(){editing.value=true;const s=choices.value.length===1?choices.value[0]:null;change(s?.type==='object'?seed(s):s?.type==='array'?[]:s?.type==='string'?'':undefined);}
function selectVariant(index){variant.value=index;change(seed(choices.value[index]));}
function resetVariant(){variant.value=null;change(undefined);}
function variantLabel(schema){const p=schema.properties||{};return enumLabel(resolve(p.record_type||p.policy_type||p.kind)?.const??(Object.hasOwn(p,'at')?'原明确时刻':'原时刻未知或不适用'));}
function integerValue(value){change(/^(0|[1-9]\d*)$/.test(value)&&Number.isSafeInteger(Number(value))?Number(value):undefined);}
function addItem(){const items=Array.isArray(props.modelValue)?[...props.modelValue]:[];items.push(seed(effective.value.items));change(items);page.value=Math.ceil(items.length/20);}
function replaceItem(index,value){const items=[...props.modelValue];items[index]=value;change(items);}
function removeItem(index){change(props.modelValue.filter((_,i)=>i!==index));}
watch(()=>props.modelValue?.length,count=>{if(Number.isInteger(count))page.value=Math.min(page.value,Math.max(1,Math.ceil(count/20)));});
</script>

<style scoped>
fieldset{border:1px solid #dcdfe6;margin:10px 0;padding:12px}legend{font-weight:600}.array-item{border-left:3px solid #dcdfe6;padding:8px;margin:10px 0}.el-select{width:100%}.surgery-field{min-width:0}
</style>
