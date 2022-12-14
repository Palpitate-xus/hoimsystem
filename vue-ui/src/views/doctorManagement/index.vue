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
        label="医生姓名"
      ></el-table-column>
      <el-table-column show-overflow-tooltip prop="sex" label="性别" sortable>
        <template slot-scope="scope">
          <el-tag
            :type="scope.row.sex === 1 ? 'warning' : 'success'"
            disable-transitions
          >
            {{ scope.row.sex === 1 ? '男' : '女' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="title"
        label="职称"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="education"
        label="学历"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="phone"
        label="联系方式"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="permission"
        label="权限"
        sortable
      >
        <template slot-scope="scope">
          <el-tag
            :type="scope.row.permission === 'director' ? 'warning' : 'info'"
            disable-transitions
          >
            {{ scope.row.permission === 'director' ? '科室主任' : '科室医生' }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column show-overflow-tooltip label="操作" width="200">
        <template #default="{ row }">
          <el-button type="text" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>
<script>
  import { getDoctorList } from '../../api/doctorManagement'
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
