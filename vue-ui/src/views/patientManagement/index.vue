<template>
  <div class="test-container">
    <el-divider content-position="left">这是病人管理</el-divider>
    <el-table ref="filterTable" :data="tableData" style="width: 100%">
      <el-table-column
        prop="address"
        label="地址"
        :formatter="formatter"
      ></el-table-column>
      <el-table-column
        prop="tag"
        label="标签"
        width="100"
        :filter-method="filterTag"
        filter-placement="bottom-end"
      >
        <template slot-scope="scope">
          <el-tag
            :type="scope.row.tag === '家' ? 'primary' : 'success'"
            disable-transitions
          >
            {{ scope.row.tag }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>
<script>
  export default {
    name: 'Index',
    data() {
      return {
        tableData: [
          {
            date: '2016-05-01',
            name: '王小虎',
            address: '上海市普陀区金沙江路 1519 弄',
            tag: '家',
          },
          {
            date: '2016-05-03',
            name: '王小虎',
            address: '上海市普陀区金沙江路 1516 弄',
            tag: '公司',
          },
        ],
      }
    },
    methods: {
      resetDateFilter() {
        this.$refs.filterTable.clearFilter('date')
      },
      clearFilter() {
        this.$refs.filterTable.clearFilter()
      },
      formatter(row, column) {
        return row.address
      },
      filterTag(value, row) {
        return row.tag === value
      },
      filterHandler(value, row, column) {
        const property = column['property']
        return row[property] === value
      },
    },
  }
</script>
