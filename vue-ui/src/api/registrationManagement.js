import request from '@/utils/request'

export function getRegistrationList(data) {
  return request({
    url: '/registrationManagement/getList',
    method: 'post',
    data,
  })
}

export function makeRegistration(data) {
  return request({
    url: '/registrationManagement/create',
    method: 'post',
    data,
  })
}

export function cancelRegistration(data) {
  return request({
    url: '/registrationManagement/cancel',
    method: 'post',
    data,
  })
}
