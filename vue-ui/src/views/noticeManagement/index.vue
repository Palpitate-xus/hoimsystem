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
        prop="uuid"
        label="uuid"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="title"
        label="标题"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="content"
        label="内容"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="isemergency"
        label="是否紧急"
      >
        <template slot-scope="scope">
          <el-tag
            :type="scope.row.isemergency === 1 ? 'danger' : 'success'"
            disable-transitions
          >
            {{ scope.row.isemergency === 1 ? '是' : '否' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="towho"
        label="发送对象"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="readnum"
        label="已读数量"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="sendtime"
        label="发送时间"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="expiredtime"
        label="过期时间"
      ></el-table-column>
      <el-table-column
        show-overflow-tooltip
        prop="writer"
        label="发送人"
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
  import { getNoticeList } from '../../api/notice'
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
        const { data } = await getNoticeList()
        this.list = data
        this.listLoading = false
      },
    },
  }
</script>
