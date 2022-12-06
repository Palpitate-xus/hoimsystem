<template>
  <div>
    <el-form ref="form" :model="form" label-width="124px">
      <el-form-item label="科室名称">
        <el-input v-model="form.name"></el-input>
      </el-form-item>
      <el-form-item label="科室联系方式">
        <el-input v-model="form.phone"></el-input>
      </el-form-item>
      <el-form-item label="科室主任">
        <el-select v-model="form.director" placeholder="请选择科室主任">
          <el-option
            v-for="item in doctorList"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          ></el-option>
        </el-select>
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
  import { createDepartment } from '../../api/departmentManagement'
  import { getDoctorList } from '../../api/doctorManagement'
  export default {
    name: 'DepartmentRegister',
    data() {
      return {
        form: {
          director: 1,
        },
        doctorList: [],
      }
    },
    created() {
      this.fetchData()
    },
    methods: {
      async fetchData() {
        const { data } = await getDoctorList()
        this.doctorList = data
      },
      async onSubmit() {
        console.log('submit!')
        console.log(this.form)
        await createDepartment(this.form)
        this.form = { director: 1 }
      },
    },
  }
</script>
