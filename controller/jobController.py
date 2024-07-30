"""
@Author：dr34m
@Date  ：2024/7/10 12:10 
"""
from concurrent.futures import ThreadPoolExecutor

from tornado.concurrent import run_on_executor

from controller.baseController import BaseHandler, handle_request
from service.alist import alistService
from service.syncJob import jobService


class Alist(BaseHandler):
    executor = ThreadPoolExecutor(1)

    @run_on_executor
    @handle_request
    def get(self, req):
        if 'alistId' in req and 'path' in req:
            return alistService.getChildPath(int(req['alistId']), req['path'])
        return alistService.getClientList()

    @run_on_executor
    @handle_request
    def post(self, req):
        alistService.addClient(req)

    @run_on_executor
    @handle_request
    def put(self, req):
        alistService.updateClient(req)

    @run_on_executor
    @handle_request
    def delete(self, req):
        alistService.removeClient(req['id'])


class Job(BaseHandler):
    executor = ThreadPoolExecutor(1)

    @run_on_executor
    @handle_request
    def get(self, req):
        if 'id' in req:
            return jobService.getTaskList(req)
        elif 'taskId' in req:
            return jobService.getTaskItemList(req)
        return jobService.getJobList(req)

    @run_on_executor
    @handle_request
    def post(self, req):
        if 'id' in req:
            jobService.editJobClient(req)
        else:
            jobService.addJobClient(req)

    @run_on_executor
    @handle_request
    def put(self, req):
        if req['pause'] is None:
            jobService.doJobManual(req['id'])
        elif req['pause'] is True:
            jobService.pauseJob(req['id'], req.get('cancel', False))
        else:
            jobService.continueJob(req['id'])

    @run_on_executor
    @handle_request
    def delete(self, req):
        if 'id' in req:
            jobService.removeJobClient(req['id'], req.get('cancel', False))
        elif 'taskId' in req:
            jobService.removeTask(req['taskId'])
