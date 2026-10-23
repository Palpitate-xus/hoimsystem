<template>
  <div class="rca-field">
    <template v-if="fixedKeys.includes(fieldKey)"><p>{{ label }}：{{ modelValue===undefined?'待绑定明确原件':JSON.stringify(modelValue) }}</p></template>
    <template v-else-if="nullable&&modelValue===undefined&&!editing"><span>{{ label }}：未填写</span><el-button size="small" @click="change(null)">明确为空</el-button><el-button size="small" @click="startValue">填写原值</el-button></template>
    <template v-else-if="nullable&&modelValue===null"><span>{{ label }}：原明确为空（null）</span><el-button size="small" @click="startValue">改为填写原值</el-button></template>
    <el-form-item v-else-if="Object.hasOwn(lookups,fieldKey)" :label="label"><el-select :model-value="modelValue" :aria-label="label" placeholder="选择完整明确原件或身份" :value-key="lookupItems[0]?.value?.source_record_id?'source_record_id':'value'" :disabled="!lookupItems.length" @update:model-value="change"><el-option v-for="item in lookupItems" :key="item.label" :value="item.value" :label="item.label" /></el-select></el-form-item>
    <template v-else-if="choices.length>1&&!selected">
      <el-form-item :label="label+'原类型'"><el-select :model-value="null" :aria-label="label+'原类型'" @update:model-value="selectVariant"><el-option v-for="(item,index) in choices" :key="index" :value="index" :label="variantLabel(item)" /></el-select></el-form-item>
    </template>
    <template v-else-if="effective?.type==='object'">
      <fieldset><legend>{{ label }}</legend><el-button v-if="choices.length>1" size="small" @click="resetVariant">重新选择原类型</el-button>
        <RcaEvidenceFields v-for="[key,child] in Object.entries(effective.properties||{})" :key="key" :schema="child" :root="root" :label="fieldLabel(key)" :field-key="key" :field-labels="fieldLabels" :lookups="lookups" :fixed-keys="effective.properties?.expected_resource_hash?[...fixedKeys,'resource_id']:fixedKeys" :locked-arrays="lockedArrays" :context="childContext" :resource-kind="{room:'room',roles:'person',equipment:'equipment'}[key]||resourceKind" :model-value="modelValue?.[key]" @update:model-value="value=>change({...modelValue,[key]:value})" />
      </fieldset>
    </template>
    <template v-else-if="effective?.type==='array'">
      <fieldset><legend>{{ label }} · {{ Array.isArray(modelValue)?modelValue.length+'条原件条目':'未填写' }}</legend>
        <el-button v-if="!lockedArrays.includes(fieldKey)&&!Array.isArray(modelValue)" size="small" @click="change([])">明确空集合</el-button>
        <el-button v-if="!lockedArrays.includes(fieldKey)" size="small" :disabled="Array.isArray(modelValue)&&modelValue.length>=(effective.maxItems??Infinity)" @click="addItem">添加原条目</el-button>
        <template v-if="Array.isArray(modelValue)"><div v-for="index in visibleIndices" :key="index" class="array-item"><RcaEvidenceFields :schema="effective.items" :root="root" :label="label+' 第'+(index+1)+'项'" :field-labels="fieldLabels" :lookups="lookups" :fixed-keys="fixedKeys" :locked-arrays="lockedArrays" :context="childContext" :resource-kind="resourceKind" :model-value="modelValue[index]" @update:model-value="value=>replaceItem(index,value)" /><el-button v-if="!lockedArrays.includes(fieldKey)" size="small" @click="removeItem(index)">删除本条目</el-button></div>
          <el-pagination v-if="modelValue.length>20" v-model:current-page="page" :page-size="20" :total="modelValue.length" layout="prev,pager,next,total" /><p v-if="modelValue.length>20">分页仅控制显示，提交和完整性核对包含全部条目。</p>
        </template>
      </fieldset>
    </template>
    <template v-else-if="Object.hasOwn(effective||{},'const')">
      <p v-if="typeof effective.const==='string'">{{ label }}：{{ enumLabel(effective.const) }}</p>
      <el-form-item v-else :label="label"><el-select :model-value="modelValue" :aria-label="label" @update:model-value="change"><el-option :value="effective.const" :label="enumLabel(effective.const)" /></el-select></el-form-item>
    </template>
    <el-form-item v-else-if="effective?.enum||effective?.type==='boolean'" :label="label"><el-select :model-value="modelValue" :aria-label="label" placeholder="明确选择原声明" @update:model-value="change"><el-option v-for="value in effective.enum||(effective.type==='boolean'?[true,false]:[])" :key="String(value)" :value="value" :label="enumLabel(value)" /></el-select></el-form-item>
    <el-form-item v-else-if="effective?.type==='integer'" :label="label"><el-input :model-value="modelValue===undefined?'':String(modelValue)" :aria-label="label" inputmode="numeric" placeholder="原实际整数；空白不补零" @update:model-value="integerValue" /></el-form-item>
    <el-form-item v-else :label="label"><el-input :model-value="modelValue??''" :aria-label="label" :type="label.includes('依据')||label.includes('原文')?'textarea':'text'" :autosize="{minRows:2,maxRows:5}" placeholder="填写原值；原时刻须明确UTC六位微秒" @update:model-value="change" /></el-form-item>
  </div>
</template>

<script setup>
import {computed,ref,watch} from 'vue';
defineOptions({name:'RcaEvidenceFields'});
const props=defineProps({schema:{type:[Object,Boolean],required:true},root:{type:Object,required:true},modelValue:{default:undefined},label:{type:String,required:true},fieldKey:{type:String,default:''},fieldLabels:{type:Object,default:()=>({})},lookups:{type:Object,default:()=>({})},fixedKeys:{type:Array,default:()=>[]},lockedArrays:{type:Array,default:()=>[]},context:{type:Object,default:()=>({})},resourceKind:{type:String,default:null}}),emit=defineEmits(['update:modelValue']),page=ref(1),editing=ref(false),variant=ref(null);
const labels={"event_id":"实际事件标识","expected_event_patient_id":"原事件关联患者标识","grantee_id":"实际授权用户","permission_kind":"明确独立用途许可","purpose":"本项固定用途","valid_until":"许可截止UTC6","basis_note":"本次明确依据","explicit_scope_review":"本人明确复核本件许可范围","origin_kind":"本件原始来源类型","text":"完整原文（不裁剪或规范化）","provenance":"原件来源声明","method":"明确来源方式","provenance_note":"原件来源依据","witness_kind":"实际旧原件种类","witness_id":"明确旧原件标识","expected_raw_hash":"已读完整旧原件SHA","timeline":"独立人工时间线","entry_id":"本条人工时间线UUID","statement":"原文中的人工陈述","occurred_time":"人工声明发生时刻","status":"本条时间声明状态","at":"明确发生UTC6","start_at":"明确区间开始UTC6","end_at":"明确区间结束UTC6","basis_hash":"原时间依据完整SHA","evidence":"本条原件逐字依据","start":"Unicode起点（含）","end":"Unicode终点（不含）","quote":"原文逐字引文","assertion_status":"本项固定陈述性质","expected_collection_hash":"已审完整同事件集合SHA"};
const enums={"manual_evidence":"独立人工原件","human_timeline":"独立人工时间线","legacy_event":"旧事件人工衍生稿","legacy_rca":"旧RCA人工衍生稿","human_authored_record":"本人独立登记文字","human_declared_derivative":"明确旧原件的人工衍生","event_investigation":"本件事件调查用途","associated_patient_processing":"实际关联患者处理用途","incident_rca":"本次事件RCA调查","human_recorded_statement_not_causal_verification":"人工记录陈述，未确认因果","unknown":"未知","human_declared_exact":"人工明确单一时刻","human_declared_interval":"人工明确时间区间","confirmed":"本人明确确认","not_confirmed":"本人未确认","true":"明确是","false":"明确否"};
const fieldLabel=key=>props.fieldLabels[key]||labels[key]||`原${key}`,enumLabel=value=>enums[String(value)]??String(value);
function resolve(v){let result=v;for(let i=0;i<20&&result?.$ref;i++){const m=/^#\/\$defs\/([A-Za-z][A-Za-z0-9_]*)$/.exec(result.$ref);if(!m||!Object.hasOwn(props.root.$defs||{},m[1]))return null;result=props.root.$defs[m[1]];}return result;}
const declared=computed(()=>resolve(props.schema)),nullable=computed(()=>declared.value?.anyOf?.some(v=>resolve(v)?.type==='null')||false);
function flatten(v){const s=resolve(v);return s?.oneOf?s.oneOf.flatMap(flatten):[s];}
const choices=computed(()=>{const s=nullable.value?declared.value.anyOf.filter(v=>resolve(v)?.type!=='null'):declared.value?.anyOf||[declared.value];return s.flatMap(flatten).filter(Boolean);});
const selected=computed(()=>{if(choices.value.length===1)return choices.value[0];if(variant.value!==null&&choices.value[variant.value])return choices.value[variant.value];if(!props.modelValue||typeof props.modelValue!=='object')return null;const matches=choices.value.filter(s=>Object.entries(s.properties||{}).every(([key,value])=>{const field=resolve(value)||{};return Object.hasOwn(field,'const')?props.modelValue[key]===field.const:['kind','record_type','policy_type'].includes(key)&&field.enum?field.enum.includes(props.modelValue[key]):true;}));return matches.length===1?matches[0]:null;});
const effective=computed(()=>selected.value||choices.value[0]);
const childContext=computed(()=>({...props.context,...(props.modelValue?.application_id?{applicationId:props.modelValue.application_id}:{}),...(props.modelValue?.resource_id?{resourceId:props.modelValue.resource_id}:{})}));
const lookupItems=computed(()=>{const items=props.lookups[props.fieldKey]||[];return items.filter(item=>(!item.kind||!props.resourceKind||item.kind===props.resourceKind)&&(!item.applicationId||!props.context.applicationId||item.applicationId===props.context.applicationId)&&(!item.resourceId||!props.context.resourceId||item.resourceId===props.context.resourceId));});
const visibleIndices=computed(()=>Array.isArray(props.modelValue)?props.modelValue.map((_,index)=>index).slice((page.value-1)*20,page.value*20):[]);
function seed(schema){const s=resolve(schema);return s?.type==='object'?Object.fromEntries(Object.entries(s.properties||{}).filter(([,v])=>typeof resolve(v)?.const==='string').map(([key,value])=>[key,resolve(value).const])):undefined;}
function change(value){emit('update:modelValue',value);}
function startValue(){editing.value=true;const s=choices.value.length===1?choices.value[0]:null;change(s&&Object.hasOwn(s,'const')?s.const:s?.type==='object'?seed(s):s?.type==='array'?[]:s?.type==='string'?'':undefined);}
function selectVariant(index){variant.value=index;change(seed(choices.value[index]));}
function resetVariant(){variant.value=null;change(undefined);}
function variantLabel(schema){const p=schema.properties||{};return enumLabel(resolve(p.method||p.status||p.kind)?.const??(Object.hasOwn(p,'at')?'原明确时刻':'明确原始类型'));}
function integerValue(value){change(/^(0|[1-9]\d*)$/.test(value)&&Number.isSafeInteger(Number(value))?Number(value):undefined);}
function addItem(){const items=Array.isArray(props.modelValue)?[...props.modelValue]:[];items.push(seed(effective.value.items));change(items);page.value=Math.ceil(items.length/20);}
function replaceItem(index,value){const items=[...props.modelValue];items[index]=value;change(items);}
function removeItem(index){change(props.modelValue.filter((_,i)=>i!==index));}
watch(()=>props.modelValue?.length,count=>{if(Number.isInteger(count))page.value=Math.min(page.value,Math.max(1,Math.ceil(count/20)));});
</script>

<style scoped>
fieldset{border:1px solid #dcdfe6;margin:10px 0;padding:12px}legend{font-weight:600}.array-item{border-left:3px solid #dcdfe6;padding:8px;margin:10px 0}.el-select{width:100%}.rca-field{min-width:0}
</style>
