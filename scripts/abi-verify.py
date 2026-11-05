#!/usr/bin/env python3
"""
构建后 ABI 全表自检。

做两件事:
  1. 直接读 vmlinux 里的 __crc_* 绝对符号 (= genksyms 为每个 EXPORT_SYMBOL 算的 CRC),
     与 `stock-versions.txt` 里从设备原厂 .ko 扒出来的 518 条记录逐条比对。
  2. 顺便报 module_layout 的 CRC —— 它是 struct module 布局的指纹, 也是
     vendor 模块最先卡住的那个符号。

为什么必须在构建阶段查:
  内核的 check_version() 是按 ____versions 顺序逐符号校验的, 第一个不匹配就
  request_module 失败并中止。所以设备上只会看到 module_layout 一条, 后面的
  printk / __stack_chk_fail 全被挡住看不见。只修 module_layout 是修不完的 ——
  必须整张表对上, 否则刷进去就是"模块能加载/不能加载"的随机结果。

真值来源:
  scripts/stock-versions.txt 由设备 /vendor/lib/modules 下的
  qca_cld3_wlan.ko (429 项) 与 audio_wcd_core.ko (131 项) 的 __versions 段
  合并去重而来, 两个模块对同一符号的 CRC 完全一致, 可互相印证。

用法: abi-verify.py out/vmlinux
"""
import os
import struct
import sys

EXPECTED_MODULE_LAYOUT = 0x4AD0CD64


def load_sections(path):
    data = open(path, "rb").read()
    if data[:4] != b"\x7fELF" or data[4] != 2:
        raise SystemExit("ERROR: %s 不是 ELF64" % path)
    shoff = struct.unpack_from("<Q", data, 0x28)[0]
    shentsize = struct.unpack_from("<H", data, 0x3A)[0]
    shnum = struct.unpack_from("<H", data, 0x3C)[0]
    shstrndx = struct.unpack_from("<H", data, 0x3E)[0]
    secs = []
    for i in range(shnum):
        o = shoff + i * shentsize
        (name, typ, flags, addr, off, size,
         link, info, align, entsize) = struct.unpack_from("<IIQQQQIIQQ", data, o)
        secs.append(dict(name_off=name, typ=typ, addr=addr, off=off, size=size,
                         link=link, entsize=entsize))
    stroff = secs[shstrndx]["off"]
    for s in secs:
        end = data.index(b"\0", stroff + s["name_off"])
        s["name"] = data[stroff + s["name_off"]:end].decode(errors="replace")
    return data, secs


def read_all_crcs(path):
    """vmlinux 里 __crc_xxx 是 ld -T <genksyms 的 .ver> 生成的绝对符号,
    st_shndx == SHN_ABS, st_value 就是 CRC 本身。
    老式做法里它也可能落在 __kcrctab 段, 两种都兼容。"""
    data, secs = load_sections(path)
    symtab = next((s for s in secs if s["typ"] == 2), None)
    if symtab is None:
        raise SystemExit("ERROR: vmlinux 没有 .symtab (被 strip 了?)")
    link = secs[symtab["link"]]
    strtab = data[link["off"]:link["off"] + link["size"]]
    entsize = symtab["entsize"] or 24
    crcs = {}
    for i in range(symtab["size"] // entsize):
        o = symtab["off"] + i * entsize
        st_name, st_info, st_other, st_shndx, st_value, st_size = \
            struct.unpack_from("<IBBHQQ", data, o)
        if st_shndx == 0:
            continue
        end = strtab.index(b"\0", st_name)
        if not strtab.startswith(b"__crc_", st_name):
            continue
        name = strtab[st_name:end].decode(errors="replace")[6:]
        if st_shndx == 0xFFF1:                      # SHN_ABS: 值即 CRC
            crcs[name] = st_value & 0xFFFFFFFF
        elif st_shndx < len(secs):
            sec = secs[st_shndx]
            nbytes = st_size if st_size in (4, 8) else 8
            raw = data[sec["off"] + (st_value - sec["addr"]):][:nbytes]
            if len(raw) == nbytes:
                crcs[name] = struct.unpack("<Q", raw.ljust(8, b"\0"))[0] & 0xFFFFFFFF
    return crcs


def load_stock(path):
    stock = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        crc_s, name = line.split(None, 1)
        stock[name] = int(crc_s, 16)
    return stock


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: abi-verify.py <vmlinux>")
    vmlinux = sys.argv[1]
    here = os.path.dirname(os.path.abspath(__file__))
    stock_path = os.path.join(here, "stock-versions.txt")
    if not os.path.exists(stock_path):
        raise SystemExit("ERROR: 缺少 %s" % stock_path)

    stock = load_stock(stock_path)
    crcs = read_all_crcs(vmlinux)
    print("=== [ABI-CHECK] vmlinux 里共 %d 个 __crc_*, 出厂表 %d 条 ==="
          % (len(crcs), len(stock)))

    got_ml = crcs.get("module_layout")
    print("  module_layout: 实测 %s  期望 0x%08x  %s"
          % ({None: "缺失"}.get(got_ml, "0x%08x" % got_ml),
             EXPECTED_MODULE_LAYOUT,
             "OK" if got_ml == EXPECTED_MODULE_LAYOUT else "MISMATCH"))

    mismatch, missing = [], []
    for name, want in stock.items():
        got = crcs.get(name)
        if got is None:
            missing.append(name)
        elif got != want:
            mismatch.append((name, got, want))

    print("  全表比对: 一致 %d / 不一致 %d / 缺失 %d"
          % (len(stock) - len(mismatch) - len(missing), len(mismatch), len(missing)))

    if mismatch:
        print("  --- 不一致 (前 40) ---")
        for name, got, want in mismatch[:40]:
            print("    %-34s 实测 0x%08x  期望 0x%08x" % (name, got, want))
        if len(mismatch) > 40:
            print("    ... 还有 %d 条" % (len(mismatch) - 40))
    if missing:
        print("  --- 缺失 (前 20) ---")
        for name in missing[:20]:
            print("    %s" % name)

    if got_ml != EXPECTED_MODULE_LAYOUT:
        print()
        print("=== [ABI-CHECK] FAIL: struct module 布局与出厂不一致 ===")
        print("  module_layout 是 genksyms 对 struct module 的摘要, 它不对就是布局不对。")
        print("  逐个字段排查 scripts/abi-align-414180.sh 的 5 个 patch:")
        print("   1) using_gplonly_symbols         (无 ifdef, 必须删)")
        print("   2) CONFIG_BPF_EVENTS 两字段       (无 prompt 的 default y, 只能源码摘)")
        print("   3) CONFIG_FUNCTION_ERROR_INJECTION 两字段")
        print("   4) CONFIG_ARM64_MODULE_PLTS 必须 =y (struct mod_arch_specific 差 3 指针+3 int)")
        print("   5) CONFIG_CFI_CLANG 必须关")
        sys.exit(1)

    if mismatch or missing:
        print()
        print("=== [ABI-CHECK] FAIL: 布局对了, 但有符号 CRC/导出状态不符 ===")
        print("  这类差异只可能来自: 源码版本与出厂不同 / 原型被 MIUI 改过 /")
        print("  某个 CONFIG 改变了头文件里的 typedef。按上面列出的符号逐个看声明。")
        sys.exit(1)

    print()
    print("=== [ABI-CHECK] PASS: 518 条出符号 CRC 全部一致, vendor .ko 必然可加载 ===")


if __name__ == "__main__":
    main()
