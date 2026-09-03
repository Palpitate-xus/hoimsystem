const { randomUUID } = require('node:crypto')
const { handleRandomImage } = require('../utils')

const List = []
const count = 999

const randomInteger = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min
const randomItem = (items) => items[randomInteger(0, items.length - 1)]
const randomDateTime = () => {
  const end = Date.now()
  const start = end - 365 * 24 * 60 * 60 * 1000
  return new Date(randomInteger(start, end)).toISOString().replace('T', ' ').slice(0, 19)
}
const createRow = () => ({
  uuid: randomUUID(),
  id: randomInteger(100000, 999999),
  title: randomItem(['门诊记录', '住院记录', '检验报告', '处方审核']),
  status: randomItem(['published', 'draft', 'deleted']),
  author: randomItem(['张医生', '李医生', '王医生', '陈医生']),
  datetime: randomDateTime(),
  pageViews: randomInteger(300, 5000),
  img: handleRandomImage(200, 200),
  smallImg: handleRandomImage(40, 40),
  switch: Math.random() >= 0.5,
  percent: randomInteger(80, 99),
})

for (let i = 0; i < count; i++) {
  List.push(createRow())
}

module.exports = [
  {
    url: '/table/getList',
    type: 'post',
    response(config) {
      if (!config.body) {
        return {
          code: 200,
          msg: 'success',
          totalCount: count,
          data: Array.from({ length: 50 }, createRow),
        }
      }
      const { title = '', pageNo = 1, pageSize = 20 } = config.body
      let mockList = List.filter((item) => {
        return !(title && item.title.indexOf(title) < 0)
      })
      const pageList = mockList.filter((item, index) => index < pageSize * pageNo && index >= pageSize * (pageNo - 1))
      return {
        code: 200,
        msg: 'success',
        totalCount: count,
        data: pageList,
      }
    },
  },
  {
    url: '/table/doEdit',
    type: 'post',
    response() {
      return {
        code: 200,
        msg: '模拟保存成功',
      }
    },
  },
  {
    url: '/table/doDelete',
    type: 'post',
    response() {
      return {
        code: 200,
        msg: '模拟删除成功',
      }
    },
  },
]
