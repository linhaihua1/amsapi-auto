import datetime
from pathlib import Path
from config.settings import DynamicParam

from utils.execlutil import read_case_data, update_case_result, get_sheet
from utils.logutil import logger
import common.base as Base

import json
import pytest
from utils.requestsutil import RequestSend
from common.project_path import Path

# 假设get_sheet和read_case_data为已定义的函数，分别用于获取Excel表格和读取数据
def get_sheet(filename, sheetname):
        # 实现读取Excel sheet的逻辑
    pass

def read_case_data(sheet):
        # 实现读取用例数据的逻辑，这里假设返回的是一个用例列表
    pass

def correlation(data):
        # 实现数据关联替换逻辑
    pass

def set_relation(relation, res_data):
        # 实现设置关联变量的逻辑
    pass

def assert_respoes(case, res_data):
        # 实现响应断言逻辑
    pass

    class RequestSend:
        @staticmethod
        def send(url, method, data=None, headers=None, cookies=None):
            # 实现发送请求逻辑
            pass

    # 新增函数：根据模块筛选用例
    def filter_cases_by_module(case_list, modules_to_run):
        return [case for case in case_list if case['module'] in modules_to_run]

    # 假设Path.test_case_path为已定义的路径
    filename = Path.test_case_path
    sheetname = 'test_case_list'
    case_sheet = get_sheet(filename, sheetname)
    case_list = read_case_data(case_sheet)

    # 定义要运行的模块
    modules_to_run = ['模块A', '模块B']

    # 筛选指定模块的用例
    filtered_case_list = filter_cases_by_module(case_list, modules_to_run)

    current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 使用pytest框架编写测试类
    class TestApi:
        @staticmethod
        def setup_class():
            logger.info(f"***** 开始执行测试用例，开始时间为：{current_time} *****")

        @pytest.mark.parametrize('case', filtered_case_list)
        def test_run(self, case):
            logger.info(f"*********{case}**********")
            res_data = None
            # 根据条件，从数据库获取url信息，并拼接完整url信息
            url = case['url']
            # 获取method内容
            method = case['method']
            # 获取headers内容，格式化字符为字典
            headers = eval(case['headers'])
            cookies = eval(case['cookies'])
            data = eval(case['request_body'])
            # 获取关联内容
            relation = str(case['relation'])
            # 获取用例名称
            case_name = case['title']

            # 根据关联获取headers参数中是否有变量需要被替换，有则替换，无则默认
            headers = self.correlation(headers)
            cookies = self.correlation(cookies)
            data = self.correlation(data)
            try:
                logger.info("正在执行{}用例".format(case_name))
                res_data = RequestSend().send(url, method, data=data, headers=headers, cookies=cookies)
                # logger.info{f"*********{res_data}**********"}
                logger.info("用例执行成功，请求的结果为{}".format(res_data))
                # print(case_list)
            except:
                logger.info("用例执行失败，请查看日志找原因")
                assert False
            if res_data:
                if relation != "None":
                    # 根据响应结果，以及关联信息（token=cookies.admin-token）,设置变量token的值为形影结果的信息
                    self.set_relation(relation, res_data)
            self.assert_respoes(case, res_data)
            return res_data
    @staticmethod
    def set_relation(relation, res_data):
        try:
            if relation:
                # 根据,切割为list
                relation = relation.split(',')
                print(relation)
                for i in relation:
                    var = i.split('=')
                    # 列表第1个值设置为var_name
                    var_name = var[0]
                    var_tmp = var[1].split('.')
                    print(var_tmp)
                    res = Base.parse_relation(var_tmp, res_data)
                    # print(f"{var_name}={res}")
                    print(res)
                    setattr(DynamicParam, var_name, res)
        except Exception as e:
            print(e)

    # 根据关联，获取改变量内容
    @staticmethod
    def correlation(data):
        # 根据正则，获取数据
        res_data = Base.find(data)
        if res_data:
            replace_dict = {}
            for i in res_data:
                # 根据名称，从DynamicParam动态获取属性值，并把结果内容赋值给变量data_tmp
                data_tmp = getattr(DynamicParam, str(i), 'None')
                # 把结果更新到字典replace_dict中
                replace_dict.update({str(i):data_tmp})
            # 参数精心替换，并把str转换为Python对象
            data = json.loads(Base.relace(data, replace_dict))
        return data

    @staticmethod
    def assert_respoes(case, res_data):
        is_pass = False
        try:
            assert int(res_data['body']['status']) == int(case['expected_code'])
            logger.info("用例断言成功")
            is_pass = True
        except:
            is_pass = False
            logger.info("用例断言失败")
        finally:
            # 把结果跟新到数据库
            # case_data.updateResults(res_data, is_pass, str(case['id']))
            # 把结果更新到excel中
            update_case_result(filename, sheetname, response=res_data, ispass=is_pass, row_id=int(case['id'])+1)
            # 根据结果是True还是False进行断言验证，成功则通过，失败则未通过
            assert is_pass
        return is_pass

    @staticmethod
    def teardown_class():
        logger.info(f"***** 执行用例完成，完成时间为：{current_time} *****")
        # AllureHandler().execute_command()


if __name__ == '__main__':
    pytest.main()