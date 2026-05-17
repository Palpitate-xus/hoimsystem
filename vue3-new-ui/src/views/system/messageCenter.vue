<template>
  <div class="app-container">
    <vab-page-header title="消息中心" description="查看和管理系统消息通知" />
    <el-card>
      <el-table :data="messageList" empty-text="暂无记录">
        <el-table-column prop="title" label="标题" />
        <el-table-column prop="content" label="内容" />
        <el-table-column prop="msg_type" label="类型" width="80">
          <template #default="{row}">
            <el-tag v-if="row.msg_type==='sms'">短信</el-tag>
            <el-tag v-else type="success">站内信</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="is_read" label="状态" width="80">
          <template #default="{row}">
            <el-tag v-if="row.is_read" type="info">已读</el-tag>
            <el-tag v-else type="warning">未读</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="时间" sortable />
        <el-table-column label="操作" width="100">
          <template #default="{row}">
            <el-button v-if="!row.is_read" size="small" @click="markRead(row)">标为已读</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { getMessageList, readMessage } from "@/api/system";
import { ElMessage } from "element-plus";

const messageList = ref([]);

const loadData = async () => {
  try {
    const res = await getMessageList();
    messageList.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

const markRead = async (row) => {
  try {
    await readMessage({ message_id: row.message_id });
    ElMessage.success("已标记为已读");
    loadData();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

onMounted(loadData);
</script>
