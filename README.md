# amsapi-auto 接口自动化测试框架

基于 **Python + Requests + pytest** 的数据驱动接口自动化框架，采用 **PO（API Object）分层管理**。
支持 **Excel / YAML / MySQL** 三种用例数据源，一份执行逻辑、多种数据来源，产出 **Allure** 报告。
通过**系统适配档案**适配党政/政务、财务/ERP、商城/购物、数据中台等各类主流 web 系统。

```
数据驱动 + PO 分层 + 参数关联 + 多数据源 + 系统适配 + Allure 报告
```

---

## 一、文档导航

> **新人请从「新手完整指引」开始。** 它一份文档串起：看哪 → 写用例 → 跑用例 → 接 Jenkins → 接 CI/CD。

| 文档 | 面向 | 内容 |
| --- | --- | --- |
| **[★ 新手完整指引](docs/00-新手完整指引.md)** | **第一次接手本项目的人** | **从看懂框架到接入 CI：阅读路线、写用例、执行用例、Jenkins、CI/CD 流水线、第一天 Checklist** |
| **[新人上手指南](docs/01-新人上手.md)** | 需要更细的环境准备 | 环境准备、30 分钟跑通、学习路径、第一天 Checklist |
| **[操作手册](docs/02-操作手册.md)** | 日常使用者 | 运行/筛选用例、切环境、换数据源、看报告、调试、MySQL 使用 |
| **[框架设计](docs/03-框架设计.md)** | 要改框架的人 | 分层架构、执行时序、核心机制（参数化/关联/断言）、设计决策与取舍 |
| **[开发指南](docs/04-开发指南.md)** | 要写用例/接口的人 | 新增接口、新增用例（4 种方式）、新增断言/数据源/工具、编码规范 |
| **[常见问题FAQ](docs/05-常见问题FAQ.md)** | 遇到报错的人 | 按现象分类的排错手册 + 通用排错流程 |
| **[CI/CD 集成](docs/06-CICD集成.md)** | 接流水线的人 | 冒烟机制、环境变量覆盖、Jenkins/GitLab/Actions 接入、部署后自动触发 |
| **[单元测试](docs/07-单元测试.md)** | 改框架代码的人 | 框架自测套件说明、覆盖率、如何新增单元测试、CI 中的位置 |
| **[系统适配指南](docs/08-系统适配指南.md)** | 要接**别的 web 系统**的人 | 适配档案全字段、认证策略、响应判定、签名/加解密、五类系统接入示例 |
| **[用例编写模板](docs/09-用例编写模板.md)** | **第一次写用例的新手** | **填空式模板**：Excel/YAML 各一套，登录取票 → 依赖 → 关联 → 断言 → 清理；栏位速查、21 种断言算子、自查清单、常见错误对照 |
| **[变更记录](CHANGELOG.md)** | 维护者 | 版本变更、与旧版本的对应关系、迁移指南 |

**最短路径**：

```
第一次来 → 00-新手完整指引（一份走完）
跑起来 → 01-新人上手
会用它 → 02-操作手册
写用例 → 04-开发指南（配合 03-框架设计）
接系统 → 08-系统适配指南
改框架 → 03-框架设计 + 07-单元测试
接 CI  → 06-CICD集成
报错了 → 05-常见问题FAQ
```

---

## 二、30 秒快速开始

```bash
cd amsapi-auto
pip install -r requirements.txt
pip install -r requirements-dev.txt     # 开发/CI 附加：flake8、覆盖率、xdist、重试等
python tools/preflight.py               # 环境预检：依赖 / 配置 / 数据 / 目录 / 目标连通性
python -m pytest tests                  # 框架自测（离线，秒级，不依赖被测环境）
python main.py                          # 执行全部用例
python tools/generate_report.py --open  # 打开 Allure 报告
```

> `tests/` 是**框架自身的单元测试**（离线、不碰真实数据）；`testcase/` 是**业务接口用例**（需要真实环境）。
> 详见 [单元测试](docs/07-单元测试.md)。
> `tools/preflight.py --strict` 会让警告也返回非 0 退出码，适合在流水线里当门禁；日常本地跑不加 `--strict`。

### 手里没有被测系统？30 秒离线跑通

```bash
python tools/mock_server.py                                                  # 终端 A：本地 mock 服务
AMSAPI_BASE_URL=http://127.0.0.1:18080 AMSAPI_DATA_SOURCE=yaml python main.py  # 终端 B：跑用例
```

本地 mock 服务复刻了示例接口，**不连内网、不连外网**就能把请求 → 关联 → 断言 → 报告整条链路走完。
详细步骤与每步验证了什么，见
[操作手册 · 不连内网也能跑通](docs/02-操作手册.md#26-不连内网也能跑通离线体验) 与
[`examples/README.md`](examples/README.md)（商城 / 数据中台 / 老系统三套对照示例）。

报告位置：

| 报告 | 路径 |
| --- | --- |
| Allure（推荐） | `report/allure-report/index.html` |
| HTML（备选） | `report/report.html` |

> Allure HTML 渲染需 `allure` 命令行工具（依赖 Java），未安装不影响测试执行。
> 详见 [操作手册 · 测试报告](docs/02-操作手册.md#六测试报告)。

---

## 三、目录结构

```
amsapi-auto/
├── config/                     配置层
│   ├── settings.py             配置中心（路径 / 开关 / 环境 / 数据库 / 环境变量覆盖）
│   ├── conf.ini                ★ 外部配置，改这里切换环境与数据源
│   ├── conf.ci.ini             CI/CD 配置参考模板（默认不加载）
│   └── systems/                ★ 系统适配档案（换被测系统只改这里）
│       ├── default.ini         内置默认（等价改造前行为）
│       ├── gov.ini     党政 / 政务
│       ├── finance_erp.ini     财务 / ERP
│       ├── mall.ini            商城 / 购物
│       └── dataplatform.ini    数据中台 / 信息系统
│
├── common/                     公共层
│   ├── base.py                 参数化核心：${var} 查找/替换、关联路径取值、安全解析、XML 互转
│   ├── variable.py             全局变量池 GlobalVar（接口间传参）
│   ├── profile.py              ★ 系统适配档案层（域名/编码/响应判定/认证/钩子的统一入口）
│   ├── auth.py                 ★ 认证策略层（none/basic/bearer/header/apikey/cookie/oauth2）
│   ├── response.py             ★ 响应判定层（status/code/success/errno/retcode/raw 六种风格）
│   ├── hooks.py                ★ 请求/响应钩子与签名工具（时间戳、md5 签名、AES/RSA）
│   ├── asserts.py              ★ 断言增强层（21 种字段级算子，expects 的执行引擎）
│   ├── mask.py                 ★ 敏感信息脱敏（口令/令牌/票据，日志与报告落盘前打码）
│   ├── metadata.py             ★ 执行元数据（git 提交 / 构建号 / 依赖版本 → Allure 环境页）
│   ├── exceptions.py           ConfigError / CaseSkipped
│   ├── project_path.py         项目路径常量
│   └── read_config.py          ini 配置读取
│
├── utils/                      工具层
│   ├── requestsutil.py         HTTP 请求封装（多方法 / 自动 body / XML 原文 / 编码 / 耗时 / 代理绕过）
│   ├── excelutil.py            Excel 用例读写（工作簿缓存 + 延迟落盘）
│   ├── yamlutil.py             YAML 用例读取
│   ├── mysqlutil.py            MySQL 连接与执行（可选，惰性连接）
│   ├── readmysql.py            MySQL 用例数据访问（可选）
│   ├── logutil.py              日志（控制台 + 按天文件 + 轮转/保留 + 脱敏 Filter）
│   └── allureutil.py           Allure 报告封装（附件 / 步骤 / 环境信息 / 写入前脱敏）
│
├── api/                        ★ 接口层（PO 层）
│   ├── base_api.py             接口基类：URL 组装 / 参数化 / 认证 / 钩子 / 关联 / 断言 / 生命周期
│   ├── login_api.py            登录接口对象
│   ├── dict_api.py             字典接口对象
│   └── admin_api.py            管理端接口对象
│
├── testcase/                   ★ 用例层：日常写用例就在这里（连内网、会读写 data/）
│   ├── conftest.py             全局配置、marker、会话钩子、fixture
│   ├── test_excel_driver.py    Excel 数据驱动用例
│   ├── test_yaml_driver.py     YAML 数据驱动用例
│   ├── test_sql_driver.py      MySQL 数据驱动用例（可选）
│   └── test_login.py           PO 风格手写用例示例
│
├── tests/                      ⚠️ 框架单元测试（离线自测，不依赖被测环境）
│                               ⚠️ 不是业务用例目录！写用例请去 testcase/  ← 最易混
│   ├── conftest.py             替身对象（FakeSession / FakePymysql）与状态隔离
│   ├── test_common_*.py        公共层：参数化解析、变量池、配置、档案、认证、响应、钩子、断言
│   ├── test_utils_*.py         工具层：请求、Excel/YAML、日志、Allure、MySQL
│   ├── test_api_*.py           接口层：URL 组装、参数化、认证注入、钩子、断言、生命周期、分页
│   ├── test_main_*.py          入口：参数解析、冒烟合并、CI 判定、报告决策
│   ├── test_common_mask.py     脱敏规则与日志 Filter 集成
│   ├── test_common_metadata.py 执行元数据采集
│   ├── test_repo_sanitized.py  开源合规：全仓扫描，禁止残留真实地址/账号/口令
│   └── test_testcase_layer.py  用例层：钩子、用例 id、SQL 驱动执行
│
├── data/                       ★ 数据层（全部为通用示例数据，不含真实业务信息）
│   ├── api_tables.xlsx         Excel 用例（sheet: test_case_list，A~V 共 22 列）
│   └── cases/*.yaml            YAML 用例
│
├── examples/                   ★ 换系统的对照示例（配合 tools/mock_server.py 离线可跑）
│   ├── README.md               三套示例的跑法与环境变量
│   ├── mall/cases/             商城：success 判定 + Bearer + teardown
│   ├── dataplatform/cases/     数据中台：code 判定 + OAuth2
│   ├── legacy/cases/           老系统：XML 报文 / GBK 编码 / 请求签名
│   └── template/               ★ 新手用例编写模板（Excel + YAML，填空即用）
│
├── docs/                       项目文档
│   ├── 00-新手完整指引.md       ★ 新人第一份要读的（看哪/写用例/跑用例/接 CI 一条龙）
│   ├── 01-新人上手.md
│   ├── 02-操作手册.md
│   ├── 03-框架设计.md
│   ├── 04-开发指南.md
│   ├── 05-常见问题FAQ.md
│   ├── 06-CICD集成.md
│   ├── 07-单元测试.md
│   ├── 08-系统适配指南.md
│   └── 09-用例编写模板.md   ★ 新手写用例的填空式模板（配合 examples/template/）
│
├── tools/
│   ├── generate_report.py      生成 Allure HTML 报告
│   ├── preflight.py            ★ 环境预检（依赖 / 配置 / 数据 / 目录 / 代理 / 连通性）
│   └── mock_server.py          ★ 本地 mock 服务（离线体验用，零外部依赖）
├── main.py                     统一测试入口
├── Jenkinsfile                 Jenkins 流水线定义
├── pytest.ini                  pytest 配置
├── requirements.txt            运行依赖清单（带版本上限）
├── requirements-dev.txt        开发/校验依赖（flake8 / pytest-cov / xdist / jsonschema / cryptography）
├── .flake8                     风格检查配置（`python -m flake8 .`）
├── pyproject.toml              覆盖率配置（pytest 配置仍在 pytest.ini）
├── CHANGELOG.md                变更记录
├── .gitignore                  版本管理忽略规则
│
├── log/                        运行日志（按天，自动生成）
├── report/                     报告输出（自动生成）
│   ├── report.html
│   ├── allure-results/
│   ├── allure-report/
│   └── unit-coverage/          框架单元测试覆盖率报告
└── legacy/                     旧版本文件归档（不参与运行）
```

带 ★ 的是日常最常接触的六处：改配置（`config/conf.ini`）、接系统（`config/systems/`）、
看接口（`api/`）、写用例（`testcase/`）、添数据（`data/`）、公共能力（`common/`）。

> **⚠️ `testcase/` 与 `tests/` 只差一个字母，职责却完全相反**：
> `testcase/` 测**你的业务系统**（要连内网、会读写 `data/`），
> `tests/` 测**框架自己**（完全离线、只读 `data/`）。
> 写用例去 `testcase/`；`tests/` 只在改了框架代码后才需要碰，
> 且其内部**禁止**出现 `network` / `mysql` 标记（收集阶段会直接报错）。
> 详见 [07-单元测试](docs/07-单元测试.md)。

---

## 四、分层职责

| 层 | 目录 | 职责 | 不该做的事 |
| --- | --- | --- | --- |
| 数据层 | `data/` | 提供用例数据 | 不写任何逻辑 |
| 接口层（PO） | `api/` | 描述「怎么调接口」 | 不写期望值、不组织流程 |
| 用例层 | `testcase/` | 描述「测什么、期望什么」 | 不出现 url 拼接、json 序列化 |
| 工具层 | `utils/` | 可复用的技术能力 | 不含业务语义 |
| 公共层 | `common/` | 参数化、变量池等基础能力 | 不依赖上层 |
| 配置层 | `config/` | 提供配置与路径 | 不写业务逻辑 |
| 单元测试层 | `tests/` | 验证**框架自身代码**是否正确 | 不测业务系统、不发真实请求、不改 `data/` |

依赖方向单向下行：`data → api → testcase`，`config` 被所有层只读依赖。

> 详细说明与执行时序见 [框架设计](docs/03-框架设计.md)。

---

## 五、常用命令

```bash
python main.py                      # 按 conf.ini 执行全部用例
python main.py --smoke              # ★ 只执行冒烟用例（CI/CD 构建后快速验证）
python main.py --report allure      # 生成 Allure 报告（非 CI 环境自动渲染 HTML）
python main.py --report html        # 只生成 pytest-html 报告
python main.py --report both        # 两种报告都要
python main.py --report none        # 不生成报告（快速回归）

python main.py -m excel             # 只跑 Excel 数据驱动用例
python main.py -m yaml              # 只跑 YAML 数据驱动用例
python main.py -m mysql             # 只跑 MySQL 数据驱动用例
python main.py -m "not network"     # 跳过依赖真实服务环境的用例
python main.py -k login             # 只跑名称含 login 的用例
python main.py --collect-only       # 只收集不执行（完全只读，排查用例是否被读到）

python -m pytest tests              # ★ 框架单元测试（离线自检，改代码后必跑）
python -m pytest tests -q           # 同上，简洁输出
python -m flake8 .                  # ★ 风格检查（0 问题才算过）

python tools/preflight.py           # ★ 环境预检（依赖/配置/数据/目录/代理/连通性）
python tools/generate_report.py --clean --open   # 单独渲染并打开报告
```

**可用 marker**：`smoke`、`excel`、`yaml`、`mysql`、`network`

**CI 中推荐用环境变量覆盖配置**（优先级高于 `conf.ini`）：

```bash
AMSAPI_ENV=uat AMSAPI_BASE_URL=https://api.example.com AMSAPI_SYSTEM=mall AMSAPI_WRITE_BACK=false \
python main.py --smoke --report allure
```

完整用法见 [操作手册](docs/02-操作手册.md)，CI 接入见 [CI/CD 集成](docs/06-CICD集成.md)。

---

## 六、配置速查（config/conf.ini）

> **框架里没有任何硬编码的业务数据**：地址、账号、口令、超时、编码、判定规则、
> 日志格式、报告标题……全部集中在 `config/conf.ini` 与 `config/systems/*.ini`。
> 每一**项**都能被环境变量覆盖（命名规则见下）。

```ini
[env]
env = test                                   ; 环境标识（仅用于日志与报告展示）
base_url =                                   ; 全局域名，留空则用例需写全 url
system = default                             ; 系统适配档案名（config/systems/<名>.ini）
                                             ; 换被测系统只改这里，或用 AMSAPI_SYSTEM=<名>

[run]
data_source = excel                          ; 数据源：excel | yaml | mysql | all
                                             ; all = 同时跑 Excel 与 YAML 驱动
sheet_name = test_case_list                  ; Excel 用例所在 sheet
write_back = true                            ; 是否回写执行结果
timeout = 10                                 ; 请求超时（秒）
verify = false                               ; 是否校验 https 证书
smoke = false                                ; 是否只跑冒烟用例（CI/CD 用）
tags = smoke                                 ; 冒烟标签（对应用例的 tags）

[db]
host =                                       ; 留空 = 未配置，框架不会去连库
user =
password =
database =
port = 3306
charset = utf8
web =                                        ; MySQL 数据源业务标识（test_case_list.web）
environment =                                ; MySQL 数据源配置环境（test_config.environment）

[report]
report_type = allure                         ; allure | html | both | none
title = 接口自动化测试                        ; 报告标题
project = amsapi-auto                        ; 项目名（Allure 环境页）
html_name = report.html                      ; pytest-html 文件名
max_attach_len = 20000                       ; Allure 单条附件最大字符数（超出截断）

[log]
level = DEBUG                                ; DEBUG | INFO | WARNING | ERROR
console_level = DEBUG                        ; 控制台级别（CI 里可调 INFO 少刷屏）
file_name_format = %Y_%m_%d                  ; 日志文件名格式（按天滚动）
format = %(asctime)s | %(levelname)-7s | %(filename)s:%(lineno)d | %(message)s
date_format = %Y-%m-%d %H:%M:%S
root_name = amsapi                           ; logger 根名称
mask_sensitive = true                        ; 日志/报告中的口令、令牌一律打码（强烈建议保持 true）
max_bytes = 20971520                         ; 单文件上限（字节），超出自动轮转 .1/.2；0 = 不限
backup_count = 5                             ; 轮转备份个数
keep_days = 30                               ; 历史日志保留天数；0 = 不清理

[mask]
mode = partial                               ; partial = 保留首尾少量字符 | full = 全遮蔽
keep_prefix = 3                              ; partial 模式保留前缀字符数
keep_suffix = 2                              ; partial 模式保留后缀字符数
extra_keys =                                 ; 追加敏感字段名（逗号分隔），如 mobile,idcard

[network]
trust_env = true                             ; 是否沿用系统代理（HTTP_PROXY / HTTPS_PROXY）
auto_bypass_proxy = true                     ; 内网/环回地址自动绕过代理（必须为 true）
bypass_hosts =                               ; 额外不走代理的主机，如 corp.internal,10.

[auth]
refresh_ahead = 60                           ; OAuth2 令牌到期前多少秒提前续期
token_timeout = 10                           ; 取令牌请求超时（秒）
token_verify = false                         ; 取令牌是否校验 https 证书

[ci]
detect_env_vars = JENKINS_URL,JENKINS_HOME,GITLAB_CI,BUILD_NUMBER,GITHUB_ACTIONS,TF_BUILD,CI
                                             ; 出现任一变量即判定为 CI，自动跳过本地 HTML 渲染
```

**环境变量命名规律**：

| 目标 | 变量 |
| --- | --- |
| `conf.ini` 的项 | `AMSAPI_<项名大写>`，如 `AMSAPI_TIMEOUT`、`AMSAPI_LOG_LEVEL` |
| `conf.ini` `[mask]` 段 | `AMSAPI_MASK_SENSITIVE`、`AMSAPI_MASK_MODE`、`AMSAPI_MASK_EXTRA_KEYS` |
| `conf.ini` `[network]` 段 | `AMSAPI_TRUST_ENV`、`AMSAPI_AUTO_BYPASS_PROXY`、`AMSAPI_BYPASS_HOSTS` |
| `conf.ini` `[log]` 轮转项 | `AMSAPI_LOG_MAX_BYTES`、`AMSAPI_LOG_KEEP_DAYS` |
| 系统档案 `[env]` 段 | `AMSAPI_<字段名大写>`，如 `AMSAPI_ENCODING`、`AMSAPI_RESPONSE_FORMAT` |
| 系统档案 `[hosts]` 段 | `AMSAPI_HOST_<别名大写>`，如 `AMSAPI_HOST_ADMIN` |
| 系统档案 `[auth]` 段 | `AMSAPI_AUTH_<字段名大写>`，如 `AMSAPI_AUTH_CLIENT_SECRET` |
| 系统档案 `[hooks]` 段 | `AMSAPI_HOOKS_BEFORE_REQUEST`、`AMSAPI_HOOKS_AFTER_RESPONSE` |
| 目录重定向 | `AMSAPI_DATA_DIR` / `CASES_DIR` / `EXCEL_FILE` / `SYSTEMS_DIR` / `LOG_DIR` / `REPORT_DIR` |

完整清单见 [CI/CD 集成 · 环境变量](docs/06-CICD集成.md#三环境变量覆盖ci-的关键能力)。

---

## 七、数据源对比

| 维度 | Excel | YAML | MySQL |
| --- | --- | --- | --- |
| 文件 / 位置 | `data/api_tables.xlsx` | `data/cases/*.yaml` | 数据库三张表 |
| 适合谁维护 | 业务同学 | 开发 | 多系统共用 |
| 地址拼接 | 用例写完整 url 或相对路径 | 同左 | `test_config` 域名 + `port_num` + url |
| 结果回写 | 写回 Excel 行内 | 不回写 | 写 `test_result_record` |
| 执行粒度 | 一行 = 一个 pytest 用例 | 一条 = 一个 pytest 用例 | 整表一个用例，内部循环 |
| 启用开关 | `data_source = excel` | `= yaml` | `= mysql` |

另有 `data_source = all`：同时运行 Excel 与 YAML 驱动（兼容早期行为）；
`-m` / `-k` 命令行筛选优先于 `data_source`（如 `python main.py -m yaml`）。
取值非法时框架会明确报错并列出可选值，不会静默按默认值跑。

**三者的执行入口完全一致**（都走 `BaseApi`），切换数据源不需要改用例代码。
详见 [操作手册 · 切换数据源](docs/02-操作手册.md#四切换数据源)。

---

## 八、核心机制速览

### 参数关联（接口间传参）

```
1. 上游用例声明提取规则（Excel relation 列）  ticket=body.data.ticket
2. 框架把值写入全局变量池 GlobalVar
3. 下游用例用 ${ticket} 占位符引用，请求前自动替换
```

- 路径根是**完整响应**，所以响应体字段要带 `body.` 前缀
- 支持多级路径与列表下标：`first=body.data.rows.0.name`
- 多处关联用逗号分隔：`ticket=body.data.ticket,uid=body.data.user.id`

### 断言

| 方法 | 断言对象 |
| --- | --- |
| `check_success(expected)` | **业务成功**——按系统档案的规则判定（推荐，换系统不用改） |
| `check_status(code)` | HTTP 状态码 |
| `check_business_code(code)` | 业务状态码（默认 `body.status`，兼容存量用例） |
| `check_json(path, expected)` | 任意 JSON 路径的值（根为完整响应） |
| `assert_*` / `check_expects` | 21 种字段级断言，见下 |

`expects` 支持简写，Excel 一列/YAML 一行写完：

```yaml
expects: "contains:body.msg=操作成功; gt:body.data.total=0; elapsed=3000"
```

算子：`equals` `not_equals` `contains` `not_contains` `startswith` `endswith` `regex`
`type` `exists` `not_exists` `in` `not_in` `gt` `ge` `lt` `le` `length` `empty`
`not_empty` `elapsed` `schema`。

详见 [框架设计 · 核心机制](docs/03-框架设计.md#四核心机制) 与
[系统适配指南 · 断言与 expects](docs/08-系统适配指南.md#六断言与-expects)。

### 用例生命周期

```yaml
setup:      造数据（主请求前执行，支持 relation 提取）
teardown:   清理数据（断言失败也会执行）
depends:    依赖的用例 id，未通过则本用例跳过（skip，不是 fail）
check_business: false   # 令牌/下载类接口关掉业务码断言
```

---

## 九、系统适配（接任意主流 web 系统）

**12 处系统差异全部收敛到一份档案**：域名与多服务、认证方式、成功判定、
报文格式与编码、签名、时间戳、加解密、错误消息字段……

```bash
# 换被测系统：只改一个环境变量（或 conf.ini 的 [env] system）
AMSAPI_SYSTEM=mall python main.py --smoke
```

| 档案 | 面向系统 | 判定风格 | 认证 |
| --- | --- | --- | --- |
| `default` | 内置默认（等价改造前行为） | `body.status` | 无 |
| `gov` | 党政 / 政务 | `body.status` | 自定义头 `access-ticket` |
| `finance_erp` | 财务 / ERP | `body.code` | Cookie + 签名钩子 |
| `mall` | 商城 / 购物 | `body.success` | `Bearer` + 多域名 |
| `dataplatform` | 数据中台 / 信息系统 | `body.code == 0` | `OAuth2` 自动取令牌 |

内置 7 种认证策略、6 种响应判定风格、可插拔的签名/时间戳/加解密钩子，
以及 XML 报文与 GBK 编码支持。

**不配置也完全没问题**：默认使用内置 `default` 档案，行为与改造前一致，存量用例零迁移。

详见 [系统适配指南](docs/08-系统适配指南.md)（含五类系统的完整接入示例与差异速查表）。

---

## 十、CI/CD 接入（冒烟测试）

支持在部署完成后自动触发**冒烟测试**，快速验证本次构建是否可用。

**冒烟标记**（三处均可）：

| 数据源 | 位置 | 写法 |
| --- | --- | --- |
| Excel | `test_case_list` 表 **O 列 `tags`** | `smoke` |
| YAML | 用例的 `tags` 字段 | `tags: [ smoke ]` |
| PO 手写用例 | pytest marker | `@pytest.mark.smoke` |

**执行**：

```bash
python main.py --smoke                    # 只跑冒烟用例，其余 deselected
python main.py --smoke --report allure    # 冒烟 + 产出报告
```

**Jenkins**：仓库根目录已提供 `Jenkinsfile`，新建 Pipeline 任务指向该文件即可。
流水线流程：`检出 → 准备依赖 → 数据自检 → 冒烟/全量 → 归档 + Allure 报告`。

**环境变量覆盖**（优先级高于 `conf.ini`，CI 中无需改仓库文件）：

```bash
AMSAPI_ENV=uat AMSAPI_BASE_URL=https://api.example.com AMSAPI_SYSTEM=mall \
AMSAPI_WRITE_BACK=false AMSAPI_TIMEOUT=30 python main.py --smoke --report allure
```

**CI 下的自动优化**：检测到 CI 环境（`JENKINS_URL` / `GITLAB_CI` / `CI` 等）时
自动跳过本地 HTML 渲染，只产出 `report/allure-results/`，由流水线的 Allure 插件渲染。

**退出码**：`0` 通过，非 `0` 失败，可直接用于流水线判定。

详见 [CI/CD 集成指南](docs/06-CICD集成.md)（含 Jenkins 部署后自动触发、GitLab CI、
GitHub Actions 示例与故障排查）。

---

## 十一、支持的环境与依赖

| 组件 | 版本 | 必需 |
| --- | --- | --- |
| Python | 3.7+（建议 3.10+） | 是 |
| pytest | ≥7.0 | 是 |
| requests | ≥2.25 | 是 |
| openpyxl | ≥3.0 | 是 |
| PyYAML | ≥5.4 | 是 |
| pytest-html | ≥3.1 | 否（备选报告） |
| allure-pytest | ≥2.13 | 否（Allure 附件与步骤） |
| PyMySQL | ≥1.0 | 否（MySQL 数据源） |
| allure CLI + Java | 2.29+ | 否（渲染 Allure HTML） |
| pytest-cov | ≥4.0 | 否（覆盖率统计） |
| jsonschema | ≥4.0 | 否（`schema:` 断言） |
| cryptography | ≥3.4 | 否（AES 加解密 / RSA 签名） |

**开发 / CI 附加依赖**（`pip install -r requirements-dev.txt`，不影响运行时）：

| 组件 | 版本 | 用途 |
| --- | --- | --- |
| flake8 | ≥6.0 | 静态检查（CI 门禁） |
| pytest-cov | ≥4.0 | 覆盖率统计与门槛判定 |
| pytest-xdist | ≥3.3 | 多进程并行加速 |
| pytest-rerunfailures | ≥12.0 | 网络抖动重试 |
| pytest-timeout | ≥2.1 | 防止用例挂死 |
| jsonschema / cryptography | — | 可选能力（装了就自动启用，不装自动降级） |

**缺少可选依赖时框架会自动降级并给出安装提示，不影响已有功能**。
`tools/preflight.py` 会明确列出「已装 / 未装」及影响的能力。
详见 [系统适配指南 · 可选依赖](docs/08-系统适配指南.md#48-可选依赖一览)。

**企业级加固能力**（安全合规 / 环境健壮性 / 可观测性）：

| 能力 | 实现 | 开关 / 入口 |
| --- | --- | --- |
| 敏感信息脱敏 | `common/mask.py` + 日志 Filter + 附件写入前 + 报告落盘后兜底 | `[mask]` / `AMSAPI_MASK_SENSITIVE`（**默认开**） |
| 系统代理绕过 | `utils/requestsutil.proxies_for()`（环回 / 私网 / `*.local` 自动绕过） | `[network]` / `AMSAPI_TRUST_ENV`、`AMSAPI_BYPASS_HOSTS` |
| 执行元数据 | `common/metadata.py` → Allure「环境」页（运行位置 / Python / OS / 依赖版本；git 提交与构建号**有则显示**） | 自动，无需配置 |
| 日志轮转与保留 | `utils/logutil.py` | `[log] max_bytes / backup_count / keep_days` |
| teardown 失败登记 | `api/base_api.py` + `testcase/conftest.py` 会话收尾汇总告警 | 自动 |
| 环境预检 | `tools/preflight.py` | `--no-target` / `--strict` / `--json` |
| 风格门禁 | `.flake8` + flake8 | `python -m flake8 .` |
| 开源合规守卫 | `tests/test_repo_sanitized.py` | `python -m pytest tests/test_repo_sanitized.py -q` |

> 设计取舍与实现细节见 [框架设计 · 4.11 企业级加固](docs/03-框架设计.md#411-企业级加固安全--健壮性--可观测性250)。

---

## 十二、离线体验与开源约束

### 12.1 离线体验（不连内网也能跑通）

框架自带 `tools/mock_server.py`，把示例接口在本地复刻出来：

```bash
python tools/mock_server.py                                                 # 终端 A
AMSAPI_BASE_URL=http://127.0.0.1:18080 AMSAPI_DATA_SOURCE=yaml python main.py  # 终端 B
```

`examples/` 下还有三套「换一种系统」的对照示例，命令见
[`examples/README.md`](examples/README.md)：

| 目录 | 演示的系统形态 | 换的是什么 |
| --- | --- | --- |
| `examples/mall/` | 商城：`success` 判定 + Bearer + teardown | 一份档案 + 两个环境变量 |
| `examples/dataplatform/` | 数据中台：`code` 判定 + OAuth2 | 同上 |
| `examples/legacy/` | 老系统：XML / GBK / 请求签名 | 同上 |

**新手写用例请先看** [`examples/template/`](examples/template/README.md)：
Excel 与 YAML 各一份填空式模板，四条示例覆盖「登录取票 → 依赖 → 参数关联 → 断言 → 后置清理」，
讲解见 [用例编写模板](docs/09-用例编写模板.md)。

**用例文件长得几乎一样** —— 这正是适配层的价值：换系统改的是档案，不是用例，更不是框架代码。

### 12.2 开源约束：仓库里没有真实数据

| 约束 | 落地方式 |
| --- | --- |
| 不预置真实地址 / 账号 / 口令 / 密钥 | `conf.ini`（含 `conf.ci.ini`）的 `[db]` 全部留空；示例用例 url 一律**相对路径** |
| 示例档案用占位域名 | `*.example.com` / `*.local`，真实域名由 `AMSAPI_BASE_URL` 注入 |
| 示例用例用通用业务值 | `demo_user` / `demo-app` / `demo-type` … |
| **运行期产出不泄露口令 / 令牌** | `[log] mask_sensitive = true` + `[mask]` 生效：日志与 Allure 附件在**写入前**统一打码 |
| 自动化守卫 | `tests/test_repo_sanitized.py` 扫描全仓（含 `config/**/*.ini`）文件与弱口令，一旦有人误提交真实信息立刻失败 |
| 历史执行产物不入库 | `.gitignore` 忽略 `log/*.log`、`report/*`、`.coverage` |

---

## 十三、维护约定

| 约定 | 要求 |
| --- | --- |
| 注释 | 全中文；模块级 docstring 说明用途与用法 |
| **禁止硬编码** | 地址、账号、口令、超时、编码、格式、文件名等**一律**走 `config/conf.ini` / `config/systems/*.ini` / `AMSAPI_*` 环境变量；`config/settings.py` 是唯一配置入口 |
| 依赖方向 | 禁止上层被下层引用（如 `api/` 不得 import `testcase/`） |
| 数据契约 | 用例数据必须是含 `url`/`method` 等字段的 dict，见 [开发指南](docs/04-开发指南.md#52-数据契约必须遵守) |
| **开源合规** | 提交前不得出现真实内网地址、真实账号口令、真实用户隐私；`python -m pytest tests/test_repo_sanitized.py -q` 必须绿 |
| **脱敏** | 日志/报告落盘前必须经 `common/mask.py` 打码；新增会打印请求/响应的代码不得绕过 `mask.mask_payload()` |
| **静态检查** | `python -m flake8 .` 必须 0 问题（配置见 `.flake8`，行长上限 120） |
| **变更同步** | 改字段/配置/断言需同步更新 `docs/`，重要变更记入 `CHANGELOG.md` |

提交前自检：

```bash
python -m flake8 .                            # 静态检查（0 问题）
python -m compileall -q api common config utils testcase tools main.py
python tools/preflight.py                     # 环境预检（0 错误）
python -m pytest tests -q                     # 框架自测（含开源合规扫描 + 覆盖率）
python main.py --collect-only
python main.py --report none
```

---

## 十四、旧版本

原始版本（脚本式结构、`DynamicParam` + `eval()`、仅 Excel 驱动）的文件已归档至
`legacy/`，不参与运行，可直接删除。迁移对照见 [变更记录 · 迁移指南](CHANGELOG.md#迁移指南)。
