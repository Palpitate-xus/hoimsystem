<template>
  <section class="research-variable-assistant" data-testid="research-variable-assistant">
    <h3>科研变量提取</h3>
    <el-alert :closable="false" type="info" title="请逐条核对提取结果，并补充列出的缺项。" />
    <el-alert v-if="!sessionAllowed" :closable="false" type="warning" title="当前会话无明确科研变量角色；项目和全部患者研究、模型用途仍由服务器逐次核验。" />
    <el-alert v-else-if="!scopeValid" :closable="false" type="error" title="本功能仅接受明确变量批次和可选问题；不接受患者、诊次或其他输入。" />
    <el-alert v-else-if="!modeReady" :closable="false" type="warning" title="当前科研变量提取配置不可用，请联系管理员。" />
    <el-button v-if="closed" data-testid="variable-reopen" @click="reopen">重新选择来源</el-button>
    <template v-else-if="available">
      <el-form label-position="top">
        <research-variable-input :key="sourceEpoch" :active="available" :initial-references="sourceInitialReferences" @selection-change="sourceChanged" />
        <el-form-item label="补充问题（可选）">
          <el-input v-model="question" data-testid="variable-question" type="textarea" :rows="3" autocomplete="off" /><small aria-label="补充问题长度">{{ question===null?'问题为空值':Array.from(question).length+'/2000' }}</small>
        </el-form-item>
        <el-checkbox v-if="isSuper" v-model="previewMode" data-testid="variable-preview-mode">超级管理员试运行</el-checkbox>
      </el-form>
      <div class="actions">
        <el-button data-testid="variable-inspect" :disabled="busy || !selectionValid" @click="inspect">查看本次资料</el-button>
        <el-button data-testid="variable-submit" type="primary" :disabled="busy || !queueAllowed" @click="submit">提取变量候选</el-button>
        <el-button data-testid="variable-history" :disabled="busy || !selectionValid" @click="loadHistory">查看历史任务</el-button>
        <el-button data-testid="variable-close" @click="close">关闭并清除内容</el-button>
      </div>
      <p v-if="busy" role="status">正在核对本次资料与任务…</p>
      <el-alert v-if="error" :closable="false" type="error" :title="error" />
      <el-alert v-if="notice" :closable="false" type="info" :title="notice" />
      <article v-if="preview" data-testid="variable-preview">
        <h4>本次资料已核对</h4>
        <p>批次 {{ preview.bindingReference.batch_id }} · 原声明 {{ preview.source.records.length }} 条记录 / {{ preview.source.documents.length }} 个原字段</p>
        <p>已核对项目内全部 {{ preview.preview.research_variable_binding.request_authorization.patient_authorizations.length }} 位患者的研究用途授权；尚未调用模型。</p>
        <details><summary>输入容量与核验详情</summary><p>问题最多2000个Unicode码点、8000字节；资料上限8MiB，入队时另行检查模型请求大小。</p></details>
        <el-button data-testid="variable-evidence" @click="evidenceOpen=true">查看资料原件</el-button>
      </article>
      <div v-if="history.length" data-testid="variable-history-list">
        <h4>本批次历史任务</h4>
        <el-button v-for="row in history" :key="row.run_id" class="history-row" :disabled="busy" @click="openHistory(row)">{{ row.run_id }} · {{ row.status }}</el-button>
      </div>
      <div v-if="bundle" class="task-actions">
        <el-button data-testid="variable-refresh" :disabled="busy" @click="refresh">刷新任务</el-button>
        <el-button v-if="['queued','running'].includes(bundle.run.status)" data-testid="variable-cancel" :disabled="busy" @click="cancel">停止接收本次结果</el-button>
        <p v-if="polling">正在等待本次任务；取消后仍可能产生已发出请求的用量。</p>
        <research-variable-findings :run="bundle.run" :parts="bundle.parts" :expected-run-id="bundle.run.run_id" :expected-batch-id="batchId" :active="available" @close-requested="childCleared" @reload-requested="refresh" />
        <el-form v-if="bundle.run.status==='succeeded'" label-position="top">
          <el-form-item label="人工复核">
            <el-select v-model="feedbackOutcome" data-testid="variable-feedback-outcome"><el-option label="接受为待核候选" value="accepted" /><el-option label="修改后再核" value="modified" /><el-option label="拒绝候选" value="rejected" /></el-select>
          </el-form-item>
          <el-input v-model="feedbackComment" data-testid="variable-feedback-comment" type="textarea" placeholder="可选复核说明，不会自动发布或导出" />
          <el-button data-testid="variable-feedback" :disabled="busy" @click="feedback">保存复核结果</el-button>
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
