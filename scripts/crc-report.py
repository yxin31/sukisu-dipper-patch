#!/usr/bin/env python3
"""
把 vmlinux 的 __crc_* 全表与出厂 4.14.180 的 518 条真值比对, 直接回答一个问题:

    "这棵源码树编出来的内核, 能不能安全加载设备上的原厂 vendor .ko?"

为什么必须要全表一致:
  Linux 4.14 的 load_module() 遍历模块的 ____versions 段, 逐个符号调用
  check_version(); 只要有一条 CRC 对不上就 printk "disagrees about version of
  symbol X" 并 return 0, 整个模块拒绝加载。所以"大部分一致"等于"全部失败"。

  CRC 由 genksyms 对类型定义递归摘要得出:
    - 标量参数的函数 (如 __kmalloc(size_t, gfp_t)) 只要签名不变, CRC 就永不变;
    - 指针参数指向的结构体多/少一个成员, CRC 立刻改变。
  因此 CRC 全表一致 <=> 源码里所有被导出的类型定义与出厂树一致。
  这是比"struct module 探针"更强也更省事的判定标准。

用法:
  crc-report.py <vmlinux> [--strict]
      默认只要有一致率报告就以退出码 0 结束; --strict 时不一致即失败。
"""
import os
import struct
import sys


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
    data, secs = load_sections(path)
    symtab = next((s for s in secs if s["typ"] == 2), None)
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


def crc_of(info, data, secs):
    shndx, value, size = info
    if shndx == 0xFFF1:                      # SHN_ABS
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
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strict = "--strict" in sys.argv
    if not args:
        raise SystemExit("usage: crc-report.py <vmlinux> [--strict]")
    vmlinux = args[0]

    syms, data, secs = read_symbols(vmlinux)
    got = {}
    for k, v in syms.items():
        if k.startswith("__crc_"):
            c = crc_of(v, data, secs)
            if c is not None:
                got[k[6:]] = c

    here = os.path.dirname(os.path.abspath(__file__))
    stock_path = os.path.join(here, "stock-versions.txt")
    if not os.path.exists(stock_path):
        raise SystemExit("ERROR: 找不到 %s" % stock_path)
    stock = load_stock(stock_path)

    print("=== [CRC] vmlinux 里 __crc_* 共 %d 条, 出厂真值 %d 条 ==="
          % (len(got), len(stock)))
    if not got:
        print("  本内核没开 CONFIG_MODVERSIONS, 无法比对。")
        sys.exit(0 if not strict else 1)

    same, diff, missing = [], [], []
    for name, want in stock.items():
        have = got.get(name)
        if have is None:
            missing.append(name)
        elif have == want:
            same.append(name)
        else:
            diff.append((name, want, have))

    print("  一致 %d / 不同 %d / 内核未导出 %d"
          % (len(same), len(diff), len(missing)))
    total = len(stock)
    if total:
        print("  一致率 %.2f%%" % (100.0 * len(same) / total))

    if diff:
        print()
        print("=== [CRC] 不一致的符号 (按名字排序, 前 60) ===")
        for name, want, have in sorted(diff)[:60]:
            print("  %-42s 出厂=0x%08x 本树=0x%08x" % (name, want, have))
        if len(diff) > 60:
            print("  ... 还有 %d 条" % (len(diff) - 60))

    if missing:
        print()
        print("=== [CRC] 内核根本没导出的符号 (%d 条, 前 30) ===" % len(missing))
        print("  " + ", ".join(sorted(missing)[:30]))

    print()
    if not diff and not missing:
        print("=== [CRC] PASS: 518 条全部一致 ===")
        print("    这棵树与出厂 4.14.180 的导出类型完全一致, vendor .ko 可以安全加载。")
        sys.exit(0)

    print("=== [CRC] FAIL: 与出厂不一致 ===")
    print("    CRC 由 genksyms 对类型定义递归摘要得出, 不一致说明结构体/函数签名有差异。")
    print("    MODVERSIONS=y 时这些模块会被整体拒载; 强行关校验则运行期踩内存。")
    sys.exit(1 if strict else 0)


if __name__ == "__main__":
    main()
