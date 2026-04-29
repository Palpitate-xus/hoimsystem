<template>
  <div class="app-container">
    <vab-page-header title="通知公告" />
    <el-card>
      <el-button type="primary" @click="handleAdd">发布公告</el-button>
      <el-table :data="list" v-loading="loading" style="margin-top: 15px">
        <el-table-column prop="uuid" label="ID" width="80" />
        <el-table-column prop="title" label="标题" />
        <el-table-column prop="content" label="内容" show-overflow-tooltip />
        <el-table-column prop="isemergency" label="紧急" width="80" :formatter="(row)=>row.isemergency?'是':'否'" />
        <el-table-column prop="towho" label="目标人群" />
        <el-table-column prop="sendtime" label="发送时间" />
        <el-table-column prop="expiredtime" label="过期时间" />
        <el-table-column prop="writer" label="发布人" />
        <el-table-column label="操作" width="180">
          <template #default="{row}">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEdit?'编辑通知':'新增通知'" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="标题">
          <el-input v-model="form.title" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="form.content" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="是否紧急">
          <el-switch v-model="form.isemergency" :active-value="1" :inactive-value="0" />
        </el-form-item>
        <el-form-item label="目标人群">
          <el-checkbox-group v-model="form.towhoArr">
            <el-checkbox label="医生" />
            <el-checkbox label="病人" />
            <el-checkbox label="科室主任" />
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="过期时间">
          <el-date-picker v-model="form.expiredtime" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getNoticeList, createNotice, updateNotice, deleteNotice } from "@/api/admin";

const list = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const isEdit = ref(false);
const form = ref({ towhoArr: [] });

const fetchList = async () => {
  loading.value = true;
  const res = await getNoticeList();
  list.value = res.data || [];
  loading.value = false;
};

const handleAdd = () => {
  isEdit.value = false;
  form.value = { isemergency: 0, towhoArr: [] };
  dialogVisible.value = true;
};

const handleEdit = (row) => {
  isEdit.value = true;
  const towhoArr = row.towho ? row.towho.split(",") : [];
  form.value = { ...row, towhoArr, notice_id: row.uuid };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    const payload = { ...form.value, towho: form.value.towhoArr.join(",") };
    if (isEdit.value) {
      await updateNotice(payload);
    } else {
      await createNotice(payload);
    }
    ElMessage.success("操作成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const handleDelete = (row) => {
  ElMessageBox.confirm("确认删除该通知？", "提示", { type: "warning" }).then(async () => {
    await deleteNotice({ notice_id: row.uuid });
    ElMessage.success("删除成功");
    fetchList();
  });
};

onMounted(fetchList);
</script>
