# -*- coding: utf-8 -*-
"""
闲鱼登录态自动续期脚本（扫码优先版）
========================================
用途：当 _m_h5_tk 签名 token 即将过期（闲鱼任务出现接口超时/筛选失效）时，
自动打开闲鱼登录页，用户用闲鱼 App 扫码即可完成登录，脚本自动导出
新的闲鱼 cookies 写回 state/acc_1.json。

流程：
  1. 打开闲鱼首页，触发登录 → passport.goofish.com 登录页（二维码）
  2. 用户在窗口内用闲鱼 App 扫码（最长等待 6 分钟）
  3. 登录成功后自动跳转闲鱼首页，等待网关下发新签名 token
  4. 导出 .goofish.com cookies 写回 state/acc_1.json（旧文件自动备份 .bak）
  5. 校验闲鱼会话标记（unb/tracknick/sgcookie）与 token 过期时间

备选：
  - 若登录页出现"账号密码登录"入口，脚本会尝试自动填账号密码
    （凭据来自 state/acc_credentials.json），遇验证码则由用户完成。

安全说明：
  - 账号密码仅存于 state/（该目录已被 .gitignore 排除，不会进入 git 仓库）
  - 脚本日志不打印密码明文
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state" / "acc_1.json"
CRED_FILE = ROOT / "state" / "acc_credentials.json"
LOG_FILE = ROOT / "logs" / "refresh_login.log"
# 持久化浏览器会话目录：首次登录后保存登录态，后续刷新直接复用，
# 无需再次扫码/输密码（会话 cookie 由 Playwright 持久化到该目录）。
PROFILE_DIR = ROOT / "state" / "browser_profile"

GOOFISH_HOME = "https://www.goofish.com/"
WAIT_VERIFY_SECONDS = 6 * 60  # 扫码/验证环节最长等待
POLL_INTERVAL = 3


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[ {ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
    except Exception:
        pass


def load_credentials() -> dict:
    if not CRED_FILE.exists():
        return {}
    try:
        with open(CRED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def to_unix_local(expires: float) -> str:
    if not expires or expires <= 0:
        return "会话(浏览器关闭失效)"
    return datetime.fromtimestamp(expires).strftime("%Y-%m-%d %H:%M:%S")


def merge_cookies_into_state(new_cookies: list[dict]) -> dict:
    """将新 cookies 合并进现有 state 文件（保留其他字段如 env/headers）"""
    state = {}
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}

    if "cookies" not in state:
        state["cookies"] = []
    state["cookies"] = new_cookies
    state["_refreshed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return state


def has_xianyu_session(ctx) -> bool:
    names = {c["name"] for c in ctx.cookies() if "goofish.com" in (c.get("domain") or "")}
    return "unb" in names and "tracknick" in names


def try_fill_password_login(page, username: str, password: str) -> bool:
    """闲鱼登录页存在'账号密码登录'标签时，主动切换并自动填写。
    返回是否已填写并点击登录。"""
    if not username or not password:
        return False

    def first_visible(cands):
        for sel in cands:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    # 先尝试切换到"账号密码登录"标签（闲鱼登录页默认可能是扫码）
    for tab_sel in [
        "text=账号密码登录",
        "text=密码登录",
        "text=帐号登录",
        "text=账号登录",
        "text=手机号登录",
        "div:has-text('密码登录')",
    ]:
        try:
            tab = page.locator(tab_sel).first
            if tab.is_visible(timeout=1500):
                tab.click()
                page.wait_for_timeout(1200)
                log(f"已切换到密码登录标签: {tab_sel}")
                break
        except Exception:
            continue

    user_box = first_visible([
        "#fm-login-id",
        "input[name='loginId']",
        "input[placeholder*='邮箱']",
        "input[placeholder*='手机号']",
        "input[placeholder*='账号']",
    ])
    pass_box = first_visible([
        "#fm-login-password",
        "input[name='password']",
        "input[type='password']",
    ])
    submit_btn = first_visible([
        "#fm-login-submit",
        "button[type='submit']",
        "button:has-text('登录')",
    ])
    if user_box and pass_box and submit_btn:
        try:
            user_box.click()
            user_box.fill(username)
            pass_box.click()
            pass_box.fill(password)
            page.wait_for_timeout(800)
            submit_btn.click()
            log("已自动填写账号密码并点击登录，等待验证...")
            return True
        except Exception as exc:
            log(f"自动填写登录信息失败（将转手动）: {exc}")
            return False
    return False


def main() -> None:
    cred = load_credentials()
    username = cred.get("username", "").strip()
    password = cred.get("password", "")

    with sync_playwright() as p:
        # 持久化上下文：保存登录会话，后续刷新无需重新登录
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()

        # ---------- 1. 打开闲鱼首页，触发登录 ----------
        log("打开闲鱼首页...")
        try:
            page.goto(GOOFISH_HOME, timeout=45000, wait_until="domcontentloaded")
        except Exception as exc:
            log(f"打开闲鱼首页失败: {exc}")
            ctx.close()
            sys.exit(1)
        page.wait_for_timeout(4000)

        # 若已带闲鱼会话，直接进入 token 刷新阶段
        if has_xianyu_session(ctx):
            log("检测到闲鱼会话已存在，无需重新登录。")
        else:
            # 触发登录：点击页面登录入口或直接导航到登录页
            login_clicked = False
            for sel in [
                "text=登录",
                "button:has-text('登录')",
                "a:has-text('登录')",
                "text=请登录",
                "text=立即登录",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1500):
                        el.click()
                        login_clicked = True
                        log(f"已点击登录入口: {sel}")
                        break
                except Exception:
                    continue
            if not login_clicked:
                # 直接导航到闲鱼登录页（二维码）
                page.goto(
                    "https://passport.goofish.com/mini_login.htm"
                    "?appName=xianyu&appEntrance=web&redirectType=redirect"
                    "&returnUrl=https%3A%2F%2Fwww.goofish.com%2F",
                    timeout=45000,
                    wait_until="domcontentloaded",
                )
                page.wait_for_timeout(4000)
                log("已打开闲鱼登录页（二维码）。")

            # ---------- 2. 等待用户扫码 / 自动填密码备选 ----------
            deadline = time.time() + WAIT_VERIFY_SECONDS
            logged_in = False
            password_tried = False
            while time.time() < deadline:
                page.wait_for_timeout(POLL_INTERVAL * 1000)

                if has_xianyu_session(ctx):
                    logged_in = True
                    log("检测到闲鱼登录成功（unb/tracknick 已下发）。")
                    break

                # 登录页出现账号密码框 → 自动填写（备选通道）
                if not password_tried:
                    password_tried = try_fill_password_login(page, username, password)

                # 等待二维码扫码完成
                if password_tried and not logged_in:
                    log("等待扫码/验证完成（请在窗口内用闲鱼 App 扫码或完成验证）...")
                else:
                    log("等待闲鱼登录完成（请用闲鱼 App 扫码登录）...")

            if not logged_in:
                log("等待超时，未能确认登录成功。请重试或手动完成登录。")
                ctx.close()
                sys.exit(1)

        # ---------- 3. 跳转闲鱼首页，等待新 token 下发 ----------
        log("跳转闲鱼首页，等待网关下发新签名 token...")
        old_tk_value = None
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, "r", encoding="utf-8") as _f:
                    _old = json.load(_f)
                _old_tk = next((c for c in (_old.get("cookies") or []) if c.get("name") == "_m_h5_tk"), None)
                old_tk_value = _old_tk.get("value") if _old_tk else None
        except Exception:
            pass
        try:
            page.goto(GOOFISH_HOME, timeout=45000, wait_until="domcontentloaded")
        except Exception as exc:
            log(f"打开闲鱼首页失败: {exc}")
            ctx.close()
            sys.exit(1)
        page.wait_for_timeout(3000)
        # 访问搜索页：页面会调用闲鱼搜索 API，响应会 Set-Cookie 轮换 _m_h5_tk。
        # 只打开首页不一定触发签名接口，导致"刷新了但 cookie 没更新"。
        for attempt in range(2):
            try:
                log(f"访问搜索页触发签名 token 轮换（第 {attempt + 1} 次）...")
                page.goto(
                    "https://www.goofish.com/search?q=%E6%89%8B%E8%A1%A8",
                    timeout=45000,
                    wait_until="domcontentloaded",
                )
                page.wait_for_timeout(6000)
            except Exception as exc:
                log(f"访问搜索页失败（不影响，继续）: {exc}")
                page.wait_for_timeout(6000)
            try:
                page.evaluate("window.scrollTo(0, 500)")
            except Exception:
                pass
            page.wait_for_timeout(3000)
            # 检查 token 是否已轮换
            try:
                page.goto(GOOFISH_HOME, timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
            except Exception:
                pass
            _cur_tk = next(
                (c for c in ctx.cookies() if c.get("name") == "_m_h5_tk" and "goofish.com" in (c.get("domain") or "")),
                None,
            )
            if _cur_tk is None:
                continue
            if old_tk_value and _cur_tk.get("value") == old_tk_value and attempt == 0:
                log("token 暂未轮换，再试一次...")
                continue
            break

        # ---------- 4. 导出 cookies 写回 state ----------
        cookies = ctx.cookies()
        gf_cookies = [c for c in cookies if "goofish.com" in (c.get("domain") or "")]
        if not gf_cookies:
            log("未获取到闲鱼域 cookies，可能未建立闲鱼会话。")
            ctx.close()
            sys.exit(1)

        if STATE_FILE.exists():
            bak = STATE_FILE.with_suffix(".json.bak")
            shutil.copy2(STATE_FILE, bak)
            log(f"已备份旧登录态 → {bak.name}")

        norm = []
        for c in gf_cookies:
            norm.append(
                {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c["domain"],
                    "path": c.get("path", "/"),
                    "expires": c.get("expires", -1),
                    "httpOnly": c.get("httpOnly", False),
                    "secure": c.get("secure", False),
                    "sameSite": c.get("sameSite"),
                }
            )

        state = merge_cookies_into_state(norm)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        log(f"已写入 {STATE_FILE.name}，共 {len(norm)} 个 cookies。")

        # ---------- 5. 验证结果 ----------
        tk = next((c for c in norm if c["name"] == "_m_h5_tk"), None)
        if tk:
            log(f"新 _m_h5_tk 过期时间: {to_unix_local(tk.get('expires', 0))}")
            if old_tk_value and tk.get("value") == old_tk_value:
                log(
                    "警告：新 _m_h5_tk 与旧值相同，网关可能未下发新 token；"
                    "若任务仍报登录失效，请再运行一次刷新或稍后重试。"
                )
            else:
                log("_m_h5_tk 已轮换为新值，续期成功。")
        else:
            log("警告：未找到 _m_h5_tk，可能需要重新登录确认。")

        names = {c["name"] for c in norm}
        missing = [k for k in ("unb", "tracknick", "sgcookie") if k not in names]
        if missing:
            log(f"警告：缺少闲鱼会话标记 {missing}，任务运行可能仍被判定为未登录。")
        else:
            log("闲鱼会话标记完整（unb/tracknick/sgcookie 均在）。")

        ctx.close()
        log("完成。可以在任务管理中重新启动任务验证。")
        sys.exit(0)


if __name__ == "__main__":
    main()
