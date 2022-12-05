<template>
  <div>
    <h1>这是管理员页面</h1>
    <el-row>
      <el-col :xs="12" :sm="12" :md="12" :lg="12" :xl="12">
        <el-card>待办事项</el-card>
      </el-col>
      <el-col :xs="12" :sm="12" :md="12" :lg="12" :xl="12">
        <el-card>当前设置</el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script>
  export default {
    name: 'Index',
  }
</script>
