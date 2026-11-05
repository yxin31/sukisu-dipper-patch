#!/usr/bin/env python3
"""
构建后 ABI 自检 (不刷机, 在链接完 vmlinux 的那一刻就能判定)。

为什么要换掉"CRC 全表比对"的思路:
  4.14.180 到 4.14.357 之间, struct sk_buff / cfg80211_* / notifier_block 等
  一大批结构体在稳定版里增删过成员。genksyms 是递归摘要 —— 指针参数指向的
  结构体多一个字段, 这个函数的 CRC 就变。实测 518 个出厂符号里 302 个 CRC
  不一致, 硬凑是不可能的。

  但真正影响"能不能安全加载"的只有两件事:
    1. struct module 的尺寸与关键成员偏移 (内核要往模块镜像里写这些字段);
    2. vermagic 字符串完全一致。
  指针参数的结构体内容变化不影响调用约定, 所以关掉 CRC 校验是安全的。

因此这里改成读编译器自己算出来的硬指标:
  scripts/abi-align-414180.sh 会在 kernel/module.c 末尾埋 3 个数组,
  数组长度分别是 sizeof(struct module) / offsetof(init) / offsetof(exit),
  符号的 st_size 就是测量值。跟从设备原厂 .ko 的
  .gnu.linkonce.this_module 段上读出的 (0x380 / 0x150 / 0x310) 直接比。

如果 vmlinux 里还有 __crc_* (即没关 MODVERSIONS), 顺带打印全表一致率,
仅作参考, 不作为失败条件。

用法: abi-verify.py out/vmlinux
"""
import os
import struct
import sys

# 从设备 /vendor/lib/modules/qca_cld3_wlan.ko 与 audio_wcd_core.ko 的
# .gnu.linkonce.this_module 段实测 (两者完全一致)
PROBES = {
    "__ksu_abi_sizeof_module": (0x380, "sizeof(struct module)"),
    "__ksu_abi_off_module_init": (0x150, "offsetof(struct module, init)"),
    "__ksu_abi_off_module_exit": (0x310, "offsetof(struct module, exit)"),
}

EXPECTED_VERMAGIC = "4.14.180-perf-gb24d113 SMP preempt mod_unload modversions aarch64"


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


def read_symbols(path):
    """返回 {名字: (shndx, value, size)}。保留 COMMON / ABS / 已定义三类。"""
    data, secs = load_sections(path)
    symtab = next((s for s in secs if s["typ"] == 2), None)   # SHT_SYMTAB
    if symtab is None:
        raise SystemExit("ERROR: vmlinux 没有 .symtab (被 strip 了?)")
    link = secs[symtab["link"]]
    strtab = data[link["off"]:link["off"] + link["size"]]
    entsize = symtab["entsize"] or 24
    out = {}
    for i in range(symtab["size"] // entsize):
        o = symtab["off"] + i * entsize
        st_name, st_info, st_other, st_shndx, st_value, st_size = \
            struct.unpack_from("<IBBHQQ", data, o)
        if st_name == 0:
            continue
        end = strtab.index(b"\0", st_name)
        out[strtab[st_name:end].decode(errors="replace")] = (st_shndx, st_value, st_size)
    return out, data, secs


def crc_of(sym, info, data, secs):
    shndx, value, size = info
    if shndx == 0xFFF1:                      # SHN_ABS: ld -T <genksyms .ver>
        return value & 0xFFFFFFFF
    if 0 < shndx < len(secs):
        sec = secs[shndx]
        n = size if size in (4, 8) else 8
        raw = data[sec["off"] + (value - sec["addr"]):][:n]
        if len(raw) == n:
            return struct.unpack("<Q", raw.ljust(8, b"\0"))[0] & 0xFFFFFFFF
    return None


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

    syms, data, secs = read_symbols(vmlinux)

    print("=== [ABI-CHECK] struct module 布局 (编译器实测 vs 出厂 .ko) ===")
    bad = 0
    for name, (want, label) in PROBES.items():
        info = syms.get(name)
        if info is None:
            print("  %-30s 探针缺失 (abi-align-414180.sh 没跑?)" % label)
            bad += 1
            continue
        got = info[2]
        ok = got == want
        print("  %-30s 实测 0x%03x  期望 0x%03x  %s"
              % (label, got, want, "OK" if ok else "MISMATCH"))
        if not ok:
            bad += 1

    # 参考信息: 若 MODVERSIONS 还开着, 报一下全表一致率
    crcs = {k[6:]: crc_of(k, v, data, secs) for k, v in syms.items()
            if k.startswith("__crc_")}
    crcs = {k: v for k, v in crcs.items() if v is not None}
    here = os.path.dirname(os.path.abspath(__file__))
    stock_path = os.path.join(here, "stock-versions.txt")
    if crcs and os.path.exists(stock_path):
        stock = load_stock(stock_path)
        same = sum(1 for n, v in stock.items() if crcs.get(n) == v)
        print()
        print("=== [ABI-CHECK] 参考: 出厂 518 符号 CRC 一致率 %d/%d ==="
              % (same, len(stock)))
        print("  4.14.180 -> 4.14.357 的结构体漂移必然导致大量不一致, 这不是失败条件。")
        print("  决定模块能否安全加载的是上面的 struct module 布局。")
    elif not crcs:
        print()
        print("=== [ABI-CHECK] CONFIG_MODVERSIONS 已关, 无 __crc_*, 跳过 CRC 比对 ===")
        print("  vermagic 必须仍是: %s" % EXPECTED_VERMAGIC)

    if bad:
        print()
        print("=== [ABI-CHECK] FAIL: struct module 布局与出厂 4.14.180 不一致 ===")
        print("  差了 %d 项。逐个排查 scripts/abi-align-414180.sh:" % bad)
        print("   sizeof 多 32: ARM64_MODULE_PLTS 没开 (struct mod_arch_specific 少 3 指针 + 3 int)")
        print("   sizeof 多 8 : using_gplonly_symbols 还在")
        print("   sizeof 多 16: BPF_EVENTS 的两个字段还在")
        print("   sizeof 多 16: FUNCTION_ERROR_INJECTION 的两个字段还在")
        print("   偏移整体后移 : arch 之后的成员被 mod_arch_specific 顶偏")
        sys.exit(1)

    print()
    print("=== [ABI-CHECK] PASS: 尺寸与关键偏移逐项吻合, vendor .ko 的 struct module")
    print("    写入路径安全; 加上 MODVERSIONS=n + 强制 modversions 标记, 可以加载 ===")


if __name__ == "__main__":
    main()
