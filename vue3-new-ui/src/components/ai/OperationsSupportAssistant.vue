<template>
 <section aria-label="受审运维材料专用任务">
  <p v-if="!compatible" role="alert">当前功能、身份或入口不符合受审运维材料模式，未读取其它来源或生成通用任务。</p>
  <template v-else>
   <p>仅使用明确审核发布的材料与三个固定目标；不连接实际环境，不执行命令，不填写患者或自由补充问题。</p>
   <p v-if="error" role="alert">{{error}}</p>
   <OperationsSupportInput v-for="instance in [inputKey]" :key="instance" :initial-references="entryReferences" :active="allowed" :config-revision="configKey" @selection="value=>select(instance,value)" @availability="value=>availability(instance,value)" @invalidate="invalidateInput(instance)"/>
   <el-form label-position="top"><el-form-item label="本次固定目标"><el-select v-model="objective" aria-label="本次固定目标" :disabled="busy"><el-option v-for="(label,key) in objectives" :key="key" :value="key" :label="label"/></el-select></el-form-item></el-form>
   <el-button :disabled="!canCreate" @click="create(false)">提交明确材料与固定目标</el-button>
   <el-button v-if="role==='super_admin'" :disabled="!canPreview" @click="create(true)">以当前配置创建实际模型预览任务</el-button>
   <p v-if="role==='super_admin'">预览会创建真实排队任务并可能产生模型用量；不自动保存配置、发布来源或启用功能。</p>
   <OperationsSupportFindings v-if="runId" :key="runId" :run-id="runId" :selection="runSelection" :active="allowed" :config-revision="configKey" @invalidate="invalidateTaskSource"/>
   <OperationsSupportTasks :active="allowed" :case-id="selected?.operations_case_id??null" :config-revision="configKey"/>
  </template>
 </section>
</template>
<script setup>
import{computed,ref,watch}from'vue';
import OperationsSupportInput from'./OperationsSupportInput.vue';import OperationsSupportFindings from'./OperationsSupportFindings.vue';import OperationsSupportTasks from'./OperationsSupportTasks.vue';import{useOperationsSession}from'./useOperationsSession';
import{operationsCanonical,operationsKeys,operationsId}from'@/api/ai/operationsSupportCore';import{operationsObjectives,operationsReferencesValid,operationsFeatureAllowed,getOperationsTaskDescriptor,verifyOperationsTaskDescriptor,createOperationsTask,verifyOperationsTaskMetadata}from'@/api/ai/operationsSupportTasks';import{operationsRequestValid}from'@/api/ai/operationsSupportSources';
const props=defineProps({feature:{type:Object,default:null},featureKey:{type:String,default:''},initialInput:{type:Object,default:()=>({})},patientId:{type:Number,default:null},encounterRef:{type:String,default:''},pharmaceuticalId:{type:Number,default:null},active:{type:Boolean,default:true}});
const selected=ref(null),sourceReady=ref(false),objective=ref(null),runId=ref(null),runSelection=ref(null),descriptor=ref(null),busy=ref(false),error=ref(''),inputKey=ref(0),objectives=operationsObjectives;
let configEpoch=0;
function dropTask(){runId.value=null;runSelection.value=null;}
function reset(){configEpoch++;selected.value=null;sourceReady.value=false;dropTask();descriptor.value=null;busy.value=false;error.value='';objective.value=entryValid.value&&Object.hasOwn(props.initialInput,'objective')?props.initialInput.objective:null;inputKey.value++;}
const session=useOperationsSession(props,reset),allowed=session.allowed,role=session.role;
const entryValid=computed(()=>{const v=props.initialInput;if(operationsKeys(v,[]))return true;if(operationsReferencesValid(v))return true;return operationsKeys(v,['operations_case_id','objective'])&&operationsRequestValid('OperationsTaskSelection',v);});
const entryReferences=computed(()=>entryValid.value&&Object.hasOwn(props.initialInput,'operations_case_id')?{operations_case_id:props.initialInput.operations_case_id}:null);
const compatible=computed(()=>allowed.value&&props.featureKey==='operations_support'&&props.feature?.key==='operations_support'&&props.feature?.number===79&&props.feature?.engine==='llm'&&props.feature?.scope==='input'&&props.feature?.input_mode==='operations_support_evidence'&&operationsCanonical(props.feature?.source_reference_keys)===operationsCanonical(['operations_case_id'])&&props.patientId===null&&(props.encounterRef===null||props.encounterRef==='')&&props.pharmaceuticalId===null&&entryValid.value);
const configKey=computed(()=>operationsCanonical([props.feature,props.featureKey,props.initialInput,props.patientId,props.encounterRef,props.pharmaceuticalId,props.active,session.store.state.user?.accessToken,session.store.state.user?.username,session.store.state.user?.permissions]));
const selection=computed(()=>selected.value&&Object.hasOwn(objectives,objective.value)?{...selected.value,objective:objective.value}:null),canCreate=computed(()=>compatible.value&&descriptor.value&&sourceReady.value&&selection.value&&!busy.value&&operationsFeatureAllowed(props.feature,role.value)),canPreview=computed(()=>compatible.value&&descriptor.value&&sourceReady.value&&selection.value&&!busy.value&&operationsFeatureAllowed(props.feature,role.value,{preview:true}));
function invalidateSelection(){session.advance();selected.value=null;sourceReady.value=false;dropTask();busy.value=false;}
function availability(instance,value){if(instance===inputKey.value)sourceReady.value=value;}
function invalidateInput(instance){if(instance===inputKey.value)invalidateSelection();}
function invalidateTaskSource(){invalidateSelection();inputKey.value++;error.value='当前任务或来源已失效，请重新核对完整材料集';}
function select(instance,v){if(instance!==inputKey.value)return;dropTask();if(v===null){selected.value=null;return;}if(operationsReferencesValid(v)&&(!entryReferences.value||v.operations_case_id===entryReferences.value.operations_case_id))selected.value=v;else invalidateSelection();}
async function configure(){session.advance();reset();if(!compatible.value)return;const epoch=++configEpoch,key=configKey.value,current=()=>allowed.value&&compatible.value&&epoch===configEpoch&&key===configKey.value;try{const v=(await getOperationsTaskDescriptor()).data;if(!current())return;if(!verifyOperationsTaskDescriptor(v))throw new Error('当前固定目标与四分件协议无法核对');descriptor.value=v;}catch(e){if(current())error.value=e.message||'当前专用任务不可用';}}
async function create(preview){if(preview?!canPreview.value:!canCreate.value)return;const t=session.ticket(),request=structuredClone(selection.value);busy.value=true;dropTask();try{const value=(await createOperationsTask(request,{preview})).data;if(!session.current(t)||operationsCanonical(selection.value)!==operationsCanonical(request))return;if(!verifyOperationsTaskMetadata(value,{selection:request})||value.status!=='queued'||value.preview!==preview||!operationsId(value.run_id))throw new Error('排队回执与明确来源、目标或模式不一致');runSelection.value=request;runId.value=value.run_id;}catch(e){if(session.current(t)){invalidateSelection();error.value=e.message||'当前来源或配置不可执行';inputKey.value++;}}finally{if(session.current(t))busy.value=false;}}
watch(configKey,configure,{immediate:true,flush:'post'});watch(objective,()=>{session.advance();dropTask();busy.value=false;},{flush:'sync'});
</script>
