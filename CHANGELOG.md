# 变更记录

本文件记录框架的重要变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

---

## [未发布]

### 修复（功能验收发现的问题）

> 来源：对框架做完整功能验收（1134 条自测 + 18 条端到端链路 + 22 项专项检查 +
> 6 项异常输入探针 + 浏览器渲染验证）定位到 3 个缺陷与 2 个观察项。以下为修复记录。
> **其中 2 项会改变存量用例的结论**，已单列为「行为变更」。

#### D1【高危】Excel 数据源的明文口令会漏进 Allure 报告

- **现象**：YAML 链路下报告里的口令是 `dem****rd`；换到 Excel 链路就是 `demo_password` 明文。
- **根因**：Excel 的 `request_body` 是 JSON **字符串**，repr 之后形如
  `'request_body': '{"username": "demo_user", "password": "demo_password"}'`。
  `common/mask.py` 的正则 `'[^']*'` 会把这整段当成 `request_body` 的一个值 ——
  而 `request_body` 不是敏感词，于是内层的 `password` 再没有机会被检查。
  YAML 的 `request_body` 是 dict（键值对平铺），不触发该形态，所以问题长期未被发现。
- **修复**（`common/mask.py`）：
  - 新增 `_balanced_spans()` / `_mask_children()`：值内部如果仍是 `{}` / `[]` 结构，
    继续往里下钻脱敏（深度上限 4），并把结果原位拼回
  - 已含 `****` 的值直接跳过，保证**幂等** —— `sanitize_dir()` 对同一文件会跑多次
  - 顺带修复既有小缺陷：`Bearer <token>` 打码后空格被吃掉（输出成 `Bearerabc****56`）
- **验证**：Excel 链路全链路跑完，`report/allure-results` 与 `report/report.html` 均
  `grep` 不到明文，Allure 中出现 `dem****rd`；新增 9 条单测。

#### D2【中】漏填 `expected_code` 会假绿

- **现象**：`status` 风格用例没写 `expected_code` 时，框架退化为「HTTP 200 即成功」。
  被测接口业务失败也返回 HTTP 200（mock 下 `body.status = 401`），于是用例被判**通过**，
  日志里只留一行 WARNING。**断言其实根本没执行，看起来却像功能正常。**
- **修复**（`common/response.py`）：改为 fail-closed ——
  用例没给 `expected_code`、档案也没配 `success_values` 时直接判失败，
  错误信息同时给出三种修法（补期望值 / 配成功值集合 / 置 `check_business: false`）。
  `raw` 风格不受影响（它本来就只判 HTTP）。分页抓取这类无用例上下文的内部调用
  显式传 `strict=False`。
- **逃生舱**：档案 `[response] require_expected = false` 可退回旧行为（仍告警一次），
  用于存量系统过渡。

#### D3【低】pytest-html 报告里的中文用例名是 `\u767b\u5f55`

- **根因**：pytest 要求 nodeid 是 ASCII 安全，`parametrize(ids=<中文>)` 会被转义成
  `\u767b\u5f55`；pytest-html 直接把 nodeid 展示出来，报告里就成了转义串。
- **修复**（新增 `utils/htmlreport.py`）：报告落盘后把数据区的 `\\uXXXX` 还原成真实字符。
  只还原码点 ≥ 0x80 的字符 —— 还原 `\u0022` / `\u005c` 会破坏 JSON 结构。
  不改 nodeid 本身，因此 `-k id1001` 这类按编号筛选仍然可用。
- **时序**：修复动作挂在 `pytest_unconfigure`，而不是 `pytest_sessionfinish` ——
  pytest-html / allure-pytest 也在 sessionfinish 写文件，同级 hook 顺序取决于插件注册顺序，
  早一步就会扫到还没生成的文件（D1 的明文残留就有一部分是这个原因）。
  脱敏同样从 sessionfinish 移到此处。

#### 观察项一并修复

- **引用未定义 `${var}` 静默变空串** → 改为严格模式（`common/base.py`）：
  未定义变量直接判失败，错误信息列出变量名与当前变量池内容，并提示排查方向
  （拼写 / 依赖用例是否通过 / setup 是否成功）。`[run] strict_variable = false` 可退回旧行为。
- **空用例 / 缺 url / 缺 method 报错指向错** → `BaseApi._validate_case()` 在发请求前拦截，
  直接指出「Excel 哪一列 / YAML 哪个字段」没填。旧行为是在断言阶段以
  「业务断言失败」或 `int(None)` 的 TypeError 收场。

### 行为变更（升级需知）

| 场景 | 旧行为 | 新行为 | 恢复旧行为的方式 |
| --- | --- | --- | --- |
| `status` / `code` 风格未写 `expected_code`，档案也无 `success_values` | 只看 HTTP 状态码，**可能假绿** | 判失败，指出缺 `expected_code` | 档案 `require_expected = false`；或单条用例 `check_business: false` |
| 用例引用未定义的 `${var}` | 替换为空串后照常发请求 | 判失败，列出变量名 | `[run] strict_variable = false` |
| `sanitize_dir()` 对同一文件重复执行 | 可能二次打码、越改越长 | 幂等（已打码的值跳过） | — |

迁移检查清单：

1. 跑一遍存量用例，把报 `用例缺少 expected_code` 的用例补上期望值（推荐），
   或确属「不做业务断言」时改成 `check_business: false`；
2. 报 `用例引用了未定义变量` 的用例，检查变量名拼写与依赖顺序（`depends` / `relation`）；
3. 报告表格里的用例名会显示为中文（`\u767b\u5f55` → `登录`），属预期变化。

---

本版本主题：**去硬编码 / 开源合规 / 离线可体验**。
三类改动：①把散落在代码里的可变数据全部收进配置中心；②删除测试过程产生的真实业务数据；
③内置 mock 服务与示例用例，让**没有被测系统、没有内网**的人也能完整跑通框架链路。

### 变更（去硬编码：所有数据动态获取、可配置）

- **`config/settings.py` 扩展为唯一配置入口**，新增 4 个配置分组，全部可被 `AMSAPI_*` 覆盖：
  - `LogConfig`：日志级别 / 控制台级别 / 文件名日期格式 / 格式串 / 日期格式 / logger 名，
    另提供 `file_name()` 生成当天文件名
  - `ReportConfig`：`TITLE` / `PROJECT` / `HTML_NAME` / `MAX_ATTACH_LEN`，另提供 `html_path()`
  - `AuthConfig`：OAuth2 令牌 `REFRESH_AHEAD` / `TOKEN_TIMEOUT` / `TOKEN_VERIFY`
  - `CIConfig`：`DETECT_ENV_VARS`（CI 环境判定变量清单，默认 7 个）
- **`config/conf.ini` 新增 `[log]` / `[report]` / `[auth]` / `[ci]` 四段**，
  与 `[env]` / `[run]` / `[db]` 一起构成完整配置面；文件顶部注明「不预置任何真实地址/账号/密码/密钥」
- **新增 10 个环境变量**：`AMSAPI_LOG_LEVEL` `AMSAPI_LOG_CONSOLE_LEVEL` `AMSAPI_LOG_ROOT_NAME`
  `AMSAPI_REPORT_TITLE` `AMSAPI_REPORT_PROJECT` `AMSAPI_REPORT_HTML_NAME` `AMSAPI_ALLURE_MAX_ATTACH_LEN`
  `AMSAPI_OAUTH2_REFRESH_AHEAD` `AMSAPI_OAUTH2_TOKEN_TIMEOUT` `AMSAPI_OAUTH2_TOKEN_VERIFY`
- **系统档案每一项都可被环境变量覆盖**（`common/profile.py` 新增 `env_value()`）：
  `AMSAPI_ENCODING` / `AMSAPI_RESPONSE_FORMAT` / `AMSAPI_CONTENT_TYPE` / `AMSAPI_HOST_<别名>` /
  `AMSAPI_AUTH_<字段>` / `AMSAPI_HOOKS_BEFORE_REQUEST` / `AMSAPI_HOOKS_AFTER_REQUEST`
- **源码去硬编码**：`utils/logutil.py`（级别/格式/文件名/logger 名，文件 handler 创建失败自动降级为仅控制台）、
  `utils/allureutil.py`（附件截断长度）、`common/auth.py`（续期提前量/超时/证书校验）、
  `main.py`（CI 判定变量清单、HTML 报告文件名、横幅标题）、`testcase/conftest.py`（报告标题与项目名）
- **`configparser` 插值陷阱修复**：凡会读到含 `%`（如 `%Y_%m_%d`）或 `${}` 的 INI，
  统一使用 `ConfigParser(interpolation=None)`（`settings.py` / `read_config.py` / `profile.py`），
  并补单测锁死该行为
- **配置优先级链明确为**：环境变量 `AMSAPI_*` > `config/conf.ini` > `settings.py` 默认值；
  空字符串视为「未设置」，不会覆盖已有值

### 移除（开源合规：清理测试过程产生的真实数据）

- 删除 `log/` 下 5 个历史运行日志（含真实姓名、手机号、ticket、内网 IP）
- 删除 `legacy/api_tables.原始备份.xlsx`（含完整真实业务数据的备份）
- 删除 `data/api_tables.xlsx` 中的历史 `test` sheet（含真实请求/响应报文），
  仅保留 `test_case_list` / `test_config` / `test_result_record` 三张结构表
- `config/systems/` 下原以**真实系统代号命名**的政务档案 → **`gov.ini`**
  （档案名中性化，注释保留全部政务特征说明；`AMSAPI_SYSTEM=gov` 即可加载）
- 全仓真实环境信息脱敏：内网 IP → RFC 5737 文档网段 `192.0.2.10`；真实账号 / 口令摘要 / 签名值 /
  应用编码 / 组织编码 → 通用示例值（`demo_user` / `demo_password_hash` / `demo-admin` / `demo-org` …）；
  示例域名 → `*.example.com`
- **`[db]` 段全部留空**（`host` / `user` / `password` / `database` / `web` / `environment`），
  `settings.DB_CONFIG` 同步清空，仓库内**不含任何可用凭据**
- 示例用例 url 全部改为**相对路径**，真实域名由 `AMSAPI_BASE_URL` 或系统档案提供

### 新增（离线可体验：没有被测系统也能跑通）

- **`tools/mock_server.py`**：零外部依赖的本地 mock 服务（`ThreadingHTTPServer`），
  13 个接口复刻政务 / 商城 / 中台 / XML / GBK / 签名等场景
  （登录取票据、票据校验、组织树分页、字典、商品、下单与取消、数据源列表、ETL 触发、
  OAuth2 取令牌、XML 报文、GBK 报文、签名校验），默认 `127.0.0.1:18080`；
  内置 `sign_sorted()` 与 `common/hooks.py` 同算法，可直接验证签名钩子
- **`examples/`** 三套对照示例 + `README.md`（可复制命令、差异对照表、`-m yaml` 说明）：
  `mall`（`success` 判定 + teardown 清理）/ `dataplatform`（`code` 判定 + OAuth2 + 负向用例）/
  `legacy`（XML + GBK + 签名）
- **`data/api_tables.xlsx` 重建**为 5 条通用示例（相对路径，含依赖与跳过演示），
  列结构补齐到 A~V 22 列（P~V 为可选扩展列），并清空历史 `response` / `ispass` 残留
- **`tests/test_repo_sanitized.py`**：开源合规守卫（全仓文本扫描 + Excel 扫描 + 档案扫描 +
  「示例用例必须相对路径」「`DB_CONFIG` 不得有密码」），黑名单关键字采用片段拼接，
  避免守卫代码自身命中规则
- **`docs/02-操作手册.md`** 新增 2.6 节「不连内网也能跑通（离线体验）」与 3.5 节
  「其它可配置项（日志 / 报告 / 认证 / CI 判定）」；
  **`docs/00-新手完整指引.md`** 步进流程改为先起 mock 再跑用例；
  **`README.md`** 新增十二「离线体验与开源约束」，配置速查改写为 7 段完整版
- **`docs/00-新手完整指引.md`**（上一轮交付）：面向新人的**单一入口文档**，一份走完五件事 ——
  「从哪个文件开始看（含 9 步代码阅读顺序与按角色的阅读路线）→ 怎么编写用例（Excel/YAML/MySQL/手写四种方式）
  → 怎么执行用例（命令、筛选、报告、日志、退出码）→ 怎么接入 Jenkins（三步接入 + Jenkinsfile 阶段解读 +
  构建参数 + 部署后自动触发）→ 怎么接入 CI/CD 流水线（GitLab CI / GitHub Actions 完整配置）」，
  另含「新人最容易踩的 10 个坑」「第一天 Checklist」「一页速查卡」；
  `README.md` 文档导航将其列为**第一入口**

### 修复（端到端全面功能验证：发现问题就地修复）

一次覆盖「单测 + 6 类系统链路 + 能力矩阵 + 边界容错」的全量功能验证，共发现并修复 7 处问题：

- **`testcase/test_yaml_driver.py`：`-k` 按用例编号筛选在 YAML 驱动下不可用**
  —— YAML 驱动的参数化 id 原来是 `login.yaml::登录并提取票据`，没有 ASCII 锚点。
  而 pytest 会把 nodeid 里的非 ASCII 字符转义成 `\uXXXX`，因此 `python main.py -k 登录`
  **静默选中 0 条用例**（不报错、退出码 5），`-k id1001` 也无从下手。
  改为 `id1001[login.yaml::登录并提取票据]`，与 Excel 驱动（`id3[权限查询]`）写法统一，
  `-k id<编号>` 在两种数据源下都能稳定筛选用例；并补 1 条单测锁死该锚点

- **`main.py`：`--report html|both` 第二次执行必然失败（退出码 4）**
  —— 报告参数原写成分离式 `--html <路径>`。pytest 在 `_initini` 阶段解析命令行时
  pytest-html 的 `--html` 选项尚未注册，该「路径」被 argparse 当成**位置参数（用例路径）**；
  本框架的用例目录靠 `pytest.ini` 的 `testpaths` 定位，命令行本不带位置参数，于是：
  首次运行（`report.html` 不存在）正常，第二次运行（文件已存在）该路径成为收集入口 →
  `rootdir` 上翻到公共父目录（实测 `rootdir: C:\Users`）、`pytest.ini` 失效、
  收集范围扩到整棵上层目录（实测 `collected 1001 items`），最终 `UsageError` 退出。
  改为等号连写 `--html=<路径>`（单 token，不产生位置参数），并新增
  `tests/test_main_entry.py::TestHtmlArgForm` 4 条回归用例锁死该写法
- **`tests/conftest.py`：单测被 `AMSAPI_*` 环境变量污染，CI 下必红**
  —— `settings.py` 的路径常量在模块导入时定型，CI 注入 `AMSAPI_BASE_URL` / `AMSAPI_LOG_DIR`
  会使断言框架默认行为的单测失败（本地全绿、流水线 9 条红）。现在在 `from config import settings`
  **之前**摘除全部 `AMSAPI_*`，会话结束（`pytest_unconfigure`）再还原；
  同时把单测日志/报告强制指向 `%TEMP%\amsapi-unittest-artifacts\`，保证**零污染仓库**
- **`utils/yamlutil.py`：YAML `depends` 跨文件失效**
  —— `read_cases()` 按文件名字母序加载，`admin.yaml`（`depends: 1001`）排在 `login.yaml` 之前，
  导致 2 条依赖用例被整体跳过（表现为 `3 passed / 2 skipped`）。新增 `_order_by_depends()`
  做稳定重排，保证「被依赖者一定排在依赖者之前」，循环依赖则告警并退回原文件顺序
- **`testcase/conftest.py`：`data_source` 配置形同虚设**
  —— `data_source = excel` 时 YAML 驱动仍会执行（只有 mysql 驱动判了开关）。
  新增 `pytest_collection_modifyitems` 按数据源过滤；`-m` / `-k` 优先于配置；
  非法取值直接 `pytest.UsageError` 并列出可选值。配套 `settings` 新增
  `VALID_DATA_SOURCES` / `DATA_SOURCE_MARKERS` / `resolve_data_source()` / `data_source_marker()`
- **MySQL 未配置时甩出 `pymysql` 连接裸栈**
  —— 新增 `utils/mysqlutil.validate_db_config()`（缺 `host`/`user`/`database` 时给出
  `conf.ini [db]` 与 `AMSAPI_DB_*` 两项可操作指引），由真实使用方 `utils/readmysql.RdTestcase`
  在自建连接前调用；`testcase/test_sql_driver.py` 前置 `pytest.skip` 给出清晰跳过原因。
  校验函数刻意**不放进** `MysqlUtil.connect()` —— 低层封装允许用不完整配置验证连接机制，
  「配置填没填全」是配置层职责
- **Excel 用例文件缺失时 collection 崩溃（退出码 2）**
  —— `utils/excelutil.py` 的 `_load()` 前置 `os.path.isfile` 判断并抛 `ConfigError`，
  信息含 `AMSAPI_EXCEL_FILE` / `AMSAPI_DATA_DIR` 指引

### 新增（新手用例编写模板）

- **`docs/09-用例编写模板.md`**：面向新手的**填空式**用例编写模板，两种数据源各一套，
  覆盖「登录取票 → 带依赖 → 参数关联 → 断言 → 后置清理」完整链路，并附栏位速查表、
  21 种断言算子清单、`depends` 排序规则、常见错误对照表
- **`examples/template/`**：可直接复制的模板文件
  `api_tables_模板.xlsx`（含列说明行与示例行）/ `demo.yaml`（YAML 模板）/ `README.md`（使用步骤）

### 验证

- 框架单元测试：**978 passed / 15 skipped / 0 failed**（约 4.6 秒，全离线）
- 端到端 3 个批次共 **59 项**检查：批次 A 19 项（单测 / Excel / YAML+关联 / 冒烟 / `-k` 筛选 /
  商城档案 + teardown / 中台 + OAuth2 / 老系统 XML+GBK+签名 / 报告与退出码 / 仓库只读）、
  批次 B 11 项（7 种请求方法 / 21 种断言 + 负向 / 6 种响应风格 / 4 种认证 / 域名别名 4 种写法 / 分页）、
  批次 C 20 项（配置优先级 6 项 / `data_source` 生效 5 项 / 容错提示 3 项 / 协议钩子 2 项 / CI 判定 4 项）
- 离线端到端 6 条链路全 PASS（默认档案 YAML / Excel、商城、中台、老系统 XML+GBK+签名、冒烟筛选），
  全程用 `AMSAPI_*` 重定向到临时目录，仓库 `data/` 文件**时间戳与大小完全未变**

### 新增（企业级加固：面向企业级自动化测试的 10 项补齐）

一次针对「是否适合企业级自动化测试」的全面体检，发现 10 处不达企业级标准的短板并全部落地修复
（其中第 10 项是端到端复核阶段才扫出来的漏网路径）：

**1. 敏感信息明文落盘（最高危）→ `common/mask.py` + 三处接入**

- 实测证据：日志与 `report/allure-results/*.txt` 中出现 `password` 明文、
  `access-ticket: TK-...` 明文、`【关联】ticket = TK-...` 明文。
  日志与报告会随构建制品归档、被转发，**明文即等同口令外泄**。
- 新增 `common/mask.py`（275 行）：按**字段名**识别敏感键（`password` / `token` / `ticket` /
  `authorization` / `secret` / `sign` / `cookie` …），支持驼峰/下划线/中划线拆词，
  刻意避免 `design` / `tokenizer` 这类误伤；值支持 `partial`（前 3 后 2 + `****`）与 `full` 两种打码；
  同时处理结构化 dict（`mask_mapping`，递归且**保持结构不变**）与纯文本（`mask_text`，
  覆盖 `{'k': 'v'}` 的 repr 与 JSON）；内置 `Bearer/Basic/Token <值>` 令牌正则（修掉了
  「只打码方案名 Bearer、真令牌原样泄漏」的缺陷）。
- 三处接入：`utils/logutil.py` 的 `SensitiveFilter`（挂在 logger 上，
  handler 数量不变，既有断言不受影响）、`utils/allureutil.py` 的
  `attach_text/attach_json/attach_request/attach_response`（**写入前**打码）、
  `common/variable.py` 的变量池对外展示。
- 开关与模式配置化：`[log] mask_sensitive`、`[mask] mode / keep_prefix / keep_suffix / extra_keys`。

**2. 内网直连被系统代理拦截 → `utils/requestsutil.py` 自动绕过**

- 实测现象：沙箱注入 `HTTP_PROXY=http://127.0.0.1:52137`，`requests` 默认尊重代理，
  连 `127.0.0.1:18080` 的 mock 也被转发给代理，报出**指不到根因的 502**
  （`upstream connect failed: 目标计算机积极拒绝`）。这在 Windows 办公网/CI 机器上普遍存在。
- 新增 `is_internal_host()` / `host_matches()` / `RequestSend.proxies_for()`：
  对环回（`localhost` / `127.0.0.1` / `::1`）、私网 A/B/C 类（`10.` / `172.16-31.` / `192.168.`）、
  `169.254.`、`.local` / `.internal` / `.corp` / `.lan` 等一律 `{"http": None, "https": None}` 绕过。
- 配置化：`[network] trust_env / auto_bypass_proxy / bypass_hosts`。

**3. 合规守卫存在盲区 → `tests/test_repo_sanitized.py` 扩展**

- 旧版只扫 `settings.CONF_FILE`（即 `conf.ini`），导致 `config/conf.ci.ini` 里的
  `password = 123456`、`host = 127.0.0.1`、`user = root`、`database = api_test`、
  `web = gov`、`environment = 139` **完全没被守到**。
- 现在扫描 `config/**/*.ini` 全部文件：`password` 字段不得有值、不得出现弱口令、
  `[db]` 的 `host/user/database/web/environment` 必须为空。
- `config/conf.ci.ini` 同步清空敏感项，并新增 `[log] console_level=INFO` + `[mask] mode=full`
  （CI 制品对外，用 full 全遮蔽）。

**4. teardown 失败被静默吞掉 → `api/base_api.py` 登记 + 会话收尾汇总**

- 原实现只在 teardown 异常时 `logger.error` 一行，报告里**看不出用例其实是「带脏数据通过」的**。
- 新增 `TEARDOWN_FAIL_PREFIX` 常量、`BaseApi.teardown_errors` 列表与 `teardown_failed` 属性；
  失败时登记到 `GlobalVar`（跨用例可查）+ 由 `pytest_sessionfinish` 汇总告警 +
  三个驱动（excel/yaml/sql）在报告中 attach 痕迹。

**5. 报告无法回答「跑的是哪次提交」→ `common/metadata.py` 写入 Allure 环境页**

- 新增 `git_info()`（`git rev-parse` / `status`，失败安全返回 `{}`）、`ci_info()`
  （`BUILD_NUMBER` / `GITLAB_CI_PIPELINE_ID` / `GITHUB_RUN_NUMBER` …）、
  `dependency_versions()`（`importlib.metadata`）、`runtime_info()`，带缓存；
  键名用中文（`Git 提交` / `构建号` / `运行位置`）直接进 Allure「环境」页，
  并由 `testcase/conftest.py` 的 `env_info` 注入。

**6. 单文件日志无限增长、历史日志堆积 → 轮转 + 保留策略**

- `utils/logutil.py` 新增 `RotatingFileHandler`（`max_bytes` / `backup_count`）与
  `_cleanup_old_logs()`（按 `file_name_format` 生成正则，**只删框架自己生成的按天日志**，
  `keep_days <= 0` 时不删任何文件）。
- 配置：`[log] max_bytes / backup_count / keep_days`。一次全量回归可能产生上百 MB 日志，
  单文件既难打开也难归档。

**7. 环境问题伪装成业务失败 → `tools/preflight.py` 环境预检**

- 三档输出（错误 / 警告 / 提示），检查项：Python 版本、依赖（必需 + 可选，缺失给出影响与安装命令）、
  运行配置、用例数据、可写目录、代理、目标连通性。
- `--no-target`（跳过连通性）/ `--strict`（警告也非 0 退出）/ `--json`。
  `pytest.ini` 前置挂到 `main.py` 启动流程。

**8. 依赖无上限、无锁、无静态检查 → 版本约束 + 开发依赖 + lint 配置**

- `requirements.txt` 全部加上限约束（如 `pytest>=7.0,<10`），移除 `pytest-cov`
  （迁移到 `requirements-dev.txt`）。
- 新增 `requirements-dev.txt`：flake8 / pytest-cov / xdist / rerunfailures / timeout /
  jsonschema / cryptography。
- 新增 `.flake8`（`max-line-length=120`，忽略 E203/W503/E731/E741，排除 legacy/venv）
  与 `pyproject.toml`（只放 `[tool.coverage.*]`，pytest 配置仍留在 `pytest.ini`）。
- 端到端跑通 `flake8 .` → **0 问题**（原 14 个：`common/hooks.py` 缩进、
  `tests/test_api_base_api.py` 3×E128 + W391、`tests/test_utils_allureutil.py` F841、
  `tests/test_utils_excelutil.py` 未用 import、`tests/test_utils_requestsutil.py` E128、
  `tools/mock_server.py` 未用 import + E127）。

**9. CI 门禁偏弱 → `Jenkinsfile` 强化**

- 新增 `静态检查`（flake8）与 `环境预检`（`tools/preflight.py`）两个 stage，
  置于单测之前，快速失败。
- 新增 `COVERAGE_MIN` / `RETRIES` / `PARALLEL` 构建参数；`pluginArgs()` 辅助函数统一拼装
  `-n`（xdist 并行）与 `--reruns`（抖动重试）；覆盖率低于门槛即构建失败；归档范围扩展。

**10. 脱敏仍有两条漏网路径（端到端复核时发现）→ 修正则 + 新增落盘后兜底**

前一轮的脱敏只覆盖了「框架自己写出去」的内容，端到端实测仍在制品里扫到明文，
暴露出两条绕过路径 —— 都已修复：

- **路径 A：URL 查询串里的口令**。
  `.../login?username=demo_user&password=demo_password` 这类**请求地址**被整体打印时，
  文本脱敏正则的「值」字符集能吃掉 `&`，于是
  `username=demo_user&password=demo_password` 被当成一个值挂在**非敏感的 `username`** 名下，
  真正的口令整条漏过（日志与 Allure 的「响应信息」附件都能看到明文）。
  修复：`_KV_RE` 的值字符集排除 URL 分隔符 `? & #`（并补 2 条单测锁死该形态）。
- **路径 B：Allure 插件直接落盘的 `parametrize` 参数**。
  框架用 `@pytest.mark.parametrize("case", CASES)` 传整条用例数据，
  Allure 官方 pytest 插件会把**每个参数**自动写成报告参数，于是 `result.json` 里出现
  `"parameters": [{"name": "case", "value": "{'password': 'demo_password'}"}]`。
  这条路径由第三方插件直接写文件，不经过框架的 `attach_*`，写入时脱敏无法拦截。
  修复：新增 `mask.sanitize_file()` / `mask.sanitize_dir()` —— 在
  `testcase/conftest.py::pytest_sessionfinish` 与 `main.py` 报告渲染完成后，
  对报告目录做一次**落盘后兜底扫描**（JSON 按结构处理、其余按文本处理，
  幂等、非目标后缀不动、开关关闭时不动作），把第三方插件与未来新增输出路径一并覆盖。
- 新增 11 条单测（URL 查询串、`sanitize_file`、`sanitize_dir` 遍历/幂等/关闭开关）。

### 文档（企业级加固全量同步）

`README.md` 与 `docs/00`~`docs/09`、`examples/README.md`、`examples/template/README.md` 全部同步，
覆盖新增的 `[mask]` / `[network]` 配置段、9 个 `AMSAPI_*` 新变量、`tools/preflight.py`、
执行元数据、日志轮转、teardown 失败登记、覆盖率门槛与 flake8 门禁：

| 文档 | 本次同步内容 |
| --- | --- |
| `README.md` | 目录结构补 `mask.py` / `metadata.py` / `preflight.py` / `.flake8` / `requirements-dev.txt` / `pyproject.toml`；常用命令加 preflight 与 flake8；新增「企业级加固能力」速查表；维护约定补脱敏与静态检查 |
| `docs/00-新手完整指引.md` | 启动摘要示例补「敏感脱敏」行；「8 个坑」扩为 **10 个坑**（脱敏误认、内网 502）；速查卡补 preflight / flake8 / 两个新环境变量 |
| `docs/01-新人上手.md` | 3.4 验证环境补 flake8 与 preflight；日志章节补脱敏与轮转；目录速查补新文件 |
| `docs/02-操作手册.md` | 6.3 报告结构补「执行元数据」与脱敏状态；日志章节补轮转 / 保留 / 兜底脱敏标记 |
| `docs/03-框架设计.md` | 架构图补两模块；新增 **4.11 企业级加固**（脱敏三处接入、代理绕过、可观测性）；设计决策表与「已知限制」同步 |
| `docs/04-开发指南.md` | 配置规范补 `[mask]` / `[network]` 与 `MaskConfig` / `NetworkConfig`；提交前自检扩为 6 步；变更影响评估补三类新条目 |
| `docs/05-常见问题FAQ.md` | 新增第十一节 4 个问答（**Q57–Q60**：代理 502 / 脱敏误认 / teardown 汇总 / preflight）；通用排错流程加「第 0 步 环境预检」 |
| `docs/06-CICD集成.md` | 报告归档章节补日志轮转与保留策略；相关文件表补 preflight / mask / metadata |
| `docs/08-系统适配指南.md` | 新增 **4.9 全局配置（不属于档案）**；排查手册补代理 / 脱敏 / teardown 三行；Checklist 加「第 0 步 预检」 |
| `docs/09-用例编写模板.md` | 自查清单补敏感数据与预检两条；新增「关于敏感数据」小节；错误对照表补三行 |
| `examples/README.md`、`examples/template/README.md` | 使用步骤补预检；新增「跑完看什么」；补代理绕过与脱敏说明 |

> 环境变量名一律以 `config/settings.py::_load_env` 为准（文档已全仓核对）：
> `AMSAPI_MASK_SENSITIVE` / `AMSAPI_MASK_MODE` / `AMSAPI_MASK_EXTRA_KEYS` /
> `AMSAPI_TRUST_ENV` / `AMSAPI_AUTO_BYPASS_PROXY` / `AMSAPI_BYPASS_HOSTS` /
> `AMSAPI_LOG_MAX_BYTES` / `AMSAPI_LOG_BACKUP_COUNT` / `AMSAPI_LOG_KEEP_DAYS`。

### 验证（企业级加固）

- 框架单元测试：**1118 passed / 16 skipped / 0 failed**（原 978 passed / 15 skipped，
  新增 `tests/test_common_mask.py` 与 `tests/test_common_metadata.py`）
- 静态检查：`python -m flake8 .` → **0 问题**
- 语法检查：`python -m compileall -q api common config utils testcase tools main.py` → 退出码 0
- 环境预检：`python tools/preflight.py` → 0 错误 / 1 警告（仅可选依赖 jsonschema/cryptography 未装）
- 内网 mock 端到端：`NO_PROXY` 消除干扰后 7 passed；改用 `proxies_for()` 自动绕过代理后
  无需 `NO_PROXY` 亦可直连
- **脱敏端到端实测**：在**保留沙箱代理**（`HTTP_PROXY=http://127.0.0.1:52137`，`NO_PROXY` 为空）
  的前提下跑 `main.py --report allure`，7 passed；产物（`log/*.log`、`allure-results`、
  渲染后的 `allure-report`）中 `demo_password` / 真实票据**明文命中数为 0**，
  仅存 `dem****rd` / `TK-****hr` 形态
- **文档一致性**：全仓 grep 确认无残留旧统计数字（978 / 993 / 1107 / 1123 / 1133）、
  无错误的环境变量名（`AMSAPI_MASK_ENABLED` / `AMSAPI_NETWORK_*` 等已全部纠正）

---

## [2.4.0] - 2026-09-26

新增**系统适配层**：把「不同 web 系统的差异」从代码里抽成一份声明式档案，
使框架可以接入党政/政务、财务/ERP、商城/购物、数据中台/信息系统等**市场上主流的 web 系统**，
**换被测系统只改一份档案（或一个环境变量），用例数据与框架代码都不用改**。

### 新增

- **系统适配档案层 `common/profile.py`**
  - `SystemProfile`：一个被测系统的全部适配差异（域名 / 编码 / 报文格式 / 响应判定 / 认证 / 钩子）
  - `load_profile(name)`：带进程内缓存的档案加载；档案名写错会报错并列出可用档案
  - `available_systems()` / `clear_cache()` / `describe()`（摘要不含任何凭证）
  - 切换优先级：`AMSAPI_SYSTEM` > `conf.ini [env] system` > `load_profile("xxx")` > 内置默认
  - **内置 `default` 档案等价改造前行为**，存量用例零迁移成本（有专门单测守护）
- **认证策略层 `common/auth.py`**：7 种可插拔策略
  `none` / `basic` / `bearer` / `header`（自定义头，如 `access-ticket`）/ `apikey`（头或 query）/
  `cookie`（会话）/ `oauth2`（client_credentials，自动取令牌 + 到期前 60 秒续期）。
  令牌值支持 `${var}` 且**每次请求前**实时解析，因此「登录取票据 → 后续接口自动带上」
  只需在档案里写 `token = ${ticket}`，用例不必再写请求头
- **响应判定层 `common/response.py`**：6 种内置风格（`status`/`code`/`success`/`errno`/`retcode`/`raw`）
  \+ 自定义 `success_path`/`success_values`/`message_path`/`data_path`/`http_ok`；
  宽松比较（`"200" == 200`、`"True" == true`）；判定配置不完整时**只告警一次**
- **钩子层 `common/hooks.py`**：`before_request`（时间戳防重放 / 参数签名 / 报文加密）与
  `after_response`（解密 / 校验）；声明支持 `包.模块:函数名`、`工厂()`、`工厂({JSON参数})` 三种写法
  （漏写括号会明确报错）；`split_top_level()` 保证 JSON 参数里的逗号不被误切；
  内置 `digest()` / `sign_sorted()` 覆盖 md5/sha1/sha256/sha512/HMAC 与「排序拼串 + 盐 + 大小写 + 排空 + 排除字段」
- **断言增强层 `common/asserts.py`**：21 种字段级算子
  （`equals` `contains` `regex` `type` `exists` `in` `gt/ge/lt/le` `length` `empty` `elapsed` `schema` …），
  作为用例 `expects` 字段的执行引擎
- **用例生命周期**：`setup`（造数据）/ `teardown`（清理，**断言失败也执行**）/
  `depends`（依赖不满足转 `pytest.skip` 而非 fail）/ `check_business`（关闭业务码断言）
- **分页抓取** `BaseApi.paginate()`：带 `max_pages` 安全阀、可自定义页码字段与结束条件
- **XML 支持**：`base.xml_to_dict()` / `base.dict_to_xml()`（`@属性` / `#text` 约定、剥离命名空间、数字自动转类型）；
  请求层支持 XML / SOAP / 纯文本原文发送与按 `response_format` 解析响应
- **响应编码**：`RequestSend(encoding=...)` 强制编码（政务/财务的 GBK、GB2312）+ 自动判断兜底
- **多域名路由**：档案 `[hosts]` 别名 + 用例 `host` 字段或内联 `别名:/path`（网关 + 多服务的微服务系统）
- **四类系统的现成档案**：`gov.ini` / `finance_erp.ini` / `mall.ini` / `dataplatform.ini`
- **`docs/08-系统适配指南.md`**：12 处系统差异对照、档案字段全表、五类系统接入示例、
  认证/响应/钩子/签名用法、差异速查表、排查手册、新增档案 Checklist

### 变更

- `api/base_api.py` 重写为 8 项统一能力（URL 组装 / 参数化 / 认证 / 钩子 /
  统一请求 / 关联提取 / 统一断言 / 用例生命周期 + 分页）；
  业务成功判定下沉到 `run_case()`，**Excel / YAML / MySQL 三个驱动共用同一套规则**
- `config/settings.py`：新增 `SYSTEM`、`ENV_OVERRIDES`（区分「档案值」与「环境变量覆盖值」，
  实现 `AMSAPI_* > 档案 > conf.ini` 的超时/证书回退链）；目录类配置支持
  `AMSAPI_DATA_DIR` / `AMSAPI_CASES_DIR` / `AMSAPI_EXCEL_FILE` / `AMSAPI_SYSTEMS_DIR` /
  `AMSAPI_LOG_DIR` / `AMSAPI_REPORT_DIR` 整体重定向（CI 用另一套数据而不改仓库文件）
- `utils/excelutil.py`：`test_case_list` 追加 **7 个可选列**（16~22 列：
  `host` / `content_type` / `expects` / `setup` / `teardown` / `depends` / `check_business`），
  让 Excel 数据源也能用上适配层全部能力；**旧用例表只写到 `tags` 列也照常运行**
- `config/conf.ini`：`[env]` 新增 `system` 配置项
- `Jenkinsfile`：新增 `SYSTEM` 构建参数并注入 `AMSAPI_SYSTEM`
- `testcase/conftest.py`：Allure 环境信息改用档案 `describe()`，报告首页即可确认本次适配规则
- 三个数据源驱动统一改为调用 `BaseApi.run_case()`

### 修复（本次新增单测时发现）

| 位置 | 问题 | 影响 |
| --- | --- | --- |
| `api/base_api.py: __init__` | 档案 `[cookies]` 段被解析但**从未使用** | 依赖会话/租户 Cookie 的政务、ERP 系统接不进来 |
| `api/base_api.py: request()` | URL 路径里的 `${var}` **不做替换** | `/v1/goods/${gid}` 会把占位符原样发出去 |
| `api/base_api.py: _as_expects()` | 空字典 `{}` 未被当作「无断言」 | 传入空字典会抛算子为 `None` 的错误 |
| `api/base_api.py: run_case()` | 被 `depends` 跳过的用例沿用上一条的响应 | 结果回写出现「上一条响应 + 失败标记」，排查被带偏 |
| `tests/conftest.py: isolate_state` | 未隔离 `settings.ENV_OVERRIDES` | `AMSAPI_*` 覆盖状态跨用例泄漏，表现为「档案里写了 timeout=25 却读出 10」 |

### 验证

| 项 | 结果 |
| --- | --- |
| 框架单元测试 | **928 个用例 / 21 个文件**；未装可选依赖 **913 passed / 15 skipped**（约 4 秒，全离线） |
| 总体覆盖率 | **89%**（框架自身 `api`+`common`+`config`+`utils` 合计 **92%**；`profile` / `response` / `base` / `settings` / `excelutil` / `readmysql` / `yamlutil` / `variable` / `exceptions` 均 100%，`auth` 98%，`base_api` 91%） |
| 可选依赖双路径 | 装 `jsonschema` + `cryptography` → **928 passed / 0 skipped**，覆盖率升至 92%；卸载后对应用例自动 skip，**0 failed** |
| 端到端（本地 mock 服务） | 四条链路全部跑通：<br>① Excel + 党政档案 → 3 passed / 1 skipped（`depends` 缺失正确跳过）<br>② YAML + 中台档案（OAuth2 / `code` 判定 / 域名别名） → 4 passed<br>③ YAML + 商城档案（Bearer / `success` 判定 / `check_business: false`） → 2 passed<br>④ YAML + XML 档案（自定义业务码路径 `body.response.status`） → 1 passed |
| 接口层直连实测 | 11 项全通过：分页抓取（含 `max_pages` 安全阀）、时间戳+签名通过服务端重算校验、GBK 解码、内联/字段两种域名别名、GET/POST/PUT/PATCH/DELETE 五种方法挂载、断言失败信息含服务端原话、令牌缺失时如实失败、`describe()` 不泄露凭证 |
| 冒烟模式 | `AMSAPI_SMOKE=1` 正确筛选出 2 条 `tags=smoke` 用例 |
| 结果回写 | Excel 回写正确；被 `depends` 跳过的用例**不留痕迹**（已修复） |
| 数据安全 | 端到端验证全程使用独立临时目录（`AMSAPI_*` 重定向），`data/`、`data/cases/` 时间戳与内容**完全未变**，临时目录已清理 |

---

## [2.3.1] - 2026-09-26

针对「新人会不会被 `tests/` 目录误导」做了一次**可读性加固**。
无任何业务逻辑改动，只补边界声明与一条强制校验。

### 变更

- `tests/__init__.py` 补写包注释：明确「本目录测的是框架自身，不是业务用例目录」，
  并列出两条硬约定（不得打 `network` / `mysql` 标记、不得写入真实数据文件）。
  新人用 IDE 点进目录即可看到边界，不必先翻文档。
- `testcase/__init__.py` 由空文件补写包注释：声明这里是业务用例层，并与 `tests/` 对照说明。
- `tests/conftest.py` 新增 `pytest_collection_modifyitems` **强制校验**：
  收集阶段发现 `network` / `mysql` 标记即抛 `pytest.UsageError` 并列出违规 nodeid。
  把「`tests/` 必须离线全绿」从文档约定升级为**机器拦截**——
  否则业务用例误放进 `tests/` 后，CI 最早的「框架单元测试」阶段会莫名红一片。
  该钩子仅对 `tests/` 生效，不影响 `testcase/` 的标记与筛选。
- `docs/01-新人上手.md`：目录速查为 `tests/` 加 ⚠️ 边界提示、为 `testcase/` 补 ★；
  「代码阅读顺序」补一段说明为何刻意**不含** `tests/`。
- `docs/07-单元测试.md`：新增「为什么要有两个测试目录」（含量化对比）与
  「新手最容易误读的四点」；修正 `setUpp` 拼写错误。

### 背景数据

| 项 | 行数 |
| --- | --- |
| 框架本体（`api` / `common` / `utils` / `config` / `testcase` / `tools` / `main.py`） | 2648 |
| `tests/` 框架自测 | 3241 |
| `testcase/` 业务用例 | 439 |

测试代码量超过被测代码属正常现象；但 `testcase/` 与 `tests/` 仅一字之差、职责相反，
是本项目最容易被误读的地方，故本次专门加固引导。

### 验证

- 单元测试 **476 passed**（约 3 秒）—— 新增校验对存量用例零影响。
- **拦截实测**：临时在 `tests/` 放入一条 `@pytest.mark.network` 用例，
  收集阶段即报错并打印 `tests/xxx.py::test_xxx -> 标记 'network'`；探针文件随后删除。
- **反向实测**：`pytest --collect-only` 仍正常收集 13 条业务用例，`testcase/` 完全不受影响。

---

## [2.3.0] - 2026-09-26

对全工程的 **GET / POST / PUT / DELETE 请求场景覆盖情况**做了一次完整体检，
补齐单测缺口并修掉了请求层的一处能力缺失。单元测试从 415 增至 **476 个用例**。

### 新增

- **`RequestSend.body_location(method, headers)`**：把「请求数据挂到哪里」的判定
  抽成唯一入口，返回 `params` / `json` / `data` / `files`。
  请求层实际发送与接口层 Allure 附件展示**共用**该判定，杜绝两处规则漂移。

### 变更

- **DELETE 支持携带请求体**：原实现把 `delete` 与 `get/head/options` 同等对待，
  数据一律挂 query，无法发送 REST 批量删除常见的 JSON 体。
  现改为：未声明 `Content-Type` 时仍走 query（**完全向后兼容**），
  显式声明 `application/json` / `x-www-form-urlencoded` / `multipart/form-data` 时按声明挂载。
- `api/base_api.py: request()` 的 Allure 请求附件改用 `body_location()` 判定，
  DELETE 带 JSON 体时在报告中正确显示为「请求体」而非「查询参数」。
- `docs/03-框架设计.md` 新增 **4.9 请求体挂载规则**（方法 × Content-Type 全表 + 设计取舍）。
- `docs/04-开发指南.md` 新增 **1.5 各 HTTP 方法的参数挂载规则**；
  `OrderApi` 示例扩写为覆盖 GET / POST / PUT / PATCH / DELETE（含批量删除带体写法）。

### 新增测试

| 测试类 / 用例 | 覆盖 |
| --- | --- |
| `TestBodyLocation` | `body_location()` 全部取值组合（含大小写、无头、未知 Content-Type） |
| `TestBuildKwargs` 扩展 | DELETE 四种 Content-Type 分支；只读方法忽略 Content-Type |
| `TestSend` 扩展 | 七种方法在 `send()` 全链路的挂载结果；不传 data 时不产生多余键 |
| `TestRequest` 扩展 | 接口层 put/patch/delete 的挂载；Allure 附件位置与实际挂载一致 |

### 审计结论（本次检查结果）

| 层次 | GET | POST | PUT | DELETE | 说明 |
| --- | --- | --- | --- | --- | --- |
| 请求层 `utils/requestsutil.py` | ✅ | ✅ | ✅ | ✅ | 七种方法全支持（另含 patch/head/options） |
| 接口层 `api/*.py` | ✅ | ❌ | ❌ | ❌ | 业务对象只有查询类接口，无写接口 |
| 数据层 Excel / YAML | ✅ | ❌ | ❌ | ❌ | 存量用例全为 GET |
| 单元测试 | ✅ | ✅ | ✅ | ✅ | 本次补齐 put/delete/patch/head/options 的 send 与接口层验证 |

> 接口层与数据层缺 POST/PUT/DELETE **用例**不是缺陷，而是当前被测业务只暴露了查询接口；
> 框架侧的写方法能力与测试覆盖已完备，新增写接口时按 `docs/04-开发指南.md` 1.5 落地即可。

### 验证

| 项 | 结果 |
| --- | --- |
| 单元测试 | **476 passed**（约 3 秒） |
| 总体覆盖率 | **89%**（`api` / `common` 全部 100%） |
| 数据安全 | 跑完 476 个用例后 `data/`、`config/conf.ini`、`report/` 校验值**完全不变** |
| 业务用例收集 | 仍为 13 条，未受影响 |

---

## [2.2.0] - 2026-09-26

新增**框架单元测试套件**（415 个用例、总体覆盖率 89%），并用它发现并修复了 4 处真实缺陷。
从此框架自身的行为有契约保护：改代码不再只靠「跑起来没报错」判断。

### 新增

- **`tests/` 框架单元测试套件**（16 个文件、415 个用例，约 3 秒，完全离线）
  | 文件 | 覆盖 |
  | --- | --- |
  | `test_common_base.py` | 参数化 `${var}` 查找/替换、关联路径取值、`safe_loads`、标签解析 |
  | `test_common_variable.py` | 全局变量池（含点号路径） |
  | `test_common_config.py` | 路径常量一致性、运行开关、环境变量覆盖、INI 读取 |
  | `test_utils_requestsutil.py` | 参数挂载位置判定（params/json/data/files）、统一响应结构 |
  | `test_utils_excelutil.py` | 读取筛选、结果回写、脏标记、只读运行不落盘 |
  | `test_utils_yamlutil.py` | 两种文件结构、标准字段补全、非法项跳过、标签筛选 |
  | `test_utils_logutil.py` | 单例不重复挂 handler、按天文件、追加模式 |
  | `test_utils_allureutil.py` | 附件、长文本截断、无 Allure 时降级、环境信息 |
  | `test_utils_mysqlutil.py` | 惰性连接、DictCursor、事务提交回滚、资源释放、with 语法 |
  | `test_utils_readmysql.py` | SQL 参数化、URL 拼接规则、结果落库 |
  | `test_api_base_api.py` | URL 组装、参数化、请求、关联提取、三类断言、`run_case` |
  | `test_api_objects.py` | LoginApi / DictApi / AdminApi 的请求组装 |
  | `test_main_args.py` | 参数解析、冒烟 marker 合并、CI 判定、退出码 |
  | `test_main_entry.py` | `main()` 报告决策、CI 跳过渲染、退出码透传 |
  | `test_testcase_layer.py` | conftest 钩子、用例 id、SQL 驱动单条执行 |
  | `test_tools_generate_report.py` | 报告渲染分支、命令行拼装 |
- **测试基础设施**（`tests/conftest.py`）
  - 替身对象：`FakeResponse` / `FakeSession` / `FakePymysql` / `FakeDbMysql`
  - 样本 fixture：`excel_file`（临时 Excel，含空行/停用行/多标签）、`yaml_dir`
  - 状态隔离：用例前后自动清空 `GlobalVar`、Excel 工作簿缓存，并快照恢复 `RunConfig` / `DB_CONFIG`
  - 安全保证：Excel 相关用例一律在 `tmp_path` 副本上执行，**绝不触碰 `data/`**
- **`docs/07-单元测试.md`**：套件说明、覆盖率现状、三条铁律、替身用法、如何新增单测、CI 中的位置
- **`Jenkinsfile` 新增「框架单元测试」阶段**：排在冒烟测试之前（框架坏了就没必要跑接口测试）
- GitLab CI / GitHub Actions 示例同步加入单元测试步骤
- `requirements.txt` 新增 `pytest-cov`（覆盖率统计，可选）
- `.gitignore` 新增 `report/unit-coverage/`、`.coverage`、`_verify/`

### 修复（均由单元测试发现）

| 位置 | 问题 | 影响 |
| --- | --- | --- |
| `testcase/test_sql_driver.py: _run_one` | `@staticmethod` 内引用 fixture `api_client`，该方法拿不到该名字 | **MySQL 数据源实际无法执行**（`NameError`），现已改为显式传参 |
| `api/base_api.py: check_status` | 未取得响应时执行 `int(None)` | 抛 `TypeError` 而非清晰的断言失败，掩盖真实原因 |
| `utils/readmysql.py: is_run_data` | `case.get("isdel") == 1` 严格比较 | 库里 `isdel` 为字符串 `'1'` 时用例被全部过滤，与 Excel 侧口径不一致 |
| `common/read_config.py: get_config` | 用 `default is not None` 判断 | 显式传 `default=None` 时误抛 `KeyError`；改用哨兵区分「未传」与「传 None」 |

> 前两项属于**业务执行路径**缺陷：MySQL 驱动一旦启用就会失败，而默认配置下它是跳过的，
> 因此长期未被发现。

### 验证

| 项 | 结果 |
| --- | --- |
| 单元测试 | **415 passed**（约 3 秒） |
| 总体覆盖率 | **89%**（`common` / `utils` / `api` 核心模块 96–100%） |
| 数据安全 | 跑完 415 个用例后 `data/`、`config/conf.ini`、`report/` 校验值**完全不变** |
| 环境鲁棒性 | 默认 / CI 全量 / CI 冒烟 / CI 冒烟无匹配 —— 四种组合均通过 |
| 业务回归 | 本地 mock 环境实测 Excel + YAML + PO 三条链路 **12 passed / 1 skipped** |

---

## [2.1.0] - 2026-09-26

新增 **CI/CD 接入能力**（Jenkins / GitLab CI / GitHub Actions）与**完整文档体系**，
使框架可直接接入流水线，并支持在部署完成后自动执行冒烟测试。

### 新增

- **冒烟测试机制**
  - 用例标签：Excel 新增 `tags` 列（O 列）、YAML 支持 `tags` 字段、手写用例用 `@pytest.mark.smoke`
  - 筛选落地：`ExcelUtil.read_cases(tags=...)`、`yamlutil.read_cases(tags=...)`
  - 公共能力：`common/base.py` 新增 `parse_tags()`、`match_tags()`
  - 入口参数：`python main.py --smoke`（等价于 `pytest -m smoke`，可与 `-m` 条件合并）
  - 已标记示例：Excel id=1 登录、id=3 权限查询，YAML `login.yaml`
- **环境变量覆盖**（CI/CD 的关键能力）
  - `config/settings.py` 新增 `_load_env()`，支持 `AMSAPI_*` 前缀覆盖任意配置项
  - 优先级：环境变量 > `conf.ini` > 代码默认值；空字符串不覆盖
  - 支持 `AMSAPI_CONF_FILE` 指定独立配置文件
  - 新增 `config/conf.ci.ini` 作为 CI 配置参考模板
- **CI 感知**
  - 自动识别 `JENKINS_URL` / `GITLAB_CI` / `BUILD_NUMBER` / `GITHUB_ACTIONS` / `CI` 等
  - 检测到 CI 时跳过本地 Allure HTML 渲染，只产出 `allure-results`，缩短构建时长
  - 可用 `AMSAPI_RENDER_ALLURE=1` 强制渲染
- **Jenkins 集成**
  - 新增 `Jenkinsfile`：检出 → 准备依赖 → 数据自检 → 冒烟/全量 → 归档 + Allure 报告
  - 参数化构建：`RUN_MODE` / `TARGET_ENV` / `BASE_URL` / `WRITE_BACK` / `TIMEOUT` / `DATA_SOURCE`
  - 支持被部署流水线触发（`build job: ..., wait: true, propagate: true`）
- **`.gitignore`**：屏蔽虚拟环境、缓存、日志与报告产物，同时确保 `data/` 用例数据入库

### 文档

- 新增 6 份专题文档，共约 2900 行，全中文：
  | 文档 | 面向 |
  | --- | --- |
  | `docs/01-新人上手.md` | 新人：环境准备、30 分钟跑通、学习路径、第一天 Checklist |
  | `docs/02-操作手册.md` | 日常使用：运行筛选、切环境、换数据源、看报告、调试、MySQL |
  | `docs/03-框架设计.md` | 改框架：分层架构、执行时序、核心机制、设计决策与取舍 |
  | `docs/04-开发指南.md` | 写用例：新增接口/用例/断言/数据源/工具、编码规范 |
  | `docs/05-常见问题FAQ.md` | 排错：39 个按现象分类的问答 + 通用排错流程 |
  | `docs/06-CICD集成.md` | 接流水线：冒烟机制、环境变量、Jenkins/GitLab/Actions、故障排查 |
- 重写根 `README.md` 为「导航入口 + 速查手册」
- `CHANGELOG.md` 补充与 1.x 的迁移对照表

### 变更

- `main.py`：新增 `--smoke`；启动摘要增加「执行模式 / 结果回写 / CI 环境」；结束打印退出码含义
- `testcase/conftest.py`：注册 `smoke` marker；环境信息增加「执行模式」
- `config/conf.ini`：`[run]` 新增 `smoke`、`tags` 配置项
- `data/api_tables.xlsx`：`test_case_list` 新增 O 列 `tags`

### 修复

- **`--collect-only` 不再产生任何副作用**：此前仍会落盘 Excel、写入
  `environment.properties` 并重新渲染报告，现为完全只读（不发请求、不写文件）
- `ExcelUtil.flush()` 增加**脏标记**，只有被修改过的工作簿才写盘
- `config/settings.py` 不再预创建 Allure 结果目录，避免只读运行产生空目录
- `common/read_config.py` 自测块由读取旧配置段 `[MODE]` 改为读取 `conf.ini`
- 归档旧版残留配置 `config/test_config`、`config/test_config.ini` 至 `legacy/`

---

## [2.0.0] - 2026-09-26

按 **Python + Requests + pytest** 接口自动化框架标准完成整体重构，引入 PO 分层、
Allure 报告与可选 MySQL 数据源。

### 新增

- **接口层（PO 模式）**
  - `api/base_api.py`：接口基类，统一提供 URL 组装、参数化、请求发送、关联提取、三级断言
  - `api/login_api.py` / `api/dict_api.py` / `api/admin_api.py`：业务接口对象
- **公共层**
  - `common/variable.py`：`GlobalVar` 全局变量池（线程安全、支持路径读写），替代原 `DynamicParam` 类属性 hack
  - `common/base.py`：新增 `safe_loads()`（安全解析）、`parse_expression()`、`relace_obj()`
- **工具层**
  - `utils/excelutil.py`：Excel 读写，工作簿缓存 + 延迟落盘（替代原 `execlutil.py`）
  - `utils/yamlutil.py`：YAML 用例读取
  - `utils/allureutil.py`：Allure 封装（附件 / 步骤 / 环境信息），未安装时自动降级
- **用例层**
  - `testcase/conftest.py`：全局配置、marker 注册、会话钩子、公共 fixture
  - `testcase/test_excel_driver.py`、`testcase/test_yaml_driver.py`、`testcase/test_sql_driver.py`
  - `testcase/test_login.py`：PO 风格手写用例示例
- **数据层**
  - `data/cases/login.yaml`、`dict.yaml`、`admin.yaml`
- **入口与工具**
  - `main.py`：重写为真正的测试入口，支持 `--report allure|html|both|none`
  - `tools/generate_report.py`：Allure HTML 报告生成脚本
  - `config/conf.ini`：外部配置文件（环境 / 数据源 / 超时 / DB / 报告类型）
  - `requirements.txt`、`README.md`、`CHANGELOG.md`

### 变更

- `config/settings.py`：重构为配置中心，统一管理路径 / 运行开关 / 环境 / DB，支持 `conf.ini` 覆盖
- `common/project_path.py`、`common/read_config.py`：按新结构重写并补充中文注释
- `utils/requestsutil.py`：
  - 支持全部 HTTP 方法（原仅 get/post）
  - 按 `Content-Type` 自动决定参数挂载位置（params / json / data / files）
  - 新增耗时统计、统一响应结构、日志分级
- `utils/logutil.py`：修复重复 handler 问题
- `utils/mysqlutil.py`：
  - 由「导入即连库」改为**惰性连接**
  - 修正 `cursor=pymysql.cursors.DictCursor` 参数名错误（应为 `cursorclass`）
  - 支持参数化查询、事务提交/回滚、`with` 语法
- `utils/readmysql.py`：新增 `get_conf_value()`、`build_case_url()`，SQL 全参数化
- 全工程补充**中文注释与模块级 docstring**

### 修复

- **关联表达式路径根错误**：`body.data.ticket` 原被多剥一层，导致 Excel 用例中
  `${ticket}` 实际替换为空值（该问题此前被"断言只看 status"掩盖）
- `test_sqlrun.py` 中 `var_name = var[10]` 越界（应为 `var[0]`）
- `common/demo.py` 中 `{str(j): replace_dict}` 自引用错误
- `requestsutil` post 仅在 headers **完全等于**两种固定值时生效，其它情况返回
  `None` 导致后续崩溃
- `parse_relation` 使用 `del var[0]` 污染调用方入参

### 安全

- 移除对 Excel 内容的 `eval()` 解析，改用 `json.loads` + `ast.literal_eval`
  （`base.safe_loads()`），消除代码注入风险

### 性能

- Excel 读写由「每条用例 load + save 整个 xlsx」改为**工作簿缓存 + 会话结束统一落盘**
- Excel 结果回写改用真实物理行号，移除「行号 = 用例 id + 1」的脆弱假设

### 移除 / 归档

以下文件移至 `legacy/`，不再参与运行：

| 文件 | 原因 |
| --- | --- |
| `common/demo.py` | 演示脚本，含 bug |
| `utils/mysqltest.py` | 临时调试脚本 |
| `utils/execlutil.py` | 由 `utils/excelutil.py` 取代 |
| `testcase/test_excelrun.py` | 由 `testcase/test_excel_driver.py` 取代 |
| `testcase/test_sqlrun.py` | 由 `testcase/test_sql_driver.py` 取代 |
| `testcase/test_newexcelrun.py` | 结构性损坏的 WIP（函数体内定义类、引用不存在的字段） |

同时保留 `legacy/api_tables.原始备份.xlsx` 作为数据原始备份。

---

## 迁移指南

> 从旧版本（1.x）升级到 2.0.0 时的对照表。

| 旧用法 | 新用法 |
| --- | --- |
| `DynamicParam.xxx` | `GlobalVar.get("xxx")` / `GlobalVar.set("xxx", v)` |
| `RequestSend().api_run(url, method, data, headers, cookies)` | `RequestSend().send(...)`（`api_run` 保留为兼容别名） |
| `ExcelUtil` 在 `utils/execlutil.py` | `utils/excelutil.py` |
| `execlutil.read_case_data(sheet)` | `ExcelUtil().read_cases()` |
| `execlutil.update_case_result(...)` | `ExcelUtil().update_result(row, res, is_pass)` + `ExcelUtil.flush()` |
| 直接 `python -m pytest` 无报告 | `python main.py --report allure` |
| `get_sheet(filename, sheetname)` | `ExcelUtil(filename, sheetname).sheet`（便捷函数保留） |

**数据兼容性**：Excel 表结构与 `relation` 表达式写法**完全不变**，旧用例数据可直接使用。

---

## 版本说明

| 版本 | 说明 |
| --- | --- |
| 2.4.0 | 系统适配层：适配档案 + 7 种认证 + 6 种响应判定 + 签名/加解密钩子 + 21 种断言 + 用例生命周期 + XML/GBK + 多域名；单测增至 928 用例 |
| 2.3.1 | 新手引导加固：`tests/` 与 `testcase/` 边界声明 + 收集阶段强制校验（禁止 network/mysql 标记） |
| 2.3.0 | GET/POST/PUT/DELETE 覆盖审计 + `body_location()` 统一判定 + DELETE 支持请求体 + 单测增至 476 用例 |
| 2.2.0 | 框架单元测试套件（415 用例 / 89% 覆盖）+ 修复 4 处缺陷 + CI 增加单元测试阶段 |
| 2.1.0 | CI/CD 接入（Jenkins / GitLab / Actions）+ 冒烟测试机制 + 环境变量覆盖 + 完整文档体系 |
| 2.0.0 | PO 分层重构 + Allure 报告 + MySQL 数据源优化 + 全量中文注释 |
| 1.x | 原始版本：`DynamicParam` + `eval()` + pytest-html，脚本式结构 |
