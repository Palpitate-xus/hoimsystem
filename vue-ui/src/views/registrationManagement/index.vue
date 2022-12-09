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
        sortable
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="username"
        label="时间段"
        sortable
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="username"
        label="类别"
        sortable
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="email"
        label="剩余号源数量"
        sortable
      ></el-table-column>
      <el-table-column show-overflow-tooltip label="操作" width="200">
        <template #default="{ row }">
          <el-button type="text" @click="handleEdit(row)">挂号</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
  import { getDoctorScheduleList } from '@/api/doctorScheduleManagement'
  export default {
    name: 'RegistrationManagement',
    data() {
      return {
        form: {
          specialist: 0,
        },
        departmentList: [],
        doctorList: [],
        timeSlotList: [],
      }
    },
    created() {
      this.fetchData()
    },
    methods: {
      async fetchData() {
        const { data } = await getDoctorScheduleList()
        console.log(data)
      },
      onSubmit() {
        console.log('submit!')
      },
    },
  }
</script>
