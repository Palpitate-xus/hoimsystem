<template>
  <div class="app-container">
    <vab-page-header title="临床路径" description="管理临床路径方案和患者入径记录" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">新增路径</el-button>
      </div>
      <el-table :data="tableData" v-loading="loading" border empty-text="暂无记录">
        <el-table-column prop="name" label="路径名称" />
        <el-table-column prop="disease_code" label="疾病编码" />
        <el-table-column prop="disease_name" label="疾病名称" />
        <el-table-column prop="expected_days" label="预计天数" />
        <el-table-column prop="status_text" label="状态" />
        <el-table-column label="操作" width="360">
          <template #default="scope">
            <el-button size="small" type="primary" @click="handleEdit(scope.row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(scope.row.pathway_id)">删除</el-button>
            <ai-action v-if="canUsePathwayAI" label="AI 治疗方案比选" title="AI 所选临床路径比选" :feature-keys="['treatment_pathway', 'response_review']" initial-feature="treatment_pathway" :initial-input="{ pathway_id: String(scope.row.pathway_id) }" :disabled="scope.row.status !== 0" />
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑临床路径' : '新增临床路径'" width="740px">
      <el-form :model="form" label-width="100px" class="dialog-form">
        <el-form-item label="路径名称">
          <el-input v-model="form.name" maxlength="100" aria-label="路径名称" />
        </el-form-item>
        <el-form-item label="疾病编码">
          <el-input v-model="form.disease_code" maxlength="20" />
        </el-form-item>
        <el-form-item label="疾病名称">
          <el-input v-model="form.disease_name" maxlength="50" />
        </el-form-item>
        <el-form-item label="路径步骤JSON">
          <el-input v-model="form.steps" type="textarea" :rows="9" maxlength="1000" show-word-limit aria-label="路径步骤JSON" placeholder='填写步骤数组或含steps数组的对象；保留适用、排除条件及原始数值。例如 {"inclusion":"适用条件","exclusion":"排除条件","steps":["原步骤"]}' />
        </el-form-item>
        <p>空步骤数组仅保存模板草稿。步骤修改后，原AI审核快照失效，须由超级管理员重新导入并审核；预计天数不作个体出院目标。</p>
        <el-form-item label="预计天数">
          <el-input-number v-model="form.expected_days" :min="1" />
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio :value="0">启用</el-radio>
            <el-radio :value="1">停用</el-radio>
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
import { computed, ref, onMounted } from "vue";
import { useStore } from "vuex";
import { ElMessage, ElMessageBox } from "element-plus";
import { createPathway, getPathwayList, updatePathway, deletePathway } from "@/api/clinicalPathway";
import AiAction from "@/components/AIAction/index.vue";

const store = useStore();
const canUsePathwayAI = computed(() => store.getters["user/permissions"].some(role => ["super_admin", "doctor", "director"].includes(role)));
const tableData = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const isEdit = ref(false);
const form = ref({
  pathway_id: null,
  name: "",
  disease_code: "",
  disease_name: "",
  steps: "[]",
  expected_days: 7,
  status: 0,
});

const fetchList = async () => {
  loading.value = true;
  try {
    const res = await getPathwayList();
    tableData.value = res.data || res;
  } catch (error) {
    ElMessage.error("获取临床路径列表失败");
  }
  loading.value = false;
};

const handleAdd = () => {
  isEdit.value = false;
  form.value = { pathway_id: null, name: "", disease_code: "", disease_name: "", steps: "[]", expected_days: 7, status: 0 };
  dialogVisible.value = true;
};

const handleEdit = (row) => {
  isEdit.value = true;
  form.value = { ...row };
  dialogVisible.value = true;
};

const submitForm = async () => {
  if (!form.value.name?.trim()) { ElMessage.error("请填写路径名称"); return; }
  if (form.value.steps !== null) {
    try { const parsed = JSON.parse(form.value.steps); if (!Array.isArray(parsed) && !(parsed && typeof parsed === "object" && Array.isArray(parsed.steps))) throw new Error(); }
    catch { ElMessage.error("步骤应为JSON数组或含steps数组的对象，请保留原始内容后核对"); return; }
  }
  const payload = Object.fromEntries(["name", "disease_code", "disease_name", "steps", "expected_days", "status"].map(key => [key, form.value[key]]));
  try {
    if (isEdit.value) {
      await updatePathway({ ...payload, pathway_id: form.value.pathway_id, ...(form.value.source_revision ? { expected_source_revision: form.value.source_revision } : {}) });
      ElMessage.success("更新成功");
    } else {
      await createPathway(payload);
      ElMessage.success("新增成功");
    }
    dialogVisible.value = false;
    fetchList();
  } catch (error) {
    ElMessage.error(isEdit.value ? "更新失败" : "新增失败");
  }
};

const handleDelete = async (id) => {
  try {
    await ElMessageBox.confirm("确定删除该临床路径吗？", "提示", { type: "warning" });
    await deletePathway({ pathway_id: id });
    ElMessage.success("删除成功");
    fetchList();
  } catch (error) {
    if (error !== "cancel") {
      ElMessage.error("删除失败");
    }
  }
};

onMounted(() => {
  fetchList();
});
</script>
