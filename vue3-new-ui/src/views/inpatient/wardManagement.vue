<template>
  <div class="app-container">
    <vab-page-header title="病区床位管理" description="管理住院病区、房间和床位信息" />
    <el-row :gutter="20">
      <el-col :span="8">
        <el-card>
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span>病区列表</span>
              <el-button type="primary" size="small" @click="openWardDialog()">新增病区</el-button>
            </div>
          </template>
          <el-input v-model="wardKeyword" placeholder="搜索病区" clearable prefix-icon="Search" style="margin-bottom: 15px;" />
          <el-table :data="filteredWards" size="small" highlight-current-row @current-change="onWardSelect" empty-text="暂无记录">
            <el-table-column prop="name" label="病区名称" show-overflow-tooltip />
            <el-table-column label="床位" width="80">
              <template #default="{row}">
                <el-tag size="small" type="success">{{ row.bed_used }}/{{ row.bed_total }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{row}">
                <el-button size="small" type="primary" link @click.stop="openWardDialog(row)">编辑</el-button>
                <el-button size="small" type="danger" link @click.stop="deleteWard(row)">停用</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card>
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span>{{ currentWard ? currentWard.name + ' - 床位管理' : '请选择病区' }}</span>
              <el-button v-if="currentWard" type="primary" size="small" @click="openBedDialog()">新增床位</el-button>
            </div>
          </template>
          <div v-if="!currentWard" style="text-align: center; padding: 40px; color: #999;">
            <el-icon :size="40" style="margin-bottom: 10px;"><OfficeBuilding /></el-icon>
            <div>请从左侧选择一个病区</div>
          </div>
          <div v-else>
            <div style="margin-bottom: 15px;">
              <el-tag>总床位: {{ currentWard.bed_total }}</el-tag>
              <el-tag type="success">空闲: {{ currentWard.bed_free }}</el-tag>
              <el-tag type="danger">占用: {{ currentWard.bed_used }}</el-tag>
              <el-tag type="warning">禁用: {{ bedList.filter(b=>b.status===2).length }}</el-tag>
            </div>
            <el-table :data="bedList" size="small" v-loading="bedLoading" empty-text="暂无记录">
              <el-table-column prop="bed_no" label="床位号" width="80" />
              <el-table-column prop="room_no" label="房间号" width="80" />
              <el-table-column prop="bed_type" label="类型" width="80" />
              <el-table-column prop="price_per_day" label="每日费用" width="90">
                <template #default="{row}">¥{{ row.price_per_day }}</template>
              </el-table-column>
              <el-table-column label="状态" width="80">
                <template #default="{row}">
                  <el-tag v-if="row.status===0" type="success" size="small">空闲</el-tag>
                  <el-tag v-else-if="row.status===1" type="danger" size="small">占用</el-tag>
                  <el-tag v-else-if="row.status===2" type="info" size="small">禁用</el-tag>
                  <el-tag v-else type="warning" size="small">预订</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="120">
                <template #default="{row}">
                  <el-button size="small" type="primary" link @click="openBedDialog(row)">编辑</el-button>
                  <el-button size="small" type="danger" link @click="deleteBed(row)">禁用</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 病区对话框 -->
    <el-dialog v-model="wardDialogVisible" :title="wardForm.ward_id ? '编辑病区' : '新增病区'" width="500px">
      <el-form :model="wardForm" label-width="100px">
        <el-form-item label="病区名称" required>
          <el-input v-model="wardForm.name" placeholder="如：内科一病区" />
        </el-form-item>
        <el-form-item label="所属科室">
          <el-select v-model="wardForm.department_id" placeholder="选择科室" class="form-full-width">
            <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="床位数">
          <el-input-number v-model="wardForm.bed_count" :min="0" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="护士站电话">
          <el-input v-model="wardForm.nurse_station_phone" placeholder="联系电话" />
        </el-form-item>
        <el-form-item label="位置">
          <el-input v-model="wardForm.location" placeholder="如：住院楼3层" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="wardDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitWard">确定</el-button>
      </template>
    </el-dialog>

    <!-- 床位对话框 -->
    <el-dialog v-model="bedDialogVisible" :title="bedForm.bed_id ? '编辑床位' : '新增床位'" width="500px">
      <el-form :model="bedForm" label-width="100px">
        <el-form-item label="床位号" required>
          <el-input v-model="bedForm.bed_no" placeholder="如：01" />
        </el-form-item>
        <el-form-item label="房间号">
          <el-input v-model="bedForm.room_no" placeholder="如：301" />
        </el-form-item>
        <el-form-item label="床位类型">
          <el-select v-model="bedForm.bed_type" placeholder="选择类型" class="form-full-width">
            <el-option label="普通" value="普通" />
            <el-option label="监护" value="监护" />
            <el-option label="抢救" value="抢救" />
            <el-option label="单人" value="单人" />
            <el-option label="双人" value="双人" />
          </el-select>
        </el-form-item>
        <el-form-item label="每日费用">
          <el-input-number v-model="bedForm.price_per_day" :min="0" :precision="2" style="width: 100%;" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bedDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitBed">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { OfficeBuilding } from "@element-plus/icons-vue";
import { getWardList, createWard, updateWard, deleteWard as apiDeleteWard, getBedList, createBed, updateBed, deleteBed as apiDeleteBed } from "@/api/ward";
import { getDepartmentList } from "@/api/admin";

const wards = ref([]);
const departments = ref([]);
const wardKeyword = ref("");
const currentWard = ref(null);
const bedList = ref([]);
const bedLoading = ref(false);

const wardDialogVisible = ref(false);
const wardForm = ref({});
const bedDialogVisible = ref(false);
const bedForm = ref({});

const filteredWards = computed(() => {
  if (!wardKeyword.value) return wards.value;
  const kw = wardKeyword.value.toLowerCase();
  return wards.value.filter(w => w.name.toLowerCase().includes(kw) || (w.location && w.location.toLowerCase().includes(kw)));
});

const loadWards = async () => {
  const res = await getWardList();
  wards.value = res.data || [];
};

const loadDepartments = async () => {
  const res = await getDepartmentList();
  departments.value = res.data || [];
};

const loadBeds = async (wardId) => {
  bedLoading.value = true;
  const res = await getBedList({ ward_id: wardId });
  bedList.value = res.data || [];
  bedLoading.value = false;
};

const onWardSelect = (row) => {
  if (!row) return;
  currentWard.value = row;
  loadBeds(row.ward_id);
};

const openWardDialog = (row) => {
  if (row) {
    wardForm.value = { ...row };
  } else {
    wardForm.value = { bed_count: 0 };
  }
  wardDialogVisible.value = true;
};

const submitWard = async () => {
  if (!wardForm.value.name) {
    ElMessage.warning("请输入病区名称");
    return;
  }
  try {
    if (wardForm.value.ward_id) {
      await updateWard(wardForm.value);
    } else {
      await createWard(wardForm.value);
    }
    ElMessage.success("操作成功");
    wardDialogVisible.value = false;
    loadWards();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const deleteWard = async (row) => {
  try {
    await ElMessageBox.confirm("确定停用该病区？", "提示", { type: "warning" });
    await apiDeleteWard({ ward_id: row.ward_id });
    ElMessage.success("停用成功");
    if (currentWard.value && currentWard.value.ward_id === row.ward_id) {
      currentWard.value = null;
      bedList.value = [];
    }
    loadWards();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "操作失败");
  }
};

const openBedDialog = (row) => {
  if (row) {
    bedForm.value = { ...row };
  } else {
    bedForm.value = { ward_id: currentWard.value.ward_id, bed_type: "普通", price_per_day: 0 };
  }
  bedDialogVisible.value = true;
};

const submitBed = async () => {
  if (!bedForm.value.bed_no) {
    ElMessage.warning("请输入床位号");
    return;
  }
  try {
    if (bedForm.value.bed_id) {
      await updateBed(bedForm.value);
    } else {
      await createBed(bedForm.value);
    }
    ElMessage.success("操作成功");
    bedDialogVisible.value = false;
    loadBeds(currentWard.value.ward_id);
    loadWards();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const deleteBed = async (row) => {
  try {
    await ElMessageBox.confirm("确定禁用该床位？", "提示", { type: "warning" });
    await apiDeleteBed({ bed_id: row.bed_id });
    ElMessage.success("禁用成功");
    loadBeds(currentWard.value.ward_id);
    loadWards();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "操作失败");
  }
};

onMounted(() => {
  loadWards();
  loadDepartments();
});
</script>
