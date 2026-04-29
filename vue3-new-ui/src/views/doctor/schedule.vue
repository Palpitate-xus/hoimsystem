<template>
  <div class="app-container">
    <vab-page-header title="医生排班" />
    <el-card>
      <el-button type="primary" @click="handleAdd">设置排班</el-button>
      <el-table :data="list" v-loading="loading" style="margin-top: 15px">
        <el-table-column prop="id" label="医生ID" />
        <el-table-column prop="name" label="医生姓名" />
        <el-table-column prop="schedule" label="排班">
          <template #default="{row}">
            <el-tag v-for="(s,i) in row.schedule" :key="i" style="margin-right:5px">{{ s }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="number" label="号源数" />
        <el-table-column prop="specialist" label="专家号">
          <template #default="{row}">
            <el-tag v-if="row.specialist">是</el-tag>
            <el-tag v-else type="info">否</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="设置排班" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="医生">
          <el-select v-model="form.doctor">
            <el-option v-for="d in doctors" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="排班">
          <el-checkbox-group v-model="form.scheduleArr">
            <el-checkbox label="星期一01">周一上午</el-checkbox>
            <el-checkbox label="星期一02">周一下午</el-checkbox>
            <el-checkbox label="星期二01">周二上午</el-checkbox>
            <el-checkbox label="星期二02">周二下午</el-checkbox>
            <el-checkbox label="星期三01">周三上午</el-checkbox>
            <el-checkbox label="星期三02">周三下午</el-checkbox>
            <el-checkbox label="星期四01">周四上午</el-checkbox>
            <el-checkbox label="星期四02">周四下午</el-checkbox>
            <el-checkbox label="星期五01">周五上午</el-checkbox>
            <el-checkbox label="星期五02">周五下午</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="号源数">
          <el-input-number v-model="form.number" :min="1" />
        </el-form-item>
        <el-form-item label="专家号">
          <el-switch v-model="form.specialist" :active-value="1" :inactive-value="0" />
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
import { getDoctorScheduleList, registerDoctorSchedule } from "@/api/doctor";
import { getDoctorList } from "@/api/admin";

const list = ref([]);
const doctors = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const form = ref({ scheduleArr: [], number: 10, specialist: 0 });

const fetchList = async () => {
  loading.value = true;
  const res = await getDoctorScheduleList();
  list.value = res.data || [];
  loading.value = false;
};

const handleAdd = async () => {
  const res = await getDoctorList();
  doctors.value = res.data || [];
  form.value = { scheduleArr: [], number: 10, specialist: 0 };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    await registerDoctorSchedule({ ...form.value, schedule: form.value.scheduleArr });
    ElMessage.success("设置成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "设置失败");
  }
};

onMounted(fetchList);
</script>
