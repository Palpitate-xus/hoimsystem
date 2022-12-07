<template>
  <div>
    <el-form ref="form" :model="form" label-width="124px">
      <el-form-item label="医生选择">
        <el-select v-model="form.doctor" placeholder="请选择医生">
          <el-option
            v-for="item in doctorList"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          ></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="是否专家号">
        <el-switch
          v-model="form.specialist"
          active-value="1"
          inactive-value="0"
        ></el-switch>
      </el-form-item>
      <el-form-item label="时间段选择">
        <el-checkbox-group v-model="form.schedule">
          <el-checkbox label="星期一上午" name="type"></el-checkbox>
          <el-checkbox label="星期一下午" name="type"></el-checkbox>
          <el-checkbox label="星期二上午" name="type"></el-checkbox>
          <el-checkbox label="星期二下午" name="type"></el-checkbox>
          <el-checkbox label="星期三上午" name="type"></el-checkbox>
          <el-checkbox label="星期三下午" name="type"></el-checkbox>
          <el-checkbox label="星期四上午" name="type"></el-checkbox>
          <el-checkbox label="星期四下午" name="type"></el-checkbox>
          <el-checkbox label="星期五上午" name="type"></el-checkbox>
          <el-checkbox label="星期五下午" name="type"></el-checkbox>
        </el-checkbox-group>
      </el-form-item>
      <el-form-item label="医生接诊数">
        <el-input v-model="form.number"></el-input>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="onSubmit">注册</el-button>
        <el-button @click="cancel">取消</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script>
  import { getDoctorList } from '@/api/doctorManagement'
  import { doctorScheduleRegister } from '@/api/doctorScheduleManagement'
  export default {
    name: 'DoctorScheduleRegister',
    data() {
      return {
        form: {
          schedule: [],
          doctor: 1,
          specialist: 0,
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
        console.log(this.doctorList)
      },
      async onSubmit() {
        console.log('submit!')
        console.log(this.form)
        await doctorScheduleRegister(this.form)
        this.cancel
      },
      cancel() {
        this.form = {
          schedule: [],
          doctor: 1,
          specialist: 0,
        }
      },
    },
  }
</script>
