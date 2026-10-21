<template>
  <section aria-label="病案编码依据来源与治理">
    <p v-if="!allowed">当前身份无法读取病案编码来源。</p>
    <template v-else>
      <p>快照保留本病案全部原始编码依据。本地前缀规则只供核对，字典发布版本和历史分组规则版本仍未知；技术发布不确认诊断，也不提供官方 DRG/DIP 分组器。</p>
      <el-tabs v-model="tab"><el-tab-pane label="完整病案快照" name="case" /><el-tab-pane label="本地前缀规则包" name="package" /></el-tabs>
      <el-button @click="load" :loading="loading">重新读取当前目录</el-button>
      <el-button v-if="tab === 'case' && scopeReady && options?.can_record" @click="openCreate">捕获完整病案快照</el-button>
      <el-button v-if="tab === 'package' && options?.can_manage_rule_packages" @click="openCreate">登记本地前缀规则包</el-button>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="tab === 'case' && !scopeReady && !auditOnly">先从已授权的真实患者、住院与病案首页进入。</p>
      <el-table v-if="directory" :data="directory.items" border aria-label="编码来源技术目录">
        <el-table-column :label="tab === 'case' ? '原编码快照' : '原规则包'" min-width="300"><template #default="{row}">{{ row.case_snapshot_id || row.package_id }}</template></el-table-column>
        <el-table-column prop="status" label="原治理状态" /><el-table-column prop="revision" label="治理版本" /><el-table-column prop="created_at" label="服务器登记时刻" min-width="240" />
        <el-table-column label="操作" min-width="150"><template #default="{row}"><el-button @click="inspect(row)">核对完整原件</el-button></template></el-table-column>
      </el-table>
      <div v-if="directory && directory.total > 20"><el-button :disabled="page <= 1 || loading" @click="changePage(-1)">上一页原件</el-button><span>第 {{ page }} 页，共 {{ directory.total }} 件</span><el-button :disabled="page * 20 >= directory.total || loading" @click="changePage(1)">下一页原件</el-button></div>
      <article v-if="detail" aria-label="已核对编码依据完整原件">
        <p>原件 {{ detail.source_id }}；完整 SHA {{ detail.content_hash }}；治理 SHA {{ detail.governance_hash }}。</p>
        <p v-if="!detail.eligible">本件当前不可执行：{{ detail.exclusion_reasons.join('、') }}。</p>
        <template v-if="detail.snapshot">
          <template v-if="tab === 'case'">
            <p>完整 {{ detail.snapshot.collection.code_bindings.length }} 条编码绑定、{{ detail.snapshot.collection.dictionary_entries.length }} 条对应字典、{{ detail.snapshot.collection.recorded_groups.length }} 条已记分组、{{ detail.snapshot.collection.member_manifest.length }} 个原成员。</p>
            <dl><template v-for="field in textFields" :key="field"><dt>{{ fieldLabels[field] }}</dt><dd>{{ detail.snapshot.collection.home[field] === null ? '原件未记录' : detail.snapshot.collection.home[field] }}</dd></template></dl>
            <details><summary>原编码绑定与当前字典（完整分页）</summary><el-table :data="detail.snapshot.collection.code_bindings.slice(bindingPage * 20, bindingPage * 20 + 20)" border aria-label="完整原编码绑定分页"><el-table-column prop="kind" label="原类型" /><el-table-column prop="icd_code" label="原编码" /><el-table-column prop="icd_name" label="原存储名称" /><el-table-column prop="is_primary" label="原主要标记" /></el-table><el-button :disabled="bindingPage === 0" @click="bindingPage--">上一页编码</el-button><el-button :disabled="(bindingPage + 1) * 20 >= detail.snapshot.collection.code_bindings.length" @click="bindingPage++">下一页编码</el-button></details>
            <p>旧临床记录时钟按原始文本保留，时区依据未知，不能解释为原 UTC 或当时可得证据。</p>
          </template>
          <template v-else><p>冻结 {{ detail.snapshot.rules.length }} 条实际本地前缀规则；不是官方发布分组器。</p><el-table :data="detail.snapshot.rules" border><el-table-column prop="rule_id" label="原规则ID" /><el-table-column prop="group_code" label="原组编码" /><el-table-column prop="version" label="原本地版本" /><el-table-column prop="status" label="原状态" /></el-table></template>
        </template>
        <p v-else>当前授权仅返回失效原件的技术元数据；正文及自由治理备注已隐藏。</p>
        <el-button v-if="tab === 'case' && !auditOnly && detail.eligible && detail.public_source" @click="selectDetail">选择本条受审编码快照</el-button>
        <div v-if="detail.can_review || detail.can_revoke" aria-label="编码来源治理操作">
          <el-input v-model="basis" type="textarea" aria-label="本次编码来源治理依据" placeholder="明确审核或撤销依据，至少20个非空白字符" />
          <el-button v-if="detail.can_review" :disabled="!basisValid || governing" @click="govern('publish')">审核发布本件</el-button><el-button v-if="detail.can_review" :disabled="!basisValid || governing" @click="govern('reject')">审核拒绝本件</el-button><el-button v-if="detail.can_revoke" :disabled="!revokeBasisValid || governing" @click="govern('revoke')">撤销本件</el-button>
          <p>撤销依据至多1000个 Unicode 字符且4000 UTF-8字节；其他审核依据至多4000 UTF-8字节。</p>
        </div>
      </article>
      <el-dialog v-model="creating" :title="tab === 'case' ? '捕获完整病案原件' : '登记本地前缀规则包'" @closed="closedCreate">
        <template v-if="creating && tab === 'case'">
          <p>固定真实病案 {{ homeId }}，只捕获当前完整集合，不按旧时间回放，不使用截断清单。</p>
          <el-radio-group v-model="packageMode" aria-label="本次本地规则包用途"><el-radio value="none">明确不附加本地规则包</el-radio><el-radio value="selected">选取一个受审本地规则包</el-radio></el-radio-group>
          <el-select v-if="packageMode === 'selected'" v-model="packageId" aria-label="本次受审本地规则包" placeholder="逐件核对后明确选择" @change="selectPackage"><el-option v-for="r in packages" :key="r.package_id" :value="r.package_id" :label="r.package_id" /></el-select>
          <el-button :disabled="!captureRequest || previewing" @click="capture">预览完整当前病案集合</el-button>
          <template v-if="preview"><p aria-label="已核对完整病案预览">全部 {{ preview.member_manifest.length }} 个成员；全集 SHA {{ preview.collection_digest }}；逐件清单 SHA {{ preview.manifest_hash }}。</p><el-table :data="preview.member_manifest.slice(memberPage * 20, memberPage * 20 + 20)" border><el-table-column prop="kind" label="原件类型" /><el-table-column prop="record_id" label="原件真实标识" /><el-table-column prop="content_hash" label="成员SHA" /></el-table><el-button :disabled="memberPage === 0" @click="memberPage--">上一页成员</el-button><el-button :disabled="(memberPage + 1) * 20 >= preview.member_manifest.length" @click="memberPage++">下一页成员</el-button><p>分页只影响显示，登记绑定全部成员。</p></template>
          <el-input v-model="note" type="textarea" aria-label="院内编码快照登记备注" placeholder="可留空，至多4000 UTF-8字节；不发送给模型" />
        </template>
        <template v-if="creating && tab === 'package'">
          <p>只选择当前真实本地 DrgRule 原行。版本为本地原字段，不构成官方规则发布证明。</p>
          <el-select v-model="ruleIds" multiple aria-label="实际本地前缀规则" placeholder="明确选择原规则"><el-option v-for="r in rules" :key="r.rule_id" :value="r.rule_id" :label="`${r.rule_id} · ${r.group_code} · ${r.version}`" /></el-select>
          <el-input v-model="packageBasis" type="textarea" aria-label="本地规则包登记依据" placeholder="至少20个非空白字符，至多4000 UTF-8字节" />
        </template>
        <template #footer><el-button @click="closeCreate">关闭登记</el-button><el-button :disabled="!createValid || saving" :loading="saving" @click="save">登记待审核原件</el-button></template>
      </el-dialog>
    </template>
  </section>
</template>

<script setup>
import {computed,onActivated,onBeforeUnmount,onDeactivated,ref,watch} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical as canonical} from '@/api/inpatientSupport';
import * as api from '@/api/ai/codingEvidence';
const props=defineProps({patientId:{type:Number,default:null},admissionId:{type:String,default:null},homeId:{type:String,default:null},active:{type:Boolean,default:true},auditOnly:{type:Boolean,default:false}}),emit=defineEmits(['select','source-changed','invalidate']),store=useStore();
const roles=computed(()=>store.getters['user/permissions']||[]),allowed=computed(()=>props.active&&!!store.state.user.accessToken&&(props.auditOnly?roles.value.includes('super_admin'):roles.value.some(r=>['admin','super_admin','doctor','director'].includes(r))));
const scope=computed(()=>({patient_id:props.patientId,admission_id:props.admissionId,home_id:props.homeId})),scopeReady=computed(()=>api.codingScopeValid(scope.value));
const tab=ref('case'),options=ref(null),directory=ref(null),detail=ref(null),page=ref(1),loading=ref(false),error=ref(''),basis=ref(''),governing=ref(false),creating=ref(false),saving=ref(false),previewing=ref(false),preview=ref(null),note=ref(''),packageMode=ref(null),packageId=ref(null),selectedPackage=ref(null),packages=ref([]),rules=ref([]),ruleIds=ref([]),packageBasis=ref(''),memberPage=ref(0);
const bindingPage=ref(0);
const textFields=['admission_diagnosis','discharge_diagnosis','other_diagnosis','operation_summary','complication'],fieldLabels={admission_diagnosis:'原入院诊断',discharge_diagnosis:'原出院诊断',other_diagnosis:'原其他诊断',operation_summary:'原手术记录摘要',complication:'原并发症记录'};
const basisValid=computed(()=>api.codingEvidenceBasis(basis.value)),revokeBasisValid=computed(()=>api.codingEvidenceRevokeBasis(basis.value));
let initialized=false,alive=true,paused=false,epoch=0,loadVersion=0,inspectVersion=0,createVersion=0,governVersion=0;
const identity=()=>canonical([scope.value,props.active,props.auditOnly,store.state.user.accessToken,store.state.user.username,roles.value,tab.value]);
const ticket=()=>({epoch,identity:identity()}),current=t=>alive&&!paused&&allowed.value&&t.epoch===epoch&&t.identity===identity();
function clear(notify=true){epoch++;loadVersion++;inspectVersion++;createVersion++;governVersion++;options.value=null;directory.value=null;detail.value=null;basis.value='';error.value='';loading.value=false;governing.value=false;creating.value=false;saving.value=false;previewing.value=false;preview.value=null;selectedPackage.value=null;packages.value=[];rules.value=[];ruleIds.value=[];packageBasis.value='';note.value='';packageMode.value=null;packageId.value=null;if(notify)emit('invalidate');}
function fail(message){clear();error.value=message||'当前病案、原件或授权无法核对，旧依据已清除。';}
async function load(notify=true){
 clear(notify);const t=ticket(),version=++loadVersion;if(!current(t)||tab.value==='case'&&!scopeReady.value&&!props.auditOnly)return;loading.value=true;
 try{const params={...(scopeReady.value?scope.value:{}),audit_only:props.auditOnly},o=(await api.getCodingEvidenceOptions(params)).data;if(!current(t)||version!==loadVersion)return;if(!api.codingEvidenceOptionsValid(o,params))throw new Error('当前来源权限与真实病案范围无法核对。');options.value=o;
  const query={...params,page:page.value,page_size:20},value=(await(tab.value==='case'?api.getCodingEvidenceCases(query):api.getCodingEvidencePackages({audit_only:props.auditOnly,page:page.value,page_size:20}))).data;
  if(!current(t)||version!==loadVersion)return;
  if(!api.codingEvidenceDirectoryValid(value,tab.value,query))throw new Error('来源目录的闭集元数据、分页或实际范围无法核对。');directory.value=value;
 }catch(e){if(current(t)&&version===loadVersion)fail(e.message);}
 finally{if(current(t)&&version===loadVersion)loading.value=false;}
}
async function inspect(row){detail.value=null;basis.value='';const t=ticket(),version=++inspectVersion,id=tab.value==='case'?row.case_snapshot_id:row.package_id;
 try{const value=(await(tab.value==='case'?api.getCodingEvidenceCase(id,{auditOnly:props.auditOnly}):api.getCodingEvidencePackage(id,{auditOnly:props.auditOnly}))).data;
  if(!current(t)||version!==inspectVersion)return;
  const valid=tab.value==='case'?await api.verifyCodingEvidenceCase(value,{patientId:props.patientId,admissionId:props.admissionId,homeId:props.homeId,auditOnly:props.auditOnly}):await api.verifyCodingEvidencePackage(value,{auditOnly:props.auditOnly});
  if(!current(t)||version!==inspectVersion)return;
  if(!valid||(value.case_snapshot_id||value.package_id)!==id||value.content_hash!==row.content_hash||value.governance_hash!==row.governance_hash)throw new Error('完整原件、自身SHA、逐件全集或当前治理与目录不一致。');detail.value=value;bindingPage.value=0;
 }catch(e){if(current(t)&&version===inspectVersion)fail(e.message);}
}
async function selectDetail(){const old=detail.value;if(!old||props.auditOnly||!scopeReady.value)return;const t=ticket(),version=++inspectVersion;
 try{const value=(await api.getCodingEvidenceCase(old.case_snapshot_id,{auditOnly:false})).data;if(!current(t)||version!==inspectVersion)return;
  if(value.case_snapshot_id!==old.case_snapshot_id||value.content_hash!==old.content_hash||value.governance_hash!==old.governance_hash||!value.eligible||!await api.verifyCodingEvidenceCase(value,{patientId:props.patientId,admissionId:props.admissionId,homeId:props.homeId,auditOnly:false}))throw new Error('所选原件或治理已改变，请重新读取。');
  if(!current(t)||version!==inspectVersion)return;detail.value=value;emit('select',{coding_case_id:value.case_snapshot_id});
 }catch(e){if(current(t)&&version===inspectVersion)fail(e.message);}
}
const captureRequest=computed(()=>{if(!scopeReady.value||!['none','selected'].includes(packageMode.value))return null;const p=selectedPackage.value;if(packageMode.value==='selected'&&(!p||p.package_id!==packageId.value||!p.eligible))return null;return{...scope.value,rule_package_id:packageMode.value==='none'?null:p.package_id,expected_rule_package_content_hash:packageMode.value==='none'?null:p.content_hash,expected_rule_package_governance_hash:packageMode.value==='none'?null:p.governance_hash};});
const createBody=computed(()=>tab.value==='case'?preview.value&&captureRequest.value?{request:captureRequest.value,expected_collection_digest:preview.value.collection_digest,note:note.value}:null:{package_kind:'local_prefix_snapshot',rule_ids:ruleIds.value,basis_note:packageBasis.value});
const createValid=computed(()=>creating.value&&!!createBody.value&&api.codingEvidenceRequestValid(tab.value==='case'?'CaseCreate':'RulePackageCreate',createBody.value)&&(tab.value!=='case'||canonical(preview.value.request)===canonical(captureRequest.value)));
async function completeCatalog(kind,t,version){
 const result=[];let total=null;
 for(let p=1;;p++){const query={page:p,page_size:kind==='package'?20:100,...(kind==='package'?{audit_only:false}:{})},value=(await(kind==='package'?api.getCodingEvidencePackages(query):api.getCodingEvidenceRules(query))).data;
  if(!current(t)||version!==createVersion||!creating.value)return null;
  if(!(kind==='package'?api.codingEvidenceDirectoryValid(value,'package',query):api.codingEvidenceRulesValid(value,query))||total!==null&&value.total!==total||value.total>4096)throw new Error('当前候选目录无法完整核对或已改变，未使用截断清单。');
  total=value.total;result.push(...value.items);const key=kind==='package'?'package_id':'rule_id';
  if(new Set(result.map(r=>r[key])).size!==result.length||new TextEncoder().encode(canonical(result)).length>8388608)throw new Error('原候选目录存在重复或超出完整字节上限。');
  if(result.length===total)return result;
 }
}
async function openCreate(){closeCreate();creating.value=true;const t=ticket(),version=++createVersion;
 try{if(tab.value==='case'){if(!scopeReady.value)throw new Error('须绑定本次真实病案。');const rows=await completeCatalog('package',t,version);if(rows!==null&&current(t)&&version===createVersion&&creating.value)packages.value=rows;}else{const rows=await completeCatalog('rule',t,version);if(rows!==null&&current(t)&&version===createVersion&&creating.value)rules.value=rows;}}
 catch(e){if(current(t)&&version===createVersion&&creating.value)fail(e.message);}
}
async function selectPackage(){selectedPackage.value=null;preview.value=null;const t=ticket(),version=++createVersion,id=packageId.value;if(!id)return;try{const value=(await api.getCodingEvidencePackage(id,{auditOnly:false})).data;if(!current(t)||version!==createVersion||!creating.value)return;if(value.package_id!==id||!value.eligible||!await api.verifyCodingEvidencePackage(value,{auditOnly:false}))throw new Error('本地规则包当前无法用于原病案。');if(!current(t)||version!==createVersion||!creating.value)return;selectedPackage.value=value;}catch(e){if(current(t)&&version===createVersion&&creating.value)fail(e.message);}}
async function capture(){const body=captureRequest.value;if(!body)return;const expected=canonical(body),t=ticket(),version=++createVersion;preview.value=null;previewing.value=true;try{const value=(await api.previewCodingEvidence(body)).data;if(!current(t)||version!==createVersion||!creating.value||canonical(captureRequest.value)!==expected)return;if(!await api.verifyCodingEvidenceCapture(value,body))throw new Error('完整病案捕获的逐件哈希或作用域不一致。');if(!current(t)||version!==createVersion||!creating.value||canonical(captureRequest.value)!==expected)return;preview.value=value;memberPage.value=0;}catch(e){if(current(t)&&version===createVersion&&creating.value)fail(e.message);}finally{if(current(t)&&version===createVersion&&creating.value)previewing.value=false;}}
async function save(){if(!createValid.value)return;const body=JSON.parse(canonical(createBody.value)),expected=canonical(body),t=ticket(),version=++createVersion,kind=tab.value;saving.value=true;try{const value=(await(kind==='case'?api.createCodingEvidenceCase(body):api.createCodingEvidencePackage(body))).data;if(!current(t)||version!==createVersion||!creating.value||canonical(createBody.value)!==expected)return;const valid=kind==='case'?await api.verifyCodingEvidenceCase(value,{patientId:props.patientId,admissionId:props.admissionId,homeId:props.homeId,auditOnly:false}):await api.verifyCodingEvidencePackage(value,{auditOnly:true});if(!current(t)||version!==createVersion||!creating.value||canonical(createBody.value)!==expected)return;if(!valid||value.status!=='draft'||kind==='case'&&(value.collection_digest!==body.expected_collection_digest||canonical(value.snapshot.collection.request)!==canonical(body.request)||value.snapshot.note!==body.note)||kind==='package'&&(canonical(value.snapshot.rule_ids)!==canonical([...body.rule_ids].sort((a,b)=>a-b))||value.snapshot.basis_note!==body.basis_note))throw new Error('原件登记回执的身份、完整SHA、实际请求或治理不一致。');closeCreate();emit('source-changed');await load(false);}catch(e){if(current(t)&&version===createVersion&&creating.value)fail(e.message);}finally{if(current(t)&&version===createVersion)saving.value=false;}}
async function govern(action){const before=detail.value;if(!before||(action==='revoke'?!revokeBasisValid.value:!basisValid.value))return;const body={expected_revision:before.revision,expected_content_hash:before.content_hash,...(action==='revoke'?{}:{decision:action}),basis_note:basis.value},t=ticket(),version=++governVersion,kind=tab.value;governing.value=true;
 try{const fn=kind==='case'?(action==='revoke'?api.revokeCodingEvidenceCase:api.reviewCodingEvidenceCase):(action==='revoke'?api.revokeCodingEvidencePackage:api.reviewCodingEvidencePackage),value=(await fn(before.case_snapshot_id||before.package_id,body)).data;if(!current(t)||version!==governVersion)return;if(!await api.verifyCodingEvidenceTransition(value,before,action,body,kind))throw new Error('治理回执未绑定本次CAS及原始完整原件。');if(!current(t)||version!==governVersion)return;emit('source-changed');await load(false);}catch(e){if(current(t)&&version===governVersion)fail(e.message);}finally{if(current(t)&&version===governVersion)governing.value=false;}}
function closeCreate(){createVersion++;creating.value=false;saving.value=false;previewing.value=false;preview.value=null;note.value='';packageMode.value=null;packageId.value=null;selectedPackage.value=null;packages.value=[];rules.value=[];ruleIds.value=[];packageBasis.value='';}
function closedCreate(){if(!creating.value)closeCreate();}
function changePage(n){page.value+=n;load();}
watch(()=>canonical(captureRequest.value),()=>{createVersion++;preview.value=null;previewing.value=false;saving.value=false;},{flush:'sync'});
watch(identity,()=>{if(initialized)emit('invalidate');initialized=true;page.value=1;clear(false);load(false);},{immediate:true,flush:'sync'});
onDeactivated(()=>{paused=true;clear();});onActivated(()=>{if(paused){paused=false;load(false);}});onBeforeUnmount(()=>{alive=false;clear(false);});
</script>
<style scoped>p,dd{line-height:1.7;overflow-wrap:anywhere}article{border:1px solid #dcdfe6;padding:16px;margin-top:16px}dd{white-space:pre-wrap;margin-bottom:10px}.el-button{margin:6px}.el-select{min-width:320px}.el-textarea{margin:10px 0}</style>
