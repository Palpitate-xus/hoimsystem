<template>
  <div class="app-container">
    <vab-page-header title="不良事件上报" description="上报和处理医疗安全不良事件" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">新增不良事件</el-button>
      </div>
      <el-table :data="tableData" v-loading="loading" border empty-text="暂无记录">
        <el-table-column prop="event_type" label="事件类型" />
        <el-table-column prop="patient_name" label="患者姓名" />
        <el-table-column prop="description" label="描述" show-overflow-tooltip />
        <el-table-column prop="severity_text" label="严重程度" />
        <el-table-column prop="status_text" label="状态" />
        <el-table-column label="操作" width="310">
          <template #default="scope">
            <el-button v-if="rcaAllowed" @click="openRca(scope.row)">完整RCA来源与调查草稿</el-button>
            <el-button
              v-if="scope.row.status === 1"
              size="small"
              type="warning"
              @click="handleUpdateStatus(scope.row.id, 2)"
            >确认</el-button>
            <el-button
              v-if="scope.row.status === 2"
              size="small"
              type="success"
              @click="handleUpdateStatus(scope.row.id, 3)"
            >处理</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="rcaVisible" title="本事件完整RCA来源与调查草稿" width="90%" :close-on-click-modal="false" destroy-on-close>
      <template v-if="rcaScope&&rcaAllowed"><p>实际事件 {{rcaScope.eventId}}；本行原患者关联 {{rcaScope.expectedPatientId===null?'明确未记录患者':rcaScope.expectedPatientId}}。技术角色不能代替本件独立事件和患者用途。</p><el-tabs v-model="rcaTab"><el-tab-pane label="完整来源与独立用途" name="source"><RcaEvidenceSources v-if="rcaTab==='source'" :key="rcaKey" :event-id="rcaScope.eventId" :expected-patient-id="rcaScope.expectedPatientId" :active="rcaVisible&&rcaAllowed" selectable @select="selectRca" @invalidate="rcaReferences=null"/></el-tab-pane><el-tab-pane label="本件未核实调查任务" name="task" :disabled="!rcaReferences"><AiAssistant v-if="rcaTab==='task'&&rcaReferences" :key="rcaKey" :feature-keys="['incident_rca']" initial-feature="incident_rca" :initial-input="rcaReferences" :rca-event-id="rcaScope.eventId" :rca-expected-patient-id="rcaScope.expectedPatientId"/></el-tab-pane></el-tabs></template>
    </el-dialog>

    <el-dialog v-model="dialogVisible" title="新增不良事件" width="500px">
      <el-form :model="form" label-width="100px" class="dialog-form">
        <el-form-item label="事件类型">
          <el-select v-model="form.event_type" placeholder="请选择事件类型">
            <el-option label="用药错误" value="用药错误" />
            <el-option label="跌倒/坠床" value="跌倒/坠床" />
            <el-option label="手术并发症" value="手术并发症" />
            <el-option label="院内感染" value="院内感染" />
            <el-option label="设备故障" value="设备故障" />
            <el-option label="其他" value="其他" />
          </el-select>
        </el-form-item>
        <el-form-item label="患者">
          <el-input v-model="form.patient_id" placeholder="输入患者姓名或身份证号" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="严重程度">
          <el-radio-group v-model="form.severity">
            <el-radio :label="1">轻度</el-radio>
            <el-radio :label="2">中度</el-radio>
            <el-radio :label="3">重度</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref,computed,watch,onBeforeUnmount,onDeactivated, onMounted } from "vue";
import { ElMessage } from "element-plus";
import {useStore} from 'vuex';
import RcaEvidenceSources from '@/components/ai/RcaEvidenceSources.vue';
import AiAssistant from '@/components/AIAssistant/index.vue';
import {rcaPositive} from '@/api/ai/rcaEvidenceSources';
import { createAdverseEvent, getAdverseEventList, updateEventStatus } from "@/api/adverseEvent";

const store=useStore(),rcaAllowed=computed(()=>!!store.state.user?.accessToken&&(store.state.user?.permissions||[]).includes('super_admin')),rcaScope=ref(null),rcaVisible=ref(false),rcaReferences=ref(null),rcaTab=ref('source'),rcaKey=ref(0);
function clearRca(){rcaVisible.value=false;rcaScope.value=null;rcaReferences.value=null;rcaTab.value='source';rcaKey.value++;}
function openRca(row){clearRca();if(!rcaAllowed.value||!rcaPositive(row?.event_id)||row.patient_id!==null&&!rcaPositive(row.patient_id))return;rcaScope.value={eventId:row.event_id,expectedPatientId:row.patient_id};rcaVisible.value=true;}
function selectRca(row){if(!rcaAllowed.value||!rcaVisible.value||!row?.eligible||row.immutable.event_id!==rcaScope.value?.eventId||row.immutable.patient_id_at_capture!==rcaScope.value?.expectedPatientId)return;rcaReferences.value={rca_evidence_case_id:row.immutable.case_id};rcaTab.value='task';}
watch(rcaVisible,value=>{if(!value)clearRca();},{flush:'sync'});
watch(()=>JSON.stringify([store.state.user?.accessToken,store.state.user?.permissions,store.state.user?.username]),clearRca,{flush:'sync'});onDeactivated(clearRca);onBeforeUnmount(clearRca);
const tableData = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const form = ref({
  event_type: "",
  patient_id: "",
  description: "",
  severity: 1,
});

const fetchList = async () => {
  loading.value = true;
  try {
    const res = await getAdverseEventList();
    tableData.value = res.data || res;
  } catch (error) {
    ElMessage.error("获取不良事件列表失败");
  }
  loading.value = false;
};

const handleAdd = () => {
  form.value = { event_type: "", patient_id: "", description: "", severity: 1 };
  dialogVisible.value = true;
};

const submitForm = async () => {
  try {
    await createAdverseEvent(form.value);
    ElMessage.success("新增成功");
    dialogVisible.value = false;
    fetchList();
  } catch (error) {
    ElMessage.error("新增失败");
  }
};

const handleUpdateStatus = async (id, status) => {
  try {
    await updateEventStatus({ id, status });
    ElMessage.success("状态更新成功");
    fetchList();
  } catch (error) {
    ElMessage.error("状态更新失败");
  }
};

onMounted(() => {
  fetchList();
});
</script>
