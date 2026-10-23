<template>
 <div class="infection-field" :data-field="path">
  <template v-if="locked.includes(path)"><p>{{title}}：{{modelValue===undefined?'须先明确读取并绑定原件':JSON.stringify(modelValue)}}</p></template>
  <template v-else-if="nullable&&modelValue===null"><p>{{title}}：明确 null <el-button size="small" @click="change(undefined)">改为填写</el-button></p></template>
  <template v-else>
   <el-button v-if="nullable" size="small" @click="change(null)">{{title}}明确 null</el-button>
   <fieldset v-if="effective?.type==='object'"><legend>{{title}}</legend><InfectionFields v-for="(field,key) in effective.properties" :key="key" :schema="field" :root="root" :path="path?path+'.'+key:key" :locked="locked" :lookups="lookups" :model-value="modelValue?.[key]" @update:model-value="value=>change({...modelValue,[key]:value})"/></fieldset>
   <fieldset v-else-if="effective?.type==='array'"><legend>{{title}} · {{Array.isArray(modelValue)?modelValue.length+'项':'未填写'}}</legend>
    <el-button v-if="!Array.isArray(modelValue)" size="small" @click="change([])">明确{{title}}为空集合</el-button><el-button size="small" :disabled="modelValue?.length>=(effective.maxItems??Infinity)" @click="add">添加{{title}}</el-button>
    <div v-for="i in indices" :key="i"><InfectionFields :schema="effective.items" :root="root" :path="path+'.'+i" :locked="locked" :lookups="lookups" :model-value="modelValue[i]" @update:model-value="value=>replace(i,value)"/><el-button size="small" @click="remove(i)">删除{{title}}第{{i+1}}项</el-button></div>
    <el-pagination v-if="modelValue?.length>20" v-model:current-page="page" :page-size="20" :total="modelValue.length" layout="prev,pager,next,total"/><p v-if="modelValue?.length>20">分页仅控制显示，提交保留全部条目。</p>
   </fieldset>
   <el-form-item v-else-if="lookup||effective?.enum||Object.hasOwn(effective||{},'const')||effective?.type==='boolean'" :label="title"><el-select :model-value="modelValue" :aria-label="path" placeholder="明确选择，不自动确认" @update:model-value="change"><el-option v-for="item in options" :key="JSON.stringify(item.value)" :value="item.value" :label="item.label"/></el-select></el-form-item>
   <el-form-item v-else-if="effective?.type==='integer'" :label="title"><el-input :aria-label="path" :model-value="modelValue===undefined?'':String(modelValue)" inputmode="numeric" placeholder="实际整数，空白不补零" @update:model-value="integer"/></el-form-item>
   <el-form-item v-else :label="title"><el-input :aria-label="path" :model-value="modelValue??''" :type="/text|note|reference/.test(path)?'textarea':'text'" :autosize="{minRows:2,maxRows:8}" placeholder="保留原值；日期/UTC6须明确填写" @update:model-value="change"/><template v-if="/text|note|reference/.test(path)"><label>需逐字保留BOM/CRLF时明确载入原始UTF8文件 <input type="file" :aria-label="path+'原始UTF8文件'" @change="readText"/></label><p v-if="fileError" role="alert">{{fileError}}</p></template></el-form-item>
  </template>
 </div>
</template>
<script setup>
import{computed,onBeforeUnmount,ref,watch}from'vue';
defineOptions({name:'InfectionFields'});
const props=defineProps({schema:{type:Object,required:true},root:{type:Object,required:true},path:{type:String,default:''},modelValue:{default:undefined},locked:{type:Array,default:()=>[]},lookups:{type:Object,default:()=>({})}}),emit=defineEmits(['update:modelValue']),page=ref(1),fileError=ref('');let fileTicket=0;
const labels={patient_id:'实际患者标识',patient_ids:'明确有限患者集合',user_id:'获许可的实际账号标识',purpose:'本次明确用途',valid_from:'许可起点UTC六位微秒',valid_to:'许可终点UTC六位微秒',basis_note:'本次独立依据',version_label:'明确本地版本',definition_text:'完整本地监测定义原文',infection_type_codes:'审核后的感染分类代码全集',pathogen_codes:'审核后的病原分类代码全集',window:'原发病日期窗口（含首末日）',date_from:'原日期首日',date_to:'原日期末日',coordinate_basis:'日期坐标依据',definition_id:'明确已发布定义',assessment:'本件人工分类',infection_type:'原感染文字分类审核',pathogen:'原病原文字分类审核',reviewed_code:'本件已审代码',original_state:'原值 null/空串/非空状态',privacy_review:'本次隐私审核',faithfulness_review:'本次忠实性审核',parameters_review:'本次全参数审核',decision:'本次审核决定',department_ids:'全部明确科室（含零病例科室）',windows:'全部预声明比较窗口',pathogen_code:'明确病原代码分层',alpha_decimal:'明确 alpha 十进制原文',scope:'本地验证适用范围',validation_status:'明确本地验证状态',validation_evidence_reference:'实际本地验证依据引用',validation_basis_note:'本地验证范围与限制依据',alpha_decimals:'允许的明确 alpha 原文全集',source_window:'允许的原日期窗口',max_source_records:'适用原上报记录上限',max_comparisons:'适用完整比较族上限',unknown_department_policy:'未知科室处理声明',scope_basis:'适用范围依据',enabled:'是否明确启用',allowed_roles:'配置允许角色',daily_limit:'实际每日任务额度',validation_note:'启用验证依据与限制',profile_id:'明确本地版本',source_binding:'完整来源绑定',expected_feature_revision:'当前功能版本',expected_selection_revision:'当前选择版本'};
const enums={infection_surveillance_processing:'感染监测处理（本地计算用途）',external_model_transfer:'外部模型传输（独立用途）',confirmed:'本次明确审核确认',not_confirmed:'本次未确认',publish:'独立审核发布',reject:'独立审核拒绝',meets_definition:'按该定义人工判定符合',does_not_meet:'按该定义人工判定不符合',undetermined:'人工判定未确定',not_assessed:'尚未人工评估',mapped:'明确映射到已审代码',not_mapped:'明确未映射',null:'原值 null',empty:'原空串',present:'原非空文字',true:'明确是',false:'明确否',unreviewed:'尚未验证',pilot:'明确试点验证',validated:'明确记录已验证',suspended:'已暂停',super_admin:'超级管理员',admin:'管理员',director:'科主任'};
function resolve(v){for(let n=0;n<20&&v?.$ref;n++){const m=/^#\/\$defs\/([A-Za-z][A-Za-z0-9_]*)$/.exec(v.$ref);v=m?props.root.$defs?.[m[1]]:null;}return v;}
const declared=computed(()=>resolve(props.schema)),nullable=computed(()=>!!declared.value?.anyOf?.some(v=>resolve(v)?.type==='null')),effective=computed(()=>nullable.value?resolve(declared.value.anyOf.find(v=>resolve(v)?.type!=='null')):declared.value),title=computed(()=>labels[props.path.split('.').filter(k=>!/^\d+$/.test(k)).at(-1)]||props.path||'完整明确表单');
const lookup=computed(()=>props.lookups[props.path]??props.lookups[props.path.replace(/\.\d+(?=\.|$)/g,'.*')]),options=computed(()=>lookup.value||(effective.value?.enum||(Object.hasOwn(effective.value||{},'const')?[effective.value.const]:[true,false])).map(value=>({value,label:enums[String(value)]??String(value)}))),indices=computed(()=>Array.isArray(props.modelValue)?props.modelValue.map((_,i)=>i).slice((page.value-1)*20,page.value*20):[]);
const change=value=>emit('update:modelValue',value);
function integer(v){change(/^-?(0|[1-9]\d*)$/.test(v)&&Number.isSafeInteger(Number(v))?Number(v):undefined);}
function add(){const values=Array.isArray(props.modelValue)?[...props.modelValue]:[];values.push(resolve(effective.value.items)?.type==='object'?{}:undefined);change(values);page.value=Math.ceil(values.length/20);}
function replace(i,v){const values=[...props.modelValue];values[i]=v;change(values);}
const remove=i=>change(props.modelValue.filter((_,j)=>i!==j));
async function readText(event){const t=++fileTicket,file=event.target.files?.[0];fileError.value='';try{if(!file||file.size>8388608)throw Error();const value=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(await file.arrayBuffer());if(t===fileTicket)change(value);}catch{if(t===fileTicket)fileError.value='须为完整有效UTF8且不超过8MiB；没有接受截取件。';}finally{event.target.value='';}}
watch(()=>props.modelValue,()=>{fileTicket++;},{flush:'sync'});onBeforeUnmount(()=>{fileTicket++;});
watch(()=>props.modelValue?.length,n=>{if(Number.isInteger(n))page.value=Math.min(page.value,Math.max(1,Math.ceil(n/20)));});
</script>
<style scoped>fieldset{border:1px solid #dcdfe6;margin:10px 0;padding:12px}legend{font-weight:600}.el-select{width:100%}.infection-field{min-width:0}.el-button{margin:5px}</style>
