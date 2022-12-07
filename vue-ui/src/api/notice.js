import request from '@/utils/request'

export function getNoticeList(data) {
  return request({
    url: '/notice/getList',
    method: 'post',
    data,
  })
}

export function noticeRegister(data) {
  return request({
    url: '/notice/create',
    method: 'post',
    data,
  })
}
