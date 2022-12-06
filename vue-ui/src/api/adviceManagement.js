import request from '@/utils/request'

export function getAdviceList(data) {
  return request({
    url: '/AdvicementManagement/getList',
    method: 'post',
    data,
  })
}

export function createAdvice(data) {
  return request({
    url: '/AdviceManagement/create',
    method: 'post',
    data,
  })
}
