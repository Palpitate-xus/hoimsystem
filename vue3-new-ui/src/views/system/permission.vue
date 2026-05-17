<template>
  <div class="app-container">
    <vab-page-header title="权限分配" description="分配用户角色和系统操作权限" />
    <el-card>
      <div class="page-toolbar">
        <el-select v-model="roleFilter" placeholder="筛选角色" clearable style="width: 150px; margin-right: 10px;">
          <el-option label="全部" value="" />
          <el-option label="管理员" value="admin" />
          <el-option label="医生" value="doctor" />
          <el-option label="科室主任" value="director" />
          <el-option label="患者" value="patient" />
        </el-select>
        <el-button type="primary" @click="fetchList">查询</el-button>
        <el-button @click="roleFilter = ''; fetchList()">重置</el-button>
      </div>

      <el-table :data="list" v-loading="loading" empty-text="暂无记录">
        <el-table-column prop="user_id" label="用户ID" width="80" />
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="user_role" label="当前角色" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.user_role === 'admin'" type="danger">管理员</el-tag>
            <el-tag v-else-if="row.user_role === 'doctor'" type="primary">医生</el-tag>
            <el-tag v-else-if="row.user_role === 'director'" type="warning">科室主任</el-tag>
            <el-tag v-else-if="row.user_role === 'patient'" type="success">患者</el-tag>
            <el-tag v-else type="info">{{ row.user_role }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="openRoleDialog(row)">修改角色</el-button>
            <el-button size="small" type="warning" @click="resetPassword(row)">重置密码</el-button>
            <el-button v-if="row.user_role !== 'admin'" size="small" type="danger" @click="deleteUser(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 修改角色 -->
    <el-dialog v-model="roleVisible" title="修改用户角色" width="400px">
      <el-form label-width="100px">
        <el-form-item label="用户名">
          <span>{{ currentRow.username }}</span>
        </el-form-item>
        <el-form-item label="当前角色">
          <el-tag v-if="currentRow.user_role === 'admin'" type="danger">管理员</el-tag>
          <el-tag v-else-if="currentRow.user_role === 'doctor'" type="primary">医生</el-tag>
          <el-tag v-else-if="currentRow.user_role === 'director'" type="warning">科室主任</el-tag>
          <el-tag v-else-if="currentRow.user_role === 'patient'" type="success">患者</el-tag>
        </el-form-item>
        <el-form-item label="新角色">
          <el-radio-group v-model="newRole">
            <el-radio label="admin">管理员</el-radio>
            <el-radio label="doctor">医生</el-radio>
            <el-radio label="director">科室主任</el-radio>
            <el-radio label="patient">患者</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRoleChange">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getUserList, updateUserRole, resetUserPassword, deleteUser as apiDeleteUser } from "@/api/user";

const list = ref([]);
const loading = ref(false);
const roleFilter = ref("");
const roleVisible = ref(false);
const currentRow = ref({});
const newRole = ref("");

const fetchList = async () => {
  loading.value = true;
  try {
    const res = await getUserList(roleFilter.value ? { role: roleFilter.value } : {});
    list.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
  loading.value = false;
};

const openRoleDialog = (row) => {
  currentRow.value = { ...row };
  newRole.value = row.user_role;
  roleVisible.value = true;
};

const submitRoleChange = async () => {
  if (newRole.value === currentRow.value.user_role) {
    roleVisible.value = false;
    return;
  }
  try {
    await updateUserRole({ user_id: currentRow.value.user_id, user_role: newRole.value });
    ElMessage.success("角色修改成功");
    roleVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "修改失败");
  }
};

const resetPassword = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定重置用户 "${row.username}" 的密码吗？重置后密码为 123456`,
      "重置密码确认",
      { type: "warning" }
    );
    const res = await resetUserPassword({ user_id: row.user_id });
    if (res.code === 200) {
      ElMessage.success(`密码已重置为: ${res.data.new_password}`);
    } else {
      ElMessage.error(res.msg || "重置失败");
    }
  } catch (e) {
    if (e !== "cancel") {
      ElMessage.error(e.msg || "重置失败");
    }
  }
};

const deleteUser = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定删除用户 "${row.username}" 吗？此操作不可恢复！`,
      "删除确认",
      { type: "danger", confirmButtonText: "确定删除" }
    );
    await apiDeleteUser({ user_id: row.user_id });
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
