<template>
  <div class="app-container">
    <vab-page-header title="物资设备管理" description="设备台账、维修保养、高值耗材追溯和资产盘点" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="设备台账" name="equipment">
        <div class="page-toolbar"><el-button type="primary" @click="equipmentDialog = true">新增设备</el-button></div>
        <el-table :data="equipment" border empty-text="暂无设备"><el-table-column prop="asset_no" label="资产编号" /><el-table-column prop="name" label="设备名称" /><el-table-column prop="category" label="类别" /><el-table-column prop="location" label="位置" /><el-table-column prop="status_text" label="状态" /><el-table-column prop="inventory_status_text" label="盘点状态" /></el-table>
      </el-tab-pane>
      <el-tab-pane label="维修记录" name="maintenance"><el-table :data="maintenance" border empty-text="暂无维修记录"><el-table-column prop="equipment_name" label="设备" /><el-table-column prop="maintenance_type" label="类型" /><el-table-column prop="description" label="描述" /><el-table-column prop="status_text" label="状态" /><el-table-column prop="report_time" label="报修时间" /></el-table></el-tab-pane>
      <el-tab-pane label="保养记录" name="inspection"><el-table :data="inspection" border empty-text="暂无保养记录"><el-table-column prop="equipment_name" label="设备" /><el-table-column prop="result" label="结果" /><el-table-column prop="pass_flag" label="是否合格"><template #default="{ row }">{{ row.pass_flag ? "合格" : "不合格" }}</template></el-table-column><el-table-column prop="inspection_time" label="保养时间" /></el-table></el-tab-pane>
      <el-tab-pane label="耗材追溯" name="trace"><el-table :data="trace" border empty-text="暂无追溯记录"><el-table-column prop="consumable_name" label="耗材" /><el-table-column prop="batch_no" label="批次" /><el-table-column prop="serial_no" label="序列号" /><el-table-column prop="action" label="动作" /><el-table-column prop="quantity" label="数量" /><el-table-column prop="action_time" label="时间" /></el-table></el-tab-pane>
    </el-tabs>
    <el-dialog v-model="equipmentDialog" title="新增设备" width="520px"><el-form :model="form" label-width="100px"><el-form-item label="资产编号"><el-input v-model="form.asset_no" /></el-form-item><el-form-item label="设备名称"><el-input v-model="form.name" /></el-form-item><el-form-item label="类别"><el-input v-model="form.category" /></el-form-item><el-form-item label="型号"><el-input v-model="form.model" /></el-form-item><el-form-item label="位置"><el-input v-model="form.location" /></el-form-item></el-form><template #footer><el-button @click="equipmentDialog = false">取消</el-button><el-button type="primary" @click="saveEquipment">保存</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { createEquipment, getEquipmentList, getInspectionList, getMaintenanceList, getTraceList } from "@/api/equipment";

const activeTab = ref("equipment"); const equipmentDialog = ref(false); const equipment = ref([]); const maintenance = ref([]); const inspection = ref([]); const trace = ref([]);
const form = ref({ asset_no: "", name: "", category: "", model: "", location: "" });
const load = async () => { try { const [a, b, c, d] = await Promise.all([getEquipmentList(), getMaintenanceList(), getInspectionList(), getTraceList()]); equipment.value = a.data || []; maintenance.value = b.data || []; inspection.value = c.data || []; trace.value = d.data || []; } catch (e) { ElMessage.error(e.msg || "获取设备数据失败"); } };
const saveEquipment = async () => { try { await createEquipment(form.value); ElMessage.success("设备已保存"); equipmentDialog.value = false; await load(); } catch (e) { ElMessage.error(e.msg || "保存失败"); } };
onMounted(load);
</script>
