<template>
  <StatusPage code="404" title="页面不存在" description="请检查页面地址，或返回首页继续操作。" />
</template>

<script setup>
import StatusPage from "@/components/StatusPage/index.vue";
defineOptions({ name: "Page404" });
</script>
