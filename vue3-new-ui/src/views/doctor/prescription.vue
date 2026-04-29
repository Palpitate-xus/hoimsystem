<template>
  <div class="app-container">
    <vab-page-header title="处方管理" />
    <el-card>
      <el-button type="primary" @click="handleAdd">开处方</el-button>
      <el-table :data="list" v-loading="loading" style="margin-top: 15px">
        <el-table-column prop="uuid" label="处方ID" />
        <el-table-column prop="doctor_name" label="医生" />
        <el-table-column prop="patient_name" label="患者" />
        <el-table-column prop="status" label="状态">
          <template #default="{row}">
            <el-tag v-if="row.status===0" type="warning">待审核</el-tag>
            <el-tag v-else-if="row.status===1" type="primary">已审核</el-tag>
            <el-tag v-else-if="row.status===2" type="success">已发药</el-tag>
            <el-tag v-else type="danger">已取消</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="创建时间" />
        <el-table-column label="药品明细">
          <template #default="{row}">
            <div v-for="(p, i) in row.phas" :key="i">{{ p.name }} x{{ p.number }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{row}">
            <el-button size="small" type="danger" @click="cancel(row)">取消</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="开处方" width="700px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="患者ID">
          <el-input-number v-model="form.patient" :min="1" />
        </el-form-item>
        <el-form-item label="药品">
          <div v-for="(item, i) in form.phas" :key="i" style="margin-bottom:10px">
            <el-select v-model="item.id" placeholder="选择药品" style="width:200px;margin-right:10px">
              <el-option v-for="p in pharmaceuticals" :key="p.pharmaceutical_id" :label="p.name" :value="p.pharmaceutical_id" />
            </el-select>
            <el-input-number v-model="item.number" :min="1" style="width:120px;margin-right:10px" />
            <el-button type="danger" size="small" @click="removePharmaceutical(i)">删除</el-button>
          </div>
          <el-button type="primary" size="small" @click="addPharmaceutical">添加药品</el-button>
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
import { getPrescriptionList, createPrescription, cancelPrescription } from "@/api/doctor";
import { getPharmaceuticalList } from "@/api/pharmacy";

const list = ref([]);
const pharmaceuticals = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const form = ref({ patient: 1, phas: [] });

const fetchList = async () => {
  loading.value = true;
  const res = await getPrescriptionList();
  list.value = res.data || [];
  loading.value = false;
};

const handleAdd = async () => {
  const res = await getPharmaceuticalList();
  pharmaceuticals.value = res.data || [];
  form.value = { patient: 1, phas: [{ id: null, number: 1 }] };
  dialogVisible.value = true;
};

const addPharmaceutical = () => {
  form.value.phas.push({ id: null, number: 1 });
};

const removePharmaceutical = (i) => {
  form.value.phas.splice(i, 1);
};

const submit = async () => {
  try {
    await createPrescription(form.value);
    ElMessage.success("开方成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "开方失败");
  }
};

const cancel = async (row) => {
  try {
    await cancelPrescription({ prescription_id: row.uuid });
    ElMessage.success("取消成功");
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "取消失败");
  }
};

onMounted(fetchList);
</script>
