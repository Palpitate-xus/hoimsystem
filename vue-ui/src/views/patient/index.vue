<template>
  <div class="magnifier-container">
    <el-carousel :interval="4000" type="card" height="400px">
      <el-carousel-item v-for="item in photos" :key="item">
        <el-image :src="item" :fit="fit"></el-image>
      </el-carousel-item>
    </el-carousel>
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
    <el-divider content-position="left">医嘱</el-divider>
    <el-row>
      <el-col :xs="24" :sm="24" :md="24" :lg="24" :xl="24">
        <el-card shadow="hover">当前医嘱</el-card>
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
        photos: [
          'https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fdingyue.ws.126.net%2F2020%2F0119%2F3b214146j00q4bcun001pc200u000gqg00f6008g.jpg&refer=http%3A%2F%2Fdingyue.ws.126.net&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1673177086&t=6b7febc5173cd0e9575c2c30bbd715b4',
          'https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fx0.ifengimg.com%2Fucms%2F2022_07%2F2E76219549BF8F9C666722B98979A7CBE1453959_size103_w1080_h810.jpg&refer=http%3A%2F%2Fx0.ifengimg.com&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1673177084&t=a980ba32c22715e3c3f7a37f676996f7',
          'https://img1.baidu.com/it/u=997640452,1115131583&fm=253&fmt=auto&app=138&f=JPEG?w=2500&h=500',
          'https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fbkimg.cdn.bcebos.com%2Fpic%2F5882b2b7d0a20cf476c2eb2c7c094b36adaf99f6&refer=http%3A%2F%2Fbkimg.cdn.bcebos.com&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1673177178&t=caae765418f71062473bcd64d9f81031',
          'https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fwww.cddrzs.com%2Fuploadfile%2F2020%2F1109%2F20201109113136525.jpg&refer=http%3A%2F%2Fwww.cddrzs.com&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1673177176&t=514fb10791d3334b07ae0c9480e61aee',
          'https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fp9.itc.cn%2Fq_70%2Fimages03%2F20210115%2Fb2908279115f4dc8a6e80e5039df34bb.jpeg&refer=http%3A%2F%2Fp9.itc.cn&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1673177172&t=cf87f0a5d91594a6096db91158e1f61c',
          'https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fimagecloud.thepaper.cn%2Fthepaper%2Fimage%2F170%2F909%2F449.JPG&refer=http%3A%2F%2Fimagecloud.thepaper.cn&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1673177234&t=88932c4f751590d306f0406ffb4d4a9f',
          'https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fkoss.iyong.com%2Fswift%2Fv1%2Fiyong_public%2Fiyong_2512628156023296%2Fimage%2F20181029%2F1540777728639013620.jpg&refer=http%3A%2F%2Fkoss.iyong.com&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1673177230&t=34585f34ffdb115f026e395488c8c5a5',
          'https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fwww.xxsb.com%2Fpic%2F2021-07%2F23%2F1dfaff4b-1a00-4769-980b-34c7b7a5922f.jpg&refer=http%3A%2F%2Fwww.xxsb.com&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1673177229&t=0ec424cdc7b1fb03428bce32ddfd224c',
          'https://img1.baidu.com/it/u=1462508234,102244113&fm=253&fmt=auto&app=138&f=JPEG?w=750&h=500',
          'https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fimg.zx123.cn%2FResources%2Fzx123cn%2Fuploadfile%2F2016%2F1007%2F2bf5cc4ee6ea15c846c5f0c078d52bb3.jpg&refer=http%3A%2F%2Fimg.zx123.cn&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1673177266&t=fb2605f4ae4943284e72ccadb91f5c6d',
        ],
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

<style>
  .el-carousel__item h3 {
    color: #475669;
    font-size: 14px;
    opacity: 0.75;
    line-height: 200px;
    margin: 0;
  }
  .el-carousel__item:nth-child(2n) {
    background-color: #99a9bf;
  }
  .el-carousel__item:nth-child(2n + 1) {
    background-color: #d3dce6;
  }
</style>
