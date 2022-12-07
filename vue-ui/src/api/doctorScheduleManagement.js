import request from '@/utils/request'

export function getDoctorScheduleList(data) {
  return request({
    url: '/doctorScheduleManagement/getList',
    method: 'post',
    data,
  })
}

export function doctorScheduleRegister(data) {
  return request({
    url: '/doctorScheduleManagement/register',
    method: 'post',
    data,
  })
}
