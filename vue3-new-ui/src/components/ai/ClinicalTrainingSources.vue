<template>
<section aria-label="合成课程与独立审核治理">
 <p>当前超级管理员登记人工声明的合成材料；独立审核是材料、答案和参考适用性的人工声明，不证明匿名化、临床能力、资格或治疗有效性。</p>
 <p v-if="!v.allowed">当前身份或会话不可读取来源治理。</p>
 <template v-else>
  <p v-if="v.error" role="alert">{{v.error}}</p>
  <el-button :disabled="v.busy" @click="v.directory('lessons')">读取课程技术目录</el-button><el-button :disabled="v.busy" @click="v.directory('reviews')">读取独立审核目录</el-button><el-button :disabled="v.busy" @click="v.directory('submissions')">读取全局提交技术目录</el-button><el-button :disabled="v.busy" @click="v.beginCreate">登记明确合成课程</el-button>
  <p v-if="v.list">第{{v.list.page}}页，每页{{v.list.size}}项；这是有界候选目录，不推断完整总数，不恢复原件读取权。</p>
  <table v-if="v.list"><tbody><tr v-for="row in v.list.items" :key="row.submission_id||row.review_id||row.lesson_id"><td>{{row.title||row.submission_id||row.review_id}} {{row.version_label}}</td><td>{{row.status||'仅实际提交技术记录'}}</td><td><el-button v-if="v.kind!=='submissions'" :disabled="v.busy" @click="v.inspect(row)">核对当前技术头</el-button><span v-else>管理身份不恢复他人作答、答案或反馈正文</span></td></tr></tbody></table>
  <template v-if="v.list"><el-button :disabled="v.busy||v.list.page<=1" @click="v.directory(v.kind,v.list.page-1)">上一页</el-button><el-button :disabled="v.busy||!v.list.has_more" @click="v.directory(v.kind,v.list.next_page)">下一页</el-button></template>
  <p v-if="v.ack" role="status">实际登记或治理回执：{{v.ack.review_id||v.ack.lesson_id}}；状态{{v.ack.status}}，版本{{v.ack.revision}}。已独立GET核对，未自动启用模型功能。</p>
 </template>
 <el-dialog :model-value="v.detailOpen" title="培训来源当前技术头与受控原件" width="85%" :close-on-click-modal="false" :before-close="done=>{v.closeDetail();done();}">
  <template v-if="v.detail"><p>课程{{v.detail.lesson_id}}；审核{{v.detail.review_id||'尚未选择独立审核'}}；{{v.detail.status}}/版本{{v.detail.revision}}。</p><p>技术摘要与实际审计由服务端当前核验；正文需要另行授权，不凭摘要恢复。</p><el-button :disabled="v.busy||v.detail.status==='revoked'" @click="v.expand">显式核对完整课程和全部参考</el-button><el-button v-if="!v.detail.review_id&&v.parts" :disabled="v.busy||v.detail.status!=='active'" @click="v.beginReview">以独立账户核查本完整课程</el-button><el-button :disabled="v.busy||v.detail.status==='revoked'" @click="v.beginRevoke">撤回本明确版本</el-button>
   <article v-if="v.parts" aria-label="受控完整课程原件"><h3>{{v.parts.private.value.title}} {{v.parts.private.value.version_label}}</h3><pre>{{v.parts.private.value.scenario_text}}</pre><section v-for="(q,i) in v.parts.private.value.questions" :key="q.question_id"><h4>{{i+1}}.{{q.stem}}</h4><p>审核答案：{{q.correct_option_ids.map(k=>q.options.find(o=>o.option_id===k)?.text).join('；')}}</p><pre>{{q.reviewed_rationale}}</pre></section><h3>全部明确参考</h3><article v-for="r in v.parts.references.value.references" :key="r.metadata.document_id"><h4>{{r.metadata.title}} {{r.metadata.version}}</h4><pre>{{r.content}}</pre></article></article>
   <pre v-if="v.reviewBody" aria-label="完整独立审核原始JSON">{{v.reviewBody.raw}}</pre>
  </template>
 </el-dialog>
 <el-dialog :model-value="!!v.form" title="明确培训课程登记与治理" width="90%" :close-on-click-modal="false" :before-close="done=>{v.closeForm();done();}">
  <template v-if="v.form"><el-form :disabled="v.busy" label-position="top">
   <template v-if="v.form.kind==='create'">
    <p>不填写真实患者资料。本表不自动识别、删除或匿名化敏感内容。</p>
    <el-form-item label="明确课程版本"><el-input v-model="v.form.body.version_label" aria-label="明确课程版本"/></el-form-item><el-form-item label="课程标题"><el-input v-model="v.form.body.title" aria-label="课程标题"/></el-form-item><el-form-item label="完整合成情景"><el-input v-model="v.form.body.scenario_text" type="textarea" :rows="6" aria-label="完整合成情景"/></el-form-item>
    <el-button :disabled="v.form.body.learning_objectives.length>=32" @click="v.form.body.learning_objectives.push('')">增加明确学习目标</el-button><el-form-item v-for="(_,i) in v.form.body.learning_objectives" :key="i" :label="'学习目标'+(i+1)"><el-input v-model="v.form.body.learning_objectives[i]" :aria-label="'学习目标'+(i+1)"/></el-form-item>
    <p>参考仅来自本次实际返回的有限手工全局training候选，不声称全库；不手输来源UUID。创建时服务端还将核验全部实际作者、当前参考和隐藏原关联。</p>
    <p v-if="!v.candidates.length">当前没有可选的明确手工培训参考，不能创建课程。</p>
    <el-button :disabled="v.form.body.questions.length>=64" @click="v.addQuestion">增加明确题目</el-button>
    <fieldset v-for="(q,i) in v.form.body.questions" :key="q.question_id"><legend>题目{{i+1}}</legend><el-form-item label="明确题型"><el-select v-model="q.selection" :aria-label="'题型'+(i+1)" placeholder="明确选择"><el-option label="单选" value="single"/><el-option label="多选" value="multiple"/></el-select></el-form-item><el-form-item label="完整题干"><el-input v-model="q.stem" :aria-label="'题干'+(i+1)" type="textarea"/></el-form-item><el-form-item v-for="(o,j) in q.options" :key="o.option_id" :label="'选项'+(j+1)"><el-input v-model="o.text" :aria-label="'题目'+(i+1)+'选项'+(j+1)"/></el-form-item><el-button :disabled="q.options.length>=16" @click="v.addOption(q)">为题目{{i+1}}增加选项</el-button>
     <el-form-item label="明确受审答案选项"><el-select v-model="q.correct_option_ids" multiple :aria-label="'受审答案'+(i+1)" placeholder="明确选择，不自动填首项"><el-option v-for="(o,j) in q.options" :key="o.option_id" :value="o.option_id" :label="'选项'+(j+1)+'：'+o.text"/></el-select></el-form-item><el-form-item label="完整审核解析"><el-input v-model="q.reviewed_rationale" :aria-label="'审核解析'+(i+1)" type="textarea"/></el-form-item><el-form-item label="明确参考版本"><el-select v-model="q.reference_ids" multiple :aria-label="'参考版本'+(i+1)" placeholder="从实际有限候选选择"><el-option v-for="r in v.candidates" :key="r.document_id" :value="r.document_id" :label="r.title+' / '+r.version"/></el-select></el-form-item>
    </fieldset>
    <el-checkbox v-model="v.form.body.synthetic_material_declared">我明确声明这份材料为合成教学材料；此声明不代表已独立核实</el-checkbox>
   </template>
   <template v-else-if="v.form.kind==='review'">
    <p>课程UUID、版本和三件完整SHA固定于已核对原件；服务端必须确认当前账户与作者不同。不因超级管理员身份推断医学专业资质。</p>
    <el-form-item label="独立核查决定"><el-select v-model="v.form.body.decision" aria-label="独立核查决定" placeholder="明确选择"><el-option label="发布" value="publish"/><el-option label="拒绝" value="reject"/></el-select></el-form-item><el-checkbox v-model="v.form.body.synthetic_material_checked">已独立核查合成材料声明</el-checkbox><el-checkbox v-model="v.form.body.answer_key_checked">已独立核查答案与解析</el-checkbox><el-checkbox v-model="v.form.body.reference_applicability_checked">已独立核查所选参考适用性</el-checkbox><el-checkbox v-model="v.form.body.model_processing_allowed">另行明确允许本版本模型处理</el-checkbox><el-form-item label="完整独立核查依据"><el-input v-model="v.form.body.basis" aria-label="完整独立核查依据" type="textarea"/></el-form-item>
   </template>
   <el-form-item v-else label="本次明确撤回理由"><el-input v-model="v.form.body.reason" aria-label="本次明确撤回理由" type="textarea"/></el-form-item>
   <el-button :disabled="!v.formValid" :loading="v.busy" @click="v.save">提交明确培训来源操作</el-button><el-button @click="v.closeForm">关闭并清除本次草稿</el-button>
  </el-form></template>
 </el-dialog>
</section>
</template>
<script setup>
import{reactive}from'vue';import{useClinicalTrainingSources}from'./useClinicalTrainingSources';const props=defineProps({active:{type:Boolean,default:true},governance:{type:Boolean,default:true},configRevision:{type:[String,Number],default:null}}),emit=defineEmits(['source-changed','invalidate']),v=reactive(useClinicalTrainingSources(props,emit));
</script><style scoped>section{display:grid;gap:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:50vh;overflow:auto}article,fieldset{padding:16px;border:1px solid #ddd;margin:12px 0}table{width:100%}td{padding:12px;border-bottom:1px solid #ddd}</style>
