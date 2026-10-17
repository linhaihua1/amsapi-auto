# 常见问题 FAQ（排错手册）

> 遇到报错先在这里搜关键词。每条包含：**现象 / 原因 / 解决**。
> 没找到答案时，按 [最后一节](#十一通用排错流程) 的流程收集信息后再问。

---

## 一、环境与安装

### Q1 `ModuleNotFoundError: No module named 'pytest'`

**原因**：依赖未安装，或装到了别的 Python 环境。

**解决**：

```bash
pip install -r requirements.txt
# 确认用的是同一解释器
python -c "import pytest, requests, openpyxl, yaml; print('OK')"
```

若用了虚拟环境，确认已激活（命令行前有 `(venv)` 前缀）。

### Q2 `ModuleNotFoundError: No module named 'api'`

**原因**：不在项目根目录下执行，Python 找不到本地包。

**解决**：

```bash
cd amsapi-auto          # 必须是包含 api/ config/ 的那一层
python main.py
```

用 `python main.py` 启动时，`main.py` 会自动 `os.chdir` 到项目根目录；
但直接 `pytest` 时依赖当前工作目录，所以**推荐始终在项目根目录执行**。

### Q3 `ModuleNotFoundError: No module named 'allure'`

**原因**：未安装 `allure-pytest`。

**解决**：

```bash
pip install allure-pytest
```

> 注意：这只影响报告附件。框架已做降级处理，**没装也不会导致用例失败**，
> 只是报告里没有请求/响应附件。

### Q4 `ModuleNotFoundError: No module named 'pymysql'`

**原因**：使用了 MySQL 数据源但未安装 pymysql。

**解决**：

```bash
pip install pymysql
```

> 不使用 MySQL 数据源时不需要装，框架已做惰性导入。

### Q5 `allure: command not found`

**原因**：未安装 Allure 命令行工具，或未加入 `PATH`。

**解决**：

1. 下载 https://github.com/allure-framework/allure2/releases
2. 解压到任意目录（如 `D:\allure-2.29.0`）
3. 把 `bin` 目录加入系统 `PATH`
4. **重新打开终端**（PATH 修改对已打开的终端不生效）
5. 验证：`allure --version`

> 注意区分两个东西：
> - `allure-pytest`：Python 包，负责**产出原始数据**
> - `allure` CLI：命令行工具，负责**渲染 HTML**
> 两者都要有，才能得到可读报告。

---

## 二、运行与用例收集

### Q6 一条用例都没跑，显示 `skipped`

**现象**：

```
SKIPPED [1] testcase/test_excel_driver.py:30: Excel 中未读取到可执行用例（检查 isdel 列是否为 1）
```

**原因**：没有满足执行条件的用例。这是**设计行为**，不是 bug。

**排查**：

| 数据源 | 检查项 |
| --- | --- |
| Excel | `isdel` 列是否为 `1`（不是 `1` 则跳过）；sheet 名是否为 `test_case_list` |
| YAML | `data/cases/` 下是否有 `.yaml` 文件；`isdel` 是否被显式设为非 1 |
| MySQL | `data_source` 是否为 `mysql`；`test_case_list.web` 是否与 `conf.ini` 的 `web` 一致；`isdel=1` |

**验证是否被读到**：

```bash
python main.py --collect-only
```

**另一个高发的「0 条选中」原因：`-k` 用了中文关键字**

```bash
python main.py -k 登录        # ❌ 静默 0 条（退出码 5，不报错）
python main.py -k id1001      # ✅ 按用例编号筛，两种数据源都适用
```

pytest 会把用例 id 里的非 ASCII 字符转义成 `\uXXXX`（`-k` 匹配的是转义后的 id），
所以中文关键字匹配不上任何用例。**筛选用例请用 ASCII**：

| 目的 | 命令 |
| --- | --- |
| 按用例编号 | `python main.py -k id1001`（Excel / YAML 均适用） |
| 按数据源 | `python main.py -m excel` / `-m yaml` |
| 按冒烟标签 | `python main.py --smoke` |
| 按英文类名/文件名 | `python main.py -k TestLoginFlow`、`-k login` |

### Q7 sheet 不存在

**现象**：

```
KeyError: sheet 不存在：test_case_list（当前可用：['Sheet1', 'Sheet2']）
```

**原因**：`conf.ini` 的 `run.sheet_name` 与实际 Excel 的 sheet 名不一致。

**解决**：把 `sheet_name` 改成报错信息里列出的名字，或修改 Excel 的 sheet 名。

### Q8 我写的 `test_xxx.py` 没被执行

**排查清单**：

| 检查项 | 要求 |
| --- | --- |
| 文件名 | 必须 `test_` 开头（`pytest.ini` 的 `python_files = test_*.py`） |
| 类名 | 必须 `Test` 开头 |
| 方法名 | 必须 `test` 开头 |
| 位置 | 必须在 `testcase/` 目录下（`testpaths = testcase`） |
| 是否被跳过 | 检查是否在 `legacy/` 等未收集目录 |

### Q9 中文输出乱码

**原因**：终端编码非 UTF-8。

**解决**（Windows）：

```bash
# Git Bash 临时设置
export PYTHONIOENCODING=utf-8
# 或 CMD
chcp 65001
```

写文件时统一用 UTF-8 编码；Excel/YAML 也要注意保存为 UTF-8。

### Q10 `--collect-only` 输出为空

**原因**：`testpaths = testcase` 未生效或目录不存在。

**解决**：

```bash
ls testcase/test_*.py                  # 确认文件存在
python -m pytest testcase --collect-only   # 显式指定路径
```

---

## 三、请求与网络

### Q11 `requests.exceptions.ConnectionError: ... NewConnectionError`

**现象**：日志中出现 `请求异常：GET http://... -> ...`

**原因**：目标服务不可达。

**排查顺序**：

1. 是否在公司内网 / 需要 VPN？
2. `base_url` 或用例 url 是否写对（域名 + 端口）
3. 端口是否正确（常见 9050 / 5050）
4. **本机是否配了系统代理？** 若目标是内网 / `127.0.0.1`，
   请求可能被转发给代理（典型表现是 502）。框架已自动绕过，仍失败见 [Q57](#q57-请求内网地址返回-502日志里看不出服务端信息)
5. 先做连通性测试：

```bash
python -c "
import socket
s = socket.socket(); s.settimeout(4)
try:
    s.connect(('192.0.2.10', 9050)); print('可达')
except Exception as e:
    print('不可达:', type(e).__name__)
"
```

### Q12 `requests.exceptions.ReadTimeout`

**原因**：服务响应慢于 `timeout` 配置。

**解决**：调大超时。

```ini
[run]
timeout = 30
```

内网环境或首次冷启动的服务建议设 30 以上。

### Q13 `SSLError: certificate verify failed`

**原因**：目标是 https 且使用自签证书时开启了校验。

**解决**：

```ini
[run]
verify = false
```

> 生产环境不建议长期关闭校验，建议导入受信 CA 证书。

### Q14 所有用例都失败，响应体是 HTML 页面

**原因**：请求打到了错误的地址（如网关、反向代理首页、端口写错）。

**排查**：

1. 看 Allure 报告的"响应体"附件，确认返回的是什么页面
2. 检查 `base_url` 与用例 `url` 拼接是否正确
3. 检查是否漏了端口号

---

## 四、数据与参数关联（最常踩坑）

### Q15 请求里出现了字面量 `${ticket}`

**现象**：响应报错提示 token 无效，或日志里请求头是 `access-ticket: ${ticket}`。

**原因**：变量池里没有 `ticket`，`safe_substitute` 保留了原样。

**排查清单**：

| 检查项 | 说明 |
| --- | --- |
| 上游用例是否执行 | 登录用例必须在依赖它的用例**之前**（Excel 行序 = 执行顺序） |
| `relation` 是否配置 | 登录用例的 `relation` 列要写 `ticket=body.data.ticket` |
| 路径是否写对 | 路径根是**完整响应**，响应体字段必须带 `body.` 前缀 |
| 变量名是否一致 | 提取的是 `ticket`，引用也必须是 `${ticket}` |
| 日志是否有 `【关联】` | 有这一行才说明提取成功 |

**定位命令**：

```bash
grep "【关联】" "log/$(date +%Y_%m_%d).log"
```

若没有输出，说明关联没成功，回到上面的检查项。

### Q16 关联提取到的值是 `None`

**原因**：路径写错。

**正确写法**（路径根为完整响应）：

| 目标 | 正确 | 错误 |
| --- | --- | --- |
| 响应体里的 ticket | `ticket=body.data.ticket` | `ticket=data.ticket`（少了 body） |
| 列表第一个元素 | `first=body.data.rows.0.name` | `first=body.data.rows[0].name`（方括号不支持） |
| 顶层字段 | `code=code` | `code=res.code` |

**快速验证路径**：

```bash
python -c "
import json
from common import base
res = {'code': 200, 'body': {'status': 200, 'data': {'ticket': 'abc'}}}
print(base.parse_expression('ticket=body.data.ticket', res))
"
```

### Q17 断言失败：`业务状态码不符：期望 200，实际 None`

**原因**：响应体里没有 `status` 字段，或响应体不是 JSON。

**排查**：

| 情况 | 表现 | 解决 |
| --- | --- | --- |
| 响应体是 HTML | 有报错页内容 | 地址打错了，见 Q14 |
| 业务码字段不叫 status | body 里有内容但无 status | 用 `check_business_code(expected, path="你的字段名")` |
| 响应体被截断 | body 异常短 | 看日志确认实际响应 |

### Q18 `${var}` 替换后类型变了

**现象**：原本是数字 `123`，替换后变成字符串 `"123"`。

**原因**：`Template` 的替换结果是字符串，框架在替换后重新 `json.loads` 还原。

**说明**：

- 对 **JSON 请求体**：无影响，`json.loads` 会把数字还原
- 对 **表单 / 非 JSON 场景**：可能变成字符串，需注意

若确实需要保持类型，建议不要把变量放在非 JSON 场景，
或在接口层做显式转换。

### Q19 多个用例用同一个变量名，值被覆盖

**原因**：`GlobalVar` 是全局的，同名 key 后写覆盖先写。

**解决**：关联变量名带业务前缀，如 `orderId`、`userId`、`ticket`，避免 `id`、`name` 这类通用名。

### Q20 单独跑某条用例时失败，全量跑就通过

**原因**：该用例依赖前面用例提取的变量，单独跑时变量池为空。

**解决**：这是数据驱动的已知特性。

- 调试时把依赖的用例一起跑：`python main.py -k "id1 or id3"`
- 或改用 PO 风格手写用例，把前置步骤写在同一个用例里（见 [04-开发指南 · 方式四](04-开发指南.md#35-方式四手写-po-风格用例推荐给复杂流程)）

---

## 五、结果回写

### Q21 Excel 结果列没有更新

**排查清单**：

| 检查项 | 说明 |
| --- | --- |
| `write_back` | `conf.ini` 中是否为 `true` |
| 执行是否完成 | 中途 Ctrl+C 可能未落盘（正常结束会落盘两次） |
| 文件是否被占用 | **用 Excel 打开着文件会导致保存失败** |
| 是否看错列 | 回写的是 B（time）、L（response）、M（ispass） |

**确认落盘成功的日志**：

```bash
grep "结果已回写 Excel" "log/$(date +%Y_%m_%d).log"
```

### Q22 PermissionError 文件被占用

**现象**：

```
PermissionError: [Errno 13] Permission denied: '...\data\api_tables.xlsx'
```

**原因**：`data/api_tables.xlsx` 正被 Excel 打开，Windows 下无法写入。

**解决**：关闭 Excel 后重跑。

### Q23 不想让框架改动 Excel

**解决**：

```ini
[run]
write_back = false
```

CI 环境建议保持 `false`。

---

## 六、报告

### Q24 Allure 报告打开是空白页

**原因**：直接双击 `index.html` 用 `file://` 协议打开。
Allure 报告通过 AJAX 加载数据，被浏览器安全策略拦截。

**解决**：

```bash
python tools/generate_report.py --open
```

它会用 `allure open` 起本地 HTTP 服务。

### Q25 提示 `[提示] Allure 报告渲染失败：...`

**原因**：未安装 allure CLI 或 Java。

**说明**：这是**预期行为**，不影响测试执行与断言。

**解决**：

```bash
allure --version      # 缺失则参考 Q5 安装
```

### Q26 报告里没有请求/响应附件

**原因**：未安装 `allure-pytest`，`ALLURE_AVAILABLE` 为 `False`。

**解决**：

```bash
pip install allure-pytest
```

**确认**：报告「环境」页的 `Allure可用` 字段应为 `True`。

### Q27 `report/allure-results` 是空的

**原因**：`report_type` 不是 `allure` 或 `both`。

**解决**：

```bash
python main.py --report allure
```

或改 `conf.ini`：

```ini
[report]
report_type = allure
```

### Q28 报告里显示的是旧数据 / 有重复用例

**原因**：`allure-results` 累积了历史数据，`--clean` 只会清 report 目录，
但生成命令本身带 `--clean`，正常不会重复。

**解决**：手工清空后重跑。

```bash
rm -rf report/allure-results report/allure-report
python main.py --report allure
```

> 清理 `report/` 是安全的，它只是产物目录，可随时重新生成。

### Q29 报告里看不到步骤树

**原因**：用例没有用 `with allure.step(...)` 包裹，或没安装 allure-pytest。

**解决**：参考 [04-开发指南 · 方式四](04-开发指南.md#35-方式四手写-po-风格用例推荐给复杂流程)
的写法补充步骤。

> 内置的 Excel/YAML 驱动**已自动带步骤**（执行请求 / 断言 / 回写），
> 只有手写用例需要自行添加。

---

## 七、MySQL 数据源

### Q30 SQL 驱动被跳过

**现象**：`SKIPPED: 当前数据源不是 mysql，跳过 SQL 驱动用例`

**原因**：`conf.ini` 的 `data_source` 不是 `mysql`。

**解决**：

```ini
[run]
data_source = mysql
```

或直接用 marker：`python main.py -m mysql`

### Q31 `2003, "Can't connect to MySQL server on '127.0.0.1'`

**原因**：数据库服务未启动或地址端口不对。

**解决**：

```bash
# 检查端口连通性
python -c "
import socket
s = socket.socket(); s.settimeout(3)
try:
    s.connect(('127.0.0.1', 3306)); print('可达')
except Exception as e:
    print('不可达:', type(e).__name__)
"
```

不可达则启动 MySQL 服务，或把 `conf.ini` 的 host/port 改为正确值。

### Q32 `1045, "Access denied for user 'root'@'...'`

**原因**：账号或密码错误。

**解决**：修正 `conf.ini` 的 `[db] user / password`。

### Q33 `1146, "Table 'xxx.test_case_list' doesn't exist"`

**原因**：数据库未建表。

**解决**：按 [02-操作手册 · MySQL 数据源](02-操作手册.md#91-启用步骤) 建三张表：
`test_case_list`、`test_config`、`test_result_record`。

### Q34 拼接出的地址不对

**规则**：`配置域名 + ':' + port_num + 用例 url`

**常见原因**：

| 现象 | 原因 |
| --- | --- |
| 地址里有双冒号 `::` | `test_config.value` 末尾带了 `:`，或 `port_num` 为空 |
| 域名是 `None` | `test_config` 里没有匹配 `web` + `environment` 的记录 |
| 拼接后多了斜杠 | 域名末尾带 `/` 且 url 以 `/` 开头（框架已做 rstrip 处理，若仍出现请检查数据） |

**验证**：

```bash
python -c "
from utils.readmysql import RdTestcase
repo = RdTestcase(web='gov')
print(repo.build_case_url({'url': '/v1/users/login', 'port_num': 9050}, base_url='http://192.0.2.10'))
"
```

### Q35 结果没有写入 `test_result_record`

**排查**：

- `write_back` 是否为 `true`
- 表结构字段名是否与 SQL 一致（`case_id` / `times` / `response` / `result`）
- 是否有数据库写权限（`sql_execute` 失败会记日志并返回 `False`，不会抛异常）

```bash
grep "SQL 执行失败" "log/$(date +%Y_%m_%d).log"
```

---

## 八、其他

### Q36 日志文件在哪，怎么调级别

**位置**：`log/YYYY_MM_DD.log`，按天切分（日期格式、文件名、格式串都可配）。

**调整级别**：改 `config/conf.ini` 的 `[log] level`（文件）与 `[log] console_level`（控制台），
或用环境变量临时覆盖：

```bash
AMSAPI_LOG_LEVEL=DEBUG AMSAPI_LOG_CONSOLE_LEVEL=DEBUG python main.py -k "id1"
```

`DEBUG` 可看到完整的 headers / params / 响应体。

> **日志会越写越大吗？** 不会。单文件达到 `[log] max_bytes`（默认 20MB）即轮转，
> 最多保留 `backup_count`（默认 5）份；`keep_days` 大于 0 时还会清理超过该天数的
> **框架自己生成**的历史日志（按 `file_name_format` 生成正则匹配，不会误删别人的文件）。
> 用 `AMSAPI_LOG_MAX_BYTES` / `AMSAPI_LOG_BACKUP_COUNT` / `AMSAPI_LOG_KEEP_DAYS` 可临时覆盖。
>
> 日志里的口令、令牌会显示为 `dem****rd` 这类形态 —— 见 [Q58](#q58-日志--报告里口令变成-demrd是不是脱敏出问题了)。

### Q37 `legacy/` 目录能删吗

可以。它保存了旧版本代码，仅作对照参考，**不参与测试执行**（`testpaths = testcase`）。

> 出于开源合规，`legacy/` 下的 `api_tables.原始备份.xlsx`（含真实业务数据）**已删除**。

### Q38 `venv/` 要不要提交到仓库

不建议。它体积大且与机器绑定。项目已提供 `.gitignore`，已屏蔽以下内容：

```
venv/
__pycache__/
*.pyc
.pytest_cache/
log/*.log
report/allure-results/
report/allure-report/
report/report.html
```

> 注意：`data/api_tables.xlsx` 是**用例数据，属于项目资产，必须入库**，
> 因此 `.gitignore` 中没有、也不应忽略 `data/` 目录。

### Q39 想快速验证框架本身是否正常（不影响真实数据）

```bash
# 1. 框架单元测试（离线，最彻底的框架自检）
python -m pytest tests -q

# 2. 只收集不执行
python main.py --collect-only

# 3. 不发请求、不改数据
python main.py -m "not network" --report none

# 4. 没有被测系统？起本地 mock 再跑（见下方 Q53）
python tools/mock_server.py
```

推荐优先用第 1 条：它是**离线**的，不连被测环境，10 秒给出「框架是否被改坏」的结论。
详见 [07-单元测试](07-单元测试.md)。

### Q40 单元测试失败了，怎么判断是框架问题还是测试问题

**先看断言信息**，再判断：

| 现象 | 多半是 | 处理 |
| --- | --- | --- |
| 断言值不符（如期望 `{"json": ...}` 实际 `None`） | 框架代码被改坏 | 修复代码；不要为了通过而改测试 |
| `ImportError` / 找不到模块 | 新增文件后未加 `__init__.py`，或运行目录不对 | 在项目根目录执行 `python -m pytest tests` |
| 依赖真实环境导致的失败 | 测试写错了（单元测试不应联网/连库） | 用 `FakeSession` / `FakePymysql` 替身，见 [07-单元测试 · 六条铁律](07-单元测试.md#五六条铁律) |
| 串测失败（单跑通过、全量失败） | 用例间状态未隔离 | 依赖 conftest 的 `isolate_state`，不要手写 `setUp` 清理 |
| 报「0 匹配 / 整体跳过」 | 冒烟环境变量影响了驱动模块加载 | 检查 `AMSAPI_SMOKE` / `AMSAPI_TAGS` |

> **原则**：单元测试是「框架行为的契约」。如果行为确实要改，应同步改测试并在
> `CHANGELOG.md` 说明；如果只是因为改代码导致测试不过，就改回去。

### Q41 单元测试会不会把 `data/api_tables.xlsx` 改坏

不会。所有 Excel 相关用例都在 `tmp_path` 生成的副本上执行，并有专门用例锁定该行为
（`test_readonly_run_does_not_touch_file`、`test_dirty_is_per_file`）。
实测跑完全部 **1134 条**用例后，`data/`、`config/conf.ini`、`report/` 的校验值完全不变。

---

## 九、系统适配（接别的 web 系统）

> 本节问题都出在**系统适配档案**上。完整字段说明见
> [08-系统适配指南](08-系统适配指南.md)。

### Q42 `ConfigError: 未找到系统适配档案 'xx'`

档案名写错或文件不存在。报错信息里会直接列出可用档案：

```
ConfigError: 未找到系统适配档案 'mal'。
  期望文件：config/systems/mal.ini
  可用档案：gov, dataplatform, default, finance_erp, mall
```

按列出的名字改，或用 `AMSAPI_SYSTEM=` 指定。要新增档案就
`cp config/systems/default.ini config/systems/xx.ini` 再改内容。

### Q43 换了一个系统后，所有用例的业务断言都失败

九成是**业务码字段名不一样**。先手工调一次接口，看响应长什么样，再改档案：

| 看到的响应 | 档案怎么改 |
| --- | --- |
| `{"code": 200, "msg": "ok"}` | `[response] style = code` |
| `{"success": true, "result": ...}` | `[response] style = success` |
| `{"errno": 0, "errmsg": ""}` | `[response] style = errno` |
| `{"retCode": "0000"}` | `[response] style = retcode` |
| 业务码在很怪的地方 | `[response] success_path = body.业务码路径` |

**不要**去改用例的 `expected_code` 硬凑，那是把系统差异写进了数据里，下次还会再踩。

### Q44 换了系统后全是 401 / 未认证

令牌的**位置或头名**和原来不一样，改 `[auth]` 段：

```ini
[auth]
type = header                  ; 不是标准 Bearer 就走自定义头
header = X-Auth-Token
token = ${token}               ; 令牌来自登录接口的关联提取
```

按令牌实际放的位置选 `type`，常见五种：

- **请求头**（`Authorization: Bearer xxx`）→ `type = bearer`
- **自定义请求头**（`X-Auth-Token: xxx`）→ `type = header`
- **API Key 风格**（`X-Api-Key: xxx`）→ `type = apikey` + `key_name = X-Api-Key`
- **放在 query 参数里**（`?token=xxx`）→ `type = apikey` + `key_in = query`
- **Cookie 会话**（`SESSION=xxx`）→ `type = cookie`

### Q45 系统返回 `{"success": true}`，`expected_code` 不知道填什么

用 `success` 风格，用例里**留空**即可，由档案的成功值集合判：

```ini
[response]
style = success
```

```yaml
- title: 商品列表
  url: /api/v1/items
  method: get
  # 不写 expected_code
```

### Q46 报错 `钩子工厂需要调用后才生效（漏写括号了）`

档案里 `[hooks]` 的声明漏了括号。工厂函数必须**调用后**才是钩子：

```ini
; ❌ 错
before_request = common.hooks:make_sign_hook
; ✅ 对
before_request = common.hooks:make_sign_hook()
before_request = common.hooks:make_sign_hook({"salt": "abc"})
```

### Q47 报错 `不支持的认证类型 'xxx'`

`[auth] type` 拼错。可用 7 种：`none`、`basic`、`bearer`、`header`、
`apikey`、`cookie`、`oauth2`（报错信息里也会列出来）。

### Q48 响应里的中文是乱码

档案里强制指定编码：

```ini
[env]
encoding = gbk          ; 政务/财务老系统常见，也可能是 gb2312
```

> 留空表示自动判断（推荐）。只有自动判断出错时才需要这一行。

### Q49 响应是 XML，字段断言写不出来

两步：

```ini
[env]
response_format = xml               ; 显式声明按 XML 解析（auto 不会去猜 XML）
[response]
success_path = body.response.status ; 业务码在 XML 的哪个标签里
```

XML 转成字典后，**最外层标签会成为一个键**：

```
<response><status>200</status></response>
        ↓
{"response": {"status": 200}}
```

所以断言路径是 `body.response.status`。属性用 `@属性名`、纯文本用 `#text`。

### Q50 分页抓不到数据 / 一直卡住

- **卡住**：服务端不翻页。已内置 `max_pages` 安全阀（默认 100），调小即可。
- **抓不到**：列表不在默认路径。手写用例传 `data_path=`，或档案里配
  `[response] data_path = body.data.items`。

```python
rows = api.paginate("/v1/list", size=100, max_pages=20,
                    data_path="body.result.rows")
```

### Q51 令牌 / 文件下载 / 健康检查接口不该判业务码，但框架判了

用 `check_business` 关掉业务断言（默认是开的）：

```yaml
- title: 取令牌
  url: /oauth/token
  method: post
  check_business: false
  relation: token=body.access_token
  expects: "exists:body.access_token"
```

Excel 用例则把 V 列 `check_business` 填 `0`。

### Q52 怎么确认这次跑的是哪套适配规则？

看两处（都不含凭证）：

```bash
# 日志开头
2026-09-27 10:10:10 | INFO | 【适配】加载系统档案：gov（党政/政务）
```

Allure 报告的「环境」页会展示：

```
系统档案 / 系统名称 / 主域名 / 域名别名 / 响应格式 / 响应编码 / 超时
判定风格 / 业务码路径 / 成功值集合 / 认证方式 / 请求前钩子 / 响应后钩子
```

排查适配问题时，先确认「报告上写的规则」与「你以为的规则」是否一致。

---

## 十、离线体验与开源约定

### Q53 我没有内网、也没有可访问的被测系统，能跑通这个框架吗？

能。仓库内置了一个**零外部依赖的本地 mock 服务**，把示例接口在你本机复刻出来：

```bash
# 终端 A：保持开着
python tools/mock_server.py            # 默认 127.0.0.1:18080

# 终端 B：把域名指过去，用示例用例跑一遍
AMSAPI_BASE_URL=http://127.0.0.1:18080 python main.py -m yaml
AMSAPI_BASE_URL=http://127.0.0.1:18080 python main.py -m excel
```

登录发票据、票据校验、分页、下单与清理（teardown）、OAuth2 取令牌、
XML / GBK 报文、签名校验都能走通。三套对照示例在 `examples/`：

| 目录 | 演示的系统类型 | 关键点 |
| --- | --- | --- |
| `examples/mall/` | 商城 / 购物 | `success` 判定 + teardown 清理 |
| `examples/dataplatform/` | 数据中台 | `code` 判定 + OAuth2 + 负向用例 |
| `examples/legacy/` | 老系统 | XML + GBK + 签名钩子 |

命令怎么写见 `examples/README.md`，完整 5 步见
[02-操作手册 · 2.6 不连内网也能跑通](02-操作手册.md#26-不连内网也能跑通离线体验)。

> 为什么命令里带 `-m yaml`：`data/api_tables.xlsx` 里的 Excel 示例是按 `status` 风格写的，
> 与 `mall`（`success`）/`dataplatform`（`code`）档案天然不匹配，改用 YAML 示例即可。

### Q54 这个框架有哪些配置项？我不想改代码就想换环境

**所有可变数据都在配置里**，按优先级 `环境变量 AMSAPI_*` > `config/conf.ini` > `settings.py` 默认值：

| 想改什么 | 改哪里 |
| --- | --- |
| 域名 / 超时 / 证书校验 | `AMSAPI_BASE_URL` / `AMSAPI_TIMEOUT` / `AMSAPI_VERIFY` |
| 数据源 / 用例文件 / 目录 | `AMSAPI_DATA_SOURCE` / `AMSAPI_EXCEL_FILE` / `AMSAPI_DATA_DIR` |
| 被测系统类型 | `AMSAPI_SYSTEM`（档案名）+ 档案里的每一项都能单独被 `AMSAPI_*` 覆盖 |
| 日志级别 / 格式 / 文件名 | `conf.ini [log]` 或 `AMSAPI_LOG_LEVEL` 等 |
| 报告标题 / 项目名 / 附件上限 | `conf.ini [report]` 或 `AMSAPI_REPORT_*` |
| OAuth2 续期提前量 / 取令牌超时 | `conf.ini [auth]` 或 `AMSAPI_OAUTH2_*` |
| 「是否在 CI 里」的判定变量 | `conf.ini [ci] detect_env_vars` |
| 数据库连接 | `conf.ini [db]` 或 `AMSAPI_DB_*` |

完整清单见 [README · 六、配置速查](../README.md) 与
[02-操作手册 · 3.5 其它可配置项](02-操作手册.md#35-其它可配置项日志--报告--认证--ci-判定)。

### Q55 我接手的是一套新环境，账号密码该写在哪？

**不要写进仓库文件**。两种做法：

```bash
# 本地临时用：环境变量（空字符串会被忽略，不会污染配置）
AMSAPI_DEMO_USER=my_user AMSAPI_DEMO_PASSWORD=my_pass python main.py

# CI 用：在流水线里注入，仓库只保留占位
AMSAPI_AUTH_CLIENT_SECRET=$ERP_SECRET
AMSAPI_DB_PASSWORD=$DB_PASSWORD
```

`conf.ini` 的 `[db]` 段在仓库里**全部留空**，`settings.DB_CONFIG["password"]` 断言为空 ——
这是开源前提，也由 `tests/test_repo_sanitized.py` 守住。

### Q56 我不小心把真实地址/账号写进代码了，怎么自查？

跑一次开源守卫：

```bash
python -m pytest tests/test_repo_sanitized.py -q
```

它会扫描全仓文本文件、`config/systems/*.ini` 和 `data/api_tables.xlsx`，
命中真实内网 IP、账号、口令摘要、签名值、系统代号等片段即失败。
替换约定（示例域名 / `192.0.2.10` / `demo_user` / 相对路径）见
[07-单元测试 · 铁律 4](07-单元测试.md#铁律-4不得写入真实环境信息开源守卫)。

---

## 十一、企业级加固（脱敏 / 代理 / 预检 / 清理失败）

> 本节四个问题都来自 2.5.0 的企业级加固，是「看起来像故障、其实是保护机制」的典型。

### Q57 请求内网地址返回 502，日志里看不出服务端信息

**现象**：请求 `127.0.0.1` / `10.x` / `192.168.x` 这类地址返回 502，
错误信息里没有任何业务线索。

**原因**：本机或企业环境注入了 `HTTP_PROXY` / `HTTPS_PROXY`，
而 `requests` 默认尊重代理环境变量 —— 于是**连本机与内网地址也被转发给了代理**。

**好消息**：框架 2.5.0 起会对环回与内网地址**自动绕过代理**，正常情况下不会再遇到。
若仍失败，按下面处理：

```bash
# 方式一：整个 session 不读系统代理与 CA 环境变量（内网专线场景）
AMSAPI_TRUST_ENV=false python main.py

# 方式二：追加需要绕过的域名（支持 *.corp 通配）
AMSAPI_BYPASS_HOSTS="*.corp,10.20.30.40" python main.py

# 方式三：传统做法，显式设置 NO_PROXY（框架内部已自动处理）
NO_PROXY=127.0.0.1,localhost python main.py
```

对应配置见 `config/conf.ini` 的 `[network]` 段，
说明见 [08-系统适配指南 · 4.9](08-系统适配指南.md#49-全局配置不属于档案mask-与-network)。

### Q58 日志 / 报告里口令变成 `dem****rd`，是不是脱敏出问题了

**不是问题，是保护机制在生效。**

框架 2.5.0 起**默认开启脱敏**（`partial` 模式：保留前 3 后 2），覆盖三处落盘路径：
日志（logging Filter）、Allure 附件（写入前）、报告目录（渲染后兜底）。

| 你看到 | 含义 |
| --- | --- |
| `password` → `dem****rd` | 值被部分打码，仍可人工比对前后缀 |
| `access-ticket` → `TK-****hr` | 同上 |
| 整个值变成一排 `*` | `[mask] mode = full`（全遮蔽） |

**要看原文**（仅本地调试，**切勿在 CI 上开**）：

```bash
AMSAPI_MASK_SENSITIVE=false python main.py -k id1 --report none
```

**某类字段没被脱敏**（如工号、身份证），在 `config/conf.ini` 补字段名：

```ini
[mask]
extra_keys = idcard,phone,emp_no
```

字段名匹配会先按驼峰 / 下划线 / 中划线**拆词**再比对，
所以 `design`、`tokenizer`、`passport` 这类词不会被误伤。

### Q59 会话结束打印「teardown 汇总」告警，要不要管

**要管，但它不一定是本次用例失败的原因。**

`teardown` 是用例的清理步骤（删除测试数据之类）。它抛异常时框架的处理是：

1. 该用例**不会**因此变红 —— 清理失败通常不改变「业务是否通过」的结论；
2. 框架把它**登记**下来，并在该用例的 Allure 里留痕；
3. 整个会话结束时汇总打印：

```
[警告] 本次有 2 条用例的 teardown 失败，可能留下脏数据：id2003, id2007
```

**怎么处理**：按告警里的 case_id，到日志里搜 `teardown 失败` 看具体异常。
常见原因是「清理接口参数不对」或「数据已被他人删除」。
确认可忽略时，去掉该用例的 `teardown` 即可。

### Q60 `python tools/preflight.py` 是干什么的，输出怎么读

**作用**：在执行用例**之前**先把环境问题暴露出来，
避免把「环境坏了」误判成「业务失败了」。

检查项：Python 版本 / 必需与可选依赖 / 生效配置 / 用例数据可读性 /
可写目录 / 系统代理 / 目标连通性。

**输出分三档**：

| 档位 | 含义 | 处理 |
| --- | --- | --- |
| `[错误]` | 会导致根本跑不起来（数据文件不存在、目录不可写…） | **必须先修** |
| `[警告]` | 会降级但不影响已有功能（如可选依赖 `jsonschema` 未装） | 按需处理 |
| `[提示]` | 纯信息（Python 版本、生效档案、可执行用例条数） | 不用管 |

```bash
python tools/preflight.py                 # 常规预检
python tools/preflight.py --no-target     # 跳过目标连通性检测（手里没有被测环境时）
python tools/preflight.py --strict        # 有警告也返回非 0（把警告纳入门禁）
python tools/preflight.py --json          # 机器可读输出（给流水线解析）
```

退出码：`0` = 无错误；非 `0` = 有错误（或 `--strict` 下存在警告）。

---

## 十二、通用排错流程

按这个顺序走，80% 的问题能在第 3 步定位。

```
第 0 步：先做环境预检（把环境问题与业务失败分开）
         python tools/preflight.py
         └─ 有 [错误]？ → 先修环境，别急着怀疑用例（见 Q60）
         └─ 只有 [提示]？ → 环境没问题，继续往下

第 1 步：看终端最后几行
         └─ 有 "passed/failed" 汇总？ → 用例在跑，是断言/数据问题 → 第 3 步
         └─ 直接报异常栈？           → 看异常类型，回本文对应章节

第 2 步：确认用例被收集到
         python main.py --collect-only
         └─ 目标用例不在列表里 → 见 Q6 / Q7 / Q8

第 3 步：看 Allure 报告
         找到失败用例 → 看哪一步红了 → 展开"响应体"附件
         └─ 响应体为空/HTML → 网络或地址问题 → 第三节
         └─ 响应体正常但断言值不对 → 数据/关联问题 → 第四节

第 4 步：看日志
         grep -E "【请求】|【关联】|<== |请求异常" "log/$(date +%Y_%m_%d).log"
         └─ 确认请求地址、变量替换结果、响应耗时
         └─ 末尾有「teardown 汇总」告警？ → 见 Q59

第 5 步：缩小范围
         python main.py -k "id<用例编号>" --report none
```

### 提问模板

若以上都没解决，提问时请附上：

```
1. 执行的完整命令
2. 报错信息（完整栈）
3. 相关日志片段（log/ 下当天文件的对应部分）
4. conf.ini 的关键配置（隐去密码）
5. 是必现还是偶现
```

---

## 十三、快速索引

| 关键词 | 跳转 |
| --- | --- |
| ModuleNotFoundError | [Q1–Q4](#一环境与安装) |
| allure command not found | [Q5](#q5-allure-command-not-found) |
| 用例被跳过 skipped | [Q6](#q6-一条用例都没跑显示-skipped) |
| sheet 不存在 | [Q7](#q7-sheet-不存在) |
| 用例没被执行 | [Q8](#q8-我写的-test_xxxpy-没被执行) |
| ConnectionError / 超时 | [Q11](#q11-requestsexceptionsconnectionerror--newconnectionerror)、[Q12](#q12-requestsexceptionsreadtimeout) |
| `${ticket}` 未替换 | [Q15](#q15-请求里出现了字面量-ticket) |
| 关联取到 None | [Q16](#q16-关联提取到的值是-none) |
| 业务状态码断言失败 | [Q17](#q17-断言失败业务状态码不符期望-200实际-none) |
| Excel 没回写 | [Q21](#q21-excel-结果列没有更新) |
| Excel 被占用 | [Q22](#q22-permissionerror-文件被占用) |
| Allure 空白页 | [Q24](#q24-allure-报告打开是空白页) |
| 报告没附件 | [Q26](#q26-报告里没有请求响应附件) |
| MySQL 连不上 | [Q30–Q34](#七mysql-数据源) |
| 框架自检 / 单元测试失败 | [Q39–Q41](#q39-想快速验证框架本身是否正常不影响真实数据) |
| 没有内网 / 没有被测系统怎么跑 | [Q53](#q53-我没有内网也没有可访问的被测系统能跑通这个框架吗) |
| 有哪些配置项 / 怎么换环境 | [Q54](#q54-这个框架有哪些配置项我不想改代码就想换环境) |
| 账号密码该写在哪 | [Q55](#q55-我接手的是一套新环境账号密码该写在哪) |
| 怎么自查硬编码 / 开源合规 | [Q56](#q56-我不小心把真实地址账号写进代码了怎么自查) |
| 内网请求 502 / 被系统代理拦截 | [Q57](#q57-请求内网地址返回-502日志里看不出服务端信息) |
| 日志里口令被打码（`dem****rd`） | [Q58](#q58-日志--报告里口令变成-demrd是不是脱敏出问题了) |
| 会话结束的「teardown 汇总」告警 | [Q59](#q59-会话结束打印teardown-汇总告警要不要管) |
| 环境预检 `preflight.py` | [Q60](#q60-python-toolspreflightpy-是干什么的输出怎么读) |
