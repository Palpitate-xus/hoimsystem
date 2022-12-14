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
        sotrable
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="time"
        label="时间段"
        sotrable
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="doctor"
        label="医生"
        sotrable
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
        prop="stock"
        label="剩余号源数量"
        sotrable
      ></el-table-column>
      <el-table-column show-overflow-tooltip label="操作" width="200">
        <template #default="{ row }">
          <el-button type="text" @click="handleAppointment(row)">
            预约
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
  import {
    appointmentList,
    makeAppointment,
  } from '../../api/appointmentManagement'
  export default {
    name: 'Index',
    data() {
      return {
        form: {},
        list: [],
      }
    },
    created() {
      this.fetchData()
    },
    methods: {
      async fetchData() {
        const { data } = await appointmentList()
        this.list = data
      },
      async handleAppointment(row) {
        console.log(row)
        await makeAppointment(row)
        this.$baseMessage('预约成功！', 'success')
      },
    },
  }
</script>
