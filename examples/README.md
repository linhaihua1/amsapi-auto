# 示例用例集（离线可跑，配合 tools/mock_server.py）
=====================================================

`data/cases/` 是**框架默认的示例用例**（政务 / 平台风格，status 判定），
本目录里的几套是「换一种系统」的对照示例，用来演示**同一份框架、不同系统差异**。

所有示例都指向本地 mock 服务，**不连内网、不连外网**。

## 使用步骤

```bash
# 1) 起 mock 服务（新开一个终端，保持运行）
python tools/mock_server.py

# 2) 另开一个终端，按下面命令跑对应示例
```

| 目录 | 演示的系统形态 | 一条命令跑通 |
| --- | --- | --- |
| `mall/` | 商城 / 购物：`success` 判定、网关多域名、写接口前后置清理 | 见下 |
| `dataplatform/` | 数据中台：`code` 判定、OAuth2 客户端模式 | 见下 |
| `legacy/` | 老系统：XML 报文、GBK 编码、请求签名 | 见下 |
| `template/` | **新手模板**：Excel 与 YAML 填空式用例模板 | 见 [`template/README.md`](template/README.md) |

### 商城示例

```bash
AMSAPI_SYSTEM=mall \
AMSAPI_BASE_URL=http://127.0.0.1:18080 \
AMSAPI_DATA_SOURCE=yaml \
AMSAPI_CASES_DIR=examples/mall/cases \
python main.py -m yaml
```

### 数据中台示例（OAuth2）

```bash
AMSAPI_SYSTEM=dataplatform \
AMSAPI_BASE_URL=http://127.0.0.1:18080 \
AMSAPI_AUTH_TOKEN_URL=http://127.0.0.1:18080/oauth/token \
AMSAPI_AUTH_CLIENT_ID=demo-client \
AMSAPI_AUTH_CLIENT_SECRET=demo-secret \
AMSAPI_DATA_SOURCE=yaml \
AMSAPI_CASES_DIR=examples/dataplatform/cases \
python main.py -m yaml
```

### 老系统示例（XML / GBK / 签名）

```bash
AMSAPI_BASE_URL=http://127.0.0.1:18080 \
AMSAPI_ENCODING=gbk \
AMSAPI_RESPONSE_FORMAT=xml \
AMSAPI_HOOKS_BEFORE_REQUEST='common.hooks:make_sign_hook({"field": "sign", "salt": "mock-salt", "alg": "md5", "upper": true})' \
AMSAPI_DATA_SOURCE=yaml \
AMSAPI_CASES_DIR=examples/legacy/cases \
python main.py -m yaml
```

> Windows PowerShell 下把每行末尾的 `\` 换成反引号 `` ` ``，
> 或改用 `$env:AMSAPI_SYSTEM="mall"` 单独设置环境变量。

> **为什么命令里带 `-m yaml`？**
> `data/` 下自带的 Excel 示例是按 `status` 判定风格写的，与 `mall` / `dataplatform`
> 档案不匹配（对方的成功码在 `success` / `code` 上）。同时跑必然失败 —— 这不是框架问题，
> 而是「用例数据要和档案风格一致」的正常约束。限定只跑 YAML 驱动即可。

## 为什么这些示例能说明问题

同一套框架代码、同一套用例格式，只换了**系统档案 + 几个环境变量**：

| 差异点 | 商城 | 数据中台 | 老系统 |
| --- | --- | --- | --- |
| 成功怎么判定 | `response.style = success` | `response.style = code` | 只看字段断言 |
| 怎么鉴权 | Bearer Token | OAuth2 客户端模式 | 参数签名 |
| 报文格式 | JSON | JSON | XML / GBK |
| 域名 | 网关 + 多服务别名 | 网关 + 多服务别名 | 单域名 |

三个示例的用例文件长得几乎一样 —— 这正是适配层的价值：
**换系统改的是档案，不是用例，更不是框架代码。**
