#!/usr/bin/env python3
"""把 lelaonn/Cepheus_Raphael_Kernel_MI_A11 (MIUI A11 出货树) 修到能链接。

这两个坑都是 2026-11-05 run 41970947258 实测出来的, 不是猜的:

【坑 1】vmlinux.lds.S 里小米追加的 RTIC 段被放在了 STABS_DEBUG 之后
  STABS_DEBUG 的每个输出段都写死了 `0 :` (VMA 0), 处理完这些段之后
  链接器的 dot 就变成 0 了, 紧跟在后面的

      .bss : { /* bss segment */ RTIC_BSS }

  于是被摆在地址 0 附近。而 security/selinux/hooks.c 里被 __rticdata
  (include/linux/init.h: `__attribute__((section(".bss.rtic")))`) 修饰的
  selinux_state 正落在这个段里, 全树对它的 ADRP 就全部溢出:

      relocation truncated to fit: R_AARCH64_ADR_PREL_PG_HI21
          against symbol `selinux_state' defined in .bss.rtic section

  修法: 把 .bss.rtic 收进正常的 .bss —— 必须落在 __bss_stop 之前。
  只把那段往前挪到 STABS_DEBUG 之前也能"链接通过", 但那样 .bss.rtic 会
  排在 _end 之后, 而 arm64 只把 [_text, _end) 报给 memblock, 运行期这块
  内存会被页分配器踩掉, 表现就是开机后 selinux 随机崩。所以这里直接把
  BSS_SECTION 展开, 把 RTIC_BSS 放进 .bss 内部。

【坑 2】dsi_panel.c 无条件调用 is_tp_doubleclick_enable()
  定义在 drivers/input/touchscreen/double_click.c, 由
  CONFIG_TOUCHSCREEN_MI_DAVINCI_DOUBLE_CLICK 控制, 而
  cepheus_stock_defconfig 里根本没有这一行, Kconfig 里又是
  `bool "..."` 无 default → 默认 n → 目标文件不编译 → 链接期:

      undefined reference to `is_tp_doubleclick_enable'

  出厂内核要么没编这段代码, 要么这行被漏抄了。补 =y 即可, 对导出符号
  的 CRC 没有任何影响 (double_click.o 不导出 CRC 表里的符号)。
"""

import re
import sys
from pathlib import Path

LDS = Path("arch/arm64/kernel/vmlinux.lds.S")
DEFCONFIG = Path("arch/arm64/configs/cepheus_stock_defconfig")

OLD_BSS = "\tBSS_SECTION(0, 0, 0)\n"

NEW_BSS = """\t. = ALIGN(0);
\tVMLINUX_SYMBOL(__bss_start) = .;
\t.sbss : {
\t\t*(.dynsbss)
\t\t*(.sbss)
\t\t*(.scommon)
\t}
\t. = ALIGN(0);
\t.bss : {
\t\tBSS_FIRST_SECTIONS
\t\t*(.bss..page_aligned)
\t\t*(.dynbss)
\t\t*(BSS_MAIN)
\t\tRTIC_BSS
\t\t*(COMMON)
\t}
\t. = ALIGN(0);
\tVMLINUX_SYMBOL(__bss_stop) = .;
"""

# 末尾那个独立的 .bss 输出段, 连同注释一起删掉
TAIL_RE = re.compile(
    r"\n\t\.bss : \{\s*/\* bss segment\s*\*/\s*\n?\s*RTIC_BSS\s*\n\t\}\n"
)


def die(msg):
    print("FATAL: " + msg, file=sys.stderr)
    sys.exit(1)


def read(p):
    # newline='' 禁止 CRLF 转换, 保证只在真正改动的地方产生 diff
    with open(p, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write(p, s):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def fix_lds():
    src = read(LDS)

    if "RTIC_BSS" not in src:
        die("vmlinux.lds.S 里没有 RTIC_BSS, 树变了, 先看现场")

    # 幂等: 已经补过就直接退出 (CI 上不会遇到, 本地反复跑时有用)
    if OLD_BSS not in src and NEW_BSS in src:
        print("[skip] vmlinux.lds.S 已经补过了")
        return

    if src.count(OLD_BSS) != 1:
        die("vmlinux.lds.S 里 BSS_SECTION(0, 0, 0) 不是恰好一处 (count=%d)"
            % src.count(OLD_BSS))

    if src.count("RTIC_BSS") != 2:  # 宏定义处 1 次 + 使用处 1 次
        die("RTIC_BSS 引用次数不是 2 (count=%d), 结构变了"
            % src.count("RTIC_BSS"))

    src = src.replace(OLD_BSS, NEW_BSS)

    new_src, n = TAIL_RE.subn("\n", src)
    if n != 1:
        die("没能删掉末尾的 .bss 输出段 (match=%d), 手工看一下" % n)
    src = new_src

    # 删掉后 RTIC_BSS 应该只剩两处: 宏定义 + 我们塞进 .bss 里的那一次
    if src.count("RTIC_BSS") != 2:
        die("删除后 RTIC_BSS 有 %d 处, 期望 2 (宏定义 + .bss 内使用)"
            % src.count("RTIC_BSS"))

    if ".bss : {" not in src:
        die("展开后找不到 .bss 输出段")
    i_rtic = src.rindex("RTIC_BSS")
    i_stop = src.index("VMLINUX_SYMBOL(__bss_stop)")
    if not i_rtic < i_stop:
        die("RTIC_BSS 没排在 __bss_stop 之前")

    write(LDS, src)
    print("[ok] vmlinux.lds.S: RTIC_BSS 已并入 .bss (__bss_stop 之前)")


def fix_defconfig():
    src = read(DEFCONFIG)
    want = "CONFIG_TOUCHSCREEN_MI_DAVINCI_DOUBLE_CLICK=y"

    if re.search(r"^# CONFIG_TOUCHSCREEN_MI_DAVINCI_DOUBLE_CLICK is not set$",
                 src, re.M):
        src = re.sub(r"^# CONFIG_TOUCHSCREEN_MI_DAVINCI_DOUBLE_CLICK is not set$",
                     want, src, flags=re.M)
    elif want not in src:
        if not src.endswith("\n"):
            src += "\n"
        src += want + "\n"
    else:
        print("[skip] defconfig 已经有 " + want)
        return

    write(DEFCONFIG, src)
    print("[ok] defconfig: " + want)


def main():
    if not LDS.is_file():
        die("当前目录不是内核源码树 (找不到 %s)" % LDS)
    if not DEFCONFIG.is_file():
        die("找不到 %s" % DEFCONFIG)
    fix_lds()
    fix_defconfig()


if __name__ == "__main__":
    main()
