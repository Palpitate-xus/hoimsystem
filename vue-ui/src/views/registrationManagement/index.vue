<template>
  <div>
    <el-table
      v-loading="listLoading"
      :data="schedules_list"
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
        sortable
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="time"
        label="时间段"
        sortable
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
        sortable
      ></el-table-column>
      <el-table-column show-overflow-tooltip label="操作" width="200">
        <template #default="{ row }">
          <el-button
            type="text"
            :disabled="row.status"
            @click="handleRegister(row)"
          >
            挂号
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
  import { getList, makeRegistration } from '@/api/registrationManagement'
  export default {
    name: 'RegistrationManagement',
    data() {
      return {
        form: {
          specialist: 0,
        },
        schedules_list: [],
      }
    },
    created() {
      this.fetchData()
    },
    methods: {
      async fetchData() {
        const { data } = await getList()
        if (data === '今天为休息日') {
          this.$baseMessage(data, 'warning')
        } else {
          this.schedules_list = data
        }
        console.log(data)
      },
      async handleRegister(row) {
        await makeRegistration(row)
        this.$baseMessage('挂号成功！', 'success')
        this.fetchData()
      },
    },
  }
</script>
