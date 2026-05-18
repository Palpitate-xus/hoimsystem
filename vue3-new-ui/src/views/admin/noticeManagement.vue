<template>
  <div class="app-container">
    <vab-page-header title="通知公告" description="发布和管理院内通知公告信息" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">发布公告</el-button>
        <el-input
          v-model="searchQuery"
          placeholder="搜索公告"
          clearable
          class="page-search-input"
        ></el-input>
        <el-button type="primary" @click="fetchList">搜索</el-button>
      </div>
      <el-table :data="paginatedList" v-loading="loading" border empty-text="暂无数据">
        <el-table-column prop="title" label="标题"  sortable />
        <el-table-column prop="content" label="内容" show-overflow-tooltip />
        <el-table-column prop="isemergency" label="紧急" width="80" :formatter="(row)=>row.isemergency?'是':'否'" sortable />
        <el-table-column prop="towho" label="目标人群" />
        <el-table-column prop="sendtime" label="发送时间"  sortable />
        <el-table-column prop="expiredtime" label="过期时间"  sortable />
        <el-table-column prop="writer" label="发布人" />
        <el-table-column label="操作" width="180">
          <template #default="{row}">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="total"
        class="pagination-wrapper"
      />

    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEdit?'编辑通知':'新增通知'" width="600px">
      <el-form :model="form" label-width="100px" class="dialog-form">
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
import { ref, onMounted, computed } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getNoticeList, createNotice, updateNotice, deleteNotice } from "@/api/admin";

const list = ref([]);
const searchQuery = ref("");
const currentPage = ref(1);
const pageSize = ref(10);
const total = ref(0);
const paginatedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return list.value.slice(start, start + pageSize.value);
});

const loading = ref(false);
const dialogVisible = ref(false);
const isEdit = ref(false);
const form = ref({ towhoArr: [] });

const fetchList = async () => {
  loading.value = true;
  const res = await getNoticeList(searchQuery.value);
  list.value = res.data || [];
  total.value = list.value.length;
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
  }).catch(() => {});
};

onMounted(fetchList);
</script>
