<template>
  <section class="research-variable-assistant" data-testid="research-variable-assistant">
    <h3>科研变量原文候选抽取</h3>
    <el-alert :closable="false" type="info" title="仅生成未核实逐字候选；原记录缺失、NULL 与未提出候选均不能推出未测、正常或疾病不存在。不会自动审核矩阵、导出或写入临床。" />
    <el-alert v-if="!sessionAllowed" :closable="false" type="warning" title="当前会话无明确科研变量角色；项目和全部患者研究、模型用途仍由服务器逐次核验。" />
    <el-alert v-else-if="!scopeValid" :closable="false" type="error" title="本功能仅接受明确变量批次和可选问题；不接受患者、诊次或其他输入。" />
    <el-alert v-else-if="!modeReady" :closable="false" type="warning" title="请恢复第76项科研变量原文候选抽取及其专用来源模式；未进入通用任务。" />
    <el-button v-if="closed" data-testid="variable-reopen" @click="reopen">重新选择来源</el-button>
    <template v-else-if="available">
      <el-form label-position="top">
        <research-variable-input :key="sourceEpoch" :active="available" :initial-references="sourceInitialReferences" @selection-change="sourceChanged" />
        <el-form-item label="可选问题（原样保存，最多2000码点 / 8000 UTF8字节）">
          <el-input v-model="question" data-testid="variable-question" type="textarea" :rows="3" autocomplete="off" />
        </el-form-item>
        <el-checkbox v-if="isSuper" v-model="previewMode" data-testid="variable-preview-mode">明确超级管理员试运行（不启用或验证功能）</el-checkbox>
      </el-form>
      <div class="actions">
        <el-button data-testid="variable-inspect" :disabled="busy || !selectionValid" @click="inspect">核对完整当前来源</el-button>
        <el-button data-testid="variable-submit" type="primary" :disabled="busy || !queueAllowed" @click="submit">明确提交未核实抽取</el-button>
        <el-button data-testid="variable-history" :disabled="busy || !selectionValid" @click="loadHistory">读取该批次历史</el-button>
        <el-button data-testid="variable-close" @click="close">关闭并清除私件</el-button>
      </div>
      <p v-if="busy" role="status">正在读取并核对完整独立分件…</p>
      <el-alert v-if="error" :closable="false" type="error" :title="error" />
      <el-alert v-if="notice" :closable="false" type="info" :title="notice" />
      <article v-if="preview" data-testid="variable-preview">
        <h4>完整来源已核对，尚未调用模型</h4>
        <p>批次 {{ preview.bindingReference.batch_id }} · 原声明 {{ preview.source.records.length }} 条记录 / {{ preview.source.documents.length }} 个原字段</p>
        <p>逐患者用途覆盖原项目全部 {{ preview.preview.research_variable_binding.request_authorization.patient_authorizations.length }} 人；不是仅批次子集。</p>
        <p>登记或分件8MiB容量不保证实际完整Provider请求可容纳；入队仍会全包拒超限，不截断。</p>
        <el-button data-testid="variable-evidence" @click="evidenceOpen=true">查看完整已核原件</el-button>
      </article>
      <div v-if="history.length" data-testid="variable-history-list">
        <h4>当前所选批次历史（点击后重新核完整分件）</h4>
        <el-button v-for="row in history" :key="row.run_id" class="history-row" :disabled="busy" @click="openHistory(row)">{{ row.run_id }} · {{ row.status }}</el-button>
      </div>
      <div v-if="bundle" class="task-actions">
        <el-button data-testid="variable-refresh" :disabled="busy" @click="refresh">明确重新读取任务</el-button>
        <el-button v-if="['queued','running'].includes(bundle.run.status)" data-testid="variable-cancel" :disabled="busy" @click="cancel">停止接收本次结果</el-button>
        <p v-if="polling">仅轮询同一任务；取消在途调用后仍等待原交付的实际用量，不重复提交模型。</p>
        <research-variable-findings :run="bundle.run" :parts="bundle.parts" :expected-run-id="bundle.run.run_id" :expected-batch-id="batchId" :active="available" @close-requested="childCleared" @reload-requested="refresh" />
        <el-form v-if="bundle.run.status==='succeeded'" label-position="top">
          <el-form-item label="明确人工复核">
            <el-select v-model="feedbackOutcome" data-testid="variable-feedback-outcome"><el-option label="接受为待核候选" value="accepted" /><el-option label="修改后再核" value="modified" /><el-option label="拒绝候选" value="rejected" /></el-select>
          </el-form-item>
          <el-input v-model="feedbackComment" data-testid="variable-feedback-comment" type="textarea" placeholder="可选复核说明，不会自动发布或导出" />
          <el-button data-testid="variable-feedback" :disabled="busy" @click="feedback">明确保存人工复核</el-button>
        </el-form>
      </div>
      <el-dialog v-model="evidenceOpen" title="完整已核原件与公开投影（仅当前会话）" :before-close="closeEvidence" destroy-on-close append-to-body>
        <template v-if="evidenceOpen && preview && available">
          <p>不包含服务端HMAC密钥；技术身份只核服务器冻结锚与有序原字面值对应。</p>
          <pre data-testid="variable-private-evidence" v-text="JSON.stringify(preview.privateScope,null,2)" />
          <pre v-text="JSON.stringify(preview.source,null,2)" />
        </template>
      </el-dialog>
    </template>
  </section>
</template>
<script setup>
import ResearchVariableFindings from './ResearchVariableFindings.vue';
import ResearchVariableInput from './ResearchVariableInput.vue';
import {useResearchVariableAssistant} from './useResearchVariableAssistant';
const props=defineProps({feature:{type:Object,default:null},featureKey:{type:String,default:''},initialInput:{type:Object,default:()=>({})},patientId:{type:Number,default:null},encounterRef:{type:String,default:''},active:{type:Boolean,default:true}});
const emit=defineEmits(['cleared']);
const {batchId,sourceEpoch,sourceInitialReferences,sourceChanged,question,previewMode,busy,error,notice,preview,bundle,history,evidenceOpen,closed,sessionAllowed,isSuper,modeReady,scopeValid,available,selectionValid,queueAllowed,polling,feedbackOutcome,feedbackComment,inspect,submit,loadHistory,openHistory,refresh,cancel,feedback,close,reopen,childCleared,closeEvidence}=useResearchVariableAssistant(props,emit);
</script>
<style scoped>
.research-variable-assistant{display:grid;gap:12px}.actions,.task-actions{display:flex;flex-wrap:wrap;gap:8px}.task-actions{display:block}.task-actions>.el-button{margin-bottom:10px}.history-row{display:block;margin:8px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:48vh;overflow:auto}article{border:1px solid var(--el-border-color);padding:12px;border-radius:4px}
</style>
