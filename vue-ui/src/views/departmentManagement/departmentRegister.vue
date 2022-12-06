<template>
  <div>
    <el-form ref="form" :model="form" label-width="124px">
      <el-form-item label="科室名称">
        <el-input v-model="form.name"></el-input>
      </el-form-item>
      <el-form-item label="科室主任">
        <el-input v-model="form.director"></el-input>
      </el-form-item>
      <el-form-item label="科室联系方式">
        <el-input v-model="form.phone"></el-input>
      </el-form-item>
      <el-form-item label="科室位置">
        <el-input v-model="form.location"></el-input>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="onSubmit">注册</el-button>
        <el-button>取消</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script>
  export default {
    name: 'DepartmentRegister',
  }
</script>
