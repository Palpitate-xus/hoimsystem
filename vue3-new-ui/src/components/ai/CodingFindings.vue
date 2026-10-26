<template>
  <section aria-label="完整病案编码证据与待复核意见">
    <p v-if="checking">正在核对完整原件、投影与逐字引文……</p>
    <el-alert v-else-if="error" :title="error" type="error" :closable="false" />
    <template v-else-if="accepted">
      <el-alert title="所有模型意见均待人工复核；文字位置一致不证明医学解释或编码适用性" type="warning" :closable="false" />
      <p>单份首页及同次住院，共 {{ source.code_bindings.length }} 项编码绑定。当前字典发行版本未知，已记录分组缺少完整历史规则依据；本地前缀规则不等于官方 DRG/DIP 分组器。</p>
      <p v-if="source.missing_document_fields.length">文书字段未记录：{{ source.missing_document_fields.map(fieldName).join('、') }}。</p>
      <p v-if="!analysis">{{ accepted.run ? stateName(accepted.run.status) : '资料预览' }}：没有已接受的模型草稿，以下仅显示原记录结构。</p>
      <el-table :data="rows.slice((page-1)*20,page*20)" aria-label="完整编码绑定与模型逐项意见" row-key="binding_token">
        <el-table-column prop="code_text" label="原编码投影" />
        <el-table-column prop="stored_name" label="已记录名称投影" />
        <el-table-column label="类型与主标记"><template #default="{row}">{{ row.kind==='diagnosis'?'诊断':row.kind==='operation'?'操作':'类型未知' }} · {{ primaryName(row.is_primary) }}</template></el-table-column>
        <el-table-column label="当前字典"><template #default="{row}">{{ dictionaryName(row.current_dictionary_state) }}<br>{{ row.current_dictionary_name ?? '未提供名称' }}</template></el-table-column>
        <el-table-column label="待复核模型主张"><template #default="{row}">{{ row.claim ? assessmentName(row.claim.model_assessment) : '无已接受草稿' }}</template></el-table-column>
        <el-table-column label="核对原文"><template #default="{row}"><el-button @click="selectedToken=row.binding_token">查看本项</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-if="rows.length>20" v-model:current-page="page" :page-size="20" :total="rows.length" layout="prev,pager,next,total" />
      <section v-if="selected" aria-label="当前编码逐项核实">
        <h4>{{ selected.code_text }} · {{ selected.stored_name }}</h4>
        <template v-if="selected.claim">
          <p>{{ assessmentName(selected.claim.model_assessment) }}：{{ selected.claim.review_note }}</p>
          <p v-if="selected.claim.clarification_question">待核实问题：{{ selected.claim.clarification_question }}</p>
          <p v-if="!selected.claim.citations.length">本项没有逐字引文，不能当作文书支持已确认。</p>
          <el-table v-else :data="selected.claim.citations" aria-label="本项模型逐字引文">
            <el-table-column label="投影文书"><template #default="{row}">{{ fieldName(source.documents.find(d=>d.source_id===row.document_source_id)?.field) }}</template></el-table-column>
            <el-table-column label="引文位置"><template #default="{row}">[{{ row.start }}, {{ row.end }})</template></el-table-column>
            <el-table-column prop="quote" label="逐字引文" />
            <el-table-column label="定位"><template #default="{row}"><el-button @click="selectCitation(row)">定位原文投影</el-button></template></el-table-column>
          </el-table>
        </template>
        <p v-else>本项尚无已接受的模型意见。</p>
      </section>
      <h4>本次模型可见文书投影</h4>
      <p>直接标识最小化不保证匿名；以下位置对应投影文字，完整私有原文仍在院内快照中。</p>
      <el-button v-for="document in source.documents" :key="document.source_id" @click="selectDocument(document)">{{ fieldName(document.field) }}</el-button>
      <template v-if="document"><p>{{ fieldName(document.field) }}</p><details><summary>文书核验标识</summary><p>UTF-8 SHA256 {{ document.text_hash }}</p></details><pre aria-label="可定位的模型可见文书投影">{{ highlight.prefix }}<mark v-if="highlight.quote">{{ highlight.quote }}</mark>{{ highlight.suffix }}</pre></template>
      <el-button @click="inspect">查看完整来源依据</el-button>
      <el-button @click="showPrivate=!showPrivate">{{ showPrivate?'收起':'展开' }}完整院内原件</el-button>
      <pre v-if="showPrivate" aria-label="完整院内编码原件">{{ JSON.stringify(packet.coding_case.snapshot,null,2) }}</pre>
    </template>
  </section>
</template>
<script setup>
import {computed,onActivated,onBeforeUnmount,onDeactivated,ref,shallowRef,watch} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical} from '@/api/inpatientSupport';
import {verifyCodingContext,verifyCodingRun,verifyCodingReceipt} from '@/api/ai/codingResults';
const props=defineProps({run:{type:Object,default:null},context:{type:Object,default:null},receipt:{type:Object,default:null},expectedPatientId:{type:Number,default:null},expectedAdmissionId:{type:String,default:null},expectedHomeId:{type:String,default:null},references:{type:Object,default:null},active:{type:Boolean,default:true},auditOnly:{type:Boolean,default:false}}),emit=defineEmits(['inspect']),store=useStore();
const accepted=shallowRef(null),checking=ref(false),error=ref(''),page=ref(1),selectedToken=ref(null),documentId=ref(null),citation=ref(null),showPrivate=ref(false),blocked=new WeakSet();let epoch=0,alive=true,paused=false;
const roles=computed(()=>Array.isArray(store.getters['user/permissions'])?store.getters['user/permissions']:[]),allowed=computed(()=>props.active&&!!store.state.user.accessToken&&(props.auditOnly?roles.value.includes('super_admin'):roles.value.some(r=>['super_admin','admin','doctor','director'].includes(r))));
const auth=()=>supportCanonical([props.active,props.auditOnly,props.expectedPatientId,props.expectedAdmissionId,props.expectedHomeId,props.references,store.state.user.accessToken,store.state.user.username,roles.value]);
const packet=computed(()=>accepted.value?.run?.coding_findings||accepted.value?.run?.frozen_request?.payload?.context||accepted.value?.context),source=computed(()=>packet.value?.coding_source),analysis=computed(()=>accepted.value?.run?.result?.coding_analysis||null);
const rows=computed(()=>{const claims=new Map((analysis.value?.claims||[]).map(c=>[c.binding_token,c]));return(source.value?.code_bindings||[]).map(row=>({...row,claim:claims.get(row.binding_token)||null}));}),selected=computed(()=>rows.value.find(r=>r.binding_token===selectedToken.value)||null),document=computed(()=>source.value?.documents.find(d=>d.source_id===documentId.value)||source.value?.documents[0]||null);
const highlight=computed(()=>{const text=document.value?.text||'',c=citation.value;if(!c||c.document_source_id!==document.value?.source_id)return{prefix:text,quote:'',suffix:''};const points=Array.from(text);return{prefix:points.slice(0,c.start).join(''),quote:points.slice(c.start,c.end).join(''),suffix:points.slice(c.end).join('')};});
const fieldName=v=>({admission_diagnosis:'入院诊断',discharge_diagnosis:'出院诊断',other_diagnosis:'其他诊断',operation_summary:'操作摘要',complication:'并发症'})[v]||'文书字段未知';
const primaryName=v=>v===1?'已记录主标记':v===0?'已记录非主标记':'主标记未知或无效';
const dictionaryName=v=>({entry_unavailable:'无当前字典项',entry_status_unknown:'字典状态未知',entry_inactive:'当前字典停用',stored_name_differs:'与当前字典名称不同',matches_current_dictionary:'与当前字典名称一致'})[v]||'当前字典状态未知';
const assessmentName=v=>({support_claim:'模型称有支持（待核实）',conflict_claim:'模型称有冲突（待核实）',insufficient_evidence:'模型称证据不足（待核实）',clarification_requested:'模型提出澄清（待核实）'})[v]||'无有效模型主张';
const stateName=v=>({queued:'排队中',running:'生成中',failed:'执行失败',cancelled:'已取消接收'})[v]||'尚未接受';
function reset(){epoch++;accepted.value=null;checking.value=false;error.value='';page.value=1;selectedToken.value=null;documentId.value=null;citation.value=null;showPrivate.value=false;}
function invalidate(){for(const item of [props.run,props.context])if(item&&typeof item==='object')blocked.add(item);reset();}
async function verify(){reset();const ticket=epoch,identity=auth(),current=()=>alive&&!paused&&allowed.value&&ticket===epoch&&identity===auth();if(!current()||!props.run&&!props.context)return;if(blocked.has(props.run||props.context)){error.value='会话或页面已变化，请重新读取完整编码证据';return;}checking.value=true;try{if(!!props.run===!!props.context)throw new Error('须分别核对一件完整任务或资料预览');const value=JSON.parse(JSON.stringify(props.run?{run:props.run}:{context:props.context})),expected={patientId:props.expectedPatientId,admissionId:props.expectedAdmissionId,homeId:props.expectedHomeId,references:props.references},options={current,auditOnly:props.auditOnly};if(props.receipt&&(!value.run||!verifyCodingReceipt(props.receipt,value.run)))throw new Error('任务回执与完整编码证据范围或Prompt模型摘要不同');const valid=value.run?await verifyCodingRun(value.run,expected,options):await verifyCodingContext(value.context,expected,options);if(!current())return;if(!valid)throw new Error('完整病案、字典集合、来源投影或逐字引文无法核对，暂不展示');accepted.value=value;}catch(failure){if(current())error.value=failure.message||'完整编码证据无法核对';}finally{if(ticket===epoch)checking.value=false;}}
function selectCitation(value){citation.value=value;documentId.value=value.document_source_id;}
function selectDocument(value){citation.value=null;documentId.value=value.source_id;}
function inspect(){const b=packet.value?.coding_binding;if(b)emit('inspect',{source_id:b.source_id,kind:'clinical_record',title:'单次住院完整病案编码原件及最小化引文投影',content:supportCanonical({coding_binding:b})});}
watch(()=>supportCanonical([store.state.user.accessToken,store.state.user.username,roles.value]),invalidate,{flush:'sync'});watch(()=>props.active,v=>{if(!v)invalidate();},{flush:'sync'});watch([()=>props.run,()=>props.context,()=>props.receipt,auth],verify,{deep:true,immediate:true,flush:'sync'});watch(selectedToken,()=>{citation.value=null;});onDeactivated(()=>{paused=true;invalidate();});onActivated(()=>{if(paused){paused=false;verify();}});onBeforeUnmount(()=>{alive=false;reset();});
</script>
<style scoped>p{line-height:1.7}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:500px;overflow:auto}.el-button{margin:6px 8px 6px 0}.el-table,.el-alert{margin:12px 0}mark{background:#ffec99;color:inherit}</style>
