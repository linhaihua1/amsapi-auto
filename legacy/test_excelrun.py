import datetime
from config.settings import DynamicParam
from utils.execlutil import read_case_data, update_case_result, get_sheet
from utils.logutil import logger
import common.base as Base
import json
import pytest
import allure
# from utils.readmysql import RdTestcase
from utils.requestsutil import RequestSend
# from utils.AllureHandler import AllureHandler
from common.project_path import Path
# 初始化类
attribute = DynamicParam()
# 实例化测试用例对象
# filename = '../data/api_tables.xlsx'
filename = Path.test_case_path
sheetname = 'test_case_list'
case_sheet = get_sheet(filename, sheetname)
case_list = read_case_data(case_sheet)
# print(case_list)
# 根据测试用例对象获取测试用例列表
# case_list = case_data.is_run_data('zrlog')
# 获取当前时间
current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# @allure.feature("test_case_list")
class TestApi:
    @staticmethod
    def setup_class():
        logger.info(f"***** 开始执行测试用例，开始时间为：{current_time} *****")

    @pytest.mark.parametrize('case', case_list)
    # @pytest.fixture()
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


# if __name__ == '__main__':
#     pytest.main()