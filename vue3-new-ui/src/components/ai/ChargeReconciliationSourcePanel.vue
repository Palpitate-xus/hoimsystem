<template>
 <section aria-label="完整住院账目来源治理">
  <p v-if="!allowed">当前身份不能读取账目依据。</p>
  <template v-else>
   <p>保留本次住院全部收费、医嘱、原项目、执行和eMAR记录。已结算或已退费只是原记录状态，实收、实退、币种和收费资格仍需独立证据；不会自动收费或退款。</p>
   <p v-if="!scopeReady&&!auditOnly">请从已授权患者的真实住院记录进入，不能猜测标识。</p>
   <p v-if="auditOnly">Super全院技术审计；原件发布不代表财务专业确认。</p>
   <el-button :loading="loading" @click="reload">重新读取账目目录</el-button>
   <el-button v-if="scopeReady&&options?.can_record" @click="openCreate">捕获完整住院账目</el-button>
   <p v-if="error" role="alert">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
   <el-table v-if="directory" :data="directory.items" border aria-label="账目原件元数据目录">
    <el-table-column prop="case_snapshot_id" label="账目原件" min-width="300"/><el-table-column prop="status" label="治理状态"/><el-table-column prop="revision" label="版本"/><el-table-column prop="created_at" label="服务器UTC登记时刻" min-width="230"/>
    <el-table-column label="操作"><template #default="{row}"><el-button @click="inspect(row)">核对完整账目原件</el-button></template></el-table-column>
   </el-table>
   <div v-if="directory&&directory.total>20"><el-button :disabled="page===1||loading" @click="changePage(-1)">上一页原件</el-button><span>第{{page}}页，共{{directory.total}}件</span><el-button :disabled="page*20>=directory.total||loading" @click="changePage(1)">下一页原件</el-button></div>
   <p v-if="inspecting" role="status">正在核对完整原件与当前授权。</p>
   <article v-if="detail" aria-label="已核对住院账目原件">
    <el-button @click="clearDetail(true)">关闭账目原件</el-button>
    <p>原件{{detail.source_id}}；治理版本{{detail.revision}}。</p>
    <p v-if="!detail.eligible">当前不可用于新任务：{{detail.ineligibility_reasons.join('、')}}。</p>
    <template v-if="detail.snapshot">
     <p>完整原件SHA {{detail.content_hash}}；完整{{detail.snapshot.collection.member_manifest.length}}个成员。</p>
     <el-select v-model="group" aria-label="完整账目原集合" @change="memberPage=0"><el-option v-for="[key,label] in groups" :key="key" :value="key" :label="label+'（'+detail.snapshot.collection[key].length+'）'"/></el-select>
     <el-table :data="detail.snapshot.collection[group].slice(memberPage*20,memberPage*20+20)" border aria-label="完整账目原记录分页"><el-table-column label="原始记录"><template #default="{row}"><pre>{{JSON.stringify(row,null,2)}}</pre></template></el-table-column></el-table>
     <el-button :disabled="memberPage===0" @click="memberPage--">上一页原记录</el-button><el-button :disabled="(memberPage+1)*20>=detail.snapshot.collection[group].length" @click="memberPage++">下一页原记录</el-button>
     <p>旧时间的时区依据未知；数量保留数据库读取的原表示、NULL与零，不将其当作现金或自动计费依据。</p>
     <el-button @click="showRaw=!showRaw">{{showRaw?'收起院内完整原件':'展开院内完整原件'}}</el-button><pre v-if="showRaw" aria-label="授权院内完整账目正文">{{JSON.stringify(detail.snapshot,null,2)}}</pre>
    </template>
    <p v-else>本件原文与审核说明当前不可读。展示的是元数据及保留哈希锚点，没有恢复隐藏正文。</p>
    <el-button v-if="!auditOnly&&detail.eligible" @click="selectDetail" :loading="inspecting">选择本件完整账目</el-button>
    <template v-if="detail.can_review||detail.can_revoke"><el-form-item label="本次审核或撤销依据"><el-input v-model="basis" type="textarea" aria-label="本次账目治理依据" :disabled="governing" placeholder="至少20个非空白字符；撤销最多1000个Unicode字符、4000 UTF8字节"/></el-form-item>
     <el-button v-if="detail.can_review&&options?.can_review" :disabled="governing||!api.chargeSourceBasis(basis)" @click="govern('publish')">审核发布账目原件</el-button><el-button v-if="detail.can_review&&options?.can_review" :disabled="governing||!api.chargeSourceBasis(basis)" @click="govern('reject')">审核拒绝账目原件</el-button><el-button v-if="detail.can_revoke" :disabled="governing||!api.chargeSourceRevokeBasis(basis)" @click="govern('revoke')">撤销本件账目原件</el-button>
    </template>
   </article>
   <el-dialog :model-value="creating" title="捕获完整住院账目" @update:model-value="value=>{if(!value)closeCreate();}">
    <p>仅当前真实患者{{patientId}}、Admission{{admissionId}}。捕获全部成员，不从未记录推断零、不按同患者和时间猜执行关联。</p>
    <el-button :loading="previewing" @click="capture">重新捕获完整五类原件</el-button>
    <p v-if="preview" aria-label="完整账目捕获摘要">已核对{{preview.member_manifest.length}}个成员；{{groups.map(([key,label])=>label+preview[key].length+'条').join('、')}}。集合SHA {{preview.collection_digest}}</p>
    <el-form-item label="本次登记说明"><el-input v-model="note" type="textarea" aria-label="本次账目登记说明" :disabled="saving" placeholder="可留空；最多4000 UTF8字节"/></el-form-item>
    <el-button :disabled="!createValid||saving||previewing" :loading="saving" @click="save">登记完整账目草稿</el-button><el-button @click="closeCreate">关闭捕获</el-button>
   </el-dialog>
  </template>
 </section>
</template>
<script setup>
import{useChargeReconciliationSources}from'./useChargeReconciliationSources';
const props=defineProps({patientId:{type:Number,default:null},admissionId:{type:String,default:null},auditOnly:{type:Boolean,default:false},active:{type:Boolean,default:true}}),emit=defineEmits(['select','source-changed','invalidate']);
const{allowed,scopeReady,options,directory,detail,preview,loading,inspecting,creating,previewing,saving,governing,error,notice,note,basis,page,showRaw,group,memberPage,createValid,closeCreate,clearDetail,load,reload,inspect,selectDetail,openCreate,capture,save,govern,changePage,api}=useChargeReconciliationSources(props,emit);
const groups=[['charges','收费原行'],['orders','医嘱原单'],['order_items','医嘱原项目'],['executions','原执行记录'],['administrations','eMAR原记录']];
</script>
<style scoped>p{line-height:1.7;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:420px;overflow:auto}.el-button{margin:6px}.el-select{min-width:280px}</style>
