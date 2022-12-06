import request from '@/utils/request'

export function getDoctorList(data) {
  return request({
    url: '/doctorManagement/getList',
    method: 'post',
    data,
  })
}
