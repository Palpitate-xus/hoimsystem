<template>
 <section :aria-label="labels[kind]+'来源治理'">
  <el-alert title="项目登记、人工授权核查、技术发布和实际研究读取资格分别核对；账户角色不代替患者授权或伦理审批。" type="info" :closable="false" />
  <p v-if="!v.scopeValid" role="status">请先明确选择项目，再管理该项目的成员权限和患者授权。</p>
  <p v-else-if="!v.authorized" role="status">当前会话、角色或本项范围不满足读取条件。</p>
  <template v-else>
   <p v-if="auditOnly">冻结技术审计：只供核对，不恢复当前授权或执行资格。</p>
   <el-button :disabled="v.busy" @click="v.refresh(1)">刷新{{ labels[kind] }}目录</el-button>
   <el-button v-if="v.canCreate" :disabled="v.busy" @click="v.openCreate">登记{{ labels[kind] }}原件</el-button>
   <el-table :data="v.rows" :aria-label="labels[kind]+'技术目录'">
    <el-table-column prop="source_record_id" label="原件标识" />
    <el-table-column label="状态"><template #default="{row}">{{ states[row.status] }}</template></el-table-column>
    <el-table-column prop="created_at" label="登记UTC" />
    <el-table-column v-if="kind==='acl'" prop="user_id" label="明确成员ID" />
    <el-table-column v-if="kind==='authorization'" prop="patient_id" label="明确患者ID" />
    <el-table-column label="操作"><template #default="{row}"><el-button :disabled="v.busy" @click="v.inspect(row)">读取本件完整依据</el-button><el-button v-if="kind==='scope'" :disabled="v.busy" @click="v.chooseProject(row)">明确选择本项目</el-button></template></el-table-column>
   </el-table>
   <p>目录仅供定位本件，尚未核对完整原件；明确选择项目也不会建立患者读取或AI执行权限。</p>
   <el-button :disabled="v.busy||v.page<=1" @click="v.refresh(v.page-1)">上一页</el-button><span>第{{ v.page }}页，共{{ v.total }}件</span><el-button :disabled="v.busy||v.page*100>=v.total" @click="v.refresh(v.page+1)">下一页</el-button>
  </template>
  <p v-if="v.error" role="alert">{{ v.error }}</p><p v-if="v.notice" role="status">{{ v.notice }}</p>
  <el-dialog :model-value="v.detailOpen" :title="labels[kind]+'完整原件核对'" width="85%" :close-on-click-modal="false" @update:model-value="value=>!value&&v.closeDetail()">
   <template v-if="v.detail">
    <p>原件 {{ v.detail.source_record_id }}；状态 {{ states[v.detail.status] }}；版本 {{ v.detail.revision }}。</p>
    <template v-if="v.detail.original">
     <p>完整声明和治理关系已核对；本项状态{{ v.detail.eligible?'符合登记条件':'尚未符合登记条件' }}。患者资料访问和模型调用权限分别配置。</p>
     <el-button @click="v.showOriginal=!v.showOriginal">{{ v.showOriginal?'收起完整登记原文':'显式展开完整登记原文' }}</el-button>
     <div v-if="v.showOriginal" aria-label="完整登记原文">
      <template v-if="kind==='scope'"><p>项目编号：{{ v.detail.original.payload.protocol_key }}；标题：{{ v.detail.original.payload.title }}</p><p>完整目的：</p><pre>{{ v.detail.original.payload.purpose }}</pre><p>明确患者：{{ v.detail.original.payload.patient_ids.join('、') }}；明确用户：{{ v.detail.original.payload.proposed_user_ids.join('、') }}</p><p>数据范围：{{ v.detail.original.payload.data_families.map(value=>families[value]).join('、') }}；使用用途：{{ v.detail.original.payload.permitted_uses.map(value=>uses[value]).join('、') }}</p><p>记录日期 {{ v.detail.original.payload.record_window.date_from }} 至 {{ v.detail.original.payload.record_window.date_to }}；历史日期的原时区未知。</p><p>外部模型处理：{{ outbound[v.detail.original.payload.external_model_use] }}</p><pre>{{ v.detail.original.payload.external_model_use_basis }}</pre><p>授权声明：</p><pre>{{ v.detail.original.payload.authorization_basis }}</pre></template>
      <template v-else-if="kind==='acl'"><p>明确用户 {{ v.detail.original.payload.user_id }}；项目权限 {{ permissions[v.detail.original.payload.permission] }}。</p><pre>{{ v.detail.original.payload.basis_note }}</pre></template>
      <template v-else><p>明确患者 {{ v.detail.original.payload.patient_id }}；授权类型 {{ authorizations[v.detail.original.payload.authorization_kind] }}；访问依据 {{ access[v.detail.original.payload.access_basis] }}。</p><p>所提供授权原文：</p><pre>{{ v.detail.original.payload.original_authority_text===null?'未提供':v.detail.original.payload.original_authority_text }}</pre><p>登记依据：</p><pre>{{ v.detail.original.payload.basis_note }}</pre></template>
      <p>有效起止UTC：{{ v.detail.original.payload.valid_from===null?'未知':v.detail.original.payload.valid_from }} 至 {{ v.detail.original.payload.valid_until===null?'未知':v.detail.original.payload.valid_until }}</p>
      <p v-if="kind!=='acl'">授权材料引用：{{ v.detail.original.payload.authority_reference===null?'未提供':v.detail.original.payload.authority_reference }}</p>
      <p v-if="v.detail.original.authorization_review">独立人工核查：{{ manual[v.detail.original.authorization_review.authorization_review_status] }}</p><pre v-if="v.detail.original.authorization_review">{{ v.detail.original.authorization_review.authorization_review_basis }}</pre>
      <p>技术审核依据：</p><pre>{{ v.detail.original.governance.review_basis_note }}</pre><p>撤销依据：</p><pre>{{ v.detail.original.governance.revoke_reason }}</pre>
     </div>
     <fieldset v-if="v.canManual||v.canReview||v.canRevoke" :disabled="v.writePending"><legend>本次明确治理决定</legend>
      <el-select v-if="v.canManual||v.canReview" v-model="v.decision" aria-label="本次治理决定" placeholder="请明确选择决定"><el-option v-if="v.canManual" value="recorded_reviewed" label="已独立核查所提供授权材料" /><el-option v-if="v.canManual" value="not_confirmed" label="未能确认授权材料" /><el-option v-if="v.canReview" value="publish" label="技术发布本件" /><el-option v-if="v.canReview" value="reject" label="拒绝本件" /></el-select>
      <el-input v-model="v.basis" type="textarea" aria-label="本次治理完整依据" placeholder="请记录20字以上完整依据，保留未知和否定" />
      <el-button v-if="v.canManual" :disabled="v.busy||!['recorded_reviewed','not_confirmed'].includes(v.decision)" @click="v.mutate('authorization_review')">提交独立授权材料核查</el-button>
      <el-button v-if="v.canReview" :disabled="v.busy||!['publish','reject'].includes(v.decision)" @click="v.mutate('review')">提交技术审核</el-button>
      <el-button v-if="v.canRevoke" :disabled="v.busy" @click="v.mutate('revoke')">撤销本件</el-button>
     </fieldset>
    </template><p v-else role="status">仅返回技术元数据，完整原件不可读；没有将摘要视作完整治理核对。</p>
    <p v-if="v.formError" role="alert">{{ v.formError }}</p>
   </template>
  </el-dialog>
  <el-dialog :model-value="v.createOpen" :title="'登记'+labels[kind]+'原件'" width="80%" :close-on-click-modal="false" @update:model-value="value=>!value&&v.closeDetail()">
   <el-form v-if="v.createOpen" label-position="top" @submit.prevent="v.create">
    <fieldset :disabled="v.writePending"><legend>本次完整声明</legend>
     <template v-if="kind==='scope'">
      <el-form-item label="项目编号"><el-input v-model="v.form.protocol_key" aria-label="项目编号" /></el-form-item><el-form-item label="项目标题"><el-input v-model="v.form.title" aria-label="项目标题" /></el-form-item><el-form-item label="完整项目目的"><el-input v-model="v.form.purpose" type="textarea" aria-label="完整项目目的" /></el-form-item>
      <el-form-item label="明确患者ID，升序且不重复，以逗号分隔"><el-input v-model="v.form.patient_ids_text" aria-label="完整患者ID集合" /></el-form-item><el-form-item label="明确项目用户ID，升序且不重复"><el-input v-model="v.form.proposed_user_ids_text" aria-label="完整用户ID集合" /></el-form-item>
      <el-form-item label="明确数据范围"><el-checkbox-group v-model="v.form.data_families" aria-label="明确数据范围"><el-checkbox v-for="(label,value) in families" :key="value" :label="value">{{ label }}</el-checkbox></el-checkbox-group></el-form-item>
      <el-form-item label="明确使用用途"><el-checkbox-group v-model="v.form.permitted_uses" aria-label="明确使用用途"><el-checkbox v-for="(label,value) in uses" :key="value" :label="value">{{ label }}</el-checkbox></el-checkbox-group></el-form-item>
      <el-form-item label="记录起始日期 YYYY-MM-DD"><el-input v-model="v.form.date_from" aria-label="记录起始日期" /></el-form-item><el-form-item label="记录结束日期 YYYY-MM-DD"><el-input v-model="v.form.date_to" aria-label="记录结束日期" /></el-form-item>
      <el-form-item label="外部模型处理授权"><el-select v-model="v.form.external_model_use" aria-label="外部模型处理授权" placeholder="请明确选择"><el-option v-for="(label,value) in outbound" :key="value" :label="label" :value="value" /></el-select></el-form-item><el-form-item label="外部模型处理依据"><el-input v-model="v.form.external_model_use_basis" type="textarea" aria-label="外部模型处理完整依据" /></el-form-item><el-form-item label="完整授权声明依据"><el-input v-model="v.form.authorization_basis" type="textarea" aria-label="完整授权声明依据" /></el-form-item>
     </template>
     <template v-else-if="kind==='acl'"><p>明确绑定项目 {{ scopeId }}；只登记原项目已声明成员，不扩展成员集合。</p><el-form-item label="明确用户ID"><el-input-number v-model="v.form.user_id" :min="1" :max="2147483647" :precision="0" aria-label="明确用户ID" /></el-form-item><el-form-item label="项目权限"><el-select v-model="v.form.permission" aria-label="明确项目权限" placeholder="请明确选择"><el-option v-for="(label,value) in permissions" :key="value" :label="label" :value="value" /></el-select></el-form-item></template>
     <template v-else><p>明确绑定项目 {{ scopeId }}；只登记原项目已声明患者，不扩展患者集合。</p><el-form-item label="明确患者ID"><el-input-number v-model="v.form.patient_id" :min="1" :max="2147483647" :precision="0" aria-label="明确患者ID" /></el-form-item><el-form-item label="授权类型"><el-select v-model="v.form.authorization_kind" aria-label="明确患者授权类型" placeholder="请明确选择"><el-option v-for="(label,value) in authorizations" :key="value" :label="label" :value="value" /></el-select></el-form-item><el-form-item label="访问依据"><el-select v-model="v.form.access_basis" aria-label="明确访问依据" placeholder="请明确选择"><el-option v-for="(label,value) in access" :key="value" :label="label" :value="value" /></el-select></el-form-item><el-form-item label="授权有效期是否已知"><el-radio-group v-model="v.form.period_known" aria-label="有效期是否已知"><el-radio :label="true">明确填写有效期</el-radio><el-radio :label="false">未知，保留为空</el-radio></el-radio-group></el-form-item><el-form-item label="完整提供授权原文（未提供可留空）"><el-input v-model="v.form.original_authority_text" type="textarea" aria-label="完整提供授权原文" /></el-form-item></template>
     <template v-if="kind!=='authorization'||v.form.period_known===true"><el-form-item label="有效起始UTC，保留六位小数，例如2026-10-21T00:00:00.000000Z"><el-input v-model="v.form.valid_from" aria-label="明确有效起始UTC" /></el-form-item><el-form-item label="有效结束UTC，保留六位小数"><el-input v-model="v.form.valid_until" aria-label="明确有效结束UTC" /></el-form-item></template>
     <el-form-item v-if="kind!=='acl'" label="授权材料引用（未提供可留空）"><el-input v-model="v.form.authority_reference" aria-label="授权材料引用" /></el-form-item><el-form-item v-if="kind!=='scope'" label="完整登记依据"><el-input v-model="v.form.basis_note" type="textarea" aria-label="完整登记依据" /></el-form-item>
     <el-button :disabled="v.busy" @click="v.create">提交完整原件登记</el-button>
    </fieldset><p v-if="v.formError" role="alert">{{ v.formError }}</p>
   </el-form>
  </el-dialog>
 </section>
</template>
<script setup>
import {reactive} from 'vue';
import {useResearchCohortRegistry} from './useResearchCohortRegistry';
const props=defineProps({kind:{type:String,default:'scope'},scopeId:{type:String,default:null},active:{type:Boolean,default:true},auditOnly:{type:Boolean,default:false}}),emit=defineEmits(['project','invalidate','source-changed']),v=reactive(useResearchCohortRegistry(props,emit));
const labels={scope:'研究项目',acl:'项目成员权限',authorization:'逐患者研究授权'},states={draft:'草稿',published:'已技术发布',rejected:'已拒绝',revoked:'已撤销'},manual={unknown:'未知',recorded_reviewed:'已独立核查所提供材料',not_confirmed:'未能确认'},families={patient_demographics:'有限人口学字段',registrations:'挂号记录',admissions:'住院记录',medical_records:'门诊病历',structured_medical_records:'结构化病历'},uses={cohort_criteria_review:'科研队列条件复核',deidentification_review:'脱敏候选及输出复核',research_variable_extraction:'研究变量抽取'},permissions={read_only:'仅项目读取',read_capture:'项目读取与新捕获'},outbound={unknown:'未知，不能发送至外部模型',recorded_permitted:'已记录明确处理许可',not_permitted:'明确不允许'},authorizations={permission_recorded:'已记录授权',waiver_recorded:'已记录豁免依据',unknown:'未知',withdrawn:'已撤回',denied:'未获授权'},access={explicit_project_acl:'明确项目成员权限',current_care_or_grant:'同时核对当前诊疗或限时授予权限'};
defineExpose({clear:v.closeDetail});
</script>
<style scoped>
section{min-width:0}.el-input,.el-select{width:100%}fieldset{border:1px solid #dcdfe6;margin:12px 0;padding:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:50vh;overflow:auto;border:1px solid #dcdfe6;padding:12px}[role=alert]{color:#b42318}
</style>
