<template>
  <div class="app-container">
    <vab-page-header title="病案归档/借阅" description="病案首页归档、借阅归还及封存管理" />
    <el-card>
      <template #header>
        <div class="page-toolbar">
          <el-button type="primary" @click="openCreate">建立归档记录</el-button>
          <el-button size="small" @click="loadAll">刷新</el-button>
        </div>
      </template>
      <el-table :data="archives" v-loading="loading" size="small" empty-text="暂无归档记录">
        <el-table-column prop="archive_no" label="归档号" width="140" />
        <el-table-column prop="admission_no" label="住院号" width="130" />
        <el-table-column prop="patient_name" label="患者" width="90" />
        <el-table-column prop="location" label="存放位置" width="120" />
        <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="tagType(row.status)" size="small">{{ row.status_text }}</el-tag></template></el-table-column>
        <el-table-column prop="borrow_reason" label="借阅事由" show-overflow-tooltip />
        <el-table-column label="操作" width="250">
          <template #default="{ row }">
            <el-button v-if="row.status === 0 && canManage" size="small" type="primary" @click="archive(row)">归档</el-button>
            <el-button v-if="row.status === 1" size="small" @click="borrow(row)">借阅</el-button>
            <el-button v-if="row.status === 2" size="small" type="success" @click="returnArchive(row)">归还</el-button>
            <el-button v-if="[1, 2].includes(row.status) && canManage" size="small" type="warning" @click="seal(row)">封存</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" title="建立归档记录" width="500px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="病案首页" required>
          <el-select v-model="form.home_id" filterable placeholder="请选择已提交病案" style="width: 100%">
            <el-option v-for="item in homes" :key="item.home_id" :label="`${item.patient_name}（${item.admission_no}）`" :value="item.home_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="存放位置"><el-input v-model="form.location" placeholder="例如：A-01-01" maxlength="100" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="createArchive">建立记录</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useStore } from "vuex";
import { ElMessage, ElMessageBox } from "element-plus";
import { getMedicalRecordHomeList } from "@/api/medicalRecordHome";
import { getMedicalRecordArchiveList, createMedicalRecordArchive, archiveMedicalRecord, borrowMedicalRecord, returnMedicalRecord, sealMedicalRecord } from "@/api/medicalRecordArchive";

const store = useStore();
const permissions = computed(() => store.getters["user/permissions"] || []);
const canManage = computed(() => permissions.value.some(role => ["admin", "super_admin", "director"].includes(role)));
const loading = ref(false); const archives = ref([]); const homes = ref([]); const dialogVisible = ref(false); const form = ref({ home_id: "", location: "" });
const tagType = status => ({ 0: "warning", 1: "success", 2: "", 3: "info" }[status] || "info");
const loadAll = async () => { loading.value = true; try { archives.value = (await getMedicalRecordArchiveList()).data || []; } finally { loading.value = false; } };
const openCreate = async () => { homes.value = (await getMedicalRecordHomeList({ status: 1 })).data || []; form.value = { home_id: "", location: "" }; dialogVisible.value = true; };
const createArchive = async () => { if (!form.value.home_id) return ElMessage.warning("请选择已提交病案"); await createMedicalRecordArchive(form.value); ElMessage.success("归档记录已建立"); dialogVisible.value = false; await loadAll(); };
const archive = async row => { await archiveMedicalRecord({ archive_id: row.archive_id }); ElMessage.success("归档成功"); await loadAll(); };
const borrow = async row => { const { value } = await ElMessageBox.prompt("请输入借阅事由", "借阅病案", { inputPlaceholder: "病案质控、复印等" }); await borrowMedicalRecord({ archive_id: row.archive_id, reason: value || "" }); ElMessage.success("借阅登记成功"); await loadAll(); };
const returnArchive = async row => { await returnMedicalRecord({ archive_id: row.archive_id }); ElMessage.success("病案已归还"); await loadAll(); };
const seal = async row => { const { value } = await ElMessageBox.prompt("请输入封存原因", "封存病案", { inputPlaceholder: "年度封存等" }); await sealMedicalRecord({ archive_id: row.archive_id, reason: value || "" }); ElMessage.success("封存成功"); await loadAll(); };
onMounted(loadAll);
</script>
