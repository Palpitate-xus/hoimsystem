<template>
  <div>
    <el-form ref="form" :model="form" label-width="124px">
      <el-form-item label="通知标题">
        <el-input v-model="form.title"></el-input>
      </el-form-item>
      <el-form-item label="通知内容">
        <el-input v-model="form.content"></el-input>
      </el-form-item>
      <el-form-item label="是否紧急">
        <el-switch
          v-model="form.specialist"
          active-value="1"
          inactive-value="0"
        ></el-switch>
      </el-form-item>
      <el-form-item label="发送对象">
        <el-checkbox-group v-model="form.schedule">
          <el-checkbox label="科室主任" name="type"></el-checkbox>
          <el-checkbox label="医生" name="type"></el-checkbox>
          <el-checkbox label="病人" name="type"></el-checkbox>
        </el-checkbox-group>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="onSubmit">发送</el-button>
        <el-button @click="cancel">取消</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script>
  import { getDoctorList } from '../../api/doctorManagement'
  export default {
    name: 'NoticeRegister',
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
        await doctorRegister(this.form)
        this.form = {}
      },
      cancel() {
        this.form = {}
      },
    },
  }
</script>
