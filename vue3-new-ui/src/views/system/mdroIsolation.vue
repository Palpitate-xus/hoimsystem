<template>
  <div class="app-container">
    <vab-page-header title="MDRO 隔离管理" description="多重耐药菌隔离登记与解除；床头隔离标识跟踪" />
    <el-card>
      <div class="page-toolbar">
        <el-select v-model="query.status" placeholder="状态" clearable style="width: 120px" @change="load">
          <el-option label="隔离中" :value="1" />
          <el-option label="已解除" :value="0" />
        </el-select>
        <el-button type="primary" @click="dialogVisible = true">隔离登记</el-button>
      </div>
      <el-table :data="tableData" v-loading="loading" border empty-text="暂无隔离记录">
        <el-table-column prop="patient_name" label="患者" width="100" />
        <el-table-column prop="pathogen" label="耐药菌种" min-width="110" />
        <el-table-column prop="specimen" label="标本" width="90" />
        <el-table-column prop="isolation_type" label="隔离方式" width="100" />
        <el-table-column prop="start_date" label="开始日期" width="110" />
        <el-table-column prop="end_date" label="解除日期" width="110" />
        <el-table-column label="床头标识" width="90">
          <template #default="{ row }">
            <el-tag :type="row.bed_label ? 'danger' : 'info'" size="small">{{ row.bed_label ? "已挂" : "无" }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status_text" label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'danger' : 'success'" size="small">{{ row.status_text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button v-if="row.status === 1" size="small" type="success" @click="handleRelease(row)">解除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="隔离登记" width="480px">
      <el-form :model="form" label-width="100px" class="dialog-form">
        <el-form-item label="患者ID">
          <el-input v-model="form.patient_id" placeholder="患者档案号" />
        </el-form-item>
        <el-form-item label="耐药菌种">
          <el-select v-model="form.pathogen" filterable allow-create>
            <el-option v-for="p in ['MRSA(耐甲氧西林金黄色葡萄球菌)', 'CRKP(耐碳青霉烯肺炎克雷伯菌)', 'CRE(耐碳青霉烯肠杆菌)', 'VRE(耐万古霉素肠球菌)', 'CRAB(耐碳青霉烯鲍曼不动杆菌)', 'MDR-PA(多重耐药铜绿假单胞菌)']" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
        <el-form-item label="标本类型">
          <el-select v-model="form.specimen" filterable allow-create>
            <el-option v-for="s in ['痰液', '血液', '尿液', '伤口分泌物', '脑脊液', '其他']" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="隔离方式">
          <el-select v-model="form.isolation_type">
            <el-option label="接触隔离" value="接触隔离" />
            <el-option label="飞沫隔离" value="飞沫隔离" />
            <el-option label="空气隔离" value="空气隔离" />
          </el-select>
        </el-form-item>
        <el-form-item label="开始日期">
          <el-date-picker v-model="form.start_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">登记</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { getMdroList, createMdro, releaseMdro } from "@/api/hisModules";
import { ElMessage, ElMessageBox } from "element-plus";

export default {
  name: "MdroIsolation",
  data() {
    return {
      loading: false,
      tableData: [],
      query: { status: null },
      dialogVisible: false,
      form: { isolation_type: "接触隔离" },
    };
  },
  created() {
    this.load();
  },
  methods: {
    async load() {
      this.loading = true;
      try {
        const res = await getMdroList(this.query);
        this.tableData = res.data || [];
      } finally {
        this.loading = false;
      }
    },
    async handleCreate() {
      const res = await createMdro(this.form);
      if (res.code === 200) {
        ElMessage.success("登记成功，请打印床头隔离标识");
        this.dialogVisible = false;
        this.form = { isolation_type: "接触隔离" };
        this.load();
      } else ElMessage.error(res.msg);
    },
    async handleRelease(row) {
      const { value } = await ElMessageBox.prompt("解除日期（YYYY-MM-DD，留空为今天）", "解除隔离", { inputValue: "" });
      const res = await releaseMdro({ mdro_id: row.mdro_id, end_date: value || undefined });
      if (res.code === 200) {
        ElMessage.success("已解除");
        this.load();
      } else ElMessage.error(res.msg);
    },
  },
};
</script>
