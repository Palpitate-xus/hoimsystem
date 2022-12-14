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
        label="uuid"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="doctor"
        label="医生"
      ></el-table-column>
      <el-table-column show-overflow-tooltip prop="time" label="日期">
        <template slot-scope="scope">
          {{ scope.row.time }}
        </template>
      </el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="order"
        label="排队序号"
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
            取消挂号
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
  import {
    cancelRegistration,
    getRegistrationList,
  } from '@/api/registrationManagement'
  export default {
    name: 'RegistrationRecords',
    data() {
      return {
        form: {
          specialist: 0,
        },
        list: [],
      }
    },
    created() {
      this.fetchData()
    },
    methods: {
      async fetchData() {
        const { data } = await getRegistrationList()
        this.list = data
        console.log(data)
      },
      async handleCancel(row) {
        if (row.status === '已取消') {
          this.$baseMessage('不能取消已取消的挂号', 'warning')
        } else {
          await cancelRegistration(row)
          this.$baseMessage('取消成功', 'success')
          this.fetchData()
        }
      },
    },
  }
</script>
