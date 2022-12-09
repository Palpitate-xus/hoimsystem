<template>
  <div class="magnifier-container">
    <el-divider content-position="left">通知</el-divider>
    <el-card
      v-for="item in notices"
      :key="item"
      class="box-card"
      shadow="hover"
    >
      <div slot="header" class="clearfix">
        <span>{{ item.title }}</span>
      </div>
      <div>
        {{ item.content }}
      </div>
    </el-card>
    <el-divider content-position="left">挂号与预约</el-divider>
    <el-row>
      <el-col :xs="12" :sm="12" :md="12" :lg="12" :xl="12">
        <el-card shadow="hover">当前挂号情况</el-card>
      </el-col>
      <el-col :xs="12" :sm="12" :md="12" :lg="12" :xl="12">
        <el-card shadow="hover">当前预约情况</el-card>
      </el-col>
    </el-row>
    <el-divider content-position="left">当前病人</el-divider>
    <el-row>
      <el-col :xs="24" :sm="24" :md="24" :lg="24" :xl="24">
        <el-card shadow="hover">
          <div slot="header" class="clearfix">
            <span>高明源</span>
            <el-button style="float: right">下一个</el-button>
          </div>
          <div>病人基本信息</div>
          <div>年龄：</div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script>
  import { getNoticeList } from '../../api/notice'
  import { getAppointmentList } from '../../api/appointmentManagement'
  import { getRegistrationList } from '../../api/registrationManagement'
  export default {
    name: 'Index',
    data() {
      return {
        notices: [],
        appointments: [],
        registrations: [],
        patient: 'gmy',
      }
    },
    created() {
      this.fetchData()
    },
    mounted() {
      this.fetchData()
    },
    methods: {
      async fetchData() {
        const notices = await getNoticeList()
        this.notices = notices.data
        console.log(this.notices)
        this.appointments = getAppointmentList()
        this.registrations = getRegistrationList()
      },
    },
  }
</script>
