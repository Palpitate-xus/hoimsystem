<template>
  <el-card v-if="authorized && !dismissed" class="document-change-findings" shadow="never">
    <template #header><div class="heading"><strong>双原文核对问题草稿</strong><el-button text @click="clear">清除结果</el-button></div></template>
    <p v-if="busy" role="status">正在核对完整原件、冻结任务和逐字跨度…</p>
    <el-alert v-else-if="error" :title="error" type="error" :closable="false" />
    <template v-else-if="checked">
      <el-alert :title="coverage" type="warning" :closable="false" />
      <p>{{ auditOnly ? '超级管理员冻结审计：不声明来源当前仍可执行。' : '已比对当前范围与完整冻结原件。' }}</p>
      <dl class="facts">
        <dt>任务状态</dt><dd>{{ states[checked.run.status] }}</dd>
        <dt>声明范围</dt><dd>{{ checked.run.document_change_scope_id }}</dd>
        <dt>输入 / 输出 token</dt><dd>{{ token(checked.run.usage_receipt.input_tokens) }} / {{ token(checked.run.usage_receipt.output_tokens) }}</dd>
        <dt>实际模型调用</dt><dd>{{ attempted(checked.run.usage_receipt.model_call_attempted) }}</dd>
      </dl>
      <p>只比较明确的两件原文与有限目标集合；未提供全院规则覆盖。逐字相交不是已确认影响，未相交也不是无影响。</p>
      <template v-if="checked.result">
        <p>本次提出 {{ changes.length }} 项待核问题。</p><details><summary>任务摘要原文</summary><p class="summary">{{ checked.result.result.summary }}</p></details>
        <p v-if="!changes.length">未返回核对问题；这不表示没有变化或已完成全文检查。</p>
        <article v-for="(change,index) in changes" :key="index" class="question">
          <h4>待人工核实问题 {{ index + 1 }}</h4>
          <p>{{ change.review_note }}</p><p>{{ change.clarification_question }}</p>
          <div v-for="side in ['baseline','candidate']" :key="side">
            <strong>{{ side === 'baseline' ? '基准原文' : '候选原文' }}</strong>
            <p v-if="!change[side + '_spans'].length">本项未引用这一侧；不能据此推断全文不存在对应内容。</p>
            <figure v-for="(span,ordinal) in change[side + '_spans']" :key="ordinal">
              <figcaption>原文引文</figcaption><details><summary>引文位置</summary><p>Unicode codepoint [{{ span.start }}, {{ span.end }})</p></details><pre>{{ span.quote }}</pre>
            </figure>
          </div>
          <p v-if="!change.link_overlaps.length">本问题未产生逐字相交记录；这不表示院内规则无影响。</p>
          <ul v-else><li v-for="overlap in change.link_overlaps" :key="overlap.link.link_id">
            {{ overlap.link.target.kind }} · {{ overlap.link.target.target_id }} · {{ overlap.link.current ? '已审核且当前关联' : '未获当前关联确认' }} · {{ overlap.link.within_declared_scope ? '声明范围内' : '声明范围外，仅保留证据' }} · 目标状态 {{ overlap.target.state }}
          </li></ul>
        </article>
      </template>
      <p v-else>本状态没有已接受的问题正文。取消或失败不代表模型未调用；以上用量保留实际已知值与未知值。</p>
      <el-button @click="evidenceOpen = !evidenceOpen">{{ evidenceOpen ? '收起完整证据' : '查看完整院内证据' }}</el-button>
      <section v-if="evidenceOpen" class="evidence">
        <h4>冻结的两件完整原文</h4>
        <div v-for="side in ['baseline','candidate']" :key="side"><strong>{{ side === 'baseline' ? '基准原文' : '候选原文' }}</strong><pre>{{ checked.source.document_change_source[side].text }}</pre></div>
        <h4>完整私有目标与治理原件</h4><p>以下院内证据不作为提供方输入；执行只发送经核对的公开原文投影。</p><pre>{{ privateEvidence }}</pre>
      </section>
    </template>
  </el-card>
</template>

<script setup>
import {computed,onBeforeUnmount,onDeactivated,ref,shallowRef,watch} from 'vue';
import {useStore} from 'vuex';
import {verifyDocumentChangeRun,documentChangeCoverageNote,documentChangeRunStates} from '@/api/ai/documentChangeResults';
const props=defineProps({bundle:{type:Object,default:null},liveScope:{type:Object,default:null},auditOnly:{type:Boolean,default:false},active:{type:Boolean,default:true}});
const emit=defineEmits(['cleared']),store=useStore(),checked=shallowRef(null),busy=ref(false),error=ref(''),dismissed=ref(false),evidenceOpen=ref(false);let version=0;
const roles=computed(()=>store.getters['user/permissions'] ?? store.state.user?.permissions),authorized=computed(()=>props.active&&Array.isArray(roles.value)&&roles.value.includes('super_admin')&&typeof store.state.user?.accessToken==='string'&&store.state.user.accessToken.trim().length>0);
const states=documentChangeRunStates,coverage=documentChangeCoverageNote,changes=computed(()=>checked.value?.result?.result.document_change.changes||[]),privateEvidence=computed(()=>checked.value?JSON.stringify(checked.value.scope.scope_snapshot.inventory.targets,null,2):'');
const token=v=>v===null?'未知':String(v),attempted=v=>v===null?'未知':v?'已调用':'已证明未调用';
function wipe(){version++;checked.value=null;error.value='';busy.value=false;evidenceOpen.value=false;}
function clear(){wipe();dismissed.value=true;emit('cleared');}
async function inspect(){wipe();dismissed.value=false;if(!authorized.value||!props.bundle)return;const ticket=version,raw=props.bundle,scope=props.liveScope,audit=props.auditOnly;busy.value=true;const current=()=>version===ticket&&authorized.value&&props.bundle===raw&&props.liveScope===scope&&props.auditOnly===audit;
 const valid=await verifyDocumentChangeRun(raw,{liveScope:scope,auditOnly:audit,current});if(!current())return;busy.value=false;if(!valid){error.value='完整任务、原件、Prompt 或逐字证明核对失败，未显示私有正文。';return;}checked.value=raw;
}
watch(()=>[props.bundle,props.liveScope,props.auditOnly],inspect,{immediate:true,deep:true,flush:'sync'});
watch(()=>[store.state.user?.accessToken,store.state.user?.username,JSON.stringify(roles.value),props.active],()=>{wipe();dismissed.value=true;},{flush:'sync'});
onDeactivated(clear);onBeforeUnmount(wipe);
</script>

<style scoped>
.heading{display:flex;align-items:center;justify-content:space-between}.facts{display:grid;grid-template-columns:max-content 1fr;gap:6px 14px}.facts dd{margin:0;overflow-wrap:anywhere}.question{margin-top:16px;border-top:1px solid var(--el-border-color);padding-top:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--el-fill-color-light);padding:10px;max-height:360px;overflow:auto}figure{margin:10px 0}.evidence{margin-top:12px}p,li{line-height:1.7}
</style>
