<template>
  <div class="app-container">
    <vab-page-header title="生命体征录入" />
    <el-card>
      <el-button type="primary" @click="handleAdd">录入体征</el-button>
      <el-table :data="list" v-loading="loading" style="margin-top: 15px">
        <el-table-column prop="id" label="ID" />
        <el-table-column prop="patient_name" label="患者" />
        <el-table-column prop="temperature" label="体温" />
        <el-table-column prop="blood_pressure" label="血压" />
        <el-table-column prop="pulse" label="脉搏" />
        <el-table-column prop="weight" label="体重" />
        <el-table-column prop="check_time" label="测量时间" />
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="录入生命体征" width="600px">
      <el-form :model="form" label-width="120px">
        <el-form-item label="患者ID">
          <el-input-number v-model="form.patient_id" :min="1" />
        </el-form-item>
        <el-form-item label="体温">
          <el-input v-model="form.temperature" placeholder="例如 36.5" />
        </el-form-item>
        <el-form-item label="收缩压">
          <el-input v-model="form.blood_pressure_systolic" placeholder="例如 120" />
        </el-form-item>
        <el-form-item label="舒张压">
          <el-input v-model="form.blood_pressure_diastolic" placeholder="例如 80" />
        </el-form-item>
        <el-form-item label="脉搏">
          <el-input v-model="form.pulse" placeholder="例如 72" />
        </el-form-item>
        <el-form-item label="体重">
          <el-input v-model="form.weight" placeholder="例如 65.5" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { getVitalSignList, createVitalSign } from "@/api/vitalsign";

const list = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const form = ref({ patient_id: 1 });

const fetchList = async () => {
  loading.value = true;
  const res = await getVitalSignList();
  list.value = res.data || [];
  loading.value = false;
};

const handleAdd = () => {
  form.value = { patient_id: 1 };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    await createVitalSign(form.value);
    ElMessage.success("录入成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "录入失败");
  }
};

onMounted(fetchList);
</script>
