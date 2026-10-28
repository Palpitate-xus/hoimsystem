<template>
  <StatusPage code="401" title="当前账号没有访问权限" description="请使用有权限的账号登录，或联系管理员调整访问权限。" />
</template>

<script setup>
import StatusPage from "@/components/StatusPage/index.vue";
defineOptions({ name: "Page401" });
</script>
