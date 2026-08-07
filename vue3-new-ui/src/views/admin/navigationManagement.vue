<template>
  <div class="app-container">
    <vab-page-header title="院内路线管理" description="配置院区导航节点和路线连线，患者端按最短距离生成路线" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="导航节点" name="nodes">
        <div class="page-toolbar">
          <el-button type="primary" @click="openNodeDialog">新增节点</el-button>
          <el-button @click="loadData">刷新</el-button>
        </div>
        <el-table :data="nodes" v-loading="loading" empty-text="暂无导航节点">
          <el-table-column prop="code" label="编码" />
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="node_type" label="类型" />
          <el-table-column prop="campus_name" label="院区" />
          <el-table-column prop="department_name" label="关联科室" />
          <el-table-column prop="floor" label="楼层" />
          <el-table-column label="操作" width="100">
            <template #default="{ row }"><el-button size="small" type="danger" @click="removeNode(row)">删除</el-button></template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="路线连线" name="edges">
        <div class="page-toolbar">
          <el-button type="primary" @click="openEdgeDialog">新增路线</el-button>
          <el-button @click="loadData">刷新</el-button>
        </div>
        <el-table :data="edges" v-loading="loading" empty-text="暂无路线">
          <el-table-column prop="from_node_name" label="起点" />
          <el-table-column prop="to_node_name" label="终点" />
          <el-table-column prop="distance" label="距离（米）" />
          <el-table-column prop="instruction" label="指引" />
          <el-table-column label="操作" width="100">
            <template #default="{ row }"><el-button size="small" type="danger" @click="removeEdge(row)">删除</el-button></template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="nodeDialogVisible" title="新增导航节点" width="520px">
      <el-form :model="nodeForm" label-width="90px">
        <el-form-item label="编码" required><el-input v-model="nodeForm.code" /></el-form-item>
        <el-form-item label="名称" required><el-input v-model="nodeForm.name" /></el-form-item>
        <el-form-item label="类型"><el-select v-model="nodeForm.node_type"><el-option label="入口" value="entrance" /><el-option label="科室" value="department" /><el-option label="途经点" value="waypoint" /></el-select></el-form-item>
        <el-form-item label="院区"><el-select v-model="nodeForm.campus_id" clearable><el-option v-for="item in campuses" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="关联科室"><el-select v-model="nodeForm.department_id" clearable filterable><el-option v-for="item in departments" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="楼层"><el-input v-model="nodeForm.floor" /></el-form-item>
        <el-form-item label="位置"><el-input v-model="nodeForm.location" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="nodeDialogVisible = false">取消</el-button><el-button type="primary" @click="submitNode">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="edgeDialogVisible" title="新增路线" width="520px">
      <el-form :model="edgeForm" label-width="90px">
        <el-form-item label="起点" required><el-select v-model="edgeForm.from_node_id" filterable><el-option v-for="item in nodes" :key="item.node_id" :label="item.name" :value="item.node_id" /></el-select></el-form-item>
        <el-form-item label="终点" required><el-select v-model="edgeForm.to_node_id" filterable><el-option v-for="item in nodes" :key="item.node_id" :label="item.name" :value="item.node_id" /></el-select></el-form-item>
        <el-form-item label="距离（米）" required><el-input-number v-model="edgeForm.distance" :min="0.1" :max="100000" :precision="1" /></el-form-item>
        <el-form-item label="路线指引"><el-input v-model="edgeForm.instruction" /></el-form-item>
        <el-form-item label="双向"><el-switch v-model="edgeForm.bidirectional" :active-value="1" :inactive-value="0" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="edgeDialogVisible = false">取消</el-button><el-button type="primary" @click="submitEdge">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getCampusList, getDepartmentList } from "@/api/admin";
import { createNavigationEdge, createNavigationNode, deleteNavigationEdge, deleteNavigationNode, getNavigationEdgesAdmin, getNavigationNodesAdmin } from "@/api/navigation";

const activeTab = ref("nodes");
const loading = ref(false);
const nodes = ref([]);
const edges = ref([]);
const campuses = ref([]);
const departments = ref([]);
const nodeDialogVisible = ref(false);
const edgeDialogVisible = ref(false);
const nodeForm = ref({ node_type: "waypoint", status: 1 });
const edgeForm = ref({ distance: 1, bidirectional: 1, status: 1 });

const loadData = async () => {
  loading.value = true;
  try {
    const [nodeRes, edgeRes, campusRes, departmentRes] = await Promise.all([getNavigationNodesAdmin(), getNavigationEdgesAdmin(), getCampusList(), getDepartmentList()]);
    nodes.value = nodeRes.data || [];
    edges.value = edgeRes.data || [];
    campuses.value = campusRes.data || [];
    departments.value = departmentRes.data || [];
  } finally {
    loading.value = false;
  }
};

const openNodeDialog = () => { nodeForm.value = { node_type: "waypoint", status: 1 }; nodeDialogVisible.value = true; };
const openEdgeDialog = () => { edgeForm.value = { distance: 1, bidirectional: 1, status: 1 }; edgeDialogVisible.value = true; };
const submitNode = async () => { try { await createNavigationNode(nodeForm.value); ElMessage.success("节点已保存"); nodeDialogVisible.value = false; await loadData(); } catch (error) { ElMessage.error(error.msg || "节点保存失败"); } };
const submitEdge = async () => { try { await createNavigationEdge(edgeForm.value); ElMessage.success("路线已保存"); edgeDialogVisible.value = false; await loadData(); } catch (error) { ElMessage.error(error.msg || "路线保存失败"); } };
const removeNode = (row) => { ElMessageBox.confirm("确认删除该节点？被路线使用时无法删除。", "提示", { type: "warning" }).then(async () => { await deleteNavigationNode({ node_id: row.node_id }); ElMessage.success("删除成功"); await loadData(); }).catch(() => {}); };
const removeEdge = (row) => { ElMessageBox.confirm("确认删除该路线？", "提示", { type: "warning" }).then(async () => { await deleteNavigationEdge({ edge_id: row.edge_id }); ElMessage.success("删除成功"); await loadData(); }).catch(() => {}); };
onMounted(loadData);
</script>
