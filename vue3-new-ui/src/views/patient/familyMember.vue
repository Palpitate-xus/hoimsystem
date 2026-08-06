<template>
  <div class="app-container">
    <vab-page-header title="家庭成员" description="维护家属资料，预约或挂号时可代家属办理" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="openCreate">添加家庭成员</el-button>
      </div>
      <el-table :data="members" v-loading="loading" border empty-text="暂无家庭成员">
        <el-table-column prop="name" label="姓名" width="120" />
        <el-table-column prop="relation" label="关系" width="100" />
        <el-table-column label="身份证号">
          <template #default="{ row }">{{ maskIdentity(row.identity) }}</template>
        </el-table-column>
        <el-table-column prop="phone" label="手机号" width="140" />
        <el-table-column prop="allergy_history" label="过敏史" min-width="150" />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑家庭成员' : '添加家庭成员'" width="560px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="姓名" prop="name"><el-input v-model="form.name" maxlength="24" /></el-form-item>
        <el-form-item label="身份证号" prop="identity">
          <el-input v-model="form.identity" maxlength="18" :disabled="editing" />
        </el-form-item>
        <el-form-item label="关系" prop="relation"><el-input v-model="form.relation" maxlength="20" /></el-form-item>
        <el-form-item label="性别" prop="sex">
          <el-radio-group v-model="form.sex"><el-radio :value="1">男</el-radio><el-radio :value="0">女</el-radio></el-radio-group>
        </el-form-item>
        <el-form-item label="出生日期"><el-date-picker v-model="form.birthday" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="手机号"><el-input v-model="form.phone" maxlength="11" /></el-form-item>
        <el-form-item label="地址"><el-input v-model="form.address" maxlength="100" /></el-form-item>
        <el-form-item label="过敏史"><el-input v-model="form.allergy_history" maxlength="200" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { createFamilyMember, deleteFamilyMember, getFamilyMembers, updateFamilyMember } from "@/api/patient";

const members = ref([]);
const loading = ref(false);
const submitting = ref(false);
const dialogVisible = ref(false);
const editing = ref(false);
const formRef = ref();
const emptyForm = () => ({ family_member_id: null, name: "", identity: "", relation: "", sex: 1, birthday: null, phone: "", address: "", allergy_history: "" });
const form = ref(emptyForm());
const rules = {
  name: [{ required: true, message: "请输入姓名", trigger: "blur" }],
  identity: [{ required: true, message: "请输入身份证号", trigger: "blur" }],
  relation: [{ required: true, message: "请输入关系", trigger: "blur" }],
  sex: [{ required: true, message: "请选择性别", trigger: "change" }],
};

const maskIdentity = (identity = "") => identity.length > 8 ? `${identity.slice(0, 4)}********${identity.slice(-4)}` : identity;

const fetchMembers = async () => {
  loading.value = true;
  try {
    const res = await getFamilyMembers();
    members.value = res.data || [];
  } catch (error) {
    ElMessage.error(error?.msg || "家庭成员加载失败");
  } finally {
    loading.value = false;
  }
};

const openCreate = () => { editing.value = false; form.value = emptyForm(); dialogVisible.value = true; };
const openEdit = (row) => { editing.value = true; form.value = { ...row }; dialogVisible.value = true; };

const submit = async () => {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;
  submitting.value = true;
  try {
    if (editing.value) await updateFamilyMember(form.value);
    else await createFamilyMember(form.value);
    ElMessage.success("保存成功");
    dialogVisible.value = false;
    await fetchMembers();
  } catch (error) {
    ElMessage.error(error?.msg || "保存失败");
  } finally {
    submitting.value = false;
  }
};

const remove = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除家庭成员“${row.name}”吗？删除后不会影响其既有就诊记录。`, "提示", { type: "warning" });
    await deleteFamilyMember(row.family_member_id);
    ElMessage.success("删除成功");
    await fetchMembers();
  } catch (error) {
    if (error !== "cancel" && error !== "close") ElMessage.error(error?.msg || "删除失败");
  }
};

onMounted(fetchMembers);
</script>
