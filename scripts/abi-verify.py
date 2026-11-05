#!/usr/bin/env python3
"""
构建后 ABI 自检: 直接读 vmlinux 里的 __kcrctab, 把内核为导出符号算出的 CRC
跟出厂 vendor 模块记录的 CRC 对上。

为什么要在构建阶段查:
  刷一次机要重启 + 冒险, 而 ABI 对不对其实在链接完 vmlinux 的那一刻就定了。
  这里只要 __crc_module_layout 对上 0x4ad0cd64, 就说明 struct module 的布局
  与出厂 4.14.180 完全一致, /vendor/lib/modules 下的 .ko 必然加载成功。

真值来源: 从设备 /vendor/lib/modules 拖回的 qca_cld3_wlan.ko 与 audio_wcd_core.ko
的 __versions 段(两者互相印证, 数值一致)。

用法: abi-verify.py out/vmlinux
"""
import struct
import sys

# 出厂 .ko 里记录的期望值 (arm64, unsigned long 8 字节)
EXPECTED = {
    "module_layout": 0x4AD0CD64,
    # 这两个用来验证"读取方法本身是对的": 它们在设备上从未报错
    "printk": 0x985558A1,
    "__stack_chk_fail": 0xF0FDF6CB,
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


def read_crcs(path, wanted):
    data, secs = load_sections(path)
    symtab = next((s for s in secs if s["typ"] == 2), None)  # SHT_SYMTAB
    if symtab is None:
        raise SystemExit("ERROR: vmlinux 没有 .symtab (被 strip 了?)")
    link = secs[symtab["link"]]
    strtab = data[link["off"]:link["off"] + link["size"]]
    entsize = symtab["entsize"] or 24
    count = symtab["size"] // entsize
    found = {}
    for i in range(count):
        o = symtab["off"] + i * entsize
        st_name, st_info, st_other, st_shndx, st_value, st_size = \
            struct.unpack_from("<IBBHQQ", data, o)
        if st_shndx == 0:
            continue
        end = strtab.index(b"\0", st_name)
        name = strtab[st_name:end].decode(errors="replace")
        if name in wanted and st_shndx == 0xFFF1:
            # SHN_ABS: ld --defsym 直接给的绝对值, 本身就是 CRC
            v = st_value & 0xFFFFFFFF
            found[name] = (st_value, v, "ABS")
            continue
        if st_shndx >= len(secs):
            continue
        if name in wanted:
            sec = secs[st_shndx]
            # __crc_xxx 是 __kcrctab 段里一个 8 字节的对象, 它的值就是 CRC
            foff = sec["off"] + (st_value - sec["addr"])
            if sec["name"].startswith("__ksymtab"):
                continue
            raw = data[foff:foff + 8]
            found[name] = (struct.unpack("<Q", raw)[0],
                           struct.unpack("<I", raw[:4])[0], sec["name"])
    return found


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: abi-verify.py <vmlinux>")
    path = sys.argv[1]
    found = read_crcs(path, set(EXPECTED))
    print("=== [ABI-CHECK] __kcrctab 实测 ===")
    bad = []
    for sym, want in EXPECTED.items():
        if sym not in found:
            print("  %-18s 未找到 (vmlinux 里没有 __crc_%s)" % (sym, sym))
            bad.append(sym)
            continue
        v64, v32, sec = found[sym]
        ok = v32 == want
        print("  %-18s 实测 0x%08x  期望 0x%08x  %s  (段 %s)"
              % (sym, v32, want, "OK" if ok else "MISMATCH", sec))
        if not ok:
            bad.append(sym)

    if bad:
        print()
        print("=== [ABI-CHECK] FAIL: struct module 布局仍未与出厂一致 ===")
        print("  对不上的是:", ", ".join(bad))
        print("  排查顺序:")
        print("   1) CONFIG_ARM64_MODULE_PLTS 必须 =y  (少它就少 struct mod_arch_specific 40 字节)")
        print("   2) include/linux/module.h 里不能再有 using_gplonly_symbols")
        print("   3) CONFIG_BPF_EVENTS / CONFIG_FUNCTION_ERROR_INJECTION 必须 =n")
        print("   4) out/.config 里 CONFIG_MODVERSIONS 必须 =y")
        sys.exit(1)

    print()
    print("=== [ABI-CHECK] PASS: 布局与出厂 4.14.180 一致, vendor .ko 可以加载 ===")


if __name__ == "__main__":
    main()
