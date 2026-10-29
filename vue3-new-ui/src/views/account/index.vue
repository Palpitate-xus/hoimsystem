<template>
  <div class="account-page">
    <el-card shadow="never">
      <el-descriptions title="账号信息" :column="1" border>
        <el-descriptions-item label="用户名">{{ username }}</el-descriptions-item>
        <el-descriptions-item label="角色">{{ role }}</el-descriptions-item>
        <el-descriptions-item label="常用 AI 任务">{{ favorites.length }} 项，保存在当前浏览器</el-descriptions-item>
      </el-descriptions>
      <p>账号资料和权限由管理员维护。</p>
      <el-button :disabled="!favorites.length" @click="clearFavorites">清空本机任务收藏</el-button>
    </el-card>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { useStore } from 'vuex';
import { ElMessage } from 'element-plus';
import { roleLabel } from '@/utils/userPresentation';
import { favoriteStorageKey, readFavorites, writeFavorites } from '@/utils/aiFavorites.cjs';

defineOptions({ name: 'Account' });
const store = useStore();
const username = computed(() => store.getters['user/username']);
const permissions = computed(() => store.getters['user/permissions']);
const role = computed(() => roleLabel(permissions.value));
const key = computed(() => favoriteStorageKey(username.value, permissions.value));
const favorites = ref([]);
function storage() { try { return window.localStorage; } catch { return null; } }
watch(key, () => { favorites.value = readFavorites(storage(), key.value); }, { immediate: true });
function clearFavorites() {
  if (!writeFavorites(storage(), key.value, [])) return ElMessage.warning('浏览器未允许保存设置，请检查存储权限。');
  favorites.value = [];
  ElMessage.success('已清空本机任务收藏');
}
</script>

<style scoped>
.account-page { padding: 20px; }
p { color: var(--el-text-color-secondary); margin: 20px 0; }
</style>
