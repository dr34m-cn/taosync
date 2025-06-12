"""
@Author：dr34m
@Date  ：2024/7/10 12:10 
"""
from concurrent.futures import ThreadPoolExecutor

from tornado.concurrent import run_on_executor

from controller.baseController import BaseHandler, handle_request
from service.alist import alistService
from service.syncJob import jobService, taskService


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
    executor = ThreadPoolExecutor(4)

    @run_on_executor
    @handle_request
    def get(self, req):
        if 'id' in req:
            if 'current' in req:
                return jobService.getJobCurrent(req['id'], req.get('status', None))
            return taskService.getTaskList(req)
        elif 'taskId' in req:
            return taskService.getTaskItemList(req)
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
            if 'id' in req:
                # 手动执行作业
                jobService.doJobManual(req['id'])
            else:
                # 手动执行所有作业
                jobService.doAllJobManual()
        elif req['pause'] is True:
            # 禁用作业
            if 'abort' in req:
                jobService.abortJob(req['id'])
            else:
                jobService.pauseJob(req['id'])
        else:
            # 启用作业
            jobService.continueJob(req['id'])

    @run_on_executor
    @handle_request
    def delete(self, req):
        if 'id' in req:
            jobService.removeJobClient(req['id'])
        elif 'taskId' in req:
            taskService.removeTask(req['taskId'])
