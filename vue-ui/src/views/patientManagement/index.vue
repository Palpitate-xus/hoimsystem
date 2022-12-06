<template>
  <div class="test-container">
    <el-table
      v-loading="listLoading"
      :data="list"
      :element-loading-text="elementLoadingText"
      @selection-change="setSelectRows"
    >
      <el-table-column show-overflow-tooltip type="selection"></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="id"
        label="id"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="name"
        label="姓名"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="sex"
        label="性别"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="birthday"
        label="出生日期"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="phone"
        label="联系方式"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="address"
        label="地址"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="identity"
        label="身份证号"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="permission"
        label="挂号权限"
      ></el-table-column>
      <el-table-column show-overflow-tooltip label="操作" width="200">
        <template #default="{ row }">
          <el-button type="text" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>
<script>
  import { getPatientList } from '@/api/patientManagement'
  export default {
    name: 'Index',
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
      setSelectRows(val) {
        this.selectRows = val
      },
      handleEdit(row) {
        if (row.id) {
          this.$refs['edit'].showEdit(row)
        } else {
          this.$refs['edit'].showEdit()
        }
      },
      handleDelete(row) {
        if (row.id) {
          this.$baseConfirm('你确定要删除当前项吗', null, async () => {
            const { msg } = await doDelete({ ids: row.id })
            this.$baseMessage(msg, 'success')
            this.fetchData()
          })
        } else {
          if (this.selectRows.length > 0) {
            const ids = this.selectRows.map((item) => item.id).join()
            this.$baseConfirm('你确定要删除选中项吗', null, async () => {
              const { msg } = await doDelete({ ids })
              this.$baseMessage(msg, 'success')
              this.fetchData()
            })
          } else {
            this.$baseMessage('未选中任何行', 'error')
            return false
          }
        }
      },
      handleSizeChange(val) {
        this.queryForm.pageSize = val
        this.fetchData()
      },
      handleCurrentChange(val) {
        this.queryForm.pageNo = val
        this.fetchData()
      },
      queryData() {
        this.queryForm.pageNo = 1
        this.fetchData()
      },
      async fetchData() {
        this.listLoading = true
        const { data } = await getPatientList()
        this.list = data
        this.listLoading = false
      },
    },
  }
</script>
