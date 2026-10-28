<template>
  <main class="status-page" aria-labelledby="status-title">
    <div class="status-code" aria-hidden="true">{{ code }}</div>
    <h1 id="status-title">{{ title }}</h1>
    <p>{{ description }}</p>
    <div class="status-actions">
      <el-button @click="goBack">返回上一页</el-button>
      <router-link class="home-link" to="/">返回首页</router-link>
    </div>
  </main>
</template>

<script setup>
import { useRouter } from "vue-router";

defineProps({ code: { type: String, required: true }, title: { type: String, required: true }, description: { type: String, required: true } });
const router = useRouter();
function goBack() {
  if (window.history.state?.back) router.back();
  else router.push("/");
}
</script>

<style scoped>
.status-page { min-height: 80vh; padding: 40px 24px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; box-sizing: border-box; }
.status-code { color: var(--el-color-primary); font-size: clamp(72px, 18vw, 128px); font-weight: 700; line-height: 1; letter-spacing: 4px; }
h1 { margin: 24px 0 12px; font-size: 24px; color: var(--el-text-color-primary); }
p { max-width: 480px; margin: 0 0 28px; line-height: 1.8; color: var(--el-text-color-regular); }
.status-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 16px; }
.home-link { color: var(--el-color-primary); padding: 8px; border-radius: 4px; }
.home-link:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
</style>
