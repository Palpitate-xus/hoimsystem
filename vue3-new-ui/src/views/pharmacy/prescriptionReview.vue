<template>
  <div class="app-container">
    <vab-page-header title="处方点评" description="对处方用药合理性进行专业点评" />
    <el-card>
      <div class="page-toolbar">
        <el-input v-model="keyword" placeholder="搜索..." clearable class="page-search-input" />
        <el-button type="primary" @click="loadData">搜索</el-button>
      </div>

      <el-table :data="list">
        <el-table-column prop="uuid" label="处方ID" width="280" />
        <el-table-column prop="patient_name" label="病人" />
        <el-table-column prop="doctor_name" label="医生" />
        <el-table-column prop="phas" label="药品">
          <template #default="{row}">
            <el-tag v-for="(p, i) in row.phas" :key="i" size="small" style="margin-right: 5px;">{{ p.name }} x{{ p.number }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{row}">
            <el-button size="small" type="primary" @click="openReview(row)">点评</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="reviewedList.length > 0" style="margin-top: 15px;">
      <template #header>已点评记录</template>
      <el-table :data="reviewedList">
        <el-table-column prop="patient_name" label="病人" />
        <el-table-column prop="doctor_name" label="医生" />
        <el-table-column prop="review_score" label="评分" sortable />
        <el-table-column prop="review_comment" label="点评内容" />
        <el-table-column prop="review_time" label="点评时间" />
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="处方点评" width="500px">
      <p>处方ID: {{ currentRow.uuid }}</p>
      <p>病人: {{ currentRow.patient_name }}</p>
      <p>医生: {{ currentRow.doctor_name }}</p>
      <el-form :model="form" label-width="80px" class="dialog-form">
        <el-form-item label="评分">
          <el-rate v-model="form.score" :max="5" />
        </el-form-item>
        <el-form-item label="点评内容">
          <el-input v-model="form.comment" type="textarea" rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitReview">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { getDispenseList, reviewPrescription, getReviewList } from "@/api/pharmacy";
import { ElMessage } from "element-plus";

const list = ref([]);
const reviewedList = ref([]);
const keyword = ref("");
const dialogVisible = ref(false);
const currentRow = ref({});
const form = ref({ score: 5, comment: "" });

const loadData = async () => {
  try {
    const res = await getDispenseList(keyword.value);
    list.value = res.data || [];
    const r2 = await getReviewList();
    reviewedList.value = r2.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

const openReview = (row) => {
  currentRow.value = row;
  form.value = { score: 5, comment: "" };
  dialogVisible.value = true;
};

const submitReview = async () => {
  try {
    await reviewPrescription({
      prescription_id: currentRow.value.uuid,
      score: form.value.score,
      comment: form.value.comment,
    });
    ElMessage.success("点评成功");
    dialogVisible.value = false;
    loadData();
  } catch (e) {
    ElMessage.error(e.msg || "点评失败");
  }
};

onMounted(loadData);
</script>
