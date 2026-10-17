# -*- coding: utf-8 -*-
"""
本地 mock 服务（离线体验用，零外部依赖）
=========================================
用途：**不连内网、不连任何真实系统**，也能把整个框架完整跑起来，
     看到真实的请求日志、Allure 报告、参数关联与断言结果。

为什么需要它？
    框架的示例数据（data/cases/*.yaml、data/api_tables.xlsx）里没有真实地址，
    很多同学拿到框架后「跑不起来」不是因为框架有问题，而是**没有可访问的被测系统**。
    本服务把这些接口在本地复刻出来，于是：

        python tools/mock_server.py                 # 终端 1：起服务
        AMSAPI_BASE_URL=http://127.0.0.1:18080 python main.py   # 终端 2：跑用例

    就能 100% 跑通，且不产生任何外部请求。

模拟了哪些系统差异（正好覆盖框架的适配能力）：
    /v1/users/login                      政务风格：票据认证 + status 判定 + relation 提取
    /admin/resource/authority            需要 access-ticket 请求头，验证令牌自动注入
    /admin/org/getTreeRootParentCodePage 分页响应
    /dicts                               字典查询（GET + query 参数）
    /v1/goods                            商城风格：success 判定 + 分页
    /v1/orders（POST）                   商城下单（写接口，配合 setup / teardown 演示）
    /api/v1/datasource/list              中台风格：code 判定 + data 包裹
    /oauth/token（POST）                 OAuth2 客户端模式取令牌
    /v1/legacy/xml                       返回 XML 报文
    /v1/legacy/gbk                       返回 GBK 编码中文
    /v1/sign/verify                      服务端重算签名并比对（验证签名钩子正确性）

用法：
    python tools/mock_server.py                  # 默认 127.0.0.1:18080
    python tools/mock_server.py --port 9000      # 换端口
    python tools/mock_server.py --host 0.0.0.0   # 换绑定地址（默认仅本机可见）

停止：Ctrl + C
"""
import argparse
import hashlib
import json
import random
import string
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# 默认监听地址与端口（仅本机可见，避免暴露到局域网）
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18080

# 签名校验用的盐值（仅演示用，真实系统由对方提供）
SIGN_SALT = "mock-salt"

# 服务端已「发出」的令牌（用于校验后续请求是否带了合法票据）
_VALID_TICKETS = set()
_VALID_TOKENS = {"mock-access-token"}
_LOCK = threading.Lock()


def _rand_text(length=8):
    """生成随机小写字母串，用于 ticket / nonce。"""
    return "".join(random.choice(string.ascii_lowercase) for _ in range(length))


def sign_sorted(params, salt=SIGN_SALT, alg="md5"):
    """
    按 key 排序拼串 + 盐 + 摘要 —— 服务端侧的签名算法。

    与框架 common/hooks.py 的 sign_sorted() 保持同一算法，
    因此可用来验证客户端签名钩子算得对不对。
    """
    items = sorted((str(k), "" if v is None else str(v))
                   for k, v in params.items() if k != "sign")
    raw = "&".join("{}={}".format(k, v) for k, v in items) + salt
    return hashlib.new(alg, raw.encode("utf-8")).hexdigest().upper()


class MockHandler(BaseHTTPRequestHandler):
    """把请求分发到各模拟接口。"""

    # 关掉默认的 stderr 访问日志（改成我们自己格式化的、更易读的一行）
    def log_message(self, fmt, *args):
        print("[mock] {} {} -> {}".format(self.command, self.path, args[1] if len(args) > 1 else ""))

    # ------------------------------------------------------------------
    # 出口
    # ------------------------------------------------------------------
    def _send(self, payload, http_status=200, content_type="application/json",
              encoding="utf-8", raw_text=None):
        """
        统一回包。

        :param payload:    可 JSON 序列化的对象；为 None 时用 raw_text 原样输出
        :param http_status: HTTP 状态码（业务失败也可能给 200，与真实系统一致）
        :param content_type: 响应类型
        :param encoding:   字符编码（GBK 老系统用）
        :param raw_text:   非 JSON 的原样文本（XML / 纯文本）
        """
        if raw_text is not None:
            body = raw_text.encode(encoding)
        else:
            body = json.dumps(payload, ensure_ascii=False).encode(encoding)

        self.send_response(http_status)
        self.send_header("Content-Type", "{}; charset={}".format(content_type, encoding))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------
    # 入参解析
    # ------------------------------------------------------------------
    def _query(self):
        """query 参数 -> 一维字典（值取第一个）。"""
        parsed = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        return {k: v[0] for k, v in parsed.items()}

    def _body(self):
        """请求体 -> 字典；JSON / 表单 / 文本都能吃下，解析不了就返回 {}。"""
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            return {}
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else {"_data": obj}
        except ValueError:
            pass
        # 表单
        parsed = parse_qs(text, keep_blank_values=True)
        return {k: v[0] for k, v in parsed.items()}

    def _params(self):
        """query 与 body 合并后的全部入参。"""
        merged = self._query()
        merged.update(self._body())
        return merged

    # ------------------------------------------------------------------
    # 各 HTTP 方法
    # ------------------------------------------------------------------
    def do_GET(self):
        self._dispatch("get")

    def do_POST(self):
        self._dispatch("post")

    def do_PUT(self):
        self._dispatch("put")

    def do_DELETE(self):
        self._dispatch("delete")

    def do_PATCH(self):
        self._dispatch("patch")

    def do_HEAD(self):
        self._dispatch("head")

    def do_OPTIONS(self):
        self._dispatch("options")

    # ------------------------------------------------------------------
    # 路由
    # ------------------------------------------------------------------
    def _dispatch(self, method):
        path = urlparse(self.path).path.rstrip("/") or "/"
        params = self._params()
        handler = ROUTES.get(path)
        if handler is None:
            # 兜底：业务失败也返回 HTTP 200，与政务 / ERP 系统的常见行为一致
            self._send({"status": 404, "message": "接口不存在：{}".format(path),
                        "data": None})
            return
        try:
            handler(self, method, params)
        except Exception as exc:                       # noqa: BLE001 —— mock 不应因异常挂掉
            self._send({"status": 500, "message": "mock 内部异常：{}".format(exc),
                        "data": None})


# ======================================================================
# 一、政务 / 平台类接口（status 判定 + 票据）
# ======================================================================
def handle_login(handler, method, params):
    """
    登录：校验账号密码，返回 ticket。

    对应框架能力：relation 提取 -> 全局变量池 -> 后续请求用 ${ticket} 自动带票据
    """
    username = params.get("username") or ""
    password = params.get("password") or ""
    if not username or not password:
        handler._send({"status": 400, "message": "用户名或密码为空", "data": None})
        return

    ticket = "TK-{}".format(_rand_text(12))
    with _LOCK:
        _VALID_TICKETS.add(ticket)

    handler._send({
        "status": 200,
        "message": "success",
        "data": {
            "ticket": ticket,
            "user": {"username": username, "orgCode": "ORG-001"},
            "token": {"ticket": ticket, "expire": "2099-12-31 23:59:59"},
        },
    })


def _require_ticket(handler):
    """校验请求头里的票据；不通过时回包并返回 None。"""
    ticket = handler.headers.get("access-ticket") or ""
    with _LOCK:
        ok = ticket in _VALID_TICKETS
    if not ok:
        handler._send({"status": 401, "message": "票据无效或已过期，请先登录", "data": None})
        return None
    return ticket


def handle_authority(handler, method, params):
    """查询权限点：必须带 access-ticket（验证令牌自动注入 + 变量池解析）。"""
    if _require_ticket(handler) is None:
        return
    app_code = params.get("appCode") or ""
    type_ = params.get("type") or "btn"
    handler._send({
        "status": 200,
        "message": "success",
        "data": [
            {"code": "{}:query".format(app_code), "name": "查询", "type": type_},
            {"code": "{}:edit".format(app_code), "name": "编辑", "type": type_},
        ],
    })


def handle_org_tree(handler, method, params):
    """组织树分页：rows + total（验证分页与字段级断言）。"""
    if _require_ticket(handler) is None:
        return
    page = int(params.get("page") or 1)
    size = int(params.get("size") or 20)
    total = 5
    start = (page - 1) * size + 1
    end = min(total, page * size) + 1
    rows = [{"code": "{}-{}".format(params.get("code") or "org", i),
             "name": "组织节点{}".format(i)} for i in range(start, end)]
    handler._send({"status": 200, "message": "success", "rows": rows, "total": total})


def handle_dicts(handler, method, params):
    """字典查询：GET + query 参数，rows 结构。"""
    dict_id = params.get("id") or "demo-type"
    handler._send({
        "status": 200,
        "message": "success",
        "rows": [{
            "id": dict_id,
            "sysCode": params.get("sysCode") or "demo",
            "name": "示例字典",
            "data": [{"key": "1", "label": "选项一"}, {"key": "2", "label": "选项二"}],
        }],
        "total": 1,
    })


# ======================================================================
# 二、商城类接口（success 判定 + 写接口）
# ======================================================================
def handle_goods(handler, method, params):
    """商品列表：success 判定 + success_path 在 result 下面。"""
    page = int(params.get("page") or 1)
    page_size = int(params.get("pageSize") or 10)
    total = 23
    start = (page - 1) * page_size
    items = [{"goodsId": "G{:04d}".format(i), "name": "示例商品{}".format(i),
              "price": 9.9 + i} for i in range(start + 1, min(total, start + page_size) + 1)]
    handler._send({"success": True, "message": "",
                   "result": {"list": items, "total": total, "page": page}})


def handle_create_order(handler, method, params):
    """下单（写接口）：配合用例的 setup 造数据 / teardown 清理。"""
    goods_id = params.get("goodsId") or "G0001"
    if method not in ("post", "put"):
        handler._send({"success": False, "message": "下单请用 POST"})
        return
    handler._send({"success": True, "message": "下单成功",
                   "result": {"orderId": "ORD-{}".format(_rand_text(10)),
                              "goodsId": goods_id, "amount": 19.9,
                              "status": "CREATED"}})


def handle_cancel_order(handler, method, params):
    """取消订单（teardown 用）。"""
    handler._send({"success": True, "message": "已取消", "result": {"orderId": params.get("orderId")}})


# ======================================================================
# 三、中台类接口（code 判定 + 多服务域名别名）
# ======================================================================
def handle_datasource_list(handler, method, params):
    """数据源列表：{"code": 0, "msg": "success", "data": {...}}。"""
    handler._send({"code": 0, "msg": "success",
                   "data": {"list": [{"id": "ds-1", "name": "示例数据源"}], "total": 1}})


def handle_job_run(handler, method, params):
    """触发 ETL 任务：演示 code 判定 + 非 0 业务码的失败分支。"""
    job_id = params.get("jobId") or ""
    if not job_id:
        handler._send({"code": 1001, "msg": "jobId 不能为空", "data": None})
        return
    handler._send({"code": 0, "msg": "success", "data": {"jobId": job_id, "state": "RUNNING"}})


def handle_oauth_token(handler, method, params):
    """OAuth2 客户端模式取令牌。"""
    client_id = params.get("client_id") or ""
    client_secret = params.get("client_secret") or ""
    if not client_id or not client_secret:
        handler._send({"error": "invalid_client", "error_description": "缺少客户端凭证"},
                      http_status=401)
        return
    token = "AT-{}".format(_rand_text(16))
    with _LOCK:
        _VALID_TOKENS.add(token)
    handler._send({"access_token": token, "token_type": "Bearer", "expires_in": 3600,
                   "scope": params.get("scope") or ""})


# ======================================================================
# 四、老系统 / 报文格式（XML、GBK、签名）
# ======================================================================
def handle_legacy_xml(handler, method, params):
    """返回 XML 报文（验证 response_format=xml 与 xml_to_dict）。"""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<response><status>200</status><message>success</message>'
        '<data><item id="1">示例数据一</item><item id="2">示例数据二</item></data>'
        '</response>'
    )
    handler._send(None, content_type="application/xml", raw_text=xml)


def handle_legacy_gbk(handler, method, params):
    """返回 GBK 编码的中文（验证 encoding=gbk 与自动编码兜底）。"""
    handler._send({"status": 200, "message": "中文不乱码", "data": {"备注": "GBK 编码响应"}},
                  content_type="application/json", encoding="gbk")


def handle_sign_verify(handler, method, params):
    """
    服务端重算签名并比对 —— 验证客户端签名钩子算得对不对。

    请求需带 sign 字段；服务端用同样算法重算，一致才返回成功。
    """
    client_sign = params.get("sign")
    if not client_sign:
        handler._send({"status": 400, "message": "缺少 sign 字段", "data": None})
        return
    expected = sign_sorted(params)
    if str(client_sign).upper() != expected:
        handler._send({"status": 400, "message": "签名校验失败",
                       "data": {"expected": expected}})
        return
    handler._send({"status": 200, "message": "签名校验通过", "data": {"serverSign": expected}})


# ======================================================================
# 路由表
# ======================================================================
ROUTES = {
    # 政务 / 平台
    "/v1/users/login": handle_login,
    "/admin/resource/authority": handle_authority,
    "/admin/org/getTreeRootParentCodePage": handle_org_tree,
    "/dicts": handle_dicts,
    # 商城
    "/v1/goods": handle_goods,
    "/v1/orders": handle_create_order,
    "/v1/orders/cancel": handle_cancel_order,
    # 中台
    "/api/v1/datasource/list": handle_datasource_list,
    "/api/v1/job/run": handle_job_run,
    "/oauth/token": handle_oauth_token,
    # 老系统 / 报文
    "/v1/legacy/xml": handle_legacy_xml,
    "/v1/legacy/gbk": handle_legacy_gbk,
    "/v1/sign/verify": handle_sign_verify,
}


def serve(host=DEFAULT_HOST, port=DEFAULT_PORT):
    """启动服务（阻塞）。返回服务对象便于测试中优雅关闭。"""
    server = ThreadingHTTPServer((host, port), MockHandler)
    print("=" * 70)
    print("本地 mock 服务已启动：http://{}:{}".format(host, port))
    print("可用接口：")
    for path in sorted(ROUTES):
        print("    {}".format(path))
    print("-" * 70)
    print("跑用例（另开一个终端）：")
    print("    AMSAPI_BASE_URL=http://{}:{} python main.py".format(host, port))
    print("=" * 70)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止 mock 服务")
    finally:
        server.server_close()
    return server


def main():
    parser = argparse.ArgumentParser(description="本地 mock 服务（离线体验接口自动化框架）")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help="绑定地址，默认 {}（仅本机可见）".format(DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="端口，默认 {}".format(DEFAULT_PORT))
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
