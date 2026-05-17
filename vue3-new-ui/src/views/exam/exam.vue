<template>
  <div class="app-container">
    <vab-page-header title="体检管理" description="管理体检套餐、体检项目、体检预约和体检记录" />
    <el-tabs v-model="activeTab">
      <!-- 体检套餐 -->
      <el-tab-pane label="体检套餐" name="package">
        <div class="page-toolbar">
          <el-button type="primary" @click="openPackageDialog()">新增套餐</el-button>
          <el-input
            v-model="packageSearch"
            placeholder="搜索套餐..."
            clearable
            class="page-search-input"
          />
          <el-button type="primary" @click="fetchPackages">搜索</el-button>
        </div>
        <el-table :data="paginatedPackages" v-loading="packageLoading" empty-text="暂无记录">
          <el-table-column prop="name" label="套餐名称" sortable />
          <el-table-column prop="description" label="描述" show-overflow-tooltip />
          <el-table-column prop="price" label="价格" sortable>
            <template #default="{row}">
              <span style="color: #f56c6c; font-weight: bold;">¥ {{ row.price }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态">
            <template #default="{row}">
              <el-tag v-if="row.status === 1" type="success">启用</el-tag>
              <el-tag v-else type="info">停用</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{row}">
              <el-button size="small" type="primary" @click="openPackageDialog(row)">编辑</el-button>
              <el-button size="small" type="danger" @click="deletePackage(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="packagePage"
          v-model:page-size="packagePageSize"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          :total="packageList.length"
          class="pagination-wrapper"
        />
      </el-tab-pane>

      <!-- 体检项目 -->
      <el-tab-pane label="体检项目" name="item">
        <div class="page-toolbar">
          <el-button type="primary" @click="openItemDialog()">新增项目</el-button>
          <el-input
            v-model="itemSearch"
            placeholder="搜索项目..."
            clearable
            class="page-search-input"
          />
          <el-button type="primary" @click="fetchItems">搜索</el-button>
        </div>
        <el-table :data="paginatedItems" v-loading="itemLoading" empty-text="暂无记录">
          <el-table-column prop="name" label="项目名称" sortable />
          <el-table-column prop="category" label="分类" sortable />
          <el-table-column prop="unit" label="单位" />
          <el-table-column prop="reference_range" label="参考范围" />
          <el-table-column prop="price" label="单价" sortable>
            <template #default="{row}">
              <span style="color: #f56c6c;">¥ {{ row.price }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态">
            <template #default="{row}">
              <el-tag v-if="row.status === 1" type="success">启用</el-tag>
              <el-tag v-else type="info">停用</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{row}">
              <el-button size="small" type="primary" @click="openItemDialog(row)">编辑</el-button>
              <el-button size="small" type="danger" @click="deleteItem(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="itemPage"
          v-model:page-size="itemPageSize"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          :total="itemList.length"
          class="pagination-wrapper"
        />
      </el-tab-pane>

      <!-- 体检预约 -->
      <el-tab-pane label="体检预约" name="appointment">
        <div class="page-toolbar">
          <el-button type="primary" @click="openAppointmentDialog()">新增预约</el-button>
          <el-select v-model="appointmentStatusFilter" placeholder="状态筛选" clearable style="width: 120px; margin-right: 10px;">
            <el-option label="待确认" value="0" />
            <el-option label="已确认" value="1" />
            <el-option label="已完成" value="2" />
            <el-option label="已取消" value="3" />
          </el-select>
          <el-input
            v-model="appointmentSearch"
            placeholder="搜索预约..."
            clearable
            class="page-search-input"
          />
          <el-button type="primary" @click="fetchAppointments">搜索</el-button>
        </div>
        <el-table :data="paginatedAppointments" v-loading="appointmentLoading" empty-text="暂无记录">
          <el-table-column prop="patient_name" label="患者姓名" sortable />
          <el-table-column prop="package_name" label="体检套餐" sortable />
          <el-table-column prop="appointment_date" label="预约日期" sortable />
          <el-table-column prop="phone" label="联系电话" />
          <el-table-column prop="status" label="状态">
            <template #default="{row}">
              <el-tag v-if="row.status === 0" type="warning">待确认</el-tag>
              <el-tag v-else-if="row.status === 1" type="success">已确认</el-tag>
              <el-tag v-else-if="row.status === 2" type="info">已完成</el-tag>
              <el-tag v-else type="danger">已取消</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="280">
            <template #default="{row}">
              <el-button v-if="row.status === 0" size="small" type="success" @click="updateStatus(row, 1)">确认</el-button>
              <el-button v-if="row.status === 1" size="small" type="primary" @click="updateStatus(row, 2)">完成</el-button>
              <el-button v-if="row.status === 0 || row.status === 1" size="small" type="danger" @click="updateStatus(row, 3)">取消</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="appointmentPage"
          v-model:page-size="appointmentPageSize"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          :total="appointmentList.length"
          class="pagination-wrapper"
        />
      </el-tab-pane>

      <!-- 体检记录 -->
      <el-tab-pane label="体检记录" name="record">
        <div class="page-toolbar">
          <el-button type="primary" @click="openRecordDialog()">登记体检</el-button>
          <el-input
            v-model="recordSearch"
            placeholder="搜索记录..."
            clearable
            class="page-search-input"
          />
          <el-button type="primary" @click="fetchRecords">搜索</el-button>
        </div>
        <el-table :data="paginatedRecords" v-loading="recordLoading" empty-text="暂无记录">
          <el-table-column prop="patient_name" label="患者姓名" sortable />
          <el-table-column prop="package_name" label="体检套餐" sortable />
          <el-table-column prop="exam_date" label="体检日期" sortable />
          <el-table-column prop="doctor_name" label="体检医生" />
          <el-table-column prop="status" label="状态">
            <template #default="{row}">
              <el-tag v-if="row.status === 0" type="warning">进行中</el-tag>
              <el-tag v-else-if="row.status === 1" type="success">已完成</el-tag>
              <el-tag v-else type="info">已归档</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="280">
            <template #default="{row}">
              <el-button size="small" type="primary" @click="viewReport(row)">查看报告</el-button>
              <el-button v-if="row.status === 0" size="small" type="success" @click="openResultDialog(row)">录入结果</el-button>
              <el-button v-if="row.status === 0" size="small" @click="completeRecord(row)">完成</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="recordPage"
          v-model:page-size="recordPageSize"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          :total="recordList.length"
          class="pagination-wrapper"
        />
      </el-tab-pane>
    </el-tabs>

    <!-- 套餐对话框 -->
    <el-dialog v-model="packageDialogVisible" :title="packageForm.id ? '编辑套餐' : '新增套餐'" width="600px">
      <el-form :model="packageForm" label-width="100px" class="dialog-form">
        <el-form-item label="套餐名称" required>
          <el-input v-model="packageForm.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="packageForm.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="价格" required>
          <el-input-number v-model="packageForm.price" :min="0" :precision="2" style="width: 200px;" />
        </el-form-item>
        <el-form-item label="包含项目">
          <el-select v-model="packageForm.item_ids" multiple placeholder="选择体检项目" style="width: 100%;">
            <el-option v-for="item in itemList" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="packageForm.status" :active-value="1" :inactive-value="0" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="packageDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitPackage">确定</el-button>
      </template>
    </el-dialog>

    <!-- 项目对话框 -->
    <el-dialog v-model="itemDialogVisible" :title="itemForm.id ? '编辑项目' : '新增项目'" width="600px">
      <el-form :model="itemForm" label-width="100px" class="dialog-form">
        <el-form-item label="项目名称" required>
          <el-input v-model="itemForm.name" />
        </el-form-item>
        <el-form-item label="分类" required>
          <el-select v-model="itemForm.category" placeholder="选择分类" style="width: 100%;">
            <el-option label="一般检查" value="一般检查" />
            <el-option label="内科" value="内科" />
            <el-option label="外科" value="外科" />
            <el-option label="眼科" value="眼科" />
            <el-option label="耳鼻喉科" value="耳鼻喉科" />
            <el-option label="口腔科" value="口腔科" />
            <el-option label="妇科" value="妇科" />
            <el-option label="检验科" value="检验科" />
            <el-option label="影像科" value="影像科" />
            <el-option label="功能科" value="功能科" />
          </el-select>
        </el-form-item>
        <el-form-item label="单位">
          <el-input v-model="itemForm.unit" placeholder="如：mmHg, U/L, mg/dL" />
        </el-form-item>
        <el-form-item label="参考范围">
          <el-input v-model="itemForm.reference_range" placeholder="如：120-140 / 3.9-6.1" />
        </el-form-item>
        <el-form-item label="单价" required>
          <el-input-number v-model="itemForm.price" :min="0" :precision="2" style="width: 200px;" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="itemForm.status" :active-value="1" :inactive-value="0" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="itemDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitItem">确定</el-button>
      </template>
    </el-dialog>

    <!-- 预约对话框 -->
    <el-dialog v-model="appointmentDialogVisible" title="新增体检预约" width="600px">
      <el-form :model="appointmentForm" label-width="100px" class="dialog-form">
        <el-form-item label="患者姓名" required>
          <el-input v-model="appointmentForm.patient_name" />
        </el-form-item>
        <el-form-item label="联系电话" required>
          <el-input v-model="appointmentForm.phone" />
        </el-form-item>
        <el-form-item label="身份证号">
          <el-input v-model="appointmentForm.id_card" />
        </el-form-item>
        <el-form-item label="体检套餐" required>
          <el-select v-model="appointmentForm.package_id" placeholder="选择体检套餐" style="width: 100%;">
            <el-option v-for="pkg in packageList" :key="pkg.id" :label="pkg.name" :value="pkg.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="预约日期" required>
          <el-date-picker v-model="appointmentForm.appointment_date" type="date" placeholder="选择日期" style="width: 100%;" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="appointmentForm.remark" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="appointmentDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitAppointment">确定</el-button>
      </template>
    </el-dialog>

    <!-- 登记体检对话框 -->
    <el-dialog v-model="recordDialogVisible" title="登记体检" width="600px">
      <el-form :model="recordForm" label-width="100px" class="dialog-form">
        <el-form-item label="患者姓名" required>
          <el-input v-model="recordForm.patient_name" />
        </el-form-item>
        <el-form-item label="体检套餐" required>
          <el-select v-model="recordForm.package_id" placeholder="选择体检套餐" style="width: 100%;" @change="onPackageChange">
            <el-option v-for="pkg in packageList" :key="pkg.id" :label="pkg.name" :value="pkg.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="体检医生">
          <el-input v-model="recordForm.doctor_name" />
        </el-form-item>
        <el-form-item label="体检日期" required>
          <el-date-picker v-model="recordForm.exam_date" type="date" placeholder="选择日期" style="width: 100%;" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="recordForm.remark" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="recordDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRecord">确定</el-button>
      </template>
    </el-dialog>

    <!-- 录入结果对话框 -->
    <el-dialog v-model="resultDialogVisible" title="录入体检结果" width="700px">
      <el-form label-width="120px" class="dialog-form">
        <el-form-item label="患者">
          <span>{{ currentRecord.patient_name }}</span>
        </el-form-item>
        <el-form-item label="体检套餐">
          <span>{{ currentRecord.package_name }}</span>
        </el-form-item>
        <el-divider />
        <div v-for="(item, index) in resultItems" :key="index" style="margin-bottom: 15px;">
          <el-row :gutter="10">
            <el-col :span="6">
              <div style="line-height: 32px; text-align: right; padding-right: 10px;">{{ item.name }}</div>
            </el-col>
            <el-col :span="6">
              <el-input v-model="item.result_value" placeholder="结果值" />
            </el-col>
            <el-col :span="4">
              <el-input v-model="item.unit" placeholder="单位" disabled />
            </el-col>
            <el-col :span="8">
              <el-input v-model="item.reference_range" placeholder="参考范围" disabled />
            </el-col>
          </el-row>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="resultDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitResults">保存结果</el-button>
      </template>
    </el-dialog>

    <!-- 查看报告对话框 -->
    <el-dialog v-model="reportDialogVisible" title="体检报告详情" width="800px">
      <div v-if="reportDetail" class="report-detail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="患者姓名">{{ reportDetail.patient_name }}</el-descriptions-item>
          <el-descriptions-item label="体检日期">{{ reportDetail.exam_date }}</el-descriptions-item>
          <el-descriptions-item label="体检套餐">{{ reportDetail.package_name }}</el-descriptions-item>
          <el-descriptions-item label="体检医生">{{ reportDetail.doctor_name }}</el-descriptions-item>
        </el-descriptions>
        <el-divider />
        <h4>检查结果</h4>
        <el-table :data="reportDetail.results" size="small" border empty-text="暂无记录">
          <el-table-column prop="item_name" label="检查项目" />
          <el-table-column prop="result_value" label="结果值" />
          <el-table-column prop="unit" label="单位" />
          <el-table-column prop="reference_range" label="参考范围" />
          <el-table-column prop="abnormal_flag" label="异常标记">
            <template #default="{row}">
              <el-tag v-if="row.abnormal_flag === 1" type="danger">异常</el-tag>
              <el-tag v-else type="success">正常</el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-divider />
        <h4>医生建议</h4>
        <el-input v-model="reportDetail.doctor_advice" type="textarea" :rows="4" placeholder="请输入医生建议" />
      </div>
      <template #footer>
        <el-button @click="reportDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="saveReportAdvice">保存建议</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  getExamPackageList,
  createExamPackage,
  updateExamPackage,
  deleteExamPackage,
  getExamItemList,
  createExamItem,
  updateExamItem,
  deleteExamItem,
  getExamAppointmentList,
  createExamAppointment,
  updateAppointmentStatus,
  getExamRecordList,
  createExamRecord,
  updateExamRecord,
  completeExamRecord,
  getExamResultList,
  createExamResult,
  getExamReportDetail,
} from "@/api/exam";

const activeTab = ref("package");

// ==================== 体检套餐 ====================
const packageList = ref([]);
const packageSearch = ref("");
const packageLoading = ref(false);
const packagePage = ref(1);
const packagePageSize = ref(10);
const packageDialogVisible = ref(false);
const packageForm = ref({ id: null, name: "", description: "", price: 0, item_ids: [], status: 1 });

const paginatedPackages = computed(() => {
  const start = (packagePage.value - 1) * packagePageSize.value;
  return packageList.value.slice(start, start + packagePageSize.value);
});

const fetchPackages = async () => {
  packageLoading.value = true;
  try {
    const res = await getExamPackageList(packageSearch.value);
    packageList.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "获取套餐列表失败");
  }
  packageLoading.value = false;
};

const openPackageDialog = (row = null) => {
  if (row) {
    packageForm.value = { ...row, item_ids: row.item_ids || [] };
  } else {
    packageForm.value = { id: null, name: "", description: "", price: 0, item_ids: [], status: 1 };
  }
  packageDialogVisible.value = true;
};

const submitPackage = async () => {
  if (!packageForm.value.name) {
    ElMessage.warning("请输入套餐名称");
    return;
  }
  try {
    if (packageForm.value.id) {
      await updateExamPackage(packageForm.value);
      ElMessage.success("更新成功");
    } else {
      await createExamPackage(packageForm.value);
      ElMessage.success("创建成功");
    }
    packageDialogVisible.value = false;
    fetchPackages();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const deletePackage = async (row) => {
  try {
    await ElMessageBox.confirm("确定删除该体检套餐吗？", "提示", { type: "warning" });
    await deleteExamPackage({ id: row.id });
    ElMessage.success("删除成功");
    fetchPackages();
  } catch (e) {
    if (e !== "cancel") {
      ElMessage.error(e.msg || "删除失败");
    }
  }
};

// ==================== 体检项目 ====================
const itemList = ref([]);
const itemSearch = ref("");
const itemLoading = ref(false);
const itemPage = ref(1);
const itemPageSize = ref(10);
const itemDialogVisible = ref(false);
const itemForm = ref({ id: null, name: "", category: "", unit: "", reference_range: "", price: 0, status: 1 });

const paginatedItems = computed(() => {
  const start = (itemPage.value - 1) * itemPageSize.value;
  return itemList.value.slice(start, start + itemPageSize.value);
});

const fetchItems = async () => {
  itemLoading.value = true;
  try {
    const res = await getExamItemList(itemSearch.value);
    itemList.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "获取项目列表失败");
  }
  itemLoading.value = false;
};

const openItemDialog = (row = null) => {
  if (row) {
    itemForm.value = { ...row };
  } else {
    itemForm.value = { id: null, name: "", category: "", unit: "", reference_range: "", price: 0, status: 1 };
  }
  itemDialogVisible.value = true;
};

const submitItem = async () => {
  if (!itemForm.value.name) {
    ElMessage.warning("请输入项目名称");
    return;
  }
  if (!itemForm.value.category) {
    ElMessage.warning("请选择分类");
    return;
  }
  try {
    if (itemForm.value.id) {
      await updateExamItem(itemForm.value);
      ElMessage.success("更新成功");
    } else {
      await createExamItem(itemForm.value);
      ElMessage.success("创建成功");
    }
    itemDialogVisible.value = false;
    fetchItems();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const deleteItem = async (row) => {
  try {
    await ElMessageBox.confirm("确定删除该体检项目吗？", "提示", { type: "warning" });
    await deleteExamItem({ id: row.id });
    ElMessage.success("删除成功");
    fetchItems();
  } catch (e) {
    if (e !== "cancel") {
      ElMessage.error(e.msg || "删除失败");
    }
  }
};

// ==================== 体检预约 ====================
const appointmentList = ref([]);
const appointmentSearch = ref("");
const appointmentStatusFilter = ref("");
const appointmentLoading = ref(false);
const appointmentPage = ref(1);
const appointmentPageSize = ref(10);
const appointmentDialogVisible = ref(false);
const appointmentForm = ref({ patient_name: "", phone: "", id_card: "", package_id: null, appointment_date: "", remark: "" });

const paginatedAppointments = computed(() => {
  const start = (appointmentPage.value - 1) * appointmentPageSize.value;
  return appointmentList.value.slice(start, start + appointmentPageSize.value);
});

const fetchAppointments = async () => {
  appointmentLoading.value = true;
  try {
    const res = await getExamAppointmentList(appointmentSearch.value, appointmentStatusFilter.value);
    appointmentList.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "获取预约列表失败");
  }
  appointmentLoading.value = false;
};

const openAppointmentDialog = () => {
  appointmentForm.value = { patient_name: "", phone: "", id_card: "", package_id: null, appointment_date: "", remark: "" };
  appointmentDialogVisible.value = true;
};

const submitAppointment = async () => {
  if (!appointmentForm.value.patient_name || !appointmentForm.value.phone || !appointmentForm.value.package_id || !appointmentForm.value.appointment_date) {
    ElMessage.warning("请填写完整信息");
    return;
  }
  try {
    await createExamAppointment(appointmentForm.value);
    ElMessage.success("预约成功");
    appointmentDialogVisible.value = false;
    fetchAppointments();
  } catch (e) {
    ElMessage.error(e.msg || "预约失败");
  }
};

const updateStatus = async (row, status) => {
  const statusMap = { 1: "确认", 2: "完成", 3: "取消" };
  try {
    if (status === 3) {
      await ElMessageBox.confirm("确定取消该预约吗？", "提示", { type: "warning" });
    }
    await updateAppointmentStatus({ id: row.id, status });
    ElMessage.success(`预约已${statusMap[status]}`);
    fetchAppointments();
  } catch (e) {
    if (e !== "cancel") {
      ElMessage.error(e.msg || "操作失败");
    }
  }
};

// ==================== 体检记录 ====================
const recordList = ref([]);
const recordSearch = ref("");
const recordLoading = ref(false);
const recordPage = ref(1);
const recordPageSize = ref(10);
const recordDialogVisible = ref(false);
const recordForm = ref({ patient_name: "", package_id: null, doctor_name: "", exam_date: "", remark: "" });

const paginatedRecords = computed(() => {
  const start = (recordPage.value - 1) * recordPageSize.value;
  return recordList.value.slice(start, start + recordPageSize.value);
});

const fetchRecords = async () => {
  recordLoading.value = true;
  try {
    const res = await getExamRecordList(recordSearch.value);
    recordList.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "获取记录列表失败");
  }
  recordLoading.value = false;
};

const openRecordDialog = () => {
  recordForm.value = { patient_name: "", package_id: null, doctor_name: "", exam_date: "", remark: "" };
  recordDialogVisible.value = true;
};

const onPackageChange = (packageId) => {
  const pkg = packageList.value.find((p) => p.id === packageId);
  if (pkg && pkg.item_ids) {
    // item_ids used for result items initialization if needed
  }
};

const submitRecord = async () => {
  if (!recordForm.value.patient_name || !recordForm.value.package_id || !recordForm.value.exam_date) {
    ElMessage.warning("请填写完整信息");
    return;
  }
  try {
    await createExamRecord(recordForm.value);
    ElMessage.success("登记成功");
    recordDialogVisible.value = false;
    fetchRecords();
  } catch (e) {
    ElMessage.error(e.msg || "登记失败");
  }
};

const completeRecord = async (row) => {
  try {
    await ElMessageBox.confirm("确定完成该体检记录吗？", "提示", { type: "warning" });
    await completeExamRecord({ id: row.id });
    ElMessage.success("体检已完成");
    fetchRecords();
  } catch (e) {
    if (e !== "cancel") {
      ElMessage.error(e.msg || "操作失败");
    }
  }
};

// ==================== 结果录入 ====================
const resultDialogVisible = ref(false);
const currentRecord = ref({});
const resultItems = ref([]);

const openResultDialog = (row) => {
  currentRecord.value = { ...row };
  // Build result items from package items or existing results
  const pkg = packageList.value.find((p) => p.id === row.package_id);
  if (pkg && pkg.item_ids) {
    resultItems.value = pkg.item_ids.map((itemId) => {
      const item = itemList.value.find((i) => i.id === itemId);
      return {
        item_id: itemId,
        name: item ? item.name : "",
        unit: item ? item.unit : "",
        reference_range: item ? item.reference_range : "",
        result_value: "",
        abnormal_flag: 0,
      };
    });
  } else {
    resultItems.value = [];
  }
  resultDialogVisible.value = true;
};

const submitResults = async () => {
  try {
    const payload = {
      record_id: currentRecord.value.id,
      results: resultItems.value.map((item) => ({
        item_id: item.item_id,
        result_value: item.result_value,
        abnormal_flag: item.abnormal_flag,
      })),
    };
    await createExamResult(payload);
    ElMessage.success("结果录入成功");
    resultDialogVisible.value = false;
    fetchRecords();
  } catch (e) {
    ElMessage.error(e.msg || "录入失败");
  }
};

// ==================== 报告查看 ====================
const reportDialogVisible = ref(false);
const reportDetail = ref(null);

const viewReport = async (row) => {
  try {
    const res = await getExamReportDetail({ id: row.id });
    reportDetail.value = res.data || null;
    reportDialogVisible.value = true;
  } catch (e) {
    ElMessage.error(e.msg || "获取报告失败");
  }
};

const saveReportAdvice = async () => {
  try {
    await updateExamRecord({
      id: reportDetail.value.id,
      doctor_advice: reportDetail.value.doctor_advice,
    });
    ElMessage.success("建议保存成功");
    reportDialogVisible.value = false;
    fetchRecords();
  } catch (e) {
    ElMessage.error(e.msg || "保存失败");
  }
};

onMounted(() => {
  fetchPackages();
  fetchItems();
  fetchAppointments();
  fetchRecords();
});
</script>

<style scoped>
.report-detail h4 {
  margin: 15px 0 10px;
  color: #303133;
}
</style>
