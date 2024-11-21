"""
@Author：dr34m
@Date  ：2024/11/21 20:05
"""
from concurrent.futures import ThreadPoolExecutor

from tornado.concurrent import run_on_executor

from controller.baseController import BaseHandler, handle_request
from service.notify import notifyService


class Notify(BaseHandler):
    executor = ThreadPoolExecutor(1)

    @run_on_executor
    @handle_request
    def get(self, req):
        return notifyService.getNotifyList()

    @run_on_executor
    @handle_request
    def post(self, req):
        if 'enable' in req['notify']:
            notifyService.addNewNotify(req['notify'])
        else:
            notifyService.testNotify(req['notify'])

    @run_on_executor
    @handle_request
    def put(self, req):
        if 'notifyId' in req:
            notifyService.updateNotifyStatus(req['notifyId'], req['enable'])
        else:
            notifyService.editNotify(req['notify'])

    @run_on_executor
    @handle_request
    def delete(self, req):
        notifyService.deleteNotify(req['notifyId'])
