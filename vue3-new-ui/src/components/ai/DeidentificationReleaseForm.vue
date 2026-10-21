<template>
 <section aria-label="明确单件导出依据表单"><p>登记独立导出依据、明确收件范围和有效期；不会取得额外研究读取或外部模型权限。</p>
  <fieldset :disabled="busy">
   <el-form-item label="原记录导出依据状态"><el-select v-model="f.authority_status" aria-label="原记录导出依据状态" placeholder="请明确选择"><el-option label="未知" value="unknown"/><el-option label="已记录明确许可" value="recorded_permitted"/><el-option label="明确不允许" value="not_permitted"/></el-select></el-form-item>
   <el-checkbox v-model="referenceKnown" aria-label="提供导出依据引用">明确提供导出依据引用</el-checkbox><el-input v-if="referenceKnown" v-model="f.authority_reference" aria-label="导出依据引用"/>
   <el-checkbox v-model="authorityKnown" aria-label="提供完整导出依据原文">明确提供完整导出依据原文</el-checkbox><template v-if="authorityKnown"><p>可明确输入本次文字声明；完整原UTF8文件请直接选取，保留BOM及CRLF字节。</p><el-input v-if="rawAuthority===null" v-model="f.original_authority_text" type="textarea" aria-label="完整导出依据原文"/><input type="file" accept=".txt,.md" aria-label="完整导出依据UTF8原文件" @change="readAuthority"/><pre v-if="rawAuthority!==null" aria-label="完整导出依据文件原文">{{ rawAuthority }}</pre><el-button v-if="rawAuthority!==null" @click="clearAuthority">清除此完整依据文件</el-button></template>
   <el-form-item label="明确收件范围"><el-select v-model="f.recipient_scope" aria-label="明确收件范围" placeholder="请明确选择"><el-option label="院内明确收件人" value="internal_named_recipient"/><el-option label="明确外部收件人" value="explicit_external_recipient"/></el-select></el-form-item>
   <el-form-item label="明确收件人依据"><el-input v-model="f.recipient_reference" aria-label="明确收件人依据"/></el-form-item>
   <el-form-item label="本次完整导出目的"><el-input v-model="f.declared_purpose" type="textarea" aria-label="本次完整导出目的"/></el-form-item>
   <el-form-item label="有效期是否明确"><el-radio-group v-model="periodKnown" aria-label="导出有效期是否明确"><el-radio :label="true">明确填写原UTC6</el-radio><el-radio :label="false">未知，保留NULL</el-radio></el-radio-group></el-form-item>
   <template v-if="periodKnown===true"><el-input v-model="f.valid_from" aria-label="导出有效起始UTC6" placeholder="YYYY-MM-DDTHH:mm:ss.ffffffZ"/><el-input v-model="f.valid_until" aria-label="导出有效结束UTC6" placeholder="YYYY-MM-DDTHH:mm:ss.ffffffZ"/></template>
   <el-form-item label="最大单件下载次数1至100"><el-input v-model="maximum" aria-label="最大单件下载次数"/></el-form-item>
   <el-checkbox v-model="f.residual_risk_acknowledged" aria-label="确认导出仍有残余风险">确认选定输出仍有残余风险，没有匿名保证</el-checkbox>
   <el-form-item label="完整放行登记依据"><el-input v-model="f.basis_note" type="textarea" aria-label="完整放行登记依据"/></el-form-item>
   <el-button @click="submit">登记单件导出放行草稿</el-button>
  </fieldset><p v-if="error" role="alert">{{ error }}</p>
 </section>
</template>
<script setup>
import{onBeforeUnmount,reactive,ref,watch}from'vue';import{deidentificationRequestValid}from'@/api/ai/deidentificationSources';import{deidentificationUtf8}from'@/api/ai/deidentificationCore';
const props=defineProps({review:{type:Object,required:true},busy:Boolean}),emit=defineEmits(['submit','change']);
const f=reactive({authority_status:null,authority_reference:'',original_authority_text:'',recipient_scope:null,recipient_reference:'',declared_purpose:'',valid_from:'',valid_until:'',residual_risk_acknowledged:false,basis_note:''}),periodKnown=ref(null),referenceKnown=ref(false),authorityKnown=ref(false),maximum=ref(''),error=ref(''),rawAuthority=ref(null);let version=0;
function submit(){if(props.busy)return;const body={review_id:props.review.review_id,expected_content_hash:props.review.content_hash,expected_governance_hash:props.review.governance_hash,...f,authority_reference:referenceKnown.value?f.authority_reference:null,original_authority_text:authorityKnown.value?(rawAuthority.value===null?f.original_authority_text:rawAuthority.value):null,valid_from:periodKnown.value===true?f.valid_from:null,valid_until:periodKnown.value===true?f.valid_until:null,maximum_downloads:/^[1-9]\d*$/.test(maximum.value)?Number(maximum.value):null};if(periodKnown.value===null||!deidentificationRequestValid('ReleaseCreate',body)){error.value='请逐项明确完整依据、收件人、有效期状态和下载次数，未知不会补成许可。';return;}emit('submit',body);}
watch([f,periodKnown,referenceKnown,authorityKnown,maximum,rawAuthority],()=>{version++;error.value='';emit('change');},{deep:true,flush:'sync'});
function clearAuthority(){if(!props.busy){rawAuthority.value=null;version++;}}
async function readAuthority(event){if(props.busy||!authorityKnown.value)return;const file=event.target.files?.[0];rawAuthority.value=null;const t=++version;try{if(!file||!Number.isSafeInteger(file.size)||file.size<1||file.size>65535||!/\.(txt|md)$/iu.test(file.name))throw new Error('file');const wire=new Uint8Array(await file.arrayBuffer()),text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(wire),encoded=deidentificationUtf8(text);if(encoded.length!==wire.length||!encoded.every((v,i)=>v===wire[i]))throw new Error('bytes');if(t===version&&authorityKnown.value)rawAuthority.value=text;}catch{if(t===version)error.value='完整依据文件必须是不超过65535字节的严格UTF8 txt/md，未替换字符或改换行。';}}
watch(authorityKnown,value=>{if(!value)rawAuthority.value=null;},{flush:'sync'});onBeforeUnmount(()=>{version++;});
</script>
<style scoped>fieldset{border:1px solid #ddd;padding:12px}.el-input,.el-select{width:100%}.el-checkbox{display:flex;height:auto;white-space:normal;margin:12px 0}[role=alert]{color:#b42318}</style>
