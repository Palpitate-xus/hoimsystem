<template>
  <section aria-label="评价证据来源与治理">
    <p v-if="!allowed">当前身份不能读取评价证据来源。</p>
    <template v-else>
      <p>评价记录数不是就诊次数或应答人数。有效 1–5 评分统计与人工摘录分开核对；不提供 NPS、应答率、投诉处理率或医疗责任判断。</p>
      <el-form inline @submit.prevent="load">
        <el-form-item label="明确评价范围"><el-select v-model="scopeKind" aria-label="明确评价范围" clearable placeholder="明确选择范围，不默认全院"><el-option v-for="kind in options?.scope_kinds || []" :key="kind" :value="kind" :label="kind === 'hospital_reviews' ? '全院已记录评价' : '显式有限医生集合'" /></el-select></el-form-item>
        <el-form-item v-if="scopeKind === 'explicit_doctor_cohort'" label="实际医生集合"><el-select v-model="doctorIds" multiple filterable :multiple-limit="256" aria-label="实际医生集合" placeholder="明确选择 1–256 名实际医生"><el-option v-for="doctor in Object.values(doctorCache)" :key="doctor.doctor_id" :value="doctor.doctor_id" :label="`${doctor.name || '原姓名未记录'} · 医生 ${doctor.doctor_id}`" /></el-select></el-form-item>
        <el-form-item label="原记录起始日"><el-input v-model="dateFrom" type="date" aria-label="原记录起始日" /></el-form-item>
        <el-form-item label="原记录结束日"><el-input v-model="dateTo" type="date" aria-label="原记录结束日" /></el-form-item>
        <el-button native-type="submit" :disabled="!auditOnly && !scopeReady" :loading="loading">读取完整范围目录</el-button>
      </el-form>
      <p>日期是旧记录原存储日历，时区未知。NULL 或无法解释的时钟成员仍保留，不能补成今天；医生当前登记科室不表示评价当时科室；原人工审核时钟只保留旧字面量，不证明其时区或真实性。</p>
      <div v-if="scopeKind === 'explicit_doctor_cohort' && doctors"><span>实际医生目录第 {{ doctorPage }} 页，共 {{ doctors.total }} 名。</span><el-button :disabled="doctorPage <= 1" @click="loadDoctors(doctorPage - 1)">上一页医生</el-button><el-button :disabled="doctorPage * 100 >= doctors.total" @click="loadDoctors(doctorPage + 1)">下一页医生</el-button></div>
      <p v-if="error" role="alert">{{ error }}</p>
      <el-button v-if="canCreate" @click="openCreate">捕获完整评价证据</el-button>
      <p v-if="auditOnly && !scopeReady">超级管理员可按技术目录审计原件；创建仍须明确范围及日期。</p>
      <el-table v-if="directory" :data="directory.items" border aria-label="评价来源技术目录">
        <el-table-column prop="case_id" label="原件技术标识" min-width="300" /><el-table-column prop="scope_kind" label="声明范围" /><el-table-column prop="status" label="原治理状态" /><el-table-column prop="revision" label="治理版本" /><el-table-column prop="created_at" label="服务器登记时刻" min-width="240" /><el-table-column label="核对"><template #default="{row}"><el-button @click="inspect(row)">核对安全原件</el-button></template></el-table-column>
      </el-table>
      <div v-if="directory && directory.total > 20"><el-button :disabled="page <= 1 || loading" @click="page--; load()">上一页原件</el-button><span>第 {{ page }} 页，共 {{ directory.total }} 件</span><el-button :disabled="page * 20 >= directory.total || loading" @click="page++; load()">下一页原件</el-button></div>
      <el-dialog v-model="detailOpen" title="核对评价证据原件" @update:model-value="value => !value && clearDetail()" @closed="() => !detailOpen && clearDetail()">
        <p v-if="inspecting" role="status">正在核对完整安全胶囊、全部版本摘要和 SHA。</p>
        <article v-if="detail" aria-label="已核对完整评价证据">
          <p>原件 {{ detail.source_id }}；受保护原件锚 {{ detail.content_hash }}。</p><p>普通视图不含原评论或患者／就诊身份，不能由安全胶囊重建受保护整件 SHA；完整原件由服务端核验。</p>
          <p v-if="!detail.eligible">当前不可执行：{{ detail.exclusion_reasons.join('、') }}。</p>
          <template v-if="detail.safe_snapshot">
            <p>全部 {{ detail.safe_snapshot.all_member_statistics.record_count }} 条记录，{{ detail.safe_snapshot.member_manifest.length }} 个评价及摘录版本根；未知原日期 {{ detail.safe_snapshot.unknown_date_member_count }} 件，无法核实实际父链 {{ detail.safe_snapshot.unresolved_parent_count }} 件。</p>
            <p>全成员有效评分 {{ detail.safe_snapshot.all_member_statistics.valid_score_count }} 件，NULL {{ detail.safe_snapshot.all_member_statistics.null_score_count }} 件，异常 {{ detail.safe_snapshot.all_member_statistics.invalid_score_count }} 件；有效评分精确均分 {{ fraction(detail.safe_snapshot.all_member_statistics.mean_valid_score) }}。</p>
            <p>已知日期属于本期的有效评分精确均分 {{ fraction(detail.safe_snapshot.known_period_statistics.mean_valid_score) }}，与未知日期成员单独陈述。</p>
            <p>完整安全投影 SHA {{ detail.safe_projection_hash }}；全成员摘要 SHA {{ detail.safe_snapshot.member_manifest_hash }}。</p>
            <el-table :data="detail.safe_snapshot.member_manifest.slice(manifestPage * 20, manifestPage * 20 + 20)" border aria-label="完整评价版本摘要分页"><el-table-column prop="kind" label="根类型" /><el-table-column prop="status" label="原状态" /><el-table-column prop="version" label="原版本" /><el-table-column prop="revision" label="原治理版本" /><el-table-column prop="selected" label="明确选择" /><el-table-column prop="eligibility" label="人工声明资格" /></el-table>
            <el-button :disabled="manifestPage === 0" @click="manifestPage--">上一页成员</el-button><el-button :disabled="(manifestPage + 1) * 20 >= detail.safe_snapshot.member_manifest.length" @click="manifestPage++">下一页成员</el-button>
            <p v-for="excerpt in detail.safe_snapshot.selected_excerpts" :key="excerpt.excerpt_token">已选人工摘录：{{ excerpt.text }}（隐私和原意人工声明，不是匿名保证或事实核实）</p>
          </template><p v-else>原件当前仅可返回技术元数据；失效、拒绝或撤销正文及自由备注已隐藏。</p>
          <el-button v-if="selectable && !auditOnly && detail.eligible && !detail.audit_only" :loading="inspecting" @click="selectDetail">选择本条受审评价证据</el-button>
          <el-button v-if="auditOnly && superUser && !protectedVisible" @click="inspect(detail,{protectedRead:true})">显式读取 Super 受保护冻结原文</el-button>
          <section v-if="protectedVisible && detail.snapshot && superUser" aria-label="Super 受保护评价原文">
            <p>受保护冻结原文仅供超级管理员技术审计，含原评价及实际身份绑定；不会发送给模型。</p>
            <el-table :data="detail.snapshot.collection.reviews.slice(rawPage * 20, rawPage * 20 + 20)" border><el-table-column prop="review_id" label="原评价 ID" /><el-table-column prop="comment" label="受保护原评论" /><el-table-column prop="review_time" label="原时间字面量" /></el-table><el-button :disabled="rawPage === 0" @click="rawPage--">上一页受保护原文</el-button><el-button :disabled="(rawPage + 1) * 20 >= detail.snapshot.collection.reviews.length" @click="rawPage++">下一页受保护原文</el-button>
            <details><summary>完整冻结父绑定与原摘录版本</summary><pre>{{ JSON.stringify({parents:detail.snapshot.collection.parents,excerpts:detail.snapshot.collection.excerpts},null,2) }}</pre></details>
          </section>
          <div v-if="auditOnly && superUser && detail.can_review || detail.can_revoke" aria-label="评价来源治理操作">
            <el-input v-model="governanceBasis" type="textarea" aria-label="本次评价来源治理依据" placeholder="明确本次技术审核或撤销依据，至少 20 个字符" />
            <el-button v-if="auditOnly && superUser && detail.can_review" :disabled="!satisfactionBasis(governanceBasis) || governing" @click="govern('publish')">审核发布本件</el-button><el-button v-if="auditOnly && superUser && detail.can_review" :disabled="!satisfactionBasis(governanceBasis) || governing" @click="govern('reject')">审核拒绝本件</el-button><el-button v-if="detail.can_revoke" :disabled="!satisfactionRevokeBasis(governanceBasis) || governing" @click="govern('revoke')">撤销本件</el-button>
            <p>Super 技术发布不替代原摘录的人工隐私／原意审核。撤销至多 1000 个 Unicode 字符、4000 UTF-8 字节；完整私有治理 SHA 仅在持有完整原文时重建。</p>
          </div>
        </article>
      </el-dialog>
      <el-dialog v-model="creating" title="捕获完整评价证据" @update:model-value="value => !value && closeCreate()" @closed="() => !creating && closeCreate()">
        <template v-if="creating"><p>固定本次明确范围和日期，捕获所有评价及所有摘录版本；不按旧截止回放、不自动选择最新或有利版本。</p><el-button :loading="previewing" @click="capture">核对完整安全集合</el-button>
          <template v-if="preview"><p>完整 {{ preview.safe_snapshot.member_manifest.length }} 个根，集合 SHA {{ preview.collection_digest }}。</p><p>仅明确选择的当前合格人工摘录可进入模型；不选摘录仍可核对独立评分统计。</p>
            <el-checkbox-group v-model="selectedExcerptIds" aria-label="明确选择受审人工摘录"><div v-for="option in preview.excerpt_options.slice(excerptPage * 20, excerptPage * 20 + 20)" :key="option.excerpt_id"><el-checkbox :value="option.excerpt_id" :disabled="!option.eligible">版本 {{ option.version }} · {{ option.status }} · {{ option.eligible ? option.reviewed_text : option.exclusion_reasons.join('、') }}</el-checkbox></div></el-checkbox-group><el-button :disabled="excerptPage === 0" @click="excerptPage--">上一页摘录版本</el-button><el-button :disabled="(excerptPage + 1) * 20 >= preview.excerpt_options.length" @click="excerptPage++">下一页摘录版本</el-button>
            <el-input v-model="createBasis" type="textarea" aria-label="本次完整评价证据捕获依据" placeholder="明确本次完整来源与摘录选择依据，不默认任何人工确认" /><el-button :disabled="!createReady || saving" :loading="saving" @click="save">保存独立评价证据草稿</el-button>
          </template>
        </template>
      </el-dialog>
    </template>
  </section>
</template>

<script setup>
import {satisfactionBasis,satisfactionRevokeBasis} from '@/api/ai/satisfactionSources';
import {useSatisfactionSources} from './useSatisfactionSources';
const props=defineProps({active:{type:Boolean,default:true},auditOnly:{type:Boolean,default:false},selectable:{type:Boolean,default:false}});
const emit=defineEmits(['scope-change','select','availability','source-changed','invalidate']);
const {allowed,superUser,options,doctors,doctorPage,doctorCache,scopeKind,doctorIds,dateFrom,dateTo,scopeReady,canCreate,directory,page,loading,error,detail,inspecting,detailOpen,protectedVisible,manifestPage,rawPage,excerptPage,creating,preview,previewing,saving,selectedExcerptIds,createBasis,governanceBasis,governing,createReady,load,loadDoctors,inspect,clearDetail,openCreate,closeCreate,capture,save,govern,selectDetail}=useSatisfactionSources(props,emit);
const fraction=value=>value?`${value.numerator}/${value.denominator}`:'未知（没有有效评分）';
</script>
<style scoped>p{line-height:1.7;overflow-wrap:anywhere}.el-select{min-width:250px}.el-button{margin:5px}pre{white-space:pre-wrap;overflow-wrap:anywhere}.el-checkbox-group>div{margin:10px 0}</style>
