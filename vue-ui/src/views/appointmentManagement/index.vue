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
        prop="date"
        label="日期"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="time"
        label="时间段"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="doctor"
        label="医生"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="specialist"
        label="类别"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="available"
        label="剩余号源数量"
      ></el-table-column>
      <el-table-column show-overflow-tooltip label="操作" width="200">
        <template #default="{ row }">
          <el-button type="text" @click="handleEdit(row)">预约</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
  import { getDepartmentList } from '../../api/departmentManagement'
  import { getDoctorList } from '../../api/doctorManagement'
  export default {
    name: 'Index',
    data() {
      return {
        form: {},
        pickerOptions: {
          disabledDate(time) {
            return time.getTime() > Date.now() + 3600 * 1000 * 24 * 7
          },
        },
      }
    },
    created() {
      this.fetchData()
    },
    methods: {
      async fetchData() {
        const { data_department } = await getDepartmentList()
        const { data_doctor } = await getDoctorList()
        this.departmentList = data_department
        this.doctorList = data_doctor
      },
      onSubmit() {
        console.log('submit!')
      },
    },
  }
</script>
