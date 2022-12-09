import request from '@/utils/request'

export function getChargeList(data) {
  return request({
    url: '/chargeManagement/getList',
    method: 'post',
    data,
  })
}

export function charge(data) {
  return request({
    url: '/chargeManagement/charge',
    method: 'post',
    data,
  })
}
