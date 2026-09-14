#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trae CN 网页会话签到验证工具（方案 C：验证 star620 的云端思路）

思路（参考 star620/TRAE-Automatic-sign-in 的云端脚本）：
- 网页端登录态的 HttpOnly Cookie `X-Cloudide-Session`（约 14 天有效）
- 用它 POST /cloudide/api/v3/common/GetUserToken 换取全新 JWT（Cloud-IDE-JWT）
- 换来的 JWT + 「该账号独立随机 16 位设备」去执行每日签到

目的：验证「不依赖本机客户端注册设备、每账号用随机设备」能否在 api.trae.cn 签到。
若 code=0 成立，说明网页会话签到的设备校验与桌面链路不同，多账号可绕开一机一设备限制；
若仍 9074/9095，则说明服务端对设备校验与令牌来源无关，此路不通。

用法：
    python web_checkin.py --session "X-Cloudide-Session 的 Cookie 值"
    # 或环境变量：TRAE_SESSION=...

Cookie 获取（浏览器一次即可）：
1. 浏览器打开 https://www.trae.cn 并登录目标账号（手机验证码/扫码）
2. F12 → 应用(Application) → Cookie → https://www.trae.cn
3. 找到 `X-Cloudide-Session`，复制其 Value（可能很长，含 %2F 等无需转义）
"""

import json
import os
import random
import sys
import urllib.request

BASE = "https://api.trae.cn"


# 官方桌面客户端（TRAE SOLO CN）真实 UA，抓包确认；实测全链路可用
DEFAULT_UA = "VSCode 1.107.1 (TRAE SOLO CN)"


def post(path: str, headers: dict, body: str = "") -> tuple:
    req = urllib.request.Request(BASE + path, data=body.encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def get_token(session: str) -> str:
    """用 X-Cloudide-Session Cookie 换取全新 JWT"""
    headers = {
        "Cookie": "X-Cloudide-Session=" + session,
        "Referer": "https://www.trae.cn/",
        "Origin": "https://www.trae.cn",
        "User-Agent": DEFAULT_UA,
        "Accept": "application/json, text/plain, */*",
    }
    status, text = post("/cloudide/api/v3/common/GetUserToken", headers)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print("GetUserToken 返回非 JSON: HTTP %s %s" % (status, text[:300]))
        raise SystemExit(1)
    token = (data.get("Result") or {}).get("Token")
    if status != 200 or not token:
        raise RuntimeError("GetUserToken 失败: HTTP %s %s" % (status, text[:300]))
    return token


def call_api(path: str, token: str, device_id: str) -> dict:
    headers = {
        "Authorization": "Cloud-IDE-JWT " + token,
        "X-User-Region": "cn",
        "x-device-id": device_id,
        "Content-Type": "application/json",
        "User-Agent": DEFAULT_UA,
    }
    status, text = post(path, headers, "{}")
    try:
        return {"http": status, "body": json.loads(text)}
    except json.JSONDecodeError:
        return {"http": status, "body": {"raw": text[:300]}}


def main() -> int:
    session = (os.environ.get("TRAE_SESSION") or "").strip()
    if "--session" in sys.argv:
        idx = sys.argv.index("--session")
        if idx + 1 < len(sys.argv):
            session = sys.argv[idx + 1].strip()
    if not session:
        print("缺少 X-Cloudide-Session Cookie（--session 或环境变量 TRAE_SESSION）")
        return 1
    # 每次运行随机一个 16 位设备（复刻 star620 云端默认行为，用于验证）
    device = str(random.randint(10 ** 15, 10 ** 16 - 1))

    print("[1/3] 用 X-Cloudide-Session 换取 JWT ...")
    token = get_token(session)
    print("      成功，JWT 长度 =", len(token))

    print("[2/3] 查询签到状态 (device=%s) ..." % device)
    st = call_api("/trae/api/v2/ug/checkin_credits/status", token, device)
    sb = st["body"]
    print("      HTTP", st["http"], "| code", sb.get("code"),
          "| checked", sb.get("checked_in"), "| msg", str(sb.get("message"))[:60])

    print("[3/3] 领取签到 (随机设备) ...")
    cl = call_api("/trae/api/v2/ug/checkin_credits/claim", token, device)
    cb = cl["body"]
    # 9074 为偶发风控（实测随机设备可签到），换设备重试 2 次避免误判
    if cl["http"] == 200 and cb.get("code") == 9074:
        for attempt in range(2):
            device = str(random.randint(10 ** 15, 10 ** 16 - 1))
            print(f"      9074 偶发风控，换随机设备重试 ({attempt + 1}/2) ...")
            cl = call_api("/trae/api/v2/ug/checkin_credits/claim", token, device)
            cb = cl["body"]
            if cb.get("code") in (0, 200):
                break
    print("      HTTP", cl["http"], "| code", cb.get("code"),
          "| credits", cb.get("credits"), "| msg", str(cb.get("message"))[:80])
    ok = cl["http"] == 200 and (cb.get("code") in (0, 200) or cb.get("checked_in"))
    print("")
    print("✅ 网页会话 + 随机设备签到可行" if ok else
          "❌ 网页会话 + 随机设备仍被拒（设备校验与令牌来源无关，此路不通）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
