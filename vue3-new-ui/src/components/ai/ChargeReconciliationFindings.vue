<template>
 <section aria-label="完整住院账目证据与待核实问题">
  <el-button v-if="allowed&&(checking||accepted)" @click="close">关闭完整账目结果</el-button>
  <p v-if="!allowed">当前身份不能读取完整账目结果。</p>
  <p v-else-if="checking" role="status">正在核对完整原件、任务、实际用量及逐字引文。</p>
  <p v-else-if="error" role="alert">{{error}}</p>
  <p v-else-if="closed">结果已关闭，请显式重新读取完整账目结果。</p>
  <template v-else-if="accepted&&source">
   <p>以下为待核实的账目问题，不作收费或退款结论。请结合原记录和适用收费依据人工复核；未提示问题也不代表全部正确。</p>
   <p aria-label="完整冻结五类账目计数">{{counts.map(r=>r.label+r.count+'条').join('、')}}。记录条数不表示服务发生次数、应收费次数或资金笔数。</p>
   <p aria-label="完整收费医嘱关联状态">{{associations.map(r=>associationName(r.state)+r.count+'条').join('、')}}。医嘱层级关联不证明逐收费行与项目或执行之间的实际分摊。</p>
   <p>已记录的结算、退费状态和押金汇总不能证明实际资金收退；币种、历史价目与收费适用依据尚缺。</p>
   <p v-if="run" aria-label="本件账目任务状态">{{stateName(run.status)}}；任务{{run.run_id}}。</p>
   <p v-if="usage" aria-label="本件实际模型用量">输入token：{{tokenName(usage.input_tokens)}}；输出token：{{tokenName(usage.output_tokens)}}；{{attemptName(usage.model_call_attempted)}}；{{usage.complete?'用量已完整记录':'用量尚不完整'}}。</p>
   <p v-if="!analysis">本件没有已接受的模型草稿，仅显示已核对的完整原记录范围。</p>
   <template v-else>
    <p aria-label="部分模型问题覆盖范围">本次{{observations.length}}项待核实问题，最多128项；覆盖范围不完整，不表示财务结论或完整排查。</p>
    <el-table v-if="observations.length" :data="observations.slice((questionPage-1)*20,questionPage*20).map((row,index)=>({...row,index:(questionPage-1)*20+index}))" aria-label="部分模型待人工核实问题">
     <el-table-column label="问题类型"><template #default="{row}">{{questionName(row.kind)}}</template></el-table-column><el-table-column prop="review_note" label="模型待核实说明"/><el-table-column prop="clarification_question" label="模型澄清问题"/>
     <el-table-column label="引用核对"><template #default="{row}"><el-button @click="chooseQuestion(row.index)">核对本项引用</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-if="observations.length>20" v-model:current-page="questionPage" :page-size="20" :total="observations.length" layout="prev,pager,next,total"/>
    <section v-if="question" aria-label="本项模型逐字依据">
     <p>{{questionName(question.kind)}}；仅引用本件{{question.referenced_source_ids.length}}条原记录。</p>
     <p v-if="!question.citations.length">本项未提供逐字引文，现有证据不足，不能视为已确认。</p>
     <el-table v-else :data="question.citations" aria-label="本项模型投影逐字引文"><el-table-column prop="source_id" label="原记录引用"/><el-table-column label="显示字段"><template #default="{row}">{{fieldName(row.field)}}</template></el-table-column><el-table-column label="引文位置"><template #default="{row}">[{{row.start}}, {{row.end}})</template></el-table-column><el-table-column prop="quote" label="逐字引文"/><el-table-column label="定位"><template #default="{row}"><el-button @click="locate(row)">定位本字段投影</el-button></template></el-table-column></el-table>
    </section>
   </template>
   <template v-if="projection"><p>{{fieldName(projection.field)}} · [{{projection.start}}, {{projection.end}})，仅对应模型所见字段的Unicode码点；不是原私有全文位置。</p><pre aria-label="精确模型字段投影定位">{{projection.prefix}}<mark>{{projection.quote}}</mark>{{projection.suffix}}</pre></template>
   <el-select :model-value="group" @update:model-value="changeGroup" aria-label="模型可见账目集合"><el-option v-for="[key,label] in chargeGroups" :key="key" :value="key" :label="label+'（'+source[key].length+'）'"/></el-select><el-button @click="showPublic=!showPublic">{{showPublic?'收起本组模型可见字段':'展开本组模型可见字段'}}</el-button>
   <template v-if="showPublic"><p>已做已知直接标识最小化，不保证匿名；这些是模型所见投影。</p><el-table :data="source[group].slice(memberPage*20,memberPage*20+20)" aria-label="完整模型可见原记录分页"><el-table-column label="已核对字段"><template #default="{row}"><pre>{{JSON.stringify(row,null,2)}}</pre><p v-if="Object.hasOwn(row,'status')">原状态解释：{{chargeRecordedStateLabel(group,'status',row.status)}}</p></template></el-table-column></el-table><el-button :disabled="memberPage===0" @click="memberPage--">上一页模型原记录</el-button><el-button :disabled="(memberPage+1)*20>=source[group].length" @click="memberPage++">下一页模型原记录</el-button></template>
   <details><summary>账目来源与数值核验详情</summary><p>旧时钟的时区未知；浮点驱动表示和MySQL见证均不是最初输入的精确十进制。</p><p aria-label="本件账目可见哈希范围">完整原件、公开投影、来源绑定和已接受结果按当前可见内容核对；任务原始输入、证据及元数据的字节SHA仅为服务端锚点。{{accepted.trace?'本次Super审计另有原始JSON字节与Prompt/Provider摘要，已逐字核对。':'本件没有原始任务JSON字节，不声称已在浏览器重建这些字节摘要。'}}</p>
   <p>公开投影SHA {{packet.charge_binding.projection_hash}}；完整原件SHA {{packet.charge_binding.content_hash}}。</p></details>
   <el-button @click="inspect">查看完整账目来源依据</el-button><el-button @click="showPrivate=!showPrivate">{{showPrivate?'收起完整院内账目原件':'展开完整院内账目原件'}}</el-button><pre v-if="showPrivate" aria-label="完整院内冻结账目原件">{{JSON.stringify(caseProof.snapshot,null,2)}}</pre>
   <template v-if="accepted.trace&&superAdmin"><el-button @click="showTrace=!showTrace">{{showTrace?'收起Super原始任务字节':'展开Super原始任务字节'}}</el-button><p v-if="showTrace">以下以JSON转义形式展示原始字节字符串；核验使用字符串的原UTF8字节。</p><pre v-if="showTrace" aria-label="Super原始任务JSON字节">{{JSON.stringify(accepted.trace.raw_frozen_json,null,2)}}</pre></template>
  </template>
 </section>
</template>
<script setup>
import{useChargeReconciliationFindings,chargeGroups}from'./useChargeReconciliationFindings';
const props=defineProps({run:{type:Object,default:null},context:{type:Object,default:null},receipt:{type:Object,default:null},trace:{type:Object,default:null},expectedPatientId:{type:Number,default:null},expectedAdmissionId:{type:String,default:null},expectedRunId:{type:String,default:null},references:{type:Object,default:null},active:{type:Boolean,default:true},auditOnly:{type:Boolean,default:false},configurationKey:{type:[String,Number],default:null}}),emit=defineEmits(['inspect','invalidate']);
const{allowed,superAdmin,accepted,checking,error,closed,packet,source,caseProof,run,result,analysis,observations,question,counts,associations,usage,projection,questionPage,group,memberPage,showPublic,showPrivate,showTrace,close,chooseQuestion,locate,changeGroup,inspect,fieldName,questionName,stateName,associationName,tokenName,attemptName,chargeRecordedStateLabel}=useChargeReconciliationFindings(props,emit);
</script>
<style scoped>p{line-height:1.7;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:480px;overflow:auto}.el-button{margin:6px}.el-select{min-width:280px}mark{background:#ffec99;color:inherit}</style>
