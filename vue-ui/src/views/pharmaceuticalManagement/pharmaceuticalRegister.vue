<template>
  <div>
    <el-form ref="form" :model="form" label-width="124px">
      <el-form-item label="药品名称">
        <el-input v-model="form.name"></el-input>
      </el-form-item>
      <el-form-item label="数量">
        <el-input v-model="form.stock"></el-input>
      </el-form-item>
      <el-form-item label="单价">
        <el-input v-model="form.price"></el-input>
      </el-form-item>
      <el-form-item label="有效期">
        <el-date-picker
          v-model="form.expireddate"
          type="date"
          value-format="yyyy-MM-dd"
          placeholder="选择有效期"
        ></el-date-picker>
      </el-form-item>
      <el-form-item label="供应商">
        <el-input v-model="form.supplier"></el-input>
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.remark"></el-input>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="onSubmit">注册</el-button>
        <el-button>取消</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script>
  import { pharmaceuticalRegister } from '@/api/pharmaceuticalManagement'
  export default {
    name: 'PharmaceuticalRegister',
    data() {
      return {
        form: {},
      }
    },
    methods: {
      async onSubmit() {
        console.log('submit!')
        console.log(this.form)
        await pharmaceuticalRegister(this.form)
        this.form = {}
      },
    },
  }
</script>
