<template>
  <div>
    <el-table
      v-loading="listLoading"
      :data="list"
      :element-loading-text="elementLoadingText"
    >
      <el-table-column
        show-overflow-tooltip
        prop="id"
        label="id"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="username"
        label="医生"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="username"
        label="科室"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="username"
        label="内容"
      ></el-table-column>
    </el-table>
  </div>
</template>

<script>
  export default {
    name: 'AdviceManagement',
  }
</script>
