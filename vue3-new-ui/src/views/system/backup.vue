<template>
  <div class="app-container">
    <vab-page-header title="数据备份恢复" description="执行数据备份和恢复操作" />
    <el-card>
      <el-alert
        title="备份恢复说明"
        description="备份功能会复制当前数据库文件。恢复备份将替换当前数据库，恢复前会自动备份当前数据。恢复后需要重启后端服务。"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 20px;"
      />

      <div class="page-toolbar">
        <el-button type="primary" @click="createBackup" :loading="creating"
          >立即备份</el-button
        >
        <el-button @click="fetchList">刷新列表</el-button>
      </div>

      <el-table :data="list" v-loading="loading" empty-text="暂无记录">
        <el-table-column prop="filename" label="文件名" />
        <el-table-column prop="size_human" label="大小" width="120" />
        <el-table-column
          prop="create_time"
          label="创建时间"
          sortable
          width="180"
        />
        <el-table-column label="操作" width="250">
          <template #default="{ row }">
            <el-button size="small" @click="downloadBackup(row)">
              下载
            </el-button>
            <el-button
              size="small"
              type="warning"
              @click="restoreBackup(row)"
            >
              恢复
            </el-button>
            <el-button
              size="small"
              type="danger"
              @click="deleteBackup(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  createBackup as apiCreateBackup,
  getBackupList,
  deleteBackup as apiDeleteBackup,
  restoreBackup as apiRestoreBackup,
  downloadBackupUrl,
} from "@/api/backup";

const list = ref([]);
const loading = ref(false);
const creating = ref(false);

const fetchList = async () => {
  loading.value = true;
  try {
    const res = await getBackupList();
    list.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
  loading.value = false;
};

const createBackup = async () => {
  creating.value = true;
  try {
    const res = await apiCreateBackup();
    if (res.code === 200) {
      ElMessage.success("备份成功: " + res.data.filename);
      fetchList();
    } else {
      ElMessage.error(res.msg || "备份失败");
    }
  } catch (e) {
    ElMessage.error(e.msg || "备份失败");
  }
  creating.value = false;
};

const downloadBackup = (row) => {
  const url = downloadBackupUrl(row.filename);
  const a = document.createElement("a");
  a.href = url;
  a.download = row.filename;
  a.click();
};

const restoreBackup = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定要恢复备份 "${row.filename}" 吗？当前数据将被替换！`,
      "恢复确认",
      { type: "warning", confirmButtonText: "确定恢复" }
    );
    const res = await apiRestoreBackup({ filename: row.filename });
    if (res.code === 200) {
      ElMessage.success("恢复成功，请重启后端服务");
      fetchList();
    } else {
      ElMessage.error(res.msg || "恢复失败");
    }
  } catch (e) {
    if (e !== "cancel") {
      ElMessage.error(e.msg || "恢复失败");
    }
  }
};

const deleteBackup = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定删除备份 "${row.filename}" 吗？`,
      "删除确认",
      { type: "warning" }
    );
    await apiDeleteBackup({ filename: row.filename });
    ElMessage.success("删除成功");
    fetchList();
  } catch (e) {
    if (e !== "cancel") {
      ElMessage.error(e.msg || "删除失败");
    }
  }
};

onMounted(fetchList);
</script>
