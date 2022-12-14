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
        prop="department"
        label="科室"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="doctor"
        label="医生"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="prefer_time"
        label="时间段"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="appointment_time"
        label="预约时间"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="time"
        label="就诊时间"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="specialist"
        label="类别"
        sortable
      >
        <template slot-scope="scope">
          <el-tag
            :type="scope.row.specialist === 1 ? 'warning' : 'info'"
            disable-transitions
          >
            {{ scope.row.specialist === 1 ? '专家号' : '普通号' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="status"
        label="状态"
        sortable
      >
        <template slot-scope="scope">
          <el-tag :type="success">
            {{ scope.row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column show-overflow-tooltip label="操作" width="200">
        <template #default="{ row }">
          <el-button
            type="text"
            :disabled="row.status === '已取消'"
            @click="handleCancel(row)"
          >
            取消预约
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
  import {
    getAppointmentList,
    cancelAppointment,
  } from '@/api/appointmentManagement'
  export default {
    name: 'AppointmentRecords',
    data() {
      return {
        list: null,
        listLoading: true,
        total: 0,
        selectRows: '',
        elementLoadingText: '正在加载...',
      }
    },
    created() {
      this.fetchData()
    },
    methods: {
      async fetchData() {
        this.listLoading = true
        const { data } = await getAppointmentList()
        this.list = data
        this.listLoading = false
      },
      async handleCancel(row) {
        await cancelAppointment(row)
        this.fetchData()
      },
    },
  }
</script>
