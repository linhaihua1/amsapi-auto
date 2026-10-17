# CI/CD 集成指南

> 本文面向**把接口自动化接入流水线**的同学。
> 读完你能：在 Jenkins / GitLab CI 中跑通冒烟测试，并在部署完成后自动触发。

---

## 一、整体思路

```
开发提交代码
     │
     ▼
[CI 流水线] 构建 / 打包
     │
     ▼
[框架单元测试] ★ 离线自检（约 5 秒）—— 框架自身坏了就没必要往下跑
     │
     ▼
[CD 流水线] 部署到目标环境
     │
     ▼
[冒烟测试] ★ 本文重点 —— 快速验证部署后的核心接口是否可用
     │
     ├─ 通过 → 流水线继续（放行）
     └─ 失败 → 流水线中断 + 通知（拦截问题版本）
     │
     ▼
[定时全量回归] 每日夜间跑完整用例集
```

**为什么要有框架单元测试？**
它验证的是**测试工具本身**（参数化替换、关联提取、Excel 读写、断言逻辑……），
不依赖被测环境，几秒完成。若框架被改坏，后面的接口测试结果全是噪音，
所以放在最前面，先失败先止。详见 [07-单元测试](07-单元测试.md)。

**为什么要有冒烟测试？**
全量用例耗时较长（受网络与用例规模影响），不适合卡在每次部署的关键路径上。
冒烟测试只跑**最核心的几条链路**，几十秒内给出"本次部署是否可用"的结论。

**为什么强调环境变量？**
CI 中切换环境（测试/UAT/生产）不应靠改仓库里的配置文件——
那样每次都要提交代码、容易冲突、还可能把生产地址提交进仓库。
本框架支持用 `AMSAPI_*` 环境变量覆盖任意配置项，流水线参数直接注入即可。

---

## 二、冒烟测试机制

### 2.1 如何标记冒烟用例

三种数据源都支持，标记方式统一为「标签」概念：

| 数据源 | 位置 | 写法 |
| --- | --- | --- |
| Excel | `test_case_list` 表的 **O 列 `tags`** | `smoke` 或 `smoke,core`（多个用逗号分隔） |
| YAML | 用例的 `tags` 字段 | `tags: [ smoke ]` 或 `tags: smoke` |
| PO 风格手写用例 | pytest marker | 在类或方法上加 `@pytest.mark.smoke` |

**当前仓库已标记的冒烟用例**（可直接参考）：

| 用例 | 标记 | 覆盖点 |
| --- | --- | --- |
| Excel id=1「登录系统」 | `smoke` | 登录 + 提取 ticket |
| Excel id=3「查询用户权限点」 | `smoke` | 携带 ticket 鉴权（**验证参数关联链路**） |
| YAML `login.yaml`「登录系统」 | `smoke` | 登录 |

> **冒烟用例怎么选**：覆盖「登录鉴权 + 核心业务读写 + 参数关联」即可，
> 通常 3~10 条。数量过多就失去了"快速"的意义。
> 建议包含一条**依赖上游提取变量**的用例，这样能顺带验证关联机制没被破坏。

### 2.2 如何执行冒烟

```bash
python main.py --smoke                    # 核心入口
python main.py --smoke --report allure    # 跑冒烟并产出报告
```

三种等价方式（任选）：

| 方式 | 命令 / 配置 |
| --- | --- |
| 命令行参数（推荐） | `python main.py --smoke` |
| 环境变量 | `AMSAPI_SMOKE=1 python main.py` |
| 配置文件 | `conf.ini` 的 `[run] smoke = true` |

**自定义冒烟标签**（比如想跑 `core` 标签的用例）：

```bash
python main.py --smoke              # 配合下面任一方式指定标签
AMSAPI_TAGS=core python main.py --smoke
# 或 conf.ini： [run] tags = core
```

### 2.3 冒烟模式到底做了什么

```
1. 数据层只加载 tags 命中的用例（Excel / YAML）
2. 给数据驱动模块打上 smoke 标记
3. 给 pytest 追加 -m smoke 表达式
   └─ 未打标记的 PO 用例、SQL 驱动用例会被自动排除（deselected）
```

**结果**：只收集并执行冒烟用例，其余用例显示为 `deselected`。

```bash
# 例如：全量 13 条 → 冒烟 3 条
$ python main.py --collect-only --smoke
3/6 tests collected (3 deselected)
```

> `--smoke` 可与 `-m` 组合：`python main.py --smoke -m excel`
> 会被合并为 `-m "(excel) and smoke"`，而不是相互覆盖。

---

## 三、环境变量覆盖（CI 的关键能力）

所有配置都可通过 `AMSAPI_*` 环境变量覆盖，**优先级高于 `conf.ini`**。

### 3.1 变量速查

| 环境变量 | 对应配置 | 示例 |
| --- | --- | --- |
| `AMSAPI_CONF_FILE` | 指定配置文件 | `config/conf.ci.ini` |
| `AMSAPI_ENV` | 环境标识 | `uat` |
| `AMSAPI_BASE_URL` | 全局域名 | `https://api.example.com` |
| **`AMSAPI_SYSTEM`** | **系统适配档案名** | `mall` / `finance_erp` / `dataplatform` |
| `AMSAPI_DATA_SOURCE` | 数据源 | `excel` / `yaml` / `mysql` |
| `AMSAPI_SHEET_NAME` | Excel sheet 名 | `test_case_list` |
| `AMSAPI_WRITE_BACK` | 是否回写结果 | `false` |
| `AMSAPI_TIMEOUT` | 请求超时（秒） | `30` |
| `AMSAPI_VERIFY` | 校验 https 证书 | `false` |
| `AMSAPI_REPORT_TYPE` | 报告类型 | `allure` |
| `AMSAPI_SMOKE` | 是否只跑冒烟 | `true` |
| `AMSAPI_TAGS` | 冒烟标签 | `smoke` |
| `AMSAPI_WEB` | MySQL 业务标识 | `demo_web` |
| `AMSAPI_DB_ENVIRONMENT` | MySQL 配置环境 | `demo_env` |
| `AMSAPI_DB_HOST` | 数据库地址 | `192.0.2.10` |
| `AMSAPI_DB_PORT` | 数据库端口 | `3306` |
| `AMSAPI_DB_USER` | 数据库用户 | `ci_user` |
| `AMSAPI_DB_PASSWORD` | 数据库密码 | `******` |
| `AMSAPI_DB_NAME` | 数据库名 | `api_test` |
| `AMSAPI_DB_CHARSET` | 字符集 | `utf8` |
| `AMSAPI_RENDER_ALLURE` | 置 `1` 强制本地渲染 HTML | `1` |

**日志 / 报告 / 认证 / CI 判定**（对应 `conf.ini` 的 `[log]` `[report]` `[auth]` `[ci]` 四段）：

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `AMSAPI_LOG_LEVEL` | `DEBUG` | 文件日志级别 |
| `AMSAPI_LOG_CONSOLE_LEVEL` | `DEBUG` | 控制台日志级别（CI 里常调成 `INFO` 减噪） |
| `AMSAPI_LOG_ROOT_NAME` | `amsapi` | logger 名 |
| `AMSAPI_REPORT_TITLE` | `接口自动化测试` | 报告标题 |
| `AMSAPI_REPORT_PROJECT` | `amsapi-auto` | 报告项目名 |
| `AMSAPI_REPORT_HTML_NAME` | `report.html` | pytest-html 文件名 |
| `AMSAPI_ALLURE_MAX_ATTACH_LEN` | `20000` | Allure 附件截断长度（0/负数=不截断） |
| `AMSAPI_OAUTH2_REFRESH_AHEAD` | `60` | OAuth2 令牌到期前多少秒续期 |
| `AMSAPI_OAUTH2_TOKEN_TIMEOUT` | `10` | 取令牌请求超时（秒） |
| `AMSAPI_OAUTH2_TOKEN_VERIFY` | `false` | 取令牌时校验证书 |

**系统适配档案逐项覆盖**（改环境不必改档案文件）：

| 环境变量 | 覆盖档案里的 | 示例 |
| --- | --- | --- |
| `AMSAPI_ENCODING` | `[env] encoding` | `gbk` |
| `AMSAPI_CONTENT_TYPE` | `[env] content_type` | `application/xml` |
| `AMSAPI_RESPONSE_FORMAT` | `[env] response_format` | `xml` |
| `AMSAPI_HOST_<别名>` | `[hosts] <别名>` | `AMSAPI_HOST_ADMIN=https://admin.example.com` |
| `AMSAPI_AUTH_<字段>` | `[auth] <字段>` | `AMSAPI_AUTH_CLIENT_SECRET=******` |
| `AMSAPI_HOOKS_BEFORE_REQUEST` | `[hooks] before_request` | `common.hooks:make_sign_hook({...})` |
| `AMSAPI_HOOKS_AFTER_REQUEST` | `[hooks] after_request` | 同上 |

> `[ci]` 段本身不通过环境变量配置，它定义的是**判定「当前是否在 CI 里」要检查哪些环境变量**
> （默认 `JENKINS_URL,JENKINS_HOME,GITLAB_CI,BUILD_NUMBER,GITHUB_ACTIONS,TF_BUILD,CI`）。
> 换了别的 CI 平台，改这一段即可，不用改代码。

**目录类变量**（在进程启动时读取，用于让 CI 用另一套数据/档案而不改仓库文件）：

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `AMSAPI_SYSTEMS_DIR` | `config/systems` | 系统适配档案目录 |
| `AMSAPI_DATA_DIR` | `data` | 数据根目录（同时影响下方两项的默认值） |
| `AMSAPI_CASES_DIR` | `data/cases` | YAML 用例目录 |
| `AMSAPI_EXCEL_FILE` | `data/api_tables.xlsx` | Excel 用例文件 |
| `AMSAPI_LOG_DIR` | `log` | 日志目录 |
| `AMSAPI_REPORT_DIR` | `report` | 报告目录 |

> 用途举例：CI 里挂载另一套用例数据，或本地端到端验证时把数据落到临时目录，
> 跑完即删，**完全不碰仓库里的 `data/`**。
>
> ```bash
> AMSAPI_SYSTEM=mall \
> AMSAPI_SYSTEMS_DIR=/ci/amsapi/systems \
> AMSAPI_DATA_DIR=/ci/amsapi/data \
> python main.py --smoke
> ```

> **空字符串不覆盖**：`AMSAPI_BASE_URL=` 会被忽略，不会把配置清空。
> 这避免了 CI 中未填写的参数意外破坏配置。

> **优先级说明**：`AMSAPI_*` > 系统适配档案 > `conf.ini`。
> 也就是说 `AMSAPI_TIMEOUT` 会压过档案里写的 `timeout`，而档案又会压过 `conf.ini` ——
> 这样流水线临时放宽超时一定生效，而档案仍然是系统的默认约定。

### 3.2 用法示例

```bash
# 单条命令注入
AMSAPI_ENV=uat AMSAPI_BASE_URL=https://api.example.com python main.py --smoke

# Jenkins：在流水线 environment 块中声明（见第五节）
# GitLab CI：在 variables 块中声明（见第六节）
```

### 3.3 用独立的 CI 配置文件

仓库提供了 `config/conf.ci.ini` 作为参考模板：

```bash
AMSAPI_CONF_FILE=config/conf.ci.ini python main.py --smoke --report allure
```

适用场景：CI 的参数较多（如数据库连接），写环境变量太长，
或希望 CI 配置与本地配置彻底分离。

---

## 四、命令行接口（CI 视角）

### 4.1 关键参数

| 参数 | 说明 |
| --- | --- |
| `--smoke` | 只执行冒烟用例 |
| `--report allure\|html\|both\|none` | 报告类型。CI 推荐 `allure` |
| `-m <marker>` | 按 marker 筛选，可与 `--smoke` 组合 |
| `-k <关键字>` | 按名称筛选 |
| `--collect-only` | 只收集不执行（**完全只读**，适合做流水线的"数据自检"步骤） |

### 4.2 退出码约定

| 退出码 | 含义 | 流水线处理 |
| --- | --- | --- |
| `0` | 全部通过 | 放行 |
| `1` | 有用例失败 | **中断流水线** |
| `2` | 参数错误（如 `--report` 值非法） | 中断，检查配置 |
| `5` | 没有收集到任何用例 | 中断，检查筛选条件与用例数据 |

退出码即 pytest 退出码，**可直接用于流水线判定**，无需额外解析输出。

> 注意：退出码 `5`（无用例）通常意味着筛选条件写错，或用例数据全部
> `isdel != 1`。建议在流水线中把它也视为失败，避免"空跑"被误判为成功。

### 4.3 CI 环境下的自动行为

框架会检测常见 CI 环境变量（`JENKINS_URL`、`GITLAB_CI`、`BUILD_NUMBER`、
`GITHUB_ACTIONS`、`TF_BUILD`、`CI`），并自动：

| 行为 | 说明 |
| --- | --- |
| 跳过本地 HTML 渲染 | 只产出 `report/allure-results/`，由流水线的 Allure 插件渲染，**显著缩短构建时长** |
| 打印 CI 标识 | 启动摘要中显示 `CI 环境: 是`，便于确认参数是否正确注入 |

如需在 CI 中也渲染本地 HTML（例如把报告作为构建产物分发）：

```bash
AMSAPI_RENDER_ALLURE=1 python main.py --report allure
```

---

## 五、Jenkins 接入

### 5.1 前置要求

| 项 | 要求 |
| --- | --- |
| Jenkins 插件 | **Allure Jenkins Plugin**（渲染报告）、Pipeline |
| 节点环境 | Python 3.7+（建议 3.10+），`python` 命令可用 |
| 可选 | allure 命令行工具（若要让本流水线直接产出 HTML 报告） |

### 5.2 创建流水线

1. 新建任务 → 选择 **Pipeline**（或"多分支流水线"）
2. Pipeline 定义 → 选择 **Pipeline script from SCM**
3. SCM 选择你的仓库，脚本路径填 **`Jenkinsfile`**（仓库根目录已提供）
4. 保存并构建

仓库中的 `Jenkinsfile` 已包含完整逻辑：

```
检出代码 → 准备依赖 → 数据与配置自检 → 框架单元测试 → 冒烟测试 / 全量回归 → 归档 + Allure 报告
```

| 阶段 | 命令 | 说明 |
| --- | --- | --- |
| 数据与配置自检 | `python main.py --collect-only` | 只读，确认用例能被读到 |
| **框架单元测试** | `python -m pytest tests -q` | 离线约 5 秒，验证框架自身没被改坏 |
| 冒烟测试 | `python main.py --smoke --report allure` | `RUN_MODE=smoke` 时执行 |
| 全量回归 | `python main.py --report allure` | `RUN_MODE=full` 时执行 |

### 5.3 构建参数说明

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `RUN_MODE` | `smoke` | `smoke` 只跑冒烟；`full` 全量回归 |
| `TARGET_ENV` | `test` | 环境标识，写入报告「环境」页 |
| `BASE_URL` | 空 | 接口域名。**留空则用仓库 `conf.ini`；填写则覆盖** |
| `SYSTEM` | `default` | **系统适配档案名**（`config/systems/<名>.ini`）。切换到另一个被测系统只改这一项 |
| `SMOKE_TAGS` | `smoke` | 冒烟标签，可改为 `core` 等 |
| `WRITE_BACK` | `false` | 是否回写数据源。**CI 建议保持 false** |
| `TIMEOUT` | `30` | 请求超时（秒） |
| `DATA_SOURCE` | `excel` | 用例数据源 |

> `WRITE_BACK=false` 的原因：CI 里回写会改动仓库中的 `api_tables.xlsx`，
> 可能造成工作区脏、并发构建冲突。结果看 Allure 报告即可。

> `SYSTEM` 参数会被注入为 `AMSAPI_SYSTEM`。同一套流水线可以用不同参数
> 指向不同的被测系统，或为每个系统建一个 Job、只改这个参数。
> 可用档案见 `config/systems/`，说明见 [08-系统适配指南](08-系统适配指南.md)。

### 5.4 查看报告

构建完成后，构建页左侧会出现 **Allure Report** 入口，点开即是完整报告
（步骤树、请求/响应附件、环境信息）。

同时归档了 `log/*.log`，可在构建页 **Artifacts** 中下载排查。

### 5.5 与部署流水线联动（构建后自动冒烟）

这是用户最关心的场景：**部署完成 → 自动触发冒烟**。

**方式一：上游 Job 触发下游（推荐）**

在**部署 Job** 的末尾加上：

```groovy
stage('部署后触发冒烟') {
    steps {
        build job: 'amsapi-auto-smoke',              // 冒烟 Job 名
              parameters: [
                  string(name: 'BASE_URL', value: 'https://api.example.com'),
                  string(name: 'TARGET_ENV', value: 'uat'),
                  string(name: 'RUN_MODE', value: 'smoke')
              ],
              wait: true,                             // 等待冒烟结果，失败则本次部署判定失败
              propagate: true                         // 冒烟失败时把上游部署也标记为失败
    }
}
```

- `wait: true` + `propagate: true` 是关键：冒烟失败会让部署 Job 也失败，
  从而拦截问题版本继续流向下一环境。

**方式二：在同一个 Jenkinsfile 中串联**

如果部署也在同一个流水线里，直接在部署阶段后加冒烟阶段：

```groovy
stage('部署') {
    steps {
        sh './deploy.sh'                              // 你的部署脚本
    }
}

stage('冒烟测试') {
    steps {
        sh 'python main.py --smoke --report allure'
    }
}
```

**方式三：构建触发器（部署 Job 完成后自动启动）**

任务配置 → 构建触发器 → 勾选
**Build after other projects are built** → 填写部署 Job 名。

### 5.6 定时全量回归

任务配置 → 构建触发器 → **Build periodically**：

```
H 2 * * *        # 每天凌晨 2 点左右执行一次
```

配合 `RUN_MODE=full` 参数默认值使用。

### 5.7 推荐的 Job 划分

| Job | 触发方式 | 参数 | 用途 |
| --- | --- | --- | --- |
| `amsapi-auto-smoke` | 部署后触发 / 手动 | `RUN_MODE=smoke` | 部署验证，几十秒出结果 |
| `amsapi-auto-full` | 定时（每日）+ 手动 | `RUN_MODE=full` | 全量回归 |

---

## 六、GitLab CI 接入

在仓库根目录创建 `.gitlab-ci.yml`：

```yaml
stages:
  - unit
  - test

variables:
  # 通过 AMSAPI_* 覆盖配置，无需改动仓库文件
  AMSAPI_REPORT_TYPE: allure
  AMSAPI_WRITE_BACK: "false"
  AMSAPI_TIMEOUT: "30"
  AMSAPI_REPORT_TYPE_EXTRA: ""      # 占位，避免空值告警

# 框架单元测试：离线自检，任何变更都先跑（约 5 秒）
unit-test:
  stage: unit
  image: python:3.10
  script:
    - pip install -r requirements.txt
    - python -m pytest tests -q

# 冒烟测试：仅合并请求 / 手动触发时执行
smoke-test:
  stage: test
  image: python:3.10
  needs: ["unit-test"]                          # 框架自检通过才跑接口测试
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_PIPELINE_SOURCE == "web"          # 手动触发
  script:
    - pip install -r requirements.txt
    - python main.py --smoke --report allure
  artifacts:
    when: always                                 # 失败也要保留产物，便于排查
    paths:
      - report/allure-results/
      - log/
    expire_in: 1 week

# 全量回归：定时执行
full-regression:
  stage: test
  image: python:3.10
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
  script:
    - pip install -r requirements.txt
    - python main.py --report allure
  artifacts:
    when: always
    paths:
      - report/allure-results/
      - log/
    expire_in: 1 week
```

**要点**：

| 要点 | 说明 |
| --- | --- |
| `AMSAPI_WRITE_BACK: "false"` | YAML 中布尔值要加引号，否则会被解析成布尔而非字符串 |
| `artifacts.when: always` | 用例失败时也要保留报告，否则无法排查 |
| `CI` 变量 | GitLab CI 自动注入 `CI=true`，框架会据此跳过本地 HTML 渲染 |
| Allure 报告 | 在 GitLab 中可用 `allure-report` 类型产物，或直接下载 allure-results |

**部署后自动触发**（多项目流水线）：

```yaml
# 在部署项目的 .gitlab-ci.yml 中
trigger-smoke:
  stage: deploy
  trigger:
    project: your-group/amsapi-auto
    strategy: depend          # 等待冒烟结果，失败则本流水线失败
    branch: main
  variables:
    AMSAPI_BASE_URL: "https://api.example.com"
    AMSAPI_ENV: "uat"
```

或者在冒烟项目的 `.gitlab-ci.yml` 中声明为"可被下游触发"：

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "pipeline"     # 被上游流水线触发
```

---

## 七、GitHub Actions 接入

```yaml
name: API Smoke Test

on:
  workflow_run:
    workflows: ["Deploy"]          # 部署工作流完成后自动触发
    types: [completed]
  workflow_dispatch:               # 支持手动触发

jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: 安装依赖
        run: pip install -r requirements.txt

      - name: 框架单元测试
        run: python -m pytest tests -q

      - name: 执行冒烟测试
        env:
          AMSAPI_ENV: uat
          AMSAPI_BASE_URL: https://api.example.com
          AMSAPI_WRITE_BACK: "false"
          AMSAPI_TIMEOUT: "30"
        run: python main.py --smoke --report allure

      - name: 上传报告数据
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: allure-results
          path: report/allure-results/
```

> GitHub Actions 会自动设置 `CI=true` 与 `GITHUB_ACTIONS=true`，
> 框架据此跳过本地 HTML 渲染。

---

## 八、CI 配置建议

| 配置项 | 本地开发 | CI 冒烟 | CI 全量 |
| --- | --- | --- | --- |
| `write_back` | `true` | `false` | `false` |
| `timeout` | `10` | `30` | `30` |
| `report_type` | `allure` | `allure` | `allure` |
| `smoke` | `false` | `true` | `false` |
| 本地 HTML 渲染 | 是 | 否（由流水线插件渲染） | 否 |
| 依赖隔离 | 虚拟环境 | 容器 / 虚拟环境 | 同左 |

**三条硬性建议**：

1. **不要在 CI 中回写数据源**（`write_back=false`）
   避免改动仓库文件、避免并发构建互相覆盖。
2. **不要把生产环境密码写进仓库**
   用 Jenkins Credentials / GitLab CI Variables / Secrets，通过环境变量注入。
3. **冒烟 Job 要设超时保护**
   Jenkinsfile 已设 `timeout(time: 60, unit: 'MINUTES')`，防止网络异常导致构建挂死。

---

## 九、故障排查

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| 构建报 `python: command not found` | 节点无 Python 或未加入 PATH | 在节点安装 Python，或用 `withPython` 类插件；容器化运行 |
| **框架单元测试阶段失败** | 框架代码被改动且未通过自测 | 本地跑 `python -m pytest tests -x --tb=long`，详见 [07-单元测试](07-单元测试.md) |
| 冒烟收集到 0 条用例（退出码 5） | 无用例带 `smoke` 标签；或标签名不匹配 | 检查 Excel `tags` 列 / YAML `tags` 字段；确认 `AMSAPI_TAGS` 与标签一致 |
| 全部用例连接失败 | `BASE_URL` 未注入，仍在连测试地址 | 检查参数 `BASE_URL` 是否传入；确认框架启动摘要里的「全局域名」 |
| 报告页没有 Allure 入口 | 未安装 Allure Jenkins Plugin，或 `allure-results` 为空 | 安装插件；确认 `report_type=allure` 且未加 `--report none` |
| 每次构建都很慢 | 本地 HTML 渲染耗时 | 确认 CI 环境变量被识别（启动摘要显示 `CI 环境: 是`）；不要设 `AMSAPI_RENDER_ALLURE` |
| 构建成功但实际有失败 | 误把退出码 5（无用例）当成功 | 在流水线中显式判断退出码非 0 即失败（`sh` 步骤默认行为已满足） |
| 工作区出现 `api_tables.xlsx` 变更 | `write_back` 为 true | 设 `AMSAPI_WRITE_BACK=false` |
| 并发构建结果相互覆盖 | 多个构建写同一份数据文件 | 已用 `disableConcurrentBuilds()`；另建议 `write_back=false` |

**排查三板斧**：

1. 看构建日志开头的**启动摘要**（环境/模式/数据源/CI 判定/pytest 参数）是否与预期一致
2. 用 `python main.py --collect-only` 确认收集到的用例是否正确（该命令完全只读）
3. 下载归档的 `log/*.log`，搜 `【请求】`、`【关联】`、`请求异常` 定位具体接口

---

## 十、命令速查

```bash
# —— 框架单元测试（离线，不依赖被测环境）——
python -m pytest tests -q                               # 全部框架自测
python -m pytest tests --cov=api --cov=utils --cov=main # 带覆盖率

# —— 冒烟 ——
python main.py --smoke                                  # 只跑冒烟用例
python main.py --smoke --report allure                  # 冒烟 + Allure 报告
python main.py --smoke -m excel                         # 只跑 Excel 里的冒烟用例
AMSAPI_TAGS=core python main.py --smoke                 # 自定义冒烟标签

# —— CI 参数注入 ——
AMSAPI_ENV=uat AMSAPI_BASE_URL=https://api.example.com \
AMSAPI_WRITE_BACK=false AMSAPI_TIMEOUT=30 python main.py --smoke --report allure

# —— 切换被测系统（系统适配档案）——
AMSAPI_SYSTEM=mall python main.py --smoke
AMSAPI_SYSTEM=finance_erp AMSAPI_TAGS=core python main.py --smoke

# —— 用另一套数据/档案（不改仓库文件）——
AMSAPI_SYSTEM=mall AMSAPI_SYSTEMS_DIR=/ci/amsapi/systems \
AMSAPI_DATA_DIR=/ci/amsapi/data python main.py --smoke

# —— 使用独立 CI 配置 ——
AMSAPI_CONF_FILE=config/conf.ci.ini python main.py --smoke

# —— 自检（只读，不产生任何文件）——
python main.py --collect-only
python main.py --collect-only --smoke

# —— 全量回归 ——
python main.py --report allure
```

---

## 十一、相关文件

| 文件 | 作用 |
| --- | --- |
| `Jenkinsfile` | Jenkins 声明式流水线定义（含框架单元测试阶段） |
| `config/conf.ci.ini` | CI 专用配置参考模板 |
| `config/systems/*.ini` | 系统适配档案（`AMSAPI_SYSTEM` 指向这里，见 [08-系统适配指南](08-系统适配指南.md)） |
| `main.py` | 入口，负责参数解析、CI 检测、报告渲染 |
| `config/settings.py` | 环境变量覆盖逻辑（`_load_env`） |
| `testcase/test_excel_driver.py`、`test_yaml_driver.py` | 冒烟筛选落地处 |
| `tests/` | 框架单元测试（CI 第一阶段，见 [07-单元测试](07-单元测试.md)） |
| `testcase/conftest.py` | marker 注册、环境信息写入（含适配档案摘要） |
