<template>
 <section aria-label="本地有限病例关联统计助手">
  <p v-if="!modeValid" role="alert">当前功能、引用或业务范围不属于受审本地病例统计，旧通用入口已关闭。</p>
  <template v-else-if="authenticated">
   <p>本地固定精确统计，无外部Provider、不调用LLM。明确有限病例集内比较；没有人群分母、发生率、患者风险、暴发诊断或自动处置。</p>
   <InfectionInput v-if="executionRole" :key="childKey" :active="active" :initial-references="initialInput" @selection="selection" @availability="availability" @invalidate="unavailable"/>
   <el-checkbox v-if="canPreviewUnvalidated" v-model="previewMode">明确试运行未启用或未验证的本地版本（仍核逐患者用途）</el-checkbox>
   <el-button :disabled="!canCreate||busy" @click="preview">预览当前完整统计来源</el-button><el-button :disabled="!canCreate||busy" @click="create">明确创建本地统计任务</el-button><el-button @click="clear({all:true})">关闭并清除本次任务资料</el-button>
   <p v-if="error" role="alert">{{error}}</p>
   <div v-if="context" aria-label="已核对本地统计预览"><p>已完整核对公开来源与预声明族，{{context.source.source.reports.length}}根原记录。没有创建任务或调用模型。</p><el-button @click="previewOpen=!previewOpen">{{previewOpen?'收起完整预览':'显式展开完整预览'}}</el-button><pre v-if="previewOpen">{{JSON.stringify(context,null,2)}}</pre></div>
   <div v-if="metadata" aria-label="当前已核验任务技术状态"><p>任务{{metadata.run_id}} · {{metadata.status}}；收据{{metadata.usage_receipt_status}}。</p><p v-if="metadata.usage">外部tokens {{metadata.usage.input_tokens}}/{{metadata.usage.output_tokens}}，模型调用明确否；CPU尝试{{tri(metadata.usage.calculation_attempted)}}、完成{{tri(metadata.usage.calculation_completed)}}。</p><p v-else>本地计算尝试与用量尚待实际记录，不视为零或未计算。</p><el-button :disabled="busy" @click="refresh">刷新本任务技术状态</el-button><el-button :disabled="busy||!executionRole" @click="inspect(metadata,{clinical:true})">显式读取本任务完整来源和结果</el-button><el-button v-if="['queued','running'].includes(metadata.status)" :disabled="busy" @click="cancel">仅停止本任务</el-button></div>
   <InfectionFindings v-if="detail" :value="detail" :active="active" @invalidate="invalidateParts" @closed="invalidateParts"/>
   <el-button :disabled="busy" @click="loadHistory">读取本地任务技术目录</el-button><el-table v-if="history" :data="history.items" row-key="run_id" aria-label="本地任务技术目录"><el-table-column prop="run_id" label="真实任务标识"/><el-table-column prop="status" label="当前状态"/><el-table-column prop="usage_receipt_status" label="实际收据"/><el-table-column label="显式读取"><template #default="{row}"><el-button @click="inspect(row)">只读本条技术状态</el-button><el-button v-if="executionRole" @click="inspect(row,{clinical:true})">查看本次来源与结果</el-button></template></el-table-column></el-table><el-pagination v-if="history?.total>20" v-model:current-page="page" :page-size="20" :total="history.total" layout="prev,pager,next,total" @current-change="loadHistory"/>
  </template>
  <p v-else>当前会话不可用，未恢复旧来源或结果。</p>
 </section>
</template>
<script setup>
import{ref,watch}from'vue';import InfectionInput from'./InfectionInput.vue';import InfectionFindings from'./InfectionFindings.vue';import{useInfectionAssistant}from'./useInfectionAssistant';
const props=defineProps({feature:{default:null},featureKey:{default:'infection_cluster'},initialInput:{default:null},patientId:{default:null},encounterRef:{default:null},departmentId:{default:null},pharmaceuticalId:{default:null},active:{type:Boolean,default:true}}),emit=defineEmits(['invalidate','task-created','task-changed']),previewOpen=ref(false);
const{metadata,detail,context,error,busy,history,page,childKey,previewMode,modeValid,authenticated,executionRole,canPreviewUnvalidated,canCreate,clear,unavailable,selection,availability,preview,create,inspect,refresh,cancel,loadHistory,invalidateParts}=useInfectionAssistant(props,emit);
const tri=v=>v===true?'是':v===false?'否':'未知';watch(context,()=>previewOpen.value=false);
</script>
<style scoped>p{line-height:1.7;overflow-wrap:anywhere}.el-button{margin:5px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:60vh;overflow:auto}</style>
