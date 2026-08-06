<template>
  <div class="app-container">
    <vab-page-header title="影像检查" description="影像申请、报告书写、审核和 Viewer 调阅" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="检查申请" name="orders">
        <div class="page-toolbar">
          <el-button type="primary" @click="openOrderDialog">新建影像申请</el-button>
          <el-button @click="loadOrders">刷新</el-button>
        </div>
        <el-table :data="orders" v-loading="loading" border empty-text="暂无影像申请">
          <el-table-column prop="accession_no" label="检查号" width="210" />
          <el-table-column prop="patient_name" label="患者" width="120" />
          <el-table-column prop="modality" label="类型" width="100" />
          <el-table-column prop="body_part" label="检查部位" width="130" />
          <el-table-column prop="status_text" label="状态" width="100" />
          <el-table-column prop="create_time" label="申请时间" width="170" />
          <el-table-column label="操作" min-width="180">
            <template #default="{ row }">
              <el-button v-if="row.status === 0" size="small" @click="changeStatus(row, 1)">开始检查</el-button>
              <el-button v-if="row.status === 1" size="small" @click="changeStatus(row, 2)">完成检查</el-button>
              <el-button size="small" type="info" @click="openViewer(row)">调阅</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="报告书写" name="reports">
        <el-table :data="reports" v-loading="loading" border empty-text="暂无影像报告">
          <el-table-column prop="accession_no" label="检查号" width="210" />
          <el-table-column prop="patient_name" label="患者" width="120" />
          <el-table-column prop="modality" label="类型" width="100" />
          <el-table-column prop="report.status_text" label="报告状态" width="100" />
          <el-table-column prop="report.impression" label="诊断意见" min-width="240" show-overflow-tooltip />
          <el-table-column label="操作" width="180">
            <template #default="{ row }">
              <el-button v-if="row.report && [0, 3].includes(row.report.status)" size="small" type="primary" @click="openReport(row)">书写</el-button>
              <el-button v-if="row.report && row.report.status === 0" size="small" type="success" @click="submitReport(row)">提交审核</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="报告模板" name="templates">
        <div class="page-toolbar"><el-button type="primary" @click="templateDialog = true">新增模板</el-button></div>
        <el-table :data="templates" border empty-text="暂无模板">
          <el-table-column prop="name" label="模板名称" width="180" />
          <el-table-column prop="modality" label="类型" width="100" />
          <el-table-column prop="content" label="模板内容" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="胶片管理" name="films">
        <div class="page-toolbar"><el-button type="primary" @click="openFilmDialog">新建胶片申请</el-button><el-button @click="loadFilms">刷新</el-button></div>
        <el-table :data="films" v-loading="loading" border empty-text="暂无胶片申请">
          <el-table-column prop="accession_no" label="检查号" width="210" /><el-table-column prop="patient_name" label="患者" width="120" /><el-table-column prop="delivery_type_text" label="交付方式" width="110" /><el-table-column prop="copies" label="份数" width="70" /><el-table-column prop="status_text" label="状态" width="100" /><el-table-column prop="create_time" label="申请时间" width="170" />
          <el-table-column label="操作" width="150"><template #default="{ row }"><el-button v-if="row.status === 0" size="small" type="success" @click="completeFilm(row)">完成交付</el-button><el-button v-if="row.status === 1 && row.cloud_url" size="small" type="primary" @click="window.open(row.cloud_url, '_blank', 'noopener')">查看云胶片</el-button></template></el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="orderDialog" title="新建影像申请" width="520px">
      <el-form :model="orderForm" label-width="100px">
        <el-form-item label="患者" required><el-select v-model="orderForm.patient_id" filterable class="full-width"><el-option v-for="item in patients" :key="item.id" :label="`${item.name} (${item.identity || ''})`" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="检查类型"><el-select v-model="orderForm.modality" class="full-width"><el-option v-for="item in modalities" :key="item" :label="item" :value="item" /></el-select></el-form-item>
        <el-form-item label="检查部位" required><el-input v-model="orderForm.body_part" /></el-form-item>
        <el-form-item label="临床诊断"><el-input v-model="orderForm.clinical_diagnosis" type="textarea" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="orderDialog = false">取消</el-button><el-button type="primary" @click="saveOrder">提交申请</el-button></template>
    </el-dialog>

    <el-dialog v-model="reportDialog" title="影像报告书写" width="620px">
      <el-form :model="reportForm" label-width="100px">
        <el-form-item label="影像所见"><el-input v-model="reportForm.findings" type="textarea" :rows="5" /></el-form-item>
        <el-form-item label="诊断意见"><el-input v-model="reportForm.impression" type="textarea" :rows="4" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="reportDialog = false">取消</el-button><el-button type="primary" @click="saveReport">保存草稿</el-button></template>
    </el-dialog>

    <el-dialog v-model="templateDialog" title="新增影像报告模板" width="620px">
      <el-form :model="templateForm" label-width="100px"><el-form-item label="名称"><el-input v-model="templateForm.name" /></el-form-item><el-form-item label="类型"><el-select v-model="templateForm.modality"><el-option v-for="item in modalities" :key="item" :label="item" :value="item" /></el-select></el-form-item><el-form-item label="内容"><el-input v-model="templateForm.content" type="textarea" :rows="6" /></el-form-item></el-form>
      <template #footer><el-button @click="templateDialog = false">取消</el-button><el-button type="primary" @click="saveTemplate">保存</el-button></template>
    </el-dialog>
    <el-dialog v-model="filmDialog" title="新建胶片申请" width="520px">
      <el-form :model="filmForm" label-width="100px">
        <el-form-item label="影像检查" required><el-select v-model="filmForm.imaging_order_id" filterable class="full-width"><el-option v-for="item in orders" :key="item.imaging_order_id" :label="`${item.accession_no} - ${item.patient_name || '患者'}`" :value="item.imaging_order_id" /></el-select></el-form-item>
        <el-form-item label="交付方式"><el-radio-group v-model="filmForm.delivery_type"><el-radio label="print">实体胶片</el-radio><el-radio label="cloud">云胶片</el-radio></el-radio-group></el-form-item>
        <el-form-item label="份数"><el-input-number v-model="filmForm.copies" :min="1" :max="10" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="filmDialog = false">取消</el-button><el-button type="primary" @click="saveFilm">提交申请</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getPatientList } from "@/api/admin";
import { createImagingFilm, createImagingOrder, getImagingFilms, getImagingOrders, getImagingReports, getImagingTemplates, saveImagingReport, saveImagingTemplate, submitImagingReport, updateImagingFilmStatus, updateImagingOrderStatus } from "@/api/imaging";

const modalities = ["DR", "CT", "MRI", "超声", "内镜"];
const activeTab = ref("orders");
const loading = ref(false);
const orders = ref([]);
const reports = ref([]);
const templates = ref([]);
const films = ref([]);
const patients = ref([]);
const orderDialog = ref(false);
const reportDialog = ref(false);
const templateDialog = ref(false);
const filmDialog = ref(false);
const orderForm = ref({ patient_id: "", modality: "DR", body_part: "", clinical_diagnosis: "" });
const reportForm = ref({ report_id: "", imaging_order_id: "", findings: "", impression: "" });
const templateForm = ref({ name: "", modality: "DR", content: "" });
const filmForm = ref({ imaging_order_id: "", delivery_type: "print", copies: 1 });

const loadOrders = async () => { loading.value = true; try { const response = await getImagingOrders(); orders.value = response.data || []; } catch (e) { ElMessage.error(e.msg || "获取影像申请失败"); } finally { loading.value = false; } };
const loadReports = async () => { try { const response = await getImagingReports(); reports.value = response.data || []; } catch (e) { ElMessage.error(e.msg || "获取影像报告失败"); } };
const loadTemplates = async () => { try { const response = await getImagingTemplates(); templates.value = response.data || []; } catch (e) { ElMessage.error(e.msg || "获取报告模板失败"); } };
const loadFilms = async () => { try { const response = await getImagingFilms(); films.value = response.data || []; } catch (e) { ElMessage.error(e.msg || "获取胶片记录失败"); } };
const openOrderDialog = async () => { orderForm.value = { patient_id: "", modality: "DR", body_part: "", clinical_diagnosis: "" }; if (!patients.value.length) { const response = await getPatientList(); patients.value = response.data || []; } orderDialog.value = true; };
const saveOrder = async () => { if (!orderForm.value.patient_id || !orderForm.value.body_part) return ElMessage.warning("请选择患者并填写检查部位"); try { await createImagingOrder(orderForm.value); ElMessage.success("申请已提交"); orderDialog.value = false; await loadOrders(); } catch (e) { ElMessage.error(e.msg || "提交失败"); } };
const changeStatus = async (row, status) => { try { await updateImagingOrderStatus({ imaging_order_id: row.imaging_order_id, status }); ElMessage.success("状态已更新"); await loadOrders(); } catch (e) { ElMessage.error(e.msg || "更新失败"); } };
const openReport = (row) => { reportForm.value = { report_id: row.report.report_id, imaging_order_id: row.imaging_order_id, findings: row.report.findings || "", impression: row.report.impression || "" }; reportDialog.value = true; };
const saveReport = async () => { try { const response = await saveImagingReport(reportForm.value); reportForm.value.report_id = response.data.report_id; ElMessage.success("草稿已保存"); reportDialog.value = false; await loadReports(); } catch (e) { ElMessage.error(e.msg || "保存失败"); } };
const submitReport = async (row) => { try { await ElMessageBox.confirm("提交后将进入审核流程，确认提交？", "提示"); await submitImagingReport({ report_id: row.report.report_id }); ElMessage.success("已提交审核"); await loadReports(); } catch (e) { if (e !== "cancel" && e !== "close") ElMessage.error(e.msg || "提交失败"); } };
const saveTemplate = async () => { try { await saveImagingTemplate(templateForm.value); ElMessage.success("模板已保存"); templateDialog.value = false; await loadTemplates(); } catch (e) { ElMessage.error(e.msg || "保存失败"); } };
const openFilmDialog = () => { filmForm.value = { imaging_order_id: orders.value[0]?.imaging_order_id || "", delivery_type: "print", copies: 1 }; filmDialog.value = true; };
const saveFilm = async () => { if (!filmForm.value.imaging_order_id) return ElMessage.warning("请选择影像检查"); try { await createImagingFilm(filmForm.value); ElMessage.success("胶片申请已提交"); filmDialog.value = false; await loadFilms(); } catch (e) { ElMessage.error(e.msg || "提交失败"); } };
const completeFilm = async (row) => { try { await updateImagingFilmStatus({ film_id: row.film_id, status: 1 }); ElMessage.success("胶片已完成交付"); await loadFilms(); } catch (e) { ElMessage.error(e.msg || "更新失败"); } };
const openViewer = async (row) => { try { const response = await getImagingViewer(row.imaging_order_id); if (response.data.viewer_url) window.open(response.data.viewer_url, "_blank", "noopener"); else ElMessage.info("尚未配置 PACS/DICOM Viewer 地址"); } catch (e) { ElMessage.error(e.msg || "无法调阅影像"); } };

onMounted(() => { loadOrders(); loadReports(); loadTemplates(); loadFilms(); });
</script>

<style scoped>
.full-width { width: 100%; }
</style>
