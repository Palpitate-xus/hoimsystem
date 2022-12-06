<template>
  <div>
    <el-form ref="form" :model="form" label-width="124px">
      <el-form-item label="医生姓名">
        <el-input v-model="form.name"></el-input>
      </el-form-item>
      <el-form-item label="医生用户名">
        <el-input v-model="form.username"></el-input>
      </el-form-item>
      <el-form-item label="医生登陆密码">
        <el-input v-model="form.password"></el-input>
      </el-form-item>
      <el-form-item label="医生性别">
        <el-radio-group v-model="form.sex">
          <el-radio label="女"></el-radio>
          <el-radio label="男"></el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="医生电话">
        <el-input v-model="form.phone"></el-input>
      </el-form-item>
      <el-form-item label="医生科室">
        <el-select v-model="form.education" placeholder="请选择医生科室">
          <el-option label="本科" value="本科"></el-option>
          <el-option label="硕士" value="硕士"></el-option>
          <el-option label="博士" value="博士"></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="医生学历">
        <el-select v-model="form.education" placeholder="请选择医生学历">
          <el-option label="本科" value="本科"></el-option>
          <el-option label="硕士" value="硕士"></el-option>
          <el-option label="博士" value="博士"></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="医生职称">
        <el-select v-model="form.title" placeholder="请选择医生职称">
          <el-option label="主任医生" value="主任医生"></el-option>
          <el-option label="副主任医生" value="副主任医生"></el-option>
          <el-option label="主治医生" value="主治医生"></el-option>
          <el-option label="实习医生" value="实习医生"></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="医生权限">
        <el-select v-model="form.permission" placeholder="请选择医生权限">
          <el-option label="科室主任" value="director"></el-option>
          <el-option label="科室医生" value="doctor"></el-option>
        </el-select>
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
    name: 'AddDoctor',
    data() {
      return {
        form: {},
      }
    },
    methods: {
      onSubmit() {
        console.log('submit!')
        console.log(this.form)
      },
    },
  }
</script>
