import request from '@/utils/request'

export function getDoctorList(data) {
  return request({
    url: '/doctorManagement/getList',
    method: 'post',
    data,
  })
}

export function doctorRegister(data) {
  return request({
    url: '/doctorManagement/register',
    method: 'post',
    data,
  })
}
