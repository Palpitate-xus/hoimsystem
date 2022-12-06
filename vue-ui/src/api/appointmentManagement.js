import request from '@/utils/request'

export function getAppointmentList(data) {
  return request({
    url: '/appointmentManagement/getList',
    method: 'post',
    data,
  })
}

export function makeAppointment(data) {
  return request({
    url: '/appointmentManagement/create',
    method: 'post',
    data,
  })
}

export function cancelAppointment(data) {
  return request({
    url: '/appointmentManagement/cancel',
    method: 'post',
    data,
  })
}
