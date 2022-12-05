<template>
  <div class="magnifier-container">
    <h1>病人主页</h1>
    <el-row :gutter="20">
      <el-col :xs="24" :sm="24" :md="24" :lg="24" :xl="24">
        <el-card>医院通知</el-card>
      </el-col>
    </el-row>
    <el-row>
      <el-col :xs="12" :sm="12" :md="12" :lg="12" :xl="12">
        <el-card>当前挂号情况</el-card>
      </el-col>
      <el-col :xs="12" :sm="12" :md="12" :lg="12" :xl="12">
        <el-card>当前预约情况</el-card>
      </el-col>
    </el-row>
    <el-row>
      <el-col :xs="24" :sm="24" :md="24" :lg="24" :xl="24">
        <el-card>当前医嘱</el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script>
  export default {
    name: 'Index',
  }
</script>
