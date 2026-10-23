<template>
 <section aria-label="有限病例来源与本地统计治理">
  <p>仅处理明确有限患者和原上报记录。原状态不等于确诊；未提供人群分母，不计算发生率、患者风险或暴发结论。</p>
  <p>本地统计只需逐患者感染监测处理许可，不外发模型。技术超级管理员仍须当前逐患者许可；独立发布不代表临床验证或自动启用。</p>
  <p v-if="!allowed">当前身份不能读取此域来源。</p>
  <template v-else>
   <el-select v-model="kind" aria-label="治理来源类型"><el-option v-for="k in options" :key="k" :value="k" :label="labels[k]"/></el-select>
   <el-button :loading="busy" @click="refresh">读取技术目录</el-button><el-button v-if="manage&&['grant','definition','review','snapshot'].includes(kind)" @click="create">{{kind==='review'?'明确患者与日期以准备逐根审核':'登记'+labels[kind]}}</el-button>
   <el-button @click="clear({all:true})">关闭并清除已读资料</el-button>
   <p v-if="error" role="alert">{{error}}</p>
   <p v-if="directory">目录仅含技术锚；共{{total}}件，未自动选择或读取正文。</p>
   <el-table v-if="directory" :data="rows" row-key="content_hash"><el-table-column label="原件标识"><template #default="{row}">{{row.record_id??row.snapshot_id??row.scenario_id??row.profile_id}}</template></el-table-column><el-table-column prop="status" label="记录状态"/><el-table-column prop="recorded_at" label="原记录UTC6"/><el-table-column label="明确读取"><template #default="{row}"><el-button @click="read(row)">{{kind==='snapshot'?'读取公开来源件':'核对本件完整证明'}}</el-button><el-button v-if="kind==='snapshot'" @click="read(row,'private')">读取院内完整原件</el-button></template></el-table-column></el-table>
   <el-pagination v-if="total>20" v-model:current-page="page" :page-size="20" :total="total" layout="prev,pager,next,total" @current-change="refresh"/>
   <div v-if="record" aria-label="已核对来源证明">
    <p v-if="piece||record.payload">已核对完整可见原件SHA与治理关系。实际当前权限与审核审计由服务器核验；私钥HMAC不是浏览器独立重投影，也不保证匿名。</p><p v-else>仅核对撤回技术回执及原不透明SHA锚；没有恢复来源正文或重建未提供的审核依据。</p>
    <p>{{record.record_id??record.snapshot_id??record.scenario_id??record.profile_id}} · {{record.governance?.status??record.status??'完整来源快照'}}</p>
    <el-button v-if="piece||record.payload" @click="full=!full">{{full?'收起完整原件':'显式展开完整原件'}}</el-button><pre v-if="full&&(piece||record.payload)" aria-label="院内完整已读原件">{{JSON.stringify(piece?.value??record,null,2)}}</pre>
    <template v-if="manage"><el-button v-if="record.governance?.status==='draft'" @click="govern(false)">独立审核本件</el-button><el-button v-if="record.governance&&['draft','published','rejected'].includes(record.governance.status)" @click="govern(true)">撤回本件</el-button><el-button v-if="kind==='definition'&&record.eligible" @click="prepareProfile">基于此定义登记本地版本</el-button><el-button v-if="kind==='profile'&&record.eligible" @click="prepareConfiguration">明确配置此本地版本</el-button><el-button v-if="piece?.part==='public'" @click="prepareScenario">从此完整来源声明比较族</el-button></template>
    <el-button v-if="piece?.part==='public'" @click="browseScenarios">读取此来源的完整场景目录</el-button><el-button v-if="kind==='scenario'&&record.eligible" @click="select">明确选择此已发布统计场景</el-button>
   </div>
   <div v-if="preview" aria-label="完整逐根审核预览"><p>本次完整{{preview.root_count}}根上报记录；未按状态裁切。尚未建立快照或审核结论。</p><el-button @click="full=!full">{{full?'收起原上报正文':'显式展开原上报正文'}}</el-button><pre v-if="full">{{JSON.stringify(preview.originals,null,2)}}</pre><el-button v-for="root in preview.originals" :key="root.original.case_id" @click="prepareReview(root)">为本根登记人工审核 {{root.original.case_id}}</el-button></div>
   <div v-if="configuration" aria-label="当前本地配置"><p>当前功能版本{{configuration.feature_revision}} / 选择版本{{configuration.selection_revision}}；明确启用{{configuration.enabled}}；验证状态{{configuration.validation_status}}。来源目的许可仍需每次独立核验。</p><pre>{{JSON.stringify(configuration,null,2)}}</pre></div>
   <div v-if="currentSchema" aria-label="明确来源治理表单"><p>所有语义选择均须显式填写。发布、隐私审核和忠实性审核不是临床资质认证；所有参数提交完整集合。</p><InfectionFields v-model="form" :schema="currentSchema" :root="currentSchema" :locked="locked" :lookups="lookups"/><el-button v-if="formPurpose==='preview'" :disabled="!formValid||busy" @click="previewRoots">读取本次全部上报根以审核</el-button><el-button v-else :disabled="!formValid||busy" @click="submit">明确提交本次完整{{formPurpose==='review'?'独立审核':formPurpose==='revoke'?'撤回':'登记或配置'}}</el-button><el-button @click="clear()">取消本次表单并清除正文</el-button></div>
  </template>
 </section>
</template>
<script setup>
import InfectionFields from'./InfectionFields.vue';import{useInfectionSources}from'./useInfectionSources';
const props=defineProps({active:{type:Boolean,default:true},governance:{type:Boolean,default:false}}),emit=defineEmits(['select','source-changed','invalidate']);
const labels={snapshot:'完整病例来源快照',grant:'独立患者目的许可',definition:'本地人工监测定义',review:'逐根人工分类与文字映射',scenario:'完整预声明比较族',profile:'本地统计版本与验证范围',configuration:'本地配置与启用状态'};
const{kind,page,directory,record,piece,preview,full,busy,error,form,formPurpose,currentSchema,locked,lookups,configuration,allowed,manage,options,rows,total,formValid,refresh,read,clear,create,previewRoots,prepareReview,prepareScenario,prepareProfile,govern,prepareConfiguration,submit,select,browseScenarios}=useInfectionSources(props,emit);
</script>
<style scoped>section{min-width:0}p{line-height:1.65;overflow-wrap:anywhere}.el-button{margin:5px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:65vh;overflow:auto;border:1px solid #dcdfe6;padding:12px}.el-select{min-width:250px}</style>
