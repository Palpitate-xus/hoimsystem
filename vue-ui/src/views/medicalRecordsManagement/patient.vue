<template>
  <div>
    <el-table
      v-loading="listLoading"
      :data="list"
      :element-loading-text="elementLoadingText"
    >
      <el-table-column
        show-overflow-tooltip
        prop="uuid"
        label="id"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="doctor"
        label="医生"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="symptom"
        label="病人症状"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="result"
        label="诊断结果"
      ></el-table-column>
    </el-table>
  </div>
</template>

<script>
  export default {
    name: 'MedicalRecordsPatient',
  }
</script>
