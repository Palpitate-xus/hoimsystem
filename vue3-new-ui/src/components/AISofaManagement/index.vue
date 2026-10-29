<template>
  <section aria-label="SOFA独立规则与冻结评估治理">
    <p v-if="!allowed">仅超级管理员可管理SOFA固定实施规则和全院冻结评估。</p>
    <template v-else>
      <el-tabs v-model="tab"><el-tab-pane label="SOFA独立固定规则" name="profiles"><template v-if="tab==='profiles'">
      <p>按原单位分别审核SOFA-1评分边界，发布后在功能配置中启用。</p>
      <el-button type="primary" :disabled="!option" @click="openCreate">新建SOFA固定规则草稿</el-button>
      <el-button :loading="loading" @click="load">刷新SOFA审核目录</el-button>
      <p v-if="error" role="alert">{{ error }}</p>
      <el-table :data="items" v-loading="loading" aria-label="SOFA独立规则目录" empty-text="尚无独立SOFA审核版本">
        <el-table-column prop="name" label="审核版本名称" />
        <el-table-column prop="recipe_digest" label="固定配方摘要" min-width="240" />
        <el-table-column label="状态与版本"><template #default="{row}">{{ labels[row.status] }} · v{{ row.revision }}</template></el-table-column>
        <el-table-column label="核对"><template #default="{row}"><el-button @click="inspect(row)">核对SOFA固定规则</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-if="total > 50" v-model:current-page="page" :total="total" :page-size="50" layout="prev,pager,next" @current-change="load" />
      <el-dialog v-model="createOpen" title="新建SOFA固定规则草稿" width="min(850px,96vw)" @closed="clearCreate">
        <el-form v-if="allowed" label-position="top" :disabled="creating" @submit.prevent>
          <p>固定身份 {{ sofaRuleId }}；配方摘要 {{ option?.recipe_digest }}。</p>
          <el-form-item label="SOFA审核版本名称"><el-input v-model="form.name" aria-label="SOFA审核版本名称" maxlength="120" /></el-form-item>
          <el-form-item label="SOFA原依据标识"><el-input v-model="form.evidence_reference" aria-label="SOFA原依据标识" maxlength="1000" /></el-form-item>
          <el-form-item label="SOFA实施审核依据"><el-input v-model="form.rationale" aria-label="SOFA实施审核依据" type="textarea" maxlength="2000" placeholder="至少20字，记录实际核对依据" /></el-form-item>
          <p v-if="createError" role="alert">{{ createError }}</p>
        </el-form>
        <template #footer><el-button @click="createOpen=false">取消</el-button><el-button type="primary" :disabled="!canCreate" :loading="creating" @click="create">仅保存SOFA规则草稿</el-button></template>
      </el-dialog>
      <el-dialog v-model="detailOpen" title="SOFA固定实施规则审计" width="min(1100px,96vw)" @closed="!detailOpen&&clearDetail()">
        <div v-if="allowed" v-loading="inspecting">
          <p v-if="detailError" role="alert">{{ detailError }}</p>
          <template v-if="detail">
            <p class="hash">{{ detail.rule_profile_id }} · {{ labels[detail.status] }} · v{{ detail.revision }}<br />原内容摘要 {{ detail.content_hash }}<br />治理摘要 {{ detail.governance_hash }}</p>
            <p>{{ detail.name }} · {{ detail.rule_id }}；当前实现 {{ detail.implementation_current ? '一致' : '已变化，仅保留原版本审计' }}。</p>
            <p>原依据：{{ detail.evidence_reference }}</p><p>原实施审核：{{ detail.rationale }}</p>
            <details><summary>核对固定配方、原单位分支与本地边界条款</summary><pre>{{ JSON.stringify(detail.recipe,null,2) }}</pre><pre>{{ JSON.stringify(detail.input_policy,null,2) }}</pre></details>
            <p>原发布 {{ detail.published_at || '未发布' }}；审核说明 {{ detail.review_note || '未提供' }}；审核依据 {{ detail.review_evidence_reference || '未提供' }}。</p>
            <template v-if="detail.status==='draft'">
              <el-checkbox v-model="termsConfirmed">我已核对SOFA固定版本、原单位分支、本地边界及输入策略</el-checkbox>
              <el-input v-model="reviewEvidence" aria-label="SOFA发布依据标识" maxlength="2000" placeholder="至少5字，记录实际审核依据" />
              <el-input v-model="reviewNote" aria-label="SOFA发布审核说明" type="textarea" maxlength="2000" placeholder="至少20字，说明审核依据" />
              <el-button type="primary" :disabled="!canPublish" :loading="acting" @click="act('publish')">审核并发布SOFA固定规则</el-button>
            </template>
            <template v-if="detail.status!=='revoked'"><el-input v-model="revokeReason" aria-label="SOFA规则撤销依据" type="textarea" maxlength="1000" placeholder="至少5字，说明撤销原版本的依据" /><el-button type="danger" :disabled="acting || revokeReason.trim().length<5" :loading="acting" @click="act('revoke')">撤销SOFA固定规则</el-button></template>
            <p v-else>已撤销 {{ detail.revoked_at }}：{{ detail.revoke_reason }}；不能恢复原版本。</p>
          </template>
        </div>
      </el-dialog>
      </template></el-tab-pane><el-tab-pane label="SOFA日评估全院审计" name="daily" lazy><assessment-audit v-if="tab==='daily'" /></el-tab-pane><el-tab-pane label="SOFA变化全院审计" name="change" lazy><assessment-audit v-if="tab==='change'" :change-mode="true" /></el-tab-pane></el-tabs>
    </template>
  </section>
</template>
<script setup>
import { computed, defineAsyncComponent, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from "vue";
import { useStore } from "vuex";
import { createRiskRuleProfile, getRiskRuleOptions, getRiskRuleProfile, getRiskRuleProfiles, publishRiskRuleProfile, revokeRiskRuleProfile } from "@/api/aiNews2";
import { sofaRuleId, verifySofaProfile } from "@/api/aiSofa";
import { supportDigest, supportHash } from "@/api/inpatientSupport";
const store=useStore(),roles=computed(()=>store.getters["user/permissions"]||[]),allowed=computed(()=>!!store.state.user.accessToken&&roles.value.includes("super_admin"));
const AssessmentAudit=defineAsyncComponent(()=>import("./AssessmentAudit.vue")),tab=ref("profiles");
const labels={draft:"草稿",published:"已发布",revoked:"已撤销"},items=ref([]),total=ref(0),page=ref(1),option=ref(null),loading=ref(false),error=ref("");
const blank=()=>({name:"",evidence_reference:"",rationale:""}),form=ref(blank()),createOpen=ref(false),creating=ref(false),createError=ref("");
const detailOpen=ref(false),detail=ref(null),inspecting=ref(false),detailError=ref(""),termsConfirmed=ref(false),reviewNote=ref(""),reviewEvidence=ref(""),revokeReason=ref(""),acting=ref(false);
let epoch=0,listSequence=0,detailSequence=0,createSequence=0,paused=false,alive=true;
const identity=()=>JSON.stringify([store.state.user.accessToken,roles.value]),capture=()=>({epoch,identity:identity()}),current=ticket=>alive&&!paused&&allowed.value&&tab.value==="profiles"&&ticket.epoch===epoch&&ticket.identity===identity();
const canCreate=computed(()=>allowed.value&&!!option.value&&!creating.value&&form.value.name.trim().length>0&&form.value.evidence_reference.trim().length>=5&&form.value.rationale.trim().length>=20);
const canPublish=computed(()=>allowed.value&&detail.value?.status==="draft"&&!acting.value&&termsConfirmed.value&&reviewEvidence.value.trim().length>=5&&reviewNote.value.trim().length>=20);
function clearCreate(){createSequence++;createOpen.value=false;creating.value=false;createError.value="";form.value=blank();}
function clearDetail(){detailSequence++;detail.value=null;detailError.value="";inspecting.value=acting.value=false;termsConfirmed.value=false;reviewNote.value=reviewEvidence.value=revokeReason.value="";}
function reset(){epoch++;listSequence++;clearCreate();clearDetail();detailOpen.value=false;items.value=[];option.value=null;total.value=0;page.value=1;loading.value=false;error.value="";}
async function loadOptions(){const ticket=capture();if(!current(ticket))return;try{const response=await getRiskRuleOptions();const rows=response.data?.items;if(!Array.isArray(rows))throw new Error("SOFA固定规则选项未符合契约");const selected=rows.filter(row=>row.rule_id===sofaRuleId);if(selected.length!==1||!supportHash(selected[0].recipe_digest)||await supportDigest(selected[0].recipe)!==selected[0].recipe_digest)throw new Error("SOFA固定配方选项未能完整核对");if(current(ticket))option.value=selected[0];}catch(failure){if(current(ticket))error.value=failure?.message||"SOFA固定规则选项读取失败";}}
async function load(){const ticket=capture(),seq=++listSequence,requestedPage=page.value;if(!current(ticket))return;loading.value=true;items.value=[];error.value="";try{const response=await getRiskRuleProfiles({rule_id:sofaRuleId,page:requestedPage,page_size:50});const data=response.data;if(!current(ticket)||seq!==listSequence||requestedPage!==page.value)return;if(!Array.isArray(data?.items)||!Number.isSafeInteger(data.total)||data.total<0||data.items.some(row=>row.rule_id!==sofaRuleId)||!(await Promise.all(data.items.map(verifySofaProfile))).every(Boolean))throw new Error("SOFA规则目录与固定身份或原摘要不一致");if(current(ticket)&&seq===listSequence&&requestedPage===page.value){items.value=data.items;total.value=data.total;}}catch(failure){if(current(ticket)&&seq===listSequence)error.value=failure?.message||"SOFA治理目录读取失败";}finally{if(current(ticket)&&seq===listSequence)loading.value=false;}}
function openCreate(){if(!allowed.value||paused||!option.value)return;clearCreate();createOpen.value=true;}
async function create(){if(!canCreate.value)return;const ticket=capture(),seq=createSequence,payload={...form.value,rule_id:sofaRuleId,expected_recipe_digest:option.value.recipe_digest};creating.value=true;try{const response=await createRiskRuleProfile(payload),row=response.data;if(!current(ticket)||seq!==createSequence||!createOpen.value)return;if(!await verifySofaProfile(row)||row.status!=="draft"||row.revision!==1||row.name!==payload.name||row.recipe_digest!==payload.expected_recipe_digest)throw new Error("SOFA规则草稿回执与明确审核版本不一致");if(!current(ticket)||seq!==createSequence||!createOpen.value)return;clearCreate();await load();}catch(failure){if(current(ticket)&&seq===createSequence)createError.value=failure?.message||"SOFA规则草稿保存失败";}finally{if(current(ticket)&&seq===createSequence)creating.value=false;}}
async function inspect(original){if(!allowed.value||paused)return;clearDetail();detailOpen.value=true;inspecting.value=true;const ticket=capture(),seq=detailSequence;try{const response=await getRiskRuleProfile(original.rule_profile_id),row=response.data;if(!current(ticket)||seq!==detailSequence||!detailOpen.value)return;if(!await verifySofaProfile(row)||row.rule_profile_id!==original.rule_profile_id||row.content_hash!==original.content_hash)throw new Error("SOFA规则原件与指定版本不一致");if(current(ticket)&&seq===detailSequence&&detailOpen.value)detail.value=row;}catch(failure){if(current(ticket)&&seq===detailSequence)detailError.value=failure?.message||"SOFA规则原件核对失败";}finally{if(current(ticket)&&seq===detailSequence)inspecting.value=false;}}
async function act(action){if(!allowed.value||paused||acting.value||!detail.value||action==="publish"&&!canPublish.value||action==="revoke"&&(detail.value.status==="revoked"||revokeReason.value.trim().length<5))return;const ticket=capture(),seq=detailSequence,original=detail.value,payload=action==="publish"?{expected_revision:original.revision,expected_recipe_digest:original.recipe_digest,implementation_terms_confirmed:true,review_note:reviewNote.value.trim(),review_evidence_reference:reviewEvidence.value.trim()}:{expected_revision:original.revision,reason:revokeReason.value.trim()};acting.value=true;try{const response=await(action==="publish"?publishRiskRuleProfile(original.rule_profile_id,payload):revokeRiskRuleProfile(original.rule_profile_id,payload)),row=response.data;if(!current(ticket)||seq!==detailSequence||!detailOpen.value)return;if(!await verifySofaProfile(row)||row.rule_profile_id!==original.rule_profile_id||row.content_hash!==original.content_hash||row.status!==(action==="publish"?"published":"revoked")||row.revision!==original.revision+1)throw new Error("SOFA规则治理回执与原内容或CAS版本不一致");if(!current(ticket)||seq!==detailSequence||!detailOpen.value)return;detail.value=row;termsConfirmed.value=false;reviewNote.value=reviewEvidence.value=revokeReason.value="";await load();}catch(failure){if(current(ticket)&&seq===detailSequence)detailError.value=failure?.message||"SOFA规则治理失败，请重新核对版本";}finally{if(current(ticket)&&seq===detailSequence)acting.value=false;}}
watch(tab,()=>{reset();loadOptions();load();},{flush:"sync"});
watch(identity,()=>{reset();loadOptions();load();},{immediate:true,flush:"sync"});
onDeactivated(()=>{paused=true;reset();});onActivated(()=>{if(paused){paused=false;reset();loadOptions();load();}});onBeforeUnmount(()=>{alive=false;reset();});
</script>
<style scoped>p{line-height:1.7}.hash,pre{overflow-wrap:anywhere;white-space:pre-wrap}.el-checkbox{display:flex;white-space:normal;margin:12px 0}.el-button{margin:8px 8px 8px 0}</style>
