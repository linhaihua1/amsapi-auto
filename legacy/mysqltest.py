import pymysql

from config.settings import DB_CONFIG
from utils.readmysql import RdTestcase

db = pymysql.connect(**DB_CONFIG)

case_data = RdTestcase()
res001 = case_data.load_confkey('demo_web', 'url_api')[0]['value']
print(type(res001))

# cursor = db.cursor()
# sql = "select * from test_config where web='demo_web' and environment='url_api'"
# cursor.execute(sql)
# res = cursor.fetchone()
# print(res)
# cursor.close()
# db.close()
