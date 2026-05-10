<template>
  <div class="app-container">
    <vab-page-header title="CA数字签名" />
    <el-card>
      <el-form label-width="100px">
        <el-form-item label="签名内容">
          <el-input
            v-model="content"
            type="textarea"
            :rows="6"
            placeholder="请输入需要签名的内容"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSign">签名</el-button>
          <el-button type="success" @click="handleVerify" :disabled="!signResult">验证</el-button>
        </el-form-item>
      </el-form>

      <el-divider v-if="signResult" />

      <div v-if="signResult">
        <h3>签名结果</h3>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="签名人">{{ signResult.signer }}</el-descriptions-item>
          <el-descriptions-item label="签名时间">{{ signResult.sign_time }}</el-descriptions-item>
          <el-descriptions-item label="签名哈希">{{ signResult.sign_hash }}</el-descriptions-item>
          <el-descriptions-item label="证书序列号">{{ signResult.cert_sn }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <div v-if="verifyResult !== null" style="margin-top: 16px;">
        <el-alert
          :title="verifyResult ? '签名验证通过' : '签名验证失败'"
          :type="verifyResult ? 'success' : 'error'"
          show-icon
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { digitalSign, verifySign } from "@/api/digitalSignature";

const content = ref("");
const signResult = ref(null);
const verifyResult = ref(null);

const handleSign = async () => {
  if (!content.value.trim()) {
    ElMessage.warning("请输入签名内容");
    return;
  }
  try {
    const res = await digitalSign({ content: content.value });
    signResult.value = res.data || res;
    verifyResult.value = null;
    ElMessage.success("签名成功");
  } catch (error) {
    ElMessage.error("签名失败");
  }
};

const handleVerify = async () => {
  if (!signResult.value) {
    ElMessage.warning("请先进行签名");
    return;
  }
  try {
    const res = await verifySign({
      content: content.value,
      sign_hash: signResult.value.sign_hash,
      cert_sn: signResult.value.cert_sn,
    });
    verifyResult.value = res.data === true || res.data === 1 || res.data === "success";
    ElMessage.success("验证完成");
  } catch (error) {
    verifyResult.value = false;
    ElMessage.error("验证失败");
  }
};
</script>
