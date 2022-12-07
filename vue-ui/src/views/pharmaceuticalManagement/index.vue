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
        label="药品名称"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="stock"
        label="库存数量"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="price"
        label="单价"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="expireddate"
        label="过期时间"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="purchasing_time"
        label="采购时间"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="supplier"
        label="供应商"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="supplier"
        label="备注"
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
  import { getPharmaceuticalList } from '../../api/pharmaceuticalManagement'
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
        const { data } = await getPharmaceuticalList()
        this.list = data
        this.listLoading = false
      },
    },
  }
</script>
