import json

import common.base as Base
from config.settings import DynamicParam


def set_relation(res_data):
    relation = 'ticket=data.ticket'
    datalist = []
    datalist = relation.split(',')
    for i in datalist:
        var = i.split('=')
        # 列表第1个值设置为var_name
        var_name = var[0]
        var_tmp = var[1].split('.')
        res = Base.parse_relation(var_tmp, res_data)
        print(f"{var_name}={res}")
        setattr(DynamicParam, var_name, res)

    def correlation(data):
        # 根据正则，获取数据
        re_data = Base.find(data)
        if re_data:
            replace_dict = {}
            for j in re_data:
                # 根据名称，从DynamicParam动态获取属性值，并把结果内容赋值给变量data_tmp
                data_tmp = getattr(DynamicParam, str(j), 'None')
                # 把结果更新到字典replace_dict中
                replace_dict.update({str(j): replace_dict})
            # 参数精心替换，并把str转换为Python对象
            data = json.loads(Base.relace(data, replace_dict))
        return data


if __name__ == '__main__':
    res_data = "{'code': 200, 'body': {'status': 200, 'message': 'success', 'data': {'ticket': " \
               "'8d11b517bb2544109fcb656bd183045c'} "
    set_relation(res_data)