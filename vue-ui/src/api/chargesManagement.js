import request from '@/utils/request'

export function getChargeList(data) {
  return request({
    url: '/chargeManagement/getList',
    method: 'post',
    data,
  })
}
