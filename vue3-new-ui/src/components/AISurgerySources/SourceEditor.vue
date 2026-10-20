<template>
  <el-form label-position="top" aria-label="手术受控来源原件录入">
    <p>只登记本条原件，不生成排台。原未知、空值、零、否及空集合须按原资料明确填写；完整原件将独立留存并等待审核。</p>
    <p v-if="clinical">已绑定原手术申请 {{ applicationId }}。专业签署使用当前真实医师别名与实际照护权限；超级管理员审核不代替签署。</p>
    <p v-else>已绑定明确物理资源 {{ resourceId }}。此录入不确认岗位资格、全地点覆盖或优化可行性。</p>
    <template v-if="clinical">
      <el-form-item label="本条原专业核实状态"><el-select v-model="professionalStatus" aria-label="本条原专业核实状态"><el-option label="原专业核实未知，不伪造签署" value="unknown" /><el-option label="当前实际医师明确核实并签署" value="confirmed" /></el-select></el-form-item>
      <template v-if="professionalStatus==='confirmed'"><el-form-item label="当前真实医师别名"><el-select v-model="signerDoctorId" aria-label="当前真实医师别名"><el-option v-for="doctor in clinicalSigners" :key="doctor.doctor_id" :value="doctor.doctor_id" :label="doctor.name+' · #'+doctor.doctor_id" /></el-select></el-form-item><el-form-item label="本条原专业核实依据"><el-input v-model="professionalBasis" aria-label="本条原专业核实依据" type="textarea" :autosize="{minRows:3,maxRows:8}" placeholder="至少20个非空白字符，不超过4000 UTF-8字节" /></el-form-item></template>
    </template>
    <SurgeryFields v-if="schema" :key="kind" v-model="payload" :schema="schema.properties.payload" :root="schema" label="本条原资料" />
    <p role="status">{{ valid?'全部原字段与明确缺项通过本地类型核对，仍须服务器核当前范围与完整原件。':'原字段、明确缺项或专业核实尚不完整；保存按钮保持不可用。' }}</p>
  </el-form>
</template>

<script setup>
import {computed,ref,watch} from 'vue';
import SurgeryFields from './SurgeryFields.vue';
import {surgeryFormSchema,surgeryRequestValid} from '@/api/ai/surgerySources';
const props=defineProps({kind:{type:String,required:true},poolId:{type:String,required:true},resourceId:{type:String,default:null},applicationId:{type:String,default:null},clinicalSigners:{type:Array,default:()=>[]}}),emit=defineEmits(['validity']);
const schema=computed(()=>{const value=surgeryFormSchema('SourceCreate',props.kind);localVariants(value.properties.payload);return value;}),payload=ref({}),professionalStatus=ref(null),signerDoctorId=ref(null),professionalBasis=ref('');
// Protected busy originals are created by the explicit server-witness flow,
// never by asking an operator to invent basis/protected-witness hashes.
function localVariants(value){if(value&&typeof value==='object'){if(Array.isArray(value.oneOf))value.oneOf=value.oneOf.filter(branch=>branch.$ref!=='#/$defs/BusyPayload').map(localVariants);for(const[key,item]of Object.entries(value))if(key!=='oneOf'&&item&&typeof item==='object')localVariants(item);}return value;}

const clinical=computed(()=>['case_requirements','duration_observation','case_duration_estimate'].includes(props.kind));
const requestBody=computed(()=>({pool_id:props.poolId,resource_id:clinical.value?null:props.resourceId,application_id:clinical.value?props.applicationId:null,payload:payload.value,professional_attestation:clinical.value?{status:professionalStatus.value,signer_doctor_id:professionalStatus.value==='confirmed'?signerDoctorId.value:null,basis_note:professionalStatus.value==='confirmed'?professionalBasis.value:null}:{status:'unknown',signer_doctor_id:null,basis_note:null}}));
const valid=computed(()=>surgeryRequestValid('SourceCreate',requestBody.value)&&(!clinical.value||props.clinicalSigners.length>0&&props.applicationId!==null&&(professionalStatus.value!=='confirmed'||props.clinicalSigners.some(d=>d.doctor_id===signerDoctorId.value))));
watch(()=>[props.kind,props.poolId,props.resourceId,props.applicationId,JSON.stringify(props.clinicalSigners)],()=>{payload.value={kind:props.kind};professionalStatus.value=null;signerDoctorId.value=null;professionalBasis.value='';},{immediate:true});
watch([requestBody,valid],()=>emit('validity',{valid:valid.value,request:valid.value?JSON.parse(JSON.stringify(requestBody.value)):null}),{deep:true,immediate:true});
</script>
