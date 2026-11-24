# -*- coding: utf-8 -*-
"""astro-best src.auth.nadc_oauth TokenStore 落盘安全回归 (A3 + 静态保护)。

钉住两代纪律:

A3 (POSIX 权限位): save 之后 token 缓存文件的权限位必须收敛到 0600, 包括
"文件已存在且原权限是 0644" 的场景 (os.open 的 mode 只对新建生效, 旧文件
会原样保留宽松权限位)。

静态保护 (auth §5.6): POSIX 权限位在 Windows 上退化 (chmod 只兑现只读标志,
st_mode 恒 0o666), 0600 在本机等于无保护 — 同机其他用户可原样读走 Bearer
凭据。故缓存文件按平台门禁加静态保护: Windows 走 DPAPI 密文 (v2 信封),
POSIX/回退走 base64 明文信封; 两代文件格式 (v2 信封 / v1 裸 JSON) 都必须
能读, 保护不可用不阻断 save/load 闭环。

全部离线: 只碰临时目录里的文件, 无网络无真实凭据。
"""
from __future__ import annotations

# 标准库: 读回 JSON 内容 / 权限位判定 (stat.S_IMODE) / 平台判别 (os.name,
# sys.platform) / 时间 (旧格式缓存的未过期时间戳) / 临时文件路径类型标注
import json
import os
import stat
import sys
import time
from pathlib import Path

# 第三方: 平台条件 skip; monkeypatch 记录 os.chmod 调用与 DPAPI 可用性
import pytest

# 本地: 被测 token 缓存存取器与静态保护内件 (回退路径要 patch 可用性探测;
# import 与 from-import 同模块, isort 要求 import 语句在前)
import src.auth.nadc_oauth as nadc_oauth
from src.auth.nadc_oauth import TokenStore, _protect_record, _unprotect_record


def _write_loose_token_file(path: Path) -> None:
    """手写一个 0644 的旧 token 文件 (宽松 umask/备份还原的既有状态)。"""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT, 0o644)  # 0o644 模拟备份还原后的宽松旧态
    with os.fdopen(fd, "w", encoding="utf-8") as fh:  # fdopen 接管 fd, 不留裸描述符泄漏
        json.dump({"access_token": "old-token"}, fh, ensure_ascii=False)  # 只需一个非空 token 键
    os.chmod(str(path), 0o644)  # 补刀: 部分平台 os.open 的 mode 受 umask 影响, 不保证落地


class TestTokenSavePermission:
    """A3 回归: save 必须把已存在文件的权限位收敛到 0600。"""

    @pytest.mark.skipif(os.name != "posix", reason="Windows 无 POSIX 权限位语义 (st_mode 恒 0o666)")
    def test_save_tightens_existing_file_to_0600(self, tmp_path):
        """POSIX: 0644 旧 token 文件经 save 后权限位必须实际变为 0600。

        验证的行为: 先落一个 0644 文件, save 后 stat.S_IMODE == 0o600。
        为什么重要: access_token 是 Bearer 凭据, 0644 让同机其他用户可读;
        os.open 的 mode 不修正已存在文件, 旧文件会带着宽松权限位一直活着。
        回归背景: docs/architecture/file-size-budget.md §6 A3。
        """
        path = tmp_path / "nadc_token.json"                              # 缓存文件名固定, 断言只看权限位
        _write_loose_token_file(path)                                    # 先造成 0644 的既有状态
        assert stat.S_IMODE(os.stat(str(path)).st_mode) == 0o644         # 前置: 确实宽松, 否则用例空转
        TokenStore(path=path).save({"access_token": "new-token", "expires_in": 3600})  # 走生产 save
        assert stat.S_IMODE(os.stat(str(path)).st_mode) == 0o600         # save 之后必须收敛到 0600

    def test_save_always_chmods_0600(self, tmp_path, monkeypatch):
        """跨平台: save 必须显式 chmod 0600 (Windows 权限位退化时的最小断言)。

        验证的行为: monkeypatch 记录 os.chmod 调用, save 后调用列表恰为
        [(path, 0o600)]。为什么重要: Windows 上 os.chmod 只兑现只读标志,
        st_mode 恒报 0o666, 权限位断言无从区分 0644/0600 — 记录 chmod 调用
        本身是唯一跨平台可判定的收敛证据。
        """
        path = tmp_path / "nadc_token.json"  # 与 POSIX 用例同路径, 变量只有可观测手段
        _write_loose_token_file(path)  # 同样从 0644 起步
        calls: list[tuple[str, int]] = []  # 收 (目标, 模式), 是跨平台唯一可判的收敛证据
        real_chmod = os.chmod  # 留真实实现, 记录后照常转调

        def recording_chmod(target, mode):
            """记录 (目标, 模式) 后转调真实 chmod (不改变落地行为)。"""
            calls.append((str(target), mode))  # 只记不改, 落地行为保持原样
            return real_chmod(target, mode)  # 转调真实 chmod, 权限位结果不变

        monkeypatch.setattr(os, "chmod", recording_chmod)  # 拦全局 os.chmod, save 内部也走它
        TokenStore(path=path).save({"access_token": "new-token", "expires_in": 3600})  # 内部 chmod 会被记录
        assert calls == [(str(path), 0o600)]  # 恰一次、恰 0600, 多一次少一次都算回归


class TestTokenFileNotPlaintext:
    """静态保护回归 (auth §5.6): 落盘文本不得含明文 Bearer 凭据。

    Windows 上 0600 不生效 (权限位语义退化), 保密责任改由 DPAPI 承担;
    回退路径 (DPAPI 不可用) 至少也过 base64 信封, 不让明文 token 直接
    躺在文件里 — 这三条断言跨平台可判, 不依赖具体保护算法。
    """

    def test_saved_file_contains_no_plaintext_token(self, tmp_path):
        """save 之后文件文本里不得出现明文 access_token。"""
        path = tmp_path / "nadc_token.json"  # 文件路径即被检查对象
        TokenStore(path=path).save({"access_token": "new-token", "expires_in": 3600})  # 正常 save 看落盘文本
        assert "new-token" not in path.read_text(encoding="utf-8")  # 含连字符, base64 字母表产不出

    def test_saved_file_is_versioned_envelope(self, tmp_path):
        """落盘内容必须是 v2 信封 (v 键 + protection + data_b64), 不是裸 token。"""
        path = tmp_path / "nadc_token.json"  # 同上, 只换断言维度
        TokenStore(path=path).save({"access_token": "new-token", "expires_in": 3600})  # 落盘一次供三断言复用
        envelope = json.loads(path.read_text(encoding="utf-8"))  # 解析成 dict 才谈得上键名断言
        assert envelope["v"] == 2  # v2 = 信封标记, v1 是裸 JSON
        assert envelope["protection"] in ("dpapi", "none")  # 保护方式必留痕, 不许缺键
        assert envelope["data_b64"]  # 载荷必须存在且非空

    def test_save_load_roundtrip(self, tmp_path):
        """save -> load 闭环: 同机同账号必须解回同一记录 (Windows 实测 DPAPI)。"""
        store = TokenStore(path=tmp_path / "nadc_token.json")  # 同一个 store 才验得出 save->load 闭环
        store.save({"access_token": "round-trip-token", "expires_in": 3600})  # 写入待取回的记录
        loaded = store.load()  # 同机同账号解回
        assert loaded is not None  # 解不出就是 None, 这里必须拿到记录
        assert loaded["access_token"] == "round-trip-token"  # 值逐字相同
        assert store.valid_token() == "round-trip-token"  # 过期判断层也要认这个 token

    def test_legacy_v1_plain_file_still_loads(self, tmp_path):
        """v1 裸 JSON 旧缓存 (2026-09-30 前) 必须照常可读, 下次 save 自动升级。"""
        path = tmp_path / "nadc_token.json"  # 旧缓存的落点
        path.write_text(json.dumps({"access_token": "legacy-token",
                                    "expires_at": time.time() + 3600}),
                        encoding="utf-8")  # 手写 v1 裸 JSON, 不经 save, 无信封
        store = TokenStore(path=path)  # 只是路径容器, 本用例不触发 save
        assert store.load()["access_token"] == "legacy-token"  # 旧格式必须照常可读
        assert store.valid_token() == "legacy-token"  # 未过期时间戳让校验层放行

    def test_dpapi_unavailable_falls_back_to_plain_envelope(self, tmp_path, monkeypatch):
        """DPAPI 探测为 False 时: protection=none 且 save/load 仍闭环 (可用性优先)。

        回归锚点: 保护不可用不能阻断鉴权 (登不进去比文件宽松更糟), 但回退
        必须留痕 (envelope 里记 none) — 静默回退会让"以为有保护"变成假象。
        """
        monkeypatch.setattr(nadc_oauth, "_dpapi_available", lambda: False)  # 强制走回退分支
        envelope = _protect_record({"access_token": "fallback-token", "expires_in": 3600})  # 仍须产信封
        assert envelope["protection"] == "none"  # 留痕: 静默回退会让"以为有保护"成假象
        assert _unprotect_record(envelope)["access_token"] == "fallback-token"  # 回退也解得开
        store = TokenStore(path=tmp_path / "nadc_token.json")  # 再验 TokenStore 这一层
        store.save({"access_token": "fallback-token", "expires_in": 3600})  # 保护缺失不阻断鉴权
        assert store.load()["access_token"] == "fallback-token"  # 闭环成立

    def test_corrupt_v2_envelope_loads_as_none(self, tmp_path):
        """v2 信封损坏/解不动时 load 返回 None (按无缓存走重新授权, 不抛)。"""
        path = tmp_path / "nadc_token.json"  # 损坏信封的落点
        path.write_text(json.dumps({"v": 2, "protection": "dpapi",
                                    "data_b64": "AAAA"}), encoding="utf-8")  # base64 合法但解不出内容
        assert TokenStore(path=path).load() is None  # 损坏按无缓存处理, 不抛异常


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI 仅 Windows (crypt32)")
class TestDpapiOnWindows:
    """Windows 实机 DPAPI 回归: 真加密、真解密、真拒解密 (其余平台跳过)。

    本机开发/CI 跑在 Windows 上时这些用例是真实执行的 (不是 mock): 钉住
    "CryptProtectData/CryptUnprotectData 的 ctypes 接线没坏" — 上面向
    函数的签名/结构体布局只靠 mock 是验不出来的。
    """

    def test_real_dpapi_roundtrip_and_rejection(self, tmp_path):
        """真 DPAPI: save 落 dpapi 密文, load 解回; 乱改密文则解不动。"""
        from src.auth.nadc_oauth import _dpapi_available, _dpapi_crypt  # 本地: 可用性探测 + 加解密原语

        assert _dpapi_available() is True  # 前置: 本机确实有 crypt32
        store = TokenStore(path=tmp_path / "nadc_token.json")  # 真 DPAPI 落盘目标
        store.save({"access_token": "real-dpapi-token", "expires_in": 3600})  # 走真实 CryptProtectData
        envelope = json.loads(store.path.read_text(encoding="utf-8"))  # 读回落盘信封
        assert envelope["protection"] == "dpapi"  # 本机必须真加密, 不是 base64 回退
        assert "real-dpapi-token" not in store.path.read_text(encoding="utf-8")  # 明文不许出现在密文文件里
        assert store.load()["access_token"] == "real-dpapi-token"  # 解回原值

        import base64  # 篡改密文要用 base64 搬运字节

        blob = bytearray(base64.b64decode(envelope["data_b64"]))  # 取出密文字节
        blob[-1] ^= 0xFF  # 翻最后一字节的 8 位: 单字节改动就足以破完整性
        tampered = {"v": 2, "protection": "dpapi",
                    "data_b64": base64.b64encode(bytes(blob)).decode("ascii")}  # 按 v2 原样重包
        assert _unprotect_record(tampered) is None  # 解不动必须回 None, 不给垃圾记录

        # 加解密原语本身也要闭环 (绕过信封直接验 ctypes 接线)
        assert _dpapi_crypt(_dpapi_crypt(b"payload", True), False) == b"payload"  # 加后再解还原字节
