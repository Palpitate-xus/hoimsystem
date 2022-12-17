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
        prop="doctor"
        label="医生"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="inspection"
        label="检查名称"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="time"
        label="检查时间"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="result"
        label="检查结果"
      ></el-table-column>
      <el-table-column show-overflow-tooltip label="操作" width="200">
        <template #default="{ row }">
          <el-button type="text" @click="handleDelete(row)">
            查看检查结果
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <hematology ref="inspect"></hematology>
  </div>
</template>

<script>
  import hematology from './InspectionTemplates/hematology'
  export default {
    name: 'InspectionPatient',
    components: {
      hematology,
    },
    data() {
      return {
        form: {
          patient: 1,
          phas: [],
        },
        list: [
          {
            id: '850ac4573938481490b7a21abf01ca68',
            doctor: 'wms',
            inspection: '血常规',
            time: '2022-12-16',
            result: '白细胞异常',
          },
          {
            id: 'a66054d85367437583cb288901112757',
            doctor: 'grc',
            inspection: '血常规',
            time: '2022-12-17',
            result: '正常',
          },
        ],
      }
    },
    methods: {
      handleDelete(row) {
        this.$refs['inspect'].dialogVisible = true
        console.log(this.$refs['inspect'].dialogVisible)
      },
    },
  }
</script>
