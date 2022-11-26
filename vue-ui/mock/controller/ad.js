const data = [
  {
    title: '建党百年惊喜福利，付费版本买一得二全年最低价，点我购买',
    url: 'https://vue-admin-beautiful.com/authorization',
  },
]
module.exports = [
  {
    url: '/ad/getList',
    type: 'get',
    response() {
      return {
        code: 200,
        msg: 'success',
        data,
      }
    },
  },
]
