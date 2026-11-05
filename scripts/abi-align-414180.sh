#!/usr/bin/env bash
# =============================================================================
# 把 4.14.357-openela 树上 struct module 的布局, 逐字段还原成出厂 4.14.180 的布局
#
# 为什么必须做:
#   MIUI 12.5 的 /vendor/lib/modules/*.ko 是用出厂 4.14.180 头文件编译的。
#   内核加载 .ko 时会用 modversions 校验每个依赖符号的 CRC, 而 module_layout
#   这个"符号"的 CRC 就是 genksyms 对 struct module 的摘要。struct module 只要
#   多/少一个成员, CRC 就变, 整个模块直接被拒:
#       "disagrees about version of symbol module_layout"
#
#   更麻烦的是: 就算关掉 CONFIG_MODVERSIONS 强行放行(r7 干过这件事), 成员偏移
#   依然是错的 —— refcnt / exit / core_layout 全部错位, 第一次 try_module_get
#   就写坏内存, 表现为"能开机几秒 -> 重启循环"。
#   所以唯一正确的做法是让布局真的相等, 而不是绕过校验。
#
# 比对结果 (4.14.180 vs 4.14.357 的 include/linux/module.h), struct module
# 多出 4 处成员:
#   1) #ifdef CONFIG_CFI_CLANG  cfi_check   -> 用 gcc, 本来就为 0
#   2) bool using_gplonly_symbols; (无 ifdef) -> 稳定版新增, 删除
#   3) #ifdef CONFIG_BPF_EVENTS 两个字段      -> 该符号无 prompt 且 default y,
#                                                defconfig 关不掉, 只能改源码
#   4) #ifdef CONFIG_FUNCTION_ERROR_INJECTION 两个字段 -> 同上 (def_bool y)
# 另外 arch/arm64 的 ARM64_MODULE_PLTS 在 RELOCATABLE=n 时会被连带关掉,
# struct mod_arch_specific 少 40 字节, 把 arch 之后的所有成员都顶偏 —— 这一条
# 是 r6 (MODVERSIONS=y, 只报 module_layout) 的主因之一, 必须补回来。
#
# 用法: 在 kernel/ 目录下执行
#   bash ../this-repo/scripts/abi-align-414180.sh arch/arm64/configs/<defconfig>
# =============================================================================
set -euo pipefail

DEFCONFIG="${1:?usage: abi-align-414180.sh <defconfig path relative to kernel/> [strict|permissive]}"
MODE="${2:-strict}"
case "$MODE" in
  strict|permissive) ;;
  *) echo "ERROR: MODE 只能是 strict 或 permissive, 收到 '$MODE'"; exit 1 ;;
esac
echo "### ABI 对齐模式: $MODE"

echo "=== [ABI] 1/6 ARM64_MODULE_PLTS: 强制 default y (RELOCATABLE=n 时它会被关掉) ==="
python3 - <<'PY'
p = 'arch/arm64/Kconfig'
s = open(p).read()
if 'config ARM64_MODULE_PLTS' not in s:
    raise SystemExit('ERROR: arch/arm64/Kconfig 里找不到 ARM64_MODULE_PLTS')
if '\tdefault y\n\tselect ARM64_MODULE_CMODEL_LARGE' in s:
    print('already default y')
else:
    old = 'config ARM64_MODULE_PLTS\n\tbool\n\tselect ARM64_MODULE_CMODEL_LARGE'
    new = 'config ARM64_MODULE_PLTS\n\tbool\n\tdefault y\n\tselect ARM64_MODULE_CMODEL_LARGE'
    if old not in s:
        raise SystemExit('ERROR: ARM64_MODULE_PLTS 的 Kconfig 片段跟预期不一致')
    s = s.replace(old, new, 1)
    open(p, 'w').write(s)
    print('patched: default y')
PY
grep -A4 '^config ARM64_MODULE_PLTS$' arch/arm64/Kconfig || true

echo "=== [ABI] 2/6 include/linux/module.h: 摘掉 3 组多出来的成员 ==="
python3 - <<'PY'
p = 'include/linux/module.h'
s = open(p).read()

edits = [
    # (原样, 替换, 说明)
    ("\tbool using_gplonly_symbols;\n",
     "",
     "using_gplonly_symbols"),
    ("#ifdef CONFIG_BPF_EVENTS\n\tunsigned int num_bpf_raw_events;\n\tstruct bpf_raw_event_map *bpf_raw_events;\n#endif\n",
     "#if 0 /* ABI: 4.14.180 的 struct module 没有这两个成员 */\n\tunsigned int num_bpf_raw_events;\n\tstruct bpf_raw_event_map *bpf_raw_events;\n#endif\n",
     "BPF_EVENTS 字段"),
    ("#ifdef CONFIG_FUNCTION_ERROR_INJECTION\n\tstruct error_injection_entry *ei_funcs;\n\tunsigned int num_ei_funcs;\n#endif\n",
     "#if 0 /* ABI: 4.14.180 的 struct module 没有这两个成员 */\n\tstruct error_injection_entry *ei_funcs;\n\tunsigned int num_ei_funcs;\n#endif\n",
     "FUNCTION_ERROR_INJECTION 字段"),
]
for old, new, tag in edits:
    if new and new in s:
        print('already patched:', tag)
        continue
    if not new and old not in s:
        # 纯删除类改动 (old 不在 = 已经删过)
        print('already patched:', tag)
        continue
    if old not in s:
        raise SystemExit('ERROR: module.h 里找不到 %s 的定义片段' % tag)
    s = s.replace(old, new, 1)
    print('patched:', tag)
open(p, 'w').write(s)
assert 'using_gplonly_symbols' not in s
assert s.count('#if 0 /* ABI: 4.14.180 的 struct module 没有这两个成员 */') == 2
PY

echo "=== [ABI] 3/6 kernel/module.c: 摘掉已删字段的读写点 ==="
python3 - <<'PY'
import re
p = 'kernel/module.c'
s = open(p).read()

if 'if (0) { /* ABI: 字段已删' not in s:
    old = 'if (mod->using_gplonly_symbols) {'
    if old not in s:
        raise SystemExit('ERROR: 找不到 using_gplonly_symbols 的读取点')
    s = s.replace(old, 'if (0) { /* ABI: 字段已删, 见 module.h 补丁 */', 1)

if 'mod->using_gplonly_symbols = true;' in s:
    s = s.replace('mod->using_gplonly_symbols = true;', '(void)license;', 1)

# struct module 里已经删掉的两个"节区指针", 对应的 section_objs 调用一并去掉。
# 用正则吃掉跨行的续行, 不依赖具体缩进。
for pat, tag in (
    (r'mod->bpf_raw_events\s*=\s*section_objs\(.*?&mod->num_bpf_raw_events\);',
     'bpf_raw_events'),
    (r'mod->ei_funcs\s*=\s*section_objs\(.*?&mod->num_ei_funcs\);',
     'ei_funcs'),
):
    m = re.search(pat, s, re.S)
    if m:
        s = s[:m.start()] + '/* ABI: struct module 无 ' + tag + ' 字段 (4.14.180 布局) */' + s[m.end():]
        print('removed section_objs for', tag)
    else:
        print('already clean:', tag)

open(p, 'w').write(s)
assert 'using_gplonly_symbols' not in s
assert 'mod->bpf_raw_events' not in s
assert 'mod->ei_funcs' not in s
PY

echo "=== [ABI] 4/6 清掉 bpf_trace.c / error-inject.c 里对已删字段的引用 ==="
python3 - <<'PY'
import re

p = 'kernel/trace/bpf_trace.c'
s = open(p).read()
before = s
s = s.replace('btm->module->num_bpf_raw_events', '0 /* ABI: 字段已删 */')
s = s.replace('btp = &btm->module->bpf_raw_events[i];', 'btp = NULL; /* ABI: 字段已删 */')
s = s.replace('mod->num_bpf_raw_events == 0', '1 /* ABI: 字段已删 */')
if s != before:
    open(p, 'w').write(s)
    print('patched bpf_trace.c')
else:
    print('bpf_trace.c already clean')
for bad in ('num_bpf_raw_events', 'bpf_raw_events'):
    rest = [ln for ln in s.splitlines() if ln.strip().startswith(('mod->', 'btm->')) and bad in ln]
    assert not rest, 'residual %s reference: %r' % (bad, rest[:3])

p = 'lib/error-inject.c'
s = open(p).read()


def stub(src, fname, why):
    pat = r'static void ' + fname + r'\(struct module \*mod\)\n\{.*?\n\}'
    if not re.search(pat, src, re.S):
        return src, False
    return re.sub(
        pat,
        'static void %s(struct module *mod)\n{\n\t/* ABI: struct module 无 ei_funcs 字段 (4.14.180 布局) */\n\t(void)mod;%s\n}'
        % (fname, '' if why else ''),
        src, count=1, flags=re.S), True


s2, a = stub(s, 'module_load_ei_list', True)
s2, b = stub(s2, 'module_unload_ei_list', True)
if a or b:
    open(p, 'w').write(s2)
    print('patched error-inject.c (load=%s unload=%s)' % (a, b))
else:
    print('error-inject.c already clean')
assert 'mod->ei_funcs' not in s2
PY

echo "=== [ABI] 5/6 defconfig: MODVERSIONS 策略 (MODE=$MODE) ==="
# 两种模式, 用来做对照实验:
#
#   MODE=strict (默认, 安全)
#     CONFIG_MODVERSIONS=y 保持原样。struct module 布局虽然已对齐, 但 302 个
#     符号的 CRC 因 4.14.180 -> 4.14.357 的结构体漂移必然对不上, 其中就包括
#     module_layout, 所以 vendor .ko 仍然会被拒之门外 —— 与 r6 的行为一致。
#     内核本身干净, 用来证明"ABI 补丁没弄坏别的东西"。
#
#   MODE=permissive (实验)
#     CONFIG_MODVERSIONS=n + 强制 vermagic 保留 modversions 标记。
#     check_version() 变成恒返回 1 的 stub, vendor .ko 会被放行。
#     风险: 模块是按 4.14.180 的结构体布局编译的, 一旦它读写内核结构体内部的
#     字段(而不是只传指针), 就会在 4.14.357 的内核上踩到偏移错位 -> oops。
sed -i 's/^CONFIG_CFI_CLANG=y/# CONFIG_CFI_CLANG is not set/' "$DEFCONFIG"
grep -q '^# CONFIG_CFI_CLANG is not set' "$DEFCONFIG" || echo '# CONFIG_CFI_CLANG is not set' >> "$DEFCONFIG"

if [ "$MODE" = "permissive" ]; then
  sed -i 's/^CONFIG_MODVERSIONS=y/# CONFIG_MODVERSIONS is not set/' "$DEFCONFIG"
  grep -q 'CONFIG_MODVERSIONS' "$DEFCONFIG" || echo '# CONFIG_MODVERSIONS is not set' >> "$DEFCONFIG"
  echo "--- vermagic: 强制保留 modversions 标记 (MODVERSIONS 关了但标记要留) ---"
  python3 - <<'PY'
p = 'include/linux/vermagic.h'
s = open(p).read()
if '#if 1 /* forced-vendor-dlkm */' in s:
    print('already forced')
else:
    old = '#ifdef CONFIG_MODVERSIONS'
    if old not in s:
        raise SystemExit('ERROR: vermagic.h 里找不到 #ifdef CONFIG_MODVERSIONS')
    s = s.replace(old, '#if 1 /* forced-vendor-dlkm: modversions 关了但标记要留 */', 1)
    open(p, 'w').write(s)
    print('patched: MODULE_VERMAGIC_MODVERSIONS 恒为 "modversions "')
PY
  grep -n -A2 'MODULE_VERMAGIC_MODVERSIONS' include/linux/vermagic.h
else
  sed -i 's/^# CONFIG_MODVERSIONS is not set/CONFIG_MODVERSIONS=y/' "$DEFCONFIG"
  grep -q '^CONFIG_MODVERSIONS=y' "$DEFCONFIG" || echo 'CONFIG_MODVERSIONS=y' >> "$DEFCONFIG"
  echo "MODVERSIONS=y (strict): vendor .ko 会被 CRC 校验挡掉, 内核行为同 r6"
fi
grep -E '^CONFIG_MODVERSIONS=|^# CONFIG_MODVERSIONS' "$DEFCONFIG"
grep -E '^# CONFIG_CFI_CLANG is not set' "$DEFCONFIG" || true

echo "=== [ABI] 6/6 kernel/module.c: 埋 sizeof/offset 探针 (构建后可直读) ==="
# 关掉 MODVERSIONS 之后就没有 __crc_module_layout 可比了, 所以换一种不依赖
# genksyms 的硬指标: 在 vmlinux 里放几个数组, 数组长度 = sizeof / offsetof。
# 这些长度直接来自编译器, 读出来就能跟出厂 .ko 的实测值比对:
#   出厂 .ko 的 .gnu.linkonce.this_module: size=0x380, .init 重定位@0x150,
#                                        .exit 重定位@0x310
python3 - <<'PY'
p = 'kernel/module.c'
s = open(p).read()
if '__ksu_abi_sizeof_module' in s:
    print('already instrumented')
else:
    s += """
/*
 * ==== ABI 探针 (本仓库为对齐 MIUI vendor DLKM 而加, 无运行时开销) ====
 * 数组长度由编译器算, 落在 vmlinux 的 .bss 里, 符号的 st_size 就是测量值。
 * 与出厂 4.14.180 的 .gnu.linkonce.this_module (size=0x380, init@0x150,
 * exit@0x310) 比对, 就能在不刷机的前提下证明 struct module 布局一致。
 */
char __ksu_abi_sizeof_module[sizeof(struct module)] __used;
char __ksu_abi_off_module_init[__builtin_offsetof(struct module, init)] __used;
char __ksu_abi_off_module_exit[__builtin_offsetof(struct module, exit)] __used;
"""
    open(p, 'w').write(s)
    print('instrumented: 3 probes appended')
PY
tail -12 kernel/module.c

echo "=== [ABI] 出厂真值 (从设备 /vendor/lib/modules 实测) ==="
echo "  sizeof(struct module) = 0x380 (896)"
echo "  offsetof(init)        = 0x150 (336)"
echo "  offsetof(exit)        = 0x310 (784)"
echo "  vermagic              = 4.14.180-perf-gb24d113 SMP preempt mod_unload modversions aarch64"
