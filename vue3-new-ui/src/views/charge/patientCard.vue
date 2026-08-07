<template>
  <div class="app-container">
    <vab-page-header title="就诊卡办理" description="为患者办理、查询、挂失和注销就诊卡" />
    <el-card>
      <div class="page-toolbar">
        <el-input v-model="keyword" placeholder="卡号、患者姓名或身份证号" clearable class="page-search-input" @keyup.enter="loadCards" />
        <el-button type="primary" :loading="loading" @click="loadCards">查询</el-button>
        <el-button v-if="canIssue" type="success" @click="issueDialog = true">办理就诊卡</el-button>
      </div>
      <el-table :data="cards" v-loading="loading" border empty-text="暂无就诊卡">
        <el-table-column prop="card_no" label="卡号" width="210" />
        <el-table-column prop="patient_name" label="患者" width="120" />
        <el-table-column prop="identity" label="身份证号" width="190" />
        <el-table-column prop="status_text" label="状态" width="100" />
        <el-table-column prop="issue_time" label="办理时间" width="180" />
        <el-table-column label="操作" width="170">
          <template #default="{ row }">
            <el-button v-if="row.status === 0" size="small" type="warning" @click="lost(row)">挂失</el-button>
            <el-button v-if="canIssue && row.status !== 2" size="small" type="danger" @click="cancel(row)">注销</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="issueDialog" title="办理就诊卡" width="460px">
      <el-form :model="form" label-width="100px"><el-form-item label="身份证号" required><el-input v-model="form.identity" maxlength="20" placeholder="请输入患者身份证号" /></el-form-item></el-form>
      <template #footer><el-button @click="issueDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="issue">确认办理</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useStore } from "vuex";
import { cancelPatientCard, getPatientCards, issuePatientCard, reportPatientCardLost } from "@/api/patientCard";

const store = useStore();
const permissions = computed(() => store.getters["user/permissions"] || []);
const canIssue = computed(() => permissions.value.some(item => ["admin", "super_admin", "registrar"].includes(item)));
const keyword = ref(""); const cards = ref([]); const loading = ref(false); const saving = ref(false); const issueDialog = ref(false); const form = ref({ identity: "" });
const loadCards = async () => { loading.value = true; try { const res = await getPatientCards(keyword.value.trim()); cards.value = res.data || []; } catch (e) { ElMessage.error(e.msg || "就诊卡加载失败"); } finally { loading.value = false; } };
const issue = async () => { if (!form.value.identity.trim()) return ElMessage.warning("请输入身份证号"); saving.value = true; try { await issuePatientCard({ identity: form.value.identity.trim() }); ElMessage.success("就诊卡办理成功"); issueDialog.value = false; form.value = { identity: "" }; await loadCards(); } catch (e) { ElMessage.error(e.msg || "办理失败"); } finally { saving.value = false; } };
const lost = async row => { try { await ElMessageBox.confirm(`确认挂失就诊卡 ${row.card_no}？`, "挂失确认", { type: "warning" }); await reportPatientCardLost({ card_id: row.card_id }); ElMessage.success("已挂失"); await loadCards(); } catch (e) { if (e !== "cancel" && e !== "close") ElMessage.error(e.msg || "挂失失败"); } };
const cancel = async row => { try { await ElMessageBox.confirm(`确认注销就诊卡 ${row.card_no}？`, "注销确认", { type: "warning" }); await cancelPatientCard({ card_id: row.card_id }); ElMessage.success("已注销"); await loadCards(); } catch (e) { if (e !== "cancel" && e !== "close") ElMessage.error(e.msg || "注销失败"); } };
onMounted(loadCards);
</script>
