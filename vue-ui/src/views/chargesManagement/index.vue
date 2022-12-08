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
        prop="patient"
        label="病人"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="charge_time"
        label="收费时间"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="time"
        label="缴费时间"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="pre_id"
        label="处方编号"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="amount"
        label="收费金额"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="status"
        label="状态"
      ></el-table-column>
    </el-table>
  </div>
</template>

<script>
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
      async fetchData() {
        this.listLoading = true
        const { data } = await getDoctorList()
        this.list = data
        this.listLoading = false
      },
    },
  }
</script>
