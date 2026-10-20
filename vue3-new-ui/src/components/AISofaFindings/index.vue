<template>
  <section aria-label="SOFA完整原资料与数值协议核对">
    <p v-if="checking">正在核对原住院、完整原件、公开投影及计算绑定。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="view">
      <p v-if="!view.analysis">完整原评估与公开投影已核对；尚无计算结果，不从原量自行推分。</p>
      <p><el-button v-for="item in evidenceItems" :key="item.id" @click="emit('inspect',item.id)">核对{{ item.label }}原依据</el-button></p>
      <template v-if="view.analysis">
      <template v-if="view.changed"><p aria-label="SOFA变化上下界">SOFA变化范围：{{ view.analysis.delta_lower_bound }} 至 {{ view.analysis.delta_upper_bound }}，保留负变化。</p><p aria-label="SOFA变化数值收敛">变化数值收敛：{{ view.analysis.exact_numeric_delta??'未知' }}；完整协议变化 {{ view.analysis.complete_delta??'未知' }}。</p><p>数值变化提示：{{ thresholdLabels[view.analysis.delta_threshold_status] }}。数值变化本身不能确诊或排除脓毒症。</p><p>急性变化 {{ view.source.review.acute_change }}；感染归因 {{ view.source.review.attribution }}；相对感染时序 {{ view.source.review.temporal_relation }}，均为医生当前独立临床判读。</p><p>原感染 {{ view.source.infection.infection_status }}；原发作 {{ view.source.infection.onset_at??'未知' }}；原系统登记 {{ view.source.infection.recorded_at }}。</p><p v-if="view.source.infection.late_original_available_after_current_as_of">原感染声明在当前日历史资料截止之后才可用；本次为当前回顾，不能声称当时已经知道。</p>
        <daily-view :source="view.source.current" :analysis="view.analysis.current_analysis" title="当前日" />
        <daily-view v-if="view.source.baseline.mode==='observed'" :source="view.source.baseline.source" :analysis="view.analysis.baseline_analysis.analysis" title="独立真实基线日" />
        <p v-else-if="view.source.baseline.mode==='conditional_zero'" aria-label="SOFA条件性基线">条件性基线：{{ view.analysis.baseline_analysis.assumptions_confirmed?'两个前提均明确核实，按假设零处理，并非实测正常':'前提未全部确认，保留0至24范围，不能称基线零' }}。</p><p v-else aria-label="SOFA未知基线">原基线未知，保留0至24范围，不从缺少历史记录补零。</p><p v-for="warning in view.analysis.warnings" :key="warning">{{ warning }}</p>
      </template>
      <daily-view v-else :source="view.source" :analysis="view.analysis" />
      </template>
      <p class="hash">原内容 {{ view.scope.content_hash }}；完整公开投影 {{ view.scope.projection_hash }}；临床验证状态：未提供。</p>
    </template>
  </section>
</template>
<script setup>
import {computed,onActivated,onBeforeUnmount,onDeactivated,ref,watch} from "vue";
import {useStore} from "vuex";
import {verifySofaAnalysis,verifySofaChangeAnalysis,verifySofaContext} from "@/api/aiSofa";
import {supportCanonical} from "@/api/inpatientSupport";
import DailyView from "./DailyView.vue";
const props=defineProps({source:{type:Object,default:null},analysis:{type:Object,default:null},scope:{type:Object,default:null},expectedPatientId:{type:Number,required:true},expectedAdmissionId:{type:String,required:true},active:{type:Boolean,default:true}});
const emit=defineEmits(["inspect"]);
const evidenceItems=computed(()=>{if(!view.value)return[];const {source,scope,changed}=view.value,current=changed?source.current:source;return[{id:source.source_id,label:changed?"变化评估":"日评估"},{id:scope.snapshot.rule_profile?.source_id||scope.snapshot.current_assessment?.snapshot.rule_profile.source_id,label:"固定规则"},...(changed?[{id:current.source_id,label:"当前日"},{id:source.infection.source_id,label:"原感染"},...(source.baseline.mode==="observed"?[{id:source.baseline.source.source_id,label:"独立真实基线"}]:[])]:[])].filter(item=>item.id);});
const store=useStore(),view=ref(null),checking=ref(false),error=ref(""),thresholdLabels={at_least_two:"已证明数值变化至少2",below_two:"数值范围低于2，不据此排除脓毒症",indeterminate:"现有范围不能确定是否达到2"};
let epoch=0,alive=true,paused=false,blockedSource=null,blockedScope=null;
const identity=()=>supportCanonical([store.state.user.accessToken,store.getters["user/permissions"]||[]]);
function clear(){epoch++;view.value=null;checking.value=false;error.value="";}
function block(){blockedSource=props.source;blockedScope=props.scope;clear();}
async function validate(){clear();const ticket=epoch,session=identity();if(!alive||paused||!props.active||!props.source||!props.scope)return;if(blockedSource===props.source&&blockedScope===props.scope){error.value="会话或页面范围已变化，请重新读取完整原评估后核对。";return;}checking.value=true;const source=props.source,analysis=props.analysis,scope=props.scope,changed=source.schema_version==="sofa1_change_source_v1",packet=changed?{sofa_change_source:source,sofa_change_assessment:scope}:{sofa_source:source,sofa_assessment:scope};try{if(!await verifySofaContext(packet,props.expectedPatientId,props.expectedAdmissionId)||analysis&&!await(changed?verifySofaChangeAnalysis:verifySofaAnalysis)(source,analysis,scope.projection_hash))throw new Error("原住院、完整清单、公开原量或计算绑定不一致，已拒绝展示结果。");if(!alive||paused||!props.active||epoch!==ticket||identity()!==session)return;view.value={source,analysis,scope,changed};blockedSource=blockedScope=null;}catch(failure){if(alive&&!paused&&props.active&&epoch===ticket&&identity()===session)error.value=failure?.message||"SOFA原来源与结果无法核对，已拒绝展示。";}finally{if(epoch===ticket)checking.value=false;}}
watch([()=>props.source,()=>props.analysis,()=>props.scope,()=>props.expectedPatientId,()=>props.expectedAdmissionId,()=>props.active],()=>{if(!props.active){block();return;}validate();},{immediate:true,deep:true,flush:"sync"});watch(identity,block,{flush:"sync"});onDeactivated(()=>{paused=true;block();});onActivated(()=>{if(paused){paused=false;validate();}});onBeforeUnmount(()=>{alive=false;block();});
</script>
<style scoped>p{line-height:1.7}.hash{overflow-wrap:anywhere}</style>
