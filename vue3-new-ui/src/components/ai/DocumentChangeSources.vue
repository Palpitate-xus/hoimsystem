<template>
  <section aria-label="双原文版本核对来源治理">
    <h3>双原文与有限关联范围</h3>
    <el-alert title="这里只登记和审核人工声明的比较范围" description="选择两份原文，登记比较范围和相关依赖。" type="info" :closable="false" />
    <el-alert v-if="!v.allowed" title="仅当前超级管理员可以读取和治理这些完整原件" type="warning" :closable="false" />
    <template v-else>
      <div class="actions"><el-button :loading="v.listsBusy" @click="v.refresh">刷新来源合同与两个目录</el-button></div>
      <p v-if="v.error" role="alert">{{ v.error }}</p><p v-if="v.notice" role="status">{{ v.notice }}</p>
      <div class="originals">
        <document-change-original-input label="基线原文" :active="active" @selection-change="value=>v.selectOriginal('baseline',value)" />
        <document-change-original-input label="候选原文" :active="active" @selection-change="value=>v.selectOriginal('candidate',value)" />
      </div>
      <el-alert v-if="v.baseline&&v.candidate&&!v.pairValid" title="必须明确选择两件不同的原文，不能将同一原件作为两侧" type="warning" :closable="false" />
      <fieldset :disabled="v.busy||!v.optionsReady">
        <legend>读取明确的院内目标</legend>
        <p>从现有规则或临床路径管理复制真实标识，读取完整当前目标后再明确加入范围；不会自动选取或推断全院范围。</p>
        <el-form label-position="top" :disabled="v.busy||!v.optionsReady">
          <el-form-item label="目标种类"><el-select v-model="v.form.targetKind" aria-label="目标种类" placeholder="明确选择"><el-option label="固定风险规则实施档案" value="risk_rule_profile" /><el-option label="临床路径" value="clinical_pathway" /></el-select></el-form-item>
          <el-form-item label="真实目标标识"><el-input v-model="v.form.targetId" aria-label="真实目标标识" placeholder="规则UUID或临床路径正整数ID" /></el-form-item>
          <el-button @click="v.readTarget">读取完整当前目标</el-button>
        </el-form>
        <div v-if="v.target" aria-label="已核对当前目标"><p>目标状态：{{ v.target.snapshot.state }}；完整目标摘要：{{ v.target.snapshot_hash }}</p><el-button :disabled="!v.target.snapshot.exists||v.declared.length>=256" @click="v.addTarget">明确加入本次有限范围</el-button><details><summary>展开完整院内目标原件（不发送模型）</summary><pre>{{ v.canonical(v.target.snapshot) }}</pre></details></div>
        <ul aria-label="声明的有限目标"><li v-for="(target,index) in v.declared" :key="target.kind+target.target_id">{{ target.kind }} / {{ target.target_id }} <el-button @click="v.removeTarget(index)">移出本次声明</el-button></li></ul>
        <p v-if="!v.declared.length">当前比较范围尚未添加目标。</p>
      </fieldset>
      <fieldset :disabled="v.busy||!v.optionsReady">
        <legend>登记一条待审核人工关联</legend>
        <el-form label-position="top" :disabled="v.busy||!v.optionsReady">
          <el-form-item label="关联原文侧"><el-select v-model="v.form.side" aria-label="关联原文侧" placeholder="明确选择"><el-option label="基线原文" value="baseline" /><el-option label="候选原文" value="candidate" /></el-select></el-form-item>
          <el-form-item label="Unicode codepoint 起点（含，零起始）"><el-input v-model="v.form.start" aria-label="关联起点" placeholder="明确非负整数，可为0" /></el-form-item>
          <el-form-item label="Unicode codepoint 终点（不含）"><el-input v-model="v.form.end" aria-label="关联终点" placeholder="明确正整数" /></el-form-item>
          <details><summary>资料核验详情</summary><p>单条关联引文最多65535 UTF8字节；超限不会截取或替换原文。</p></details><pre v-if="v.quote" aria-label="逐字关联引文">{{ v.quote.quote }}</pre>
          <el-form-item label="声明的关系"><el-select v-model="v.form.dependency" aria-label="声明的关联关系" placeholder="明确选择"><el-option label="声明支持" value="declared_support" /><el-option label="声明实施" value="declared_implementation" /><el-option label="需要人工核查" value="requires_human_review" /></el-select></el-form-item>
          <el-form-item label="关联声明依据"><el-input v-model="v.form.linkBasis" aria-label="关联声明依据" type="textarea" :rows="3" /></el-form-item>
          <el-button :disabled="!v.quote||!v.target||!v.documentBasis(v.form.linkBasis)" :loading="v.busy" @click="v.enrollLink">仅登记关联草稿</el-button>
        </el-form>
      </fieldset>
      <fieldset :disabled="v.busy||!v.optionsReady">
        <legend>捕获并登记完整有限比较范围</legend>
        <el-form label-position="top" :disabled="v.busy||!v.optionsReady">
          <el-form-item label="两原文关系声明"><el-select v-model="v.form.relationship" aria-label="两原文关系声明" placeholder="明确选择"><el-option label="仅登记比较关系" value="comparison_only" /><el-option label="声明继任关系" value="declared_successor" /></el-select></el-form-item>
          <el-form-item label="同一指南家族的核实状态"><el-select v-model="v.form.family" aria-label="同一家族核实状态"><el-option label="未知" value="unknown" /><el-option label="已明确核实" value="confirmed" /><el-option label="未确认" value="not_confirmed" /></el-select></el-form-item>
          <el-form-item label="原文关系依据"><el-input v-model="v.form.relationshipBasis" aria-label="原文关系依据" type="textarea" :rows="3" /></el-form-item>
          <el-form-item label="有限范围的关联覆盖声明"><el-select v-model="v.form.coverage" aria-label="关联覆盖声明"><el-option label="未知" value="unknown" /><el-option label="不完整" value="incomplete" /><el-option label="仅明确声明范围内完整" value="complete_within_declared_scope" /></el-select></el-form-item>
          <el-form-item label="有限范围依据"><el-input v-model="v.form.declarationBasis" aria-label="有限范围依据" type="textarea" :rows="3" /></el-form-item>
          <el-button :disabled="!v.pairValid" :loading="v.busy" @click="v.captureScope">捕获全部依赖供人工核对</el-button>
        </el-form>
        <div v-if="v.capture" aria-label="待登记完整比较捕获"><p>完整成员 {{ v.capture.member_count }} 项；摘要 {{ v.capture.inventory_hash }}。当前两原文的全部直接知识发布及已登记关联均保留，非赢家不丢弃。</p><details><summary>展开捕获的全部私有原件</summary><pre>{{ v.canonical(v.capture.inventory) }}</pre></details><el-button :loading="v.busy" @click="v.enrollScope">按此完整摘要登记范围草稿</el-button></div>
        <p>每份原文上限4MiB，任务整体上限8MiB，提交时统一检查。</p>
      </fieldset>
      <div v-for="kind in ['links','scopes']" :key="kind" class="directory" :aria-label="kind==='links'?'人工关联目录':'有限范围目录'">
        <h4>{{ kind==='links'?'人工关联目录':'有限范围目录' }}</h4>
        <el-table :data="v.directories[kind]?.items||[]" empty-text="本页无记录；目录元数据不能代替完整原件">
          <el-table-column :prop="kind==='links'?'link_id':'scope_id'" label="原件标识" min-width="260" /><el-table-column label="状态" width="130"><template #default="{row}">{{ v.states[row.status] }}</template></el-table-column>
          <el-table-column prop="revision" label="版本" width="70" /><el-table-column label="操作" width="180"><template #default="{row}"><el-button :disabled="v.busy" @click="v.inspectRecord(kind,row)">读取完整件与治理</el-button></template></el-table-column>
        </el-table>
        <el-pagination v-if="v.directories[kind]" :current-page="v.directories[kind].page" :page-size="v.directories[kind].page_size" :total="v.directories[kind].total" layout="prev,pager,next,total" :disabled="v.listsBusy" @current-change="page=>v.loadDirectory(kind,page)" />
      </div>
      <section v-if="v.detail" aria-label="完整来源与显式治理">
        <p>状态：{{ v.states[v.detail.value.governance.status] }}；完整原件摘要：{{ v.detail.value.content_hash }}；当前治理摘要：{{ v.detail.value.governance_hash }}。</p>
        <details><summary>资料核验详情</summary><p>登记UTC6：{{ v.detail.value.snapshot.recorded_at }}；审核UTC6：{{ v.detail.value.governance.reviewed_at??'未审核' }}。</p></details>
        <el-alert v-if="!v.detail.value.eligible" title="本件当前不具备新任务资格，完整原件仍保留供人工核对" type="warning" :closable="false" />
        <el-button @click="v.rawOpen=!v.rawOpen">{{ v.rawOpen?'关闭完整私有原件':'展开完整私有原件' }}</el-button><el-button @click="v.clearDetail">关闭并清除当前治理详情</el-button>
        <pre v-if="v.rawOpen" aria-label="完整私有比较来源">{{ v.canonical(v.detail.value) }}</pre>
        <el-form v-if="v.detail.value.governance.status==='draft'" label-position="top" :disabled="v.busy">
          <el-form-item label="明确审核决定"><el-select v-model="v.review.decision" aria-label="审核决定" placeholder="请选择"><el-option label="明确批准发布本次声明" value="approve" /><el-option label="明确拒绝" value="reject" /></el-select></el-form-item>
          <el-form-item v-for="[field,label] in [['privacy_review','隐私审核'],['faithfulness_review','原意审核'],['dependency_review','依赖与声明核对']]" :key="field" :label="label"><el-select v-model="v.review[field]" :aria-label="label" placeholder="必须逐项明确"><el-option label="明确确认" value="confirmed" /><el-option label="未确认" value="not_confirmed" /></el-select></el-form-item>
          <el-form-item label="本次审核依据"><el-input v-model="v.review.basis_note" aria-label="本次审核依据" type="textarea" :rows="3" /></el-form-item>
          <el-button :loading="v.busy" @click="v.mutate(false)">仅保存本次明确审核</el-button>
        </el-form>
        <el-form v-if="v.detail.value.governance.status!=='revoked'" label-position="top" :disabled="v.busy"><el-form-item label="明确撤销依据"><el-input v-model="v.review.revokeBasis" aria-label="明确撤销依据" type="textarea" :rows="3" /></el-form-item><el-button :loading="v.busy" :disabled="!v.documentBasis(v.review.revokeBasis,1000)" @click="v.mutate(true)">明确撤销当前原件</el-button></el-form>
      </section>
    </template>
  </section>
</template>
<script setup>
import {reactive} from 'vue';
import DocumentChangeOriginalInput from './DocumentChangeOriginalInput.vue';
import {useDocumentChangeSources} from './useDocumentChangeSources';
const props=defineProps({active:{type:Boolean,default:true}}),v=reactive(useDocumentChangeSources(props));
</script>
<style scoped>
.originals{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}.el-alert,fieldset,.directory{margin:14px 0}fieldset{border:1px solid var(--el-border-color);border-radius:6px;padding:14px}.actions{display:flex;gap:12px;margin:12px 0}.el-select{min-width:260px}p{line-height:1.6;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:45vh;overflow:auto;padding:12px;background:var(--el-fill-color-light)}[role=alert]{color:var(--el-color-danger)}
</style>
