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
        label="收费日期"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="username"
        label="收费时间"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="username"
        label="具体项目"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="username"
        label="状态"
      ></el-table-column>
      <el-table-column show-overflow-tooltip label="操作" width="200">
        <template #default="{ row }">
          <el-button type="text" @click="handleEdit(row)">付款</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
  export default {
    name: 'ChargesPatient',
  }
</script>
