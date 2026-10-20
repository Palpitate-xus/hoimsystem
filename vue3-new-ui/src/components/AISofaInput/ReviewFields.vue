<template>
  <div>
    <el-form-item v-for="field in fields" :key="field.key" :label="label(field.key)">
      <el-select v-if="field.values" :model-value="modelValue[field.key]" :aria-label="`${prefix}${label(field.key)}`" placeholder="请明确核实并选择" @update:model-value="set(field.key,$event)">
        <el-option v-for="value in field.values" :key="String(value)" :value="value" :label="valueLabel(value,field.key)" />
      </el-select>
      <el-input v-else :model-value="modelValue[field.key] ?? ''" :aria-label="`${prefix}${label(field.key)}`" type="textarea" :maxlength="field.maxLength || 1000" placeholder="记录实际核实依据；至少20个非空白字符" @update:model-value="set(field.key,$event)" />
    </el-form-item>
  </div>
</template>
<script setup>
import { computed } from "vue";
import { sofaSchemaDefinition } from "@/api/sofaSchema";
const props=defineProps({modelValue:{type:Object,required:true},definition:{type:String,required:true},modelName:{type:String,default:"AssessmentCreate"},prefix:{type:String,default:""},omit:{type:Array,default:()=>[]}}),emit=defineEmits(["update:modelValue"]);
const fieldLabels={status:"逐源用途判读",basis_note:"核实依据",exclusion_reason:"明确排除原因",qualifying_respiratory_support:"原采样时符合本版呼吸支持定义",support_qualification_basis_note:"原采样支持定义核实依据",continuous_iv:"实际连续静脉给药",rate_scope:"原给入速率口径",weight_use_confirmed:"本段原体重使用已核实",weight_basis_note:"原体重使用核实依据",mass_basis_compatible_confirmed:"原药物质量口径可计分已核实",mass_basis_note:"药物质量口径核实依据",interpretable:"同次实际GCS可判读性",sedation_confounding_status:"镇静干扰状态",other_confounding_status:"其他意识干扰状态",confounding_basis_note:"GCS干扰因素核实依据",source_inventory:"原记录清单核查完整性",clinical_protocol:"实际临床记录协议充分性",drug_exposure:"本日血管活性药暴露核实",no_other_unrepresented_exposure_confirmed:"无其他未表示药物暴露已核实",relation:"同药物全部原流的关系",relation_confirmed:"原流关系已核实",dose_basis_consistency_confirmed:"全部原流剂量基准一致已核实"};
const valueLabels={confirmed:"已明确核实",excluded:"已明确排除",unknown:"未知",yes:"明确是",no:"明确否",not_confirmed:"未确认实际连续静脉给药",stream_rate:"每条物理流速率",agent_total:"同药物患者总给入速率",limited:"原检查受限",present:"存在干扰",complete:"清单完整",incomplete:"不完整",adequate:"记录协议充分",none:"明确未暴露",reviewed_intervals:"已核查原给入区间",single_stream:"同药物单一物理流",distinct_parallel_streams:"已确认不同物理流并行",unresolved:"关系未解决",not_patient_measurement:"非本患者测量",wrong_sample_or_analyte:"原标本或项目不适用",duplicate_record:"重复登记原件",measurement_error:"原测量错误",not_applicable:"该原件不适用",conflicting_alternative:"冲突替代原件",other_clinician_reason:"其他明确临床排除依据"};
Object.assign(fieldLabels,{no_known_preexisting_organ_dysfunction:"已核实无已知既往器官功能障碍",preinfection_baseline_assumption_confirmed:"感染前基线为零的条件性假设已核实",current_presence:"当前原感染存在核实",current_presence_basis_note:"当前原感染存在核实依据",onset_review:"原感染发作时刻核实",onset_review_basis_note:"原感染发作时刻核实依据",acute_change:"急性变化临床判读",acute_change_basis_note:"急性变化临床判读依据",attribution:"感染相关归因临床判读",attribution_basis_note:"感染相关归因核实依据",temporal_relation:"当前日与原感染的时序判读",temporal_relation_basis_note:"原感染时序判读依据"});
Object.assign(valueLabels,{known:"原始发作时刻明确已知",infection_related:"临床核实与感染相关",not_related:"临床核实与感染不相关",uncertain:"归因未确定",before:"原感染之前",overlapping:"与原感染期间交叠",after:"原感染之后"});
const label=key=>fieldLabels[key]||key,valueLabel=(value,key)=>typeof value==="boolean"?(value?"明确确认（true）":"明确未确认（false）"):value==="not_confirmed"&&key!=="continuous_iv"?"未确认":(valueLabels[value]||value);
function choices(schema){if(schema.enum)return schema.enum;if(schema.type==="boolean")return [true,false];if(schema.anyOf)return schema.anyOf.flatMap(item=>choices(item)||[]);return null;}
const fields=computed(()=>Object.entries(sofaSchemaDefinition(props.modelName,props.definition)?.properties||{}).filter(([key])=>!["kind","mode","member_key","expected_content_hash","drug_key",...props.omit].includes(key)&&!(key==="exclusion_reason"&&props.modelValue.status!=="excluded")).map(([key,schema])=>({key,values:choices(schema),maxLength:schema.maxLength})));
function set(key,value){const next={...props.modelValue,[key]:value};if(key==="status")next.exclusion_reason=value==="excluded"?undefined:null;emit("update:modelValue",next);}
</script>
