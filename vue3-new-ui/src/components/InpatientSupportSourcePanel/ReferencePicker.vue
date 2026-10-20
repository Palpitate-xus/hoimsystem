<template>
  <fieldset><legend>{{ label }}</legend>
    <el-button :loading="loading" @click="load">读取{{ label }}候选</el-button>
    <el-select :model-value="selectedId" :aria-label="label" clearable placeholder="明确选择原来源，不自动最近" @update:model-value="select"><el-option v-for="row in items" :key="identity(row)" :value="identity(row)" :label="description(row)" /></el-select>
    <p v-if="modelValue">已明确 {{ modelValue.source_id || identity(modelValue) }} · 完整摘要 {{ modelValue.content_hash }}</p><p v-if="error" role="alert">{{ error }}</p>
    <el-pagination v-if="total > 20" v-model:current-page="page" :page-size="20" :total="total" layout="prev,pager,next" @current-change="load" /><small>仅当前页目录，未列记录不表示没有资料。所有原量和时刻保留。</small>
  </fieldset>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import request from "@/utils/request";
import { getInpatientPoints } from "@/api/inpatientObservations";
import { getInpatientLabSources } from "@/api/inpatientLaboratory";
import { getSupportSources, supportHash, supportId, verifySupportSource, verifySupportPoint, verifySupportLab } from "@/api/inpatientSupport";
import { verifyVasoactiveMapping } from "@/api/vasoactiveMappings";
const props=defineProps({modelValue:{type:Object,default:null},type:{type:String,required:true},label:{type:String,required:true},patientId:{type:Number,required:true},admissionId:{type:String,required:true},mappingId:{type:String,default:""},active:{type:Boolean,default:true}}),emit=defineEmits(["update:modelValue"]);
const items=ref([]),loading=ref(false),error=ref(""),page=ref(1),total=ref(null);let sequence=0,alive=true;
const scope=()=>JSON.stringify([props.type,props.patientId,props.admissionId,props.mappingId,props.active]),identity=row=>props.type==="pao2"?row.lab_source_id:["fio2","weight"].includes(props.type)?row.observation_id:props.type==="mapping"?row.mapping_id:props.type==="respiratory_support"?row.support_source_id:props.type==="origin"?row.administration_id:row.evidence_reference?.source_id;
const selectedId=computed(()=>props.modelValue?identity(props.modelValue):"");
const description=row=>`${row.observed_at||row.collected_at_utc||row.event_at||row.name||row.snapshot?.administration?.administration_time||row.evidence_at||'原记录'} · ${identity(row)}`;
function select(id){emit("update:modelValue",items.value.find(row=>identity(row)===id)||null);}
async function load(){if(!props.active)return;const stamp=++sequence,key=scope();loading.value=true;items.value=[];error.value="";emit("update:modelValue",null);const params={patient_id:props.patientId,admission_id:props.admissionId,status:"active",page:page.value,page_size:20};try{let response;
if(["fio2","weight"].includes(props.type))response=await getInpatientPoints(params);
else if(props.type==="pao2")response=await getInpatientLabSources(params);
else if(props.type==="respiratory_support")response=await getSupportSources("respiratory_support",params);
else {const url=props.type==="mapping"?"inpatient-support/vasoactive/mapping-candidates":props.type==="origin"?"inpatient-support/vasoactive/origin-candidates":"inpatient-support/infection-evidence";response=await request({url,method:"get",params:{...params,...(props.type==="origin"&&props.mappingId?{mapping_id:props.mappingId}:{}),...(props.type.startsWith("evidence_")?{kind:props.type.slice(9)}:{})},retry:0});}
const data=response.data,rows=Array.isArray(data)?data:data?.items;if(!Array.isArray(rows))throw new Error("原来源候选目录不完整");
const accepted=[];for(let row of rows){if(row?.eligible===false)continue;if(props.type.startsWith("evidence_")){if(row?.kind!==props.type.slice(9)||!supportId(row.source_id)||!supportHash(row.expected_content_hash)||row.source_snapshot?.content_hash!==row.expected_content_hash)throw new Error("感染原证据候选绑定不一致");row={...row.source_snapshot,evidence_reference:{kind:row.kind,source_id:row.source_id,expected_content_hash:row.expected_content_hash}};}if(!row||!supportHash(row.content_hash))throw new Error("原候选缺少完整摘要");if(props.type==="mapping"){if(!await verifyVasoactiveMapping(row)||row.status!=="published"||!row.eligible)throw new Error("原药物映射未核对或尚未发布");accepted.push(row);continue;}
if((row.patient_id??row.snapshot?.patient_id)!==props.patientId||(row.admission_id??row.snapshot?.admission_id)!==props.admissionId)throw new Error("原候选与原患者或住院不一致");
if(props.type==="fio2"||props.type==="weight"){const metric=props.type==="fio2"?"fio2":"body_weight",unit=props.type==="fio2"?"%":"kg";if(!supportId(row.observation_id)||row.status!=="active"||!await verifySupportPoint(row,props.patientId,props.admissionId))throw new Error("原点测身份或治理不一致");if(row.payload?.measurements?.[metric]?.unit===unit)accepted.push(row);}
else if(props.type==="pao2"){if(row.eligible===true&&!await verifySupportLab(row,props.patientId,props.admissionId))throw new Error("原检验正文或摘要未能核对");if(row.eligible===true&&row.snapshot?.mapping?.analyte_key==="arterial_oxygen_partial_pressure")accepted.push(row);}
else if(props.type==="respiratory_support"){if(!await verifySupportSource(row,"respiratory_support",props.patientId,props.admissionId))throw new Error("呼吸支持候选正文或摘要未能核对");if(row.eligible)accepted.push(row);}
else accepted.push(row);}
if(!alive||stamp!==sequence||key!==scope())return;items.value=accepted;total.value=data.total??null;
}catch(failure){if(alive&&stamp===sequence&&key===scope())error.value=failure?.message||"原候选未能读取";}finally{if(alive&&stamp===sequence&&key===scope())loading.value=false;}}
watch(scope,()=>{sequence++;items.value=[];page.value=1;total.value=null;error.value="";loading.value=false;emit("update:modelValue",null);});onBeforeUnmount(()=>{alive=false;sequence++;});
</script>
<style scoped>fieldset{border:1px solid #ddd;margin:12px 0;padding:12px;overflow-wrap:anywhere}.el-select{width:100%;margin:8px 0}small{display:block}p{line-height:1.6}</style>
