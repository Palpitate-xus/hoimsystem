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
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="stock"
        label="剩余号源数量"
        sortable
      ></el-table-column>
      <el-table-column show-overflow-tooltip label="操作" width="200">
        <template #default="{ row }">
          <el-button type="text" @click="handleRegister(row)">挂号</el-button>
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
      },
    },
  }
</script>
