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
    <el-divider content-position="left">排班</el-divider>
    <el-row>
      <el-col :xs="24" :sm="24" :md="24" :lg="24" :xl="24">
        <el-card shadow="hover">当前排班情况</el-card>
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
      }
    },
    created() {
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
