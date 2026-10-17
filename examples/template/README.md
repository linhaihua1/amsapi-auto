# 用例编写模板（可直接复制）

新手写用例从这里开始。本目录提供**两种数据源的填空式模板**，
配套讲解见 [`docs/09-用例编写模板.md`](../../docs/09-用例编写模板.md)。

| 文件 | 用途 |
| --- | --- |
| `api_tables_模板.xlsx` | **Excel 数据源模板**：`test_case_list` 表含 4 条可跑示例，`列说明` 表逐列讲解 |
| `demo.yaml` | **YAML 数据源模板**：5 条用例覆盖「登录 → 依赖 → 关联 → 断言 → 清理」 |

两个模板里的示例都指向本地 mock 服务（`tools/mock_server.py`），
**不连内网、不连外网**，复制过去改几个值就能跑。

## 使用步骤

### 1. 起 mock 服务（新开一个终端，保持运行）

```bash
python tools/mock_server.py

# 可选：预检环境（依赖 / 配置 / 数据文件 / 目录 / 目标可达）
AMSAPI_BASE_URL=http://127.0.0.1:18080 python tools/preflight.py
```

### 2. 跑 Excel 模板

```bash
AMSAPI_BASE_URL=http://127.0.0.1:18080 \
AMSAPI_EXCEL_FILE=examples/template/api_tables_模板.xlsx \
python main.py -m excel
```

### 3. 跑 YAML 模板

```bash
AMSAPI_BASE_URL=http://127.0.0.1:18080 \
AMSAPI_CASES_DIR=examples/template \
python main.py -m yaml
```

> Windows PowerShell 下把每行末尾的 `\` 换成反引号 `` ` ``，
> 或改用 `$env:AMSAPI_BASE_URL="http://127.0.0.1:18080"` 逐条设置。

### 4. 换成你自己的接口

把模板复制到你自己的位置，然后按 [`docs/09-用例编写模板.md`](../../docs/09-用例编写模板.md)
的「填空」说明逐列替换：

- `url` → 你的接口相对路径（域名交给 `AMSAPI_BASE_URL` 或系统档案）
- `method` → 小写方法名
- `headers` / `request_body` → **合法 JSON 字符串**
- `relation` → `变量名=响应路径`（要跨用例传值时才写）
- `depends` → 上游用例的 `id`（有 `relation` 就必须配套写）
- `expects` → 至少要有一条字段级断言
- `isdel`（Excel）→ 必须是 `1`

## 模板里演示了什么

| 用例 | 演示的能力 |
| --- | --- |
| 登录并提取票据 | 请求体、`relation` 提取变量、`tags` 冒烟标签、`type` / `not_empty` 断言 |
| 查询权限点 | `${ticket}` 变量注入请求头、`depends` 依赖（前置失败则 skip 而非 fail） |
| 按 id 查询字典 / 分页查询组织树 | 数值比较 `gt`、列表下标路径 `body.rows.0.id`、`elapsed` 耗时断言 |
| 下单并自动清理 | `setup` 造数据、`teardown` 清理（**断言失败也会执行**）、`check_business` 关闭业务码断言 |

## 跑完看什么

| 看哪里 | 能看到 |
| --- | --- |
| 控制台 / `log/*.log` | `【请求】`→`【关联】`→`【断言】` 全过程；口令/令牌**已打码**（如 `dem****rd`） |
| Allure 报告「环境」页 | 本次用的是哪份档案 + **执行元数据**（运行位置 / Python / 依赖版本；git 提交与构建号有则显示） |
| 会话最后几行 | 若有 `teardown 汇总` 告警，说明清理步骤失败，按 case_id 去日志查 |

> 日志里的 `dem****rd` 是**脱敏生效**，不是用例写错了。想临时看原文：
> `AMSAPI_MASK_SENSITIVE=false python main.py ...`（仅本地调试）。

## 相关文档

- 逐列讲解与自查清单：[`docs/09-用例编写模板.md`](../../docs/09-用例编写模板.md)
- 表结构完整解释：[`docs/04-开发指南.md`](../../docs/04-开发指南.md)
- 换成别的 web 系统：[`docs/08-系统适配指南.md`](../../docs/08-系统适配指南.md)
- 其它场景对照示例：[`examples/README.md`](../README.md)
- 从零开始走一遍：[`docs/00-新手完整指引.md`](../../docs/00-新手完整指引.md)
