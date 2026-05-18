<template>
  <el-card shadow="hover">
    <template #header>
      <vab-icon icon="send-plane-2-line" />
      <!-- 计划 -->
      <el-tag class="card-header-tag" type="success">今日计划</el-tag>
    </template>

      <el-input
        v-model="searchQuery"
        placeholder="搜索计划"
        clearable
        style="width: 200px; margin-bottom: 10px;"
      ></el-input>
    <el-table :data="filteredTableData" height="283px" row-key="title" empty-text="暂无计划">
      <el-table-column align="center" label="拖拽" width="50px">
        <template #default="{}">
          <vab-icon :icon="['fas', 'arrows-alt']" style="cursor: pointer" />
        </template>
      </el-table-column>
      <el-table-column width="20px" />
      <el-table-column label="目标" prop="title" width="230px"  sortable />
      <el-table-column label="进度" width="220px">
        <template #default="{ row }">
          <el-progress :color="row.color" :percentage="row.percentage" />
        </template>
      </el-table-column>
      <el-table-column width="50px" />
      <el-table-column label="完成时间" prop="endTIme" />
    </el-table>
  </el-card>
</template>
<script>
export default {
  data() {
    return {
      searchQuery: "",
      tableData: [
        {
          title: "帮助中小企业盈利1个亿",
          endTIme: "2099-12-31",
          percentage: 50,
          color: "#95de64",
        },
        {
          title: "服务10万患者",
          endTIme: "2029-12-31",
          percentage: 35,
          color: "#69c0ff",
        },
        {
          title: "提升就诊效率",
          endTIme: "2025-12-31",
          percentage: 68,
          color: "#409EFF",
        },
        {
          title: "电子病历全覆盖",
          endTIme: "2025-06-30",
          percentage: 85,
          color: "#ffc069",
        },
        {
          title: "智慧医疗建设",
          endTIme: "2026-12-31",
          percentage: 42,
          color: "#5cdbd3",
        },
        {
          title: "患者满意度提升",
          endTIme: "2025-12-31",
          percentage: 78,
          color: "#b37feb",
        },
      ],
    };
  },

  computed: {
    filteredTableData() {
      if (!this.searchQuery) return this.tableData;
      const kw = this.searchQuery.toLowerCase();
      return this.tableData.filter(item =>
        Object.values(item).some(val =>
          String(val ?? "").toLowerCase().includes(kw)
        )
      );
    },
  },
};
</script>
