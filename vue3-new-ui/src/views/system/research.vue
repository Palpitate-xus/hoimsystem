<template>
  <div class="research-container">
    <el-card class="box-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span>科研数据导出</span>
          <el-tag type="warning">仅 admin / director 可用 | 敏感数据默认脱敏</el-tag>
        </div>
      </template>

      <el-alert
        title="数据合规提示"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 20px"
      >
        <div>导出的科研数据仅限学术研究使用。开启「脱敏模式」后姓名/身份证/手机号将做不可逆 hash 处理。</div>
      </el-alert>

      <el-form :model="form" label-width="120px">
        <el-form-item label="导出表">
          <el-select v-model="form.table" placeholder="请选择导出的数据表" style="width: 400px">
            <el-option
              v-for="t in tables"
              :key="t.table"
              :label="t.label"
              :value="t.table"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="时间范围">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            value-format="YYYY-MM-DD"
            style="width: 400px"
          />
        </el-form-item>
        <el-form-item label="脱敏模式">
          <el-switch
            v-model="form.anonymize"
            active-text="开启(推荐)"
            inactive-text="关闭"
          />
          <span class="form-tip">开启后姓名/身份证/手机号会被 hash 处理</span>
        </el-form-item>
        <el-form-item label="导出格式">
          <el-radio-group v-model="form.format">
            <el-radio label="csv">CSV</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="handleExport">
            <el-icon><Download /></el-icon> 导出数据
          </el-button>
          <el-button type="success" @click="handleExportPackage">
            <el-icon><Folder /></el-icon> 导出全量数据包(ZIP)
          </el-button>
        </el-form-item>
      </el-form>

      <el-divider />

      <h4>可导出的数据表</h4>
      <el-table :data="tables" stripe border>
        <el-table-column prop="label" label="表名" />
        <el-table-column prop="table" label="代码" />
        <el-table-column label="说明">
          <template #default="{ row: { table } }">
            {{ tableDescriptions[table] || "-" }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from "vue"
import { Download, Folder } from "@element-plus/icons-vue"
import { ElMessage } from "element-plus"
import { useUserStore } from "@/store"
import request from "@/utils/request"

const userStore = useUserStore()
const loading = ref(false)
const dateRange = ref(null)
const tables = ref([])
const form = reactive({
  table: "patients",
  anonymize: true,
  format: "csv",
})

const tableDescriptions = {
  patients: "患者基本信息(姓名/性别/出生日期/过敏史)",
  medical_records: "病历记录(主诉/诊断/时间)",
  prescriptions: "处方药品明细(药品名/数量/状态)",
  charges: "收费记录(金额/状态/时间)",
  lab_results: "检验结果(项目/结果/异常标记/审核状态)",
  surgeries: "手术记录(手术名/麻醉/状态)",
  exams: "体检结果(项目/数值/参考范围/异常标记)",
}

const fetchTables = async () => {
  const { data } = await request({ url: "/api/research/export/tables", method: "GET" })
  if (data && data.code === 200) {
    tables.value = data.data
  }
}

const handleExport = async () => {
  if (!form.table) return ElMessage.warning("请选择要导出的数据表")
  loading.value = true
  try {
    const payload = {
      table: form.table,
      anonymize: form.anonymize,
      format: form.format,
    }
    if (dateRange.value && dateRange.value.length === 2) {
      payload.from = dateRange.value[0]
      payload.to = dateRange.value[1]
    }
    const res = await request({
      url: "/api/research/export",
      method: "POST",
      data: payload,
      responseType: "blob",
    })
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const link = document.createElement("a")
    link.href = url
    const disposition = res.headers["content-disposition"]
    let filename = "research_export.csv"
    if (disposition) {
      const match = disposition.match(/filename\*=UTF-8''(.+)/)
      if (match) filename = decodeURIComponent(match[1])
    }
    link.setAttribute("download", filename)
    document.body.appendChild(link)
    link.click()
    link.remove()
    ElMessage.success("导出成功")
  } catch (error) {
    ElMessage.error("导出失败: " + (error.message || "请重试"))
  } finally {
    loading.value = false
  }
}

const handleExportPackage = async () => {
  loading.value = true
  try {
    const payload = { anonymize: form.anonymize, tables: tables.value.map((t) => t.table) }
    if (dateRange.value && dateRange.value.length === 2) {
      payload.from = dateRange.value[0]
      payload.to = dateRange.value[1]
    }
    const res = await request({
      url: "/api/research/export/package",
      method: "POST",
      data: payload,
      responseType: "blob",
    })
    const url = window.URL.createObjectURL(new Blob([res.data], { type: "application/zip" }))
    const link = document.createElement("a")
    link.href = url
    link.setAttribute("download", `research_package_${new Date().toISOString().slice(0, 10)}.zip`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    ElMessage.success("数据包导出成功")
  } catch (error) {
    ElMessage.error("导出失败: " + (error.message || "请重试"))
  } finally {
    loading.value = false
  }
}

onMounted(fetchTables)
</script>

<style scoped>
.research-container {
  padding: 20px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.form-tip {
  margin-left: 12px;
  color: #909399;
  font-size: 12px;
}
:deep(.el-divider) {
  margin: 24px 0;
}
</style>
