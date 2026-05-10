<template>
  <div class="app-container">
    <vab-page-header title="药品不良反应监测" />
    <el-card>
      <el-button type="primary" @click="handleAdd">上报ADR</el-button>
      <el-table :data="list" v-loading="loading" style="margin-top: 15px">
        <el-table-column prop="patient_name" label="患者" />
        <el-table-column prop="pharmaceutical_name" label="药品" />
        <el-table-column prop="symptom" label="症状" show-overflow-tooltip />
        <el-table-column prop="severity_text" label="严重程度" width="100" />
        <el-table-column prop="status_text" label="状态" width="100" />
        <el-table-column prop="report_time" label="上报时间" width="160" />
        <el-table-column label="操作" width="150">
          <template #default="{row}">
            <el-button v-if="row.status===0" size="small" type="primary" @click="updateStatus(row,1)">确认</el-button>
            <el-button v-if="row.status===1" size="small" type="success" @click="updateStatus(row,2)">处理</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" title="上报ADR" width="500px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="患者ID"><el-input v-model="form.patient_id" /></el-form-item>
        <el-form-item label="药品ID"><el-input v-model="form.pharmaceutical_id" /></el-form-item>
        <el-form-item label="症状"><el-input v-model="form.symptom" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="严重程度">
          <el-radio-group v-model="form.severity">
            <el-radio :label="1">轻度</el-radio><el-radio :label="2">中度</el-radio><el-radio :label="3">重度</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible=false">取消</el-button><el-button type="primary" @click="submit">确定</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { createAdverseReaction, getAdverseReactionList, updateAdrStatus } from "@/api/adverseReaction";
const list=ref([]), loading=ref(false), dialogVisible=ref(false), form=ref({severity:1});
const fetchList=async()=>{loading.value=true;const res=await getAdverseReactionList();list.value=res.data||[];loading.value=false;};
const handleAdd=()=>{form.value={severity:1};dialogVisible.value=true;};
const submit=async()=>{try{await createAdverseReaction(form.value);ElMessage.success("上报成功");dialogVisible.value=false;fetchList();}catch(e){ElMessage.error(e.msg||"上报失败");}};
const updateStatus=async(row,status)=>{try{await updateAdrStatus({reaction_id:row.reaction_id,status});ElMessage.success("状态更新成功");fetchList();}catch(e){ElMessage.error(e.msg||"更新失败");}};
onMounted(fetchList);
</script>
