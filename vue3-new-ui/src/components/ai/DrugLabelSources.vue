<template>
  <section class="drug-label-sources" aria-label="药品说明书来源治理">
    <el-alert title="请核对药品目录和完整说明书。厂家、批准号、规格和单位需在原文中确认。" type="info" :closable="false" />
    <p v-if="!v.authorized" role="status">仅当前药师或超级管理员可访问本项已释放来源。</p>
    <template v-else>
      <el-button :loading="v.loading" @click="v.refresh">刷新来源目录</el-button>
      <el-select v-model="v.selectedId" aria-label="明确选择目录药品" placeholder="从真实目录明确选择药品" clearable filterable :disabled="pharmaceuticalId!==null"><el-option v-for="item in v.catalog" :key="item.identity.pharmaceutical_id" :value="item.identity.pharmaceutical_id" :label="`${item.identity.name===null?'名称未记录':item.identity.name}（目录${item.identity.pharmaceutical_id}）`" /></el-select>
      <el-button v-if="!v.catalogComplete&&pharmaceuticalId===null" :loading="v.loading" @click="v.moreCatalog">加载下一页药品</el-button>
      <p v-if="v.selectedSku">本项比较：名称 {{ display(v.selectedSku.identity.name) }}；条码 {{ display(v.selectedSku.identity.barcode) }}；记录启停值 {{ display(v.selectedSku.identity.status) }}。库存、价格、批次和供应商不在说明书身份比较范围。</p>
      <p v-if="auditOnly">超级管理员冻结审计：原件与原签署可供核对，不恢复当前执行或治理资格。</p>
      <el-button v-if="v.options?.can_release&&!auditOnly" :disabled="!v.selectedSku||v.busy" @click="v.openCreate">关联已发布说明书原件</el-button>
      <p v-if="v.error" role="alert">{{ v.error }}</p><p v-if="v.notice" role="status">{{ v.notice }}</p>
      <p v-if="!v.selectedId&&!auditOnly">尚未选择药品；不会自动选取第一项。</p>
      <el-table :data="v.directory" aria-label="说明书来源完整元数据目录"><el-table-column label="来源标识" prop="source_binding_id" /><el-table-column label="目录药品" prop="pharmaceutical_id" /><el-table-column label="状态"><template #default="{row}">{{ states[row.status] }}</template></el-table-column><el-table-column label="登记UTC" prop="recorded_at" /><el-table-column label="核对"><template #default="{row}"><el-button @click="v.inspect(row)">读取本件完整依据</el-button></template></el-table-column></el-table>
      <p>请选择一份原文，核对内容和签署记录后再抽取。</p>
    </template>
    <el-dialog v-model="v.detailOpen" title="说明书原件与独立签署核对" width="85%" :close-on-click-modal="false">
      <template v-if="v.detail">
        <p>目录药品：{{ display(v.detail.snapshot.identity.name) }}；声明版本：{{ v.detail.snapshot.original.snapshot.metadata.version }}。官方版本真实性与完整官方说明书覆盖未知。</p>
        <p>来源状态：{{ states[v.detail.governance.status] }}；当前使用资格：{{ v.detail.eligible?'满足本项当前来源条件':'未满足，不能执行' }}。</p>
        <p>原UTF8 {{ v.detail.snapshot.original.snapshot.raw_bytes_length }} 字节；Unicode codepoint {{ v.detail.snapshot.original.snapshot.codepoint_length }}；原字节SHA256：<code>{{ v.detail.snapshot.original.snapshot.raw_bytes_hash }}</code></p>
        <el-button @click="v.showText=!v.showText">{{ v.showText?'收起完整说明书':'显式展开完整说明书' }}</el-button><pre v-if="v.showText" aria-label="完整说明书原文">{{ v.detail.snapshot.original.snapshot.text }}</pre>
        <p>释放依据：{{ v.detail.snapshot.basis_note }}</p>
        <template v-if="v.detail.professional_review"><p>药师签署：目录对应 {{ reviews[v.detail.professional_review.snapshot.catalog_match_review] }}；本次完整提供版本 {{ reviews[v.detail.professional_review.snapshot.provided_text_version_review] }}；状态 {{ v.detail.professional_review.governance.status==='signed'?'已签署':'已撤销' }}。</p><p>签署UTC：{{ v.detail.professional_review.snapshot.signed_at }}；依据：{{ v.detail.professional_review.snapshot.basis_note }}</p></template>
        <fieldset v-if="v.canSign"><legend>当前药师本人独立复核，不代签</legend><el-select v-model="v.signForm.catalog_match_review" aria-label="目录药品对应复核" placeholder="明确对应情况"><el-option v-for="(label,value) in reviews" :key="value" :label="label" :value="value" /></el-select><el-select v-model="v.signForm.provided_text_version_review" aria-label="完整提供版本复核" placeholder="明确本次提供版本情况"><el-option v-for="(label,value) in reviews" :key="value" :label="label" :value="value" /></el-select><el-input v-model="v.signForm.basis_note" type="textarea" aria-label="药师本人复核依据" /><el-button :loading="v.busy" @click="v.mutate('sign')">提交本人独立签署</el-button></fieldset>
        <fieldset v-if="v.canReview"><legend>超级管理员审核</legend><el-select v-model="v.reviewForm.decision" aria-label="来源技术审核决定" placeholder="明确发布或拒绝"><el-option label="技术发布" value="approve" :disabled="!v.canPublish" /><el-option label="拒绝" value="reject" /></el-select><el-input v-model="v.reviewForm.basis_note" type="textarea" aria-label="来源技术审核依据" /><el-button :loading="v.busy" @click="v.mutate('review')">提交本件技术审核</el-button></fieldset>
        <fieldset v-if="v.canRevoke||v.canWithdraw"><legend>明确撤销</legend><el-input v-model="v.revokeNote" type="textarea" aria-label="本件撤销依据" /><el-button v-if="v.canWithdraw" :loading="v.busy" @click="v.mutate('professional_revoke')">撤销本件专业签署</el-button><el-button v-if="v.canRevoke" :loading="v.busy" type="danger" @click="v.mutate('revoke')">撤销本件来源</el-button></fieldset>
        <p v-if="v.formError" role="alert">{{ v.formError }}</p>
      </template><template #footer><el-button v-if="v.detail?.eligible&&!auditOnly" :disabled="v.busy" @click="v.selectSource">明确选择本件来源</el-button><el-button @click="v.detailOpen=false">关闭原件核对</el-button></template>
    </el-dialog>
    <el-dialog v-model="v.createOpen" title="明确关联已发布说明书原件" width="85%" :close-on-click-modal="false">
      <p>只提供现有71原文证据中真实已发布的说明书，不能手填原件ID、代药师签署或访问外部地址。</p>
      <el-select v-model="v.originalId" aria-label="选择实际已发布说明书原件" placeholder="明确选择真实提供版本" filterable><el-option v-for="item in v.originals" :key="item.original_id" :value="item.original_id" :label="`${item.title} / ${item.version}`" /></el-select>
      <el-button :disabled="!v.originalId||v.busy" @click="v.readOriginal">读取所选原件完整证明</el-button>
      <template v-if="v.original"><p>声明版本：{{ v.original.snapshot.metadata.version }}；原字节SHA256：<code>{{ v.original.snapshot.raw_bytes_hash }}</code></p><el-button @click="v.showOriginal=!v.showOriginal">{{ v.showOriginal?'收起待关联原文':'显式展开待关联完整原文' }}</el-button><pre v-if="v.showOriginal" aria-label="待关联完整原文">{{ v.original.snapshot.text }}</pre></template>
      <el-input v-model="v.releaseNote" type="textarea" aria-label="本件原文释放依据" placeholder="明确药品对应、提供版本及允许药师读取的依据" />
      <p v-if="v.formError" role="alert">{{ v.formError }}</p>
      <template #footer><el-button @click="v.createOpen=false">取消关联</el-button><el-button :loading="v.busy" :disabled="!v.original" @click="v.createBinding">登记本件来源绑定</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import {reactive} from 'vue';
import {useDrugLabelSources} from './useDrugLabelSources';
const props=defineProps({pharmaceuticalId:{type:Number,default:null},active:{type:Boolean,default:true},auditOnly:{type:Boolean,default:false}}),emit=defineEmits(['source-changed','invalidate','select']),v=reactive(useDrugLabelSources(props,emit));
const reviews={confirmed:'已明确确认',not_confirmed:'未确认',unknown:'未知'},states={draft:'草稿待审核',published:'已技术发布',rejected:'已拒绝',revoked:'已撤销'},display=v=>v===null?'未记录':String(v);
</script>
<style scoped>
.drug-label-sources{min-width:0}.el-select,.el-input{width:100%;margin:8px 0}fieldset{border:1px solid #dcdfe6;padding:12px;margin:12px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:45vh;overflow:auto;border:1px solid #dcdfe6;padding:12px}code{overflow-wrap:anywhere}[role=alert]{color:#b42318}
</style>
