#!/usr/bin/env python3
"""
构建后 ABI 自检: 直接读 vmlinux 里的 __kcrctab, 把内核为导出符号算出的 CRC
跟出厂 vendor 模块记录的 CRC 对上。

为什么要在构建阶段查:
  刷一次机要重启 + 冒险, 而 ABI 对不对其实在链接完 vmlinux 的那一刻就定了。
  这里只要 __crc_module_layout 对上 0x4ad0cd64, 就说明 struct module 的布局
  与出厂 4.14.180 完全一致, /vendor/lib/modules 下的 .ko 必然加载成功。

真值来源: 从设备 /vendor/lib/modules 拖回的 qca_cld3_wlan.ko (429 项)
与 audio_wcd_core.ko (131 项) 的 __versions 段, 两者数值完全一致。

注意: __crc_* 在 4.14 是 unsigned long (8 字节), 因为 arm64 4.14 没有
CONFIG_HAVE_ARCH_PREL32_RELOCATIONS, 也就没有 CONFIG_MODULE_REL_CRCS。
这里按 st_size 自动判断 4/8 字节, 两种情况都能读。

用法: abi-verify.py out/vmlinux
"""
import struct
import sys

# 出厂 .ko 里记录的期望值
EXPECTED = {
    # 决定 struct module 布局 —— 全部 27 条 dmesg 报错都是它
    "module_layout": 0x4AD0CD64,
    # 下面三个是"读取方法对照": 它们能对上, 说明读取姿势没问题,
    # module_layout 要是对不上就一定是布局问题, 不是脚本问题。
    "printk": 0x985558A1,
    "__stack_chk_fail": 0xF0FDF6CB,
    "__kmalloc": 0xD2B09CE5,
}


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


def read_crcs(path):
    """返回 {符号名: (crc, 所在段, 字节数)}。

    关键点: 要找的是 `__crc_<sym>` 这个符号, 而不是 `<sym>` 本身。
    第一版脚本漏了前缀, 结果读到 .text 里函数的第一条指令, 三个符号全"对不上"。
    """
    data, secs = load_sections(path)
    symtab = next((s for s in secs if s["typ"] == 2), None)  # SHT_SYMTAB
    if symtab is None:
        raise SystemExit("ERROR: vmlinux 没有 .symtab (被 strip 了?)")
    link = secs[symtab["link"]]
    strtab = data[link["off"]:link["off"] + link["size"]]
    entsize = symtab["entsize"] or 24
    count = symtab["size"] // entsize

    wanted = {"__crc_" + k: k for k in EXPECTED}
    found = {}
    for i in range(count):
        o = symtab["off"] + i * entsize
        st_name, st_info, st_other, st_shndx, st_value, st_size = \
            struct.unpack_from("<IBBHQQ", data, o)
        if st_shndx == 0:
            continue
        end = strtab.index(b"\0", st_name)
        raw_name = strtab[st_name:end].decode(errors="replace")
        if raw_name not in wanted:
            continue
        key = wanted[raw_name]
        nbytes = st_size if st_size in (4, 8) else 8

        if st_shndx == 0xFFF1:
            # SHN_ABS: 老式 --defsym 写法给的绝对值, 本身就是 CRC
            found[key] = (st_value & 0xFFFFFFFF, "SHN_ABS", nbytes)
            continue
        if st_shndx >= len(secs):
            continue
        sec = secs[st_shndx]
        foff = sec["off"] + (st_value - sec["addr"])
        raw = data[foff:foff + nbytes]
        if len(raw) < nbytes:
            continue
        crc = struct.unpack("<I", raw[:4])[0] if nbytes == 4 \
            else struct.unpack("<Q", raw)[0]
        found[key] = (crc & 0xFFFFFFFF, sec["name"], nbytes)
    return found


def read_this_module_size(path):
    """vmlinux 里的 `__this_module` 就定义在 .gnu.linkonce.this_module 段,
    它的 st_size 就是 sizeof(struct module)。出厂 .ko 的同一段是 0x380。
    这个值不依赖 CRC 机制, 即使 CRC 读不到也能直接判断布局对不对。"""
    data, secs = load_sections(path)
    symtab = next((s for s in secs if s["typ"] == 2), None)
    if symtab is None:
        return None
    link = secs[symtab["link"]]
    strtab = data[link["off"]:link["off"] + link["size"]]
    entsize = symtab["entsize"] or 24
    for i in range(symtab["size"] // entsize):
        o = symtab["off"] + i * entsize
        st_name, st_info, st_other, st_shndx, st_value, st_size = \
            struct.unpack_from("<IBBHQQ", data, o)
        end = strtab.index(b"\0", st_name)
        if strtab[st_name:end] == b"__this_module":
            return st_size
    return None


EXPECTED_MODULE_SIZE = 0x380


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: abi-verify.py <vmlinux>")
    found = read_crcs(sys.argv[1])
    size = read_this_module_size(sys.argv[1])
    if size is not None:
        ok = size == EXPECTED_MODULE_SIZE
        print("=== [ABI-CHECK] sizeof(struct module) = 0x%x (期望 0x%x) %s ==="
              % (size, EXPECTED_MODULE_SIZE, "OK" if ok else "MISMATCH"))
    print("=== [ABI-CHECK] __kcrctab 实测 vs 出厂 .ko ===")
    bad, canary_bad = [], []
    for sym, want in EXPECTED.items():
        if sym not in found:
            print("  %-18s 未找到 (vmlinux 里没有 __crc_%s)" % (sym, sym))
            bad.append(sym)
            continue
        crc, sec, nbytes = found[sym]
        ok = crc == want
        print("  %-18s 实测 0x%08x  期望 0x%08x  %-8s (%d字节, 段 %s)"
              % (sym, crc, want, "OK" if ok else "MISMATCH", nbytes, sec))
        if not ok:
            bad.append(sym)
            if sym != "module_layout":
                canary_bad.append(sym)

    if size is not None and size != EXPECTED_MODULE_SIZE:
        print()
        print("=== [ABI-CHECK] FAIL: sizeof(struct module) 差了 %d 字节 ==="
              % (size - EXPECTED_MODULE_SIZE))
        print("  +32 通常是 ARM64_MODULE_PLTS 没了 (struct mod_arch_specific 少 3 指针 3 int)")
        print("  +8  通常是 using_gplonly_symbols 没删")
        print("  +16 通常是 BPF_EVENTS 的两个字段还在")
        print("  +16 通常是 FUNCTION_ERROR_INJECTION 的两个字段还在")
        sys.exit(1)

    if bad and len(canary_bad) == len([k for k in EXPECTED if k != "module_layout"]):
        print()
        print("=== [ABI-CHECK] FAIL: 连 printk/__kmalloc 都对不上 ===")
        print("  这不是布局问题, 是读取姿势或内核不同源。先查这几点:")
        print("   1) 内核树是否真为 4.14.180 同源分支 (看 kernel.release)")
        print("   2) CONFIG_MODVERSIONS 是否为 y (否则根本没有 __kcrctab)")
        print("   3) __crc_* 条目宽度是否被 CONFIG_MODULE_REL_CRCS 改成 4 字节")
        sys.exit(1)

    if bad:
        print()
        print("=== [ABI-CHECK] FAIL: struct module 布局与出厂不一致 ===")
        print("  对不上的是:", ", ".join(bad))
        print("  排查顺序:")
        print("   1) include/linux/module.h: using_gplonly_symbols 必须已删除")
        print("   2) CONFIG_BPF_EVENTS / CONFIG_FUNCTION_ERROR_INJECTION 的条件块要摘掉")
        print("   3) CONFIG_ARM64_MODULE_PLTS 必须 =y, 且 ARM64_MODULE_CMODEL_LARGE 跟着 =y")
        print("   4) CONFIG_MODULES / MODULE_UNLOAD / PREEMPT / SMP 必须与出厂一致")
        sys.exit(1)

    print()
    print("=== [ABI-CHECK] PASS: 与出厂 4.14.180 逐符号一致, vendor .ko 可以加载 ===")


if __name__ == "__main__":
    main()
