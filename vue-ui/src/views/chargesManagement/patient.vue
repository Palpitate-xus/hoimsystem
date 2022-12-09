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
      <el-table-column show-overflow-tooltip prop="status" label="状态">
        <template slot-scope="scope">
          <el-tag
            :type="scope.row.status === 0 ? 'danger' : 'success'"
            disable-transitions
          >
            {{ scope.row.status === 0 ? '未缴费' : '已缴费' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column show-overflow-tooltip label="操作" width="200">
        <template #default="{ row }">
          <el-button type="text" @click="handleCharge(row)">缴费</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
  import { getChargeList, charge } from '../../api/chargesManagement'
  export default {
    name: 'ChargesPatient',
    data() {
      return {
        list: null,
        listLoading: true,
        total: 0,
        selectRows: '',
        form: {},
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
      async handleCharge(row) {
        this.form.id = row.id
        await charge(this.form)
        this.fetchData()
      },
      async fetchData() {
        this.listLoading = true
        const { data } = await getChargeList()
        this.list = data
        this.listLoading = false
      },
    },
  }
</script>
