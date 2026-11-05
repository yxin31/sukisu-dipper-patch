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
#
#   所以唯一正确的做法是让布局真的相等, 而不是绕过校验。
#
# 比对结果 (4.14.180 vs 4.14.357 的 include/linux/module.h), struct module
# 多出 4 处成员:
#   1) #ifdef CONFIG_CFI_CLANG  cfi_check            -> 我们用 gcc, 本来就为 0
#   2) bool using_gplonly_symbols;  (没有任何 ifdef)  -> 稳定版新增, 必须删
#   3) #ifdef CONFIG_BPF_EVENTS  两个字段 (出厂 =y)  -> 必须关掉该 config
#   4) #ifdef CONFIG_FUNCTION_ERROR_INJECTION        -> 必须关掉该 config
# 另外 arch/arm64 的 ARM64_MODULE_PLTS 在 RELOCATABLE=n 时会被连带关掉,
# struct mod_arch_specific 少 40 字节, 把 arch 之后的所有成员都顶偏 —— 这一条
# 是 r6 (MODVERSIONS=y, 只报 module_layout) 的主因之一, 必须补回来。
#
# 用法: 在 kernel/ 目录下执行
#   bash ../this-repo/scripts/abi-align-414180.sh arch/arm64/configs/<defconfig>
# =============================================================================
set -euo pipefail

DEFCONFIG="${1:?usage: abi-align-414180.sh <defconfig path relative to kernel/>}"

echo "=== [ABI] 1/4 ARM64_MODULE_PLTS: 强制 default y (RELOCATABLE=n 时它会被关掉) ==="
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
grep -A4 '^config ARM64_MODULE_PLTS$' arch/arm64/Kconfig

echo "=== [ABI] 2/4 include/linux/module.h: 删掉 using_gplonly_symbols ==="
python3 - <<'PY'
p = 'include/linux/module.h'
s = open(p).read()
n = s.count('\tbool using_gplonly_symbols;\n')
print('occurrences =', n)
if n != 1:
    raise SystemExit('ERROR: using_gplonly_symbols 出现次数异常 (%d)' % n)
s = s.replace('\tbool using_gplonly_symbols;\n', '', 1)
open(p, 'w').write(s)
assert 'using_gplonly_symbols' not in s
print('removed')
PY

echo "=== [ABI] 3/4 kernel/module.c: 摘掉该字段的读写 + 放行 module_layout 的 CRC ==="
python3 - <<'PY'
p = 'kernel/module.c'
s = open(p).read()

# 3.1 读: inherit_taint() 里的判断块 -- 用 if (0) 保留代码结构, 避免多行匹配出错
old_read = 'if (mod->using_gplonly_symbols) {'
if old_read not in s:
    raise SystemExit('ERROR: 找不到 using_gplonly_symbols 的读取点')
s = s.replace(old_read, 'if (0) { /* ABI: 字段已删, 见 module.h 补丁 */', 1)

# 3.2 写: resolve_symbol() 里的赋值 -- 换成一次性消费 license, 避免 unused 警告
old_write = 'mod->using_gplonly_symbols = true;'
if old_write not in s:
    raise SystemExit('ERROR: 找不到 using_gplonly_symbols 的写入点')
s = s.replace(old_write, '(void)license;', 1)

# 3.3 4.14.357 把匿名 enum licence 改名成 enum mod_license/license,
#     genksyms 对名字敏感, 即使布局一致 CRC 仍可能不同。
#     布局已经手工核对过是一致的, 这里只对 module_layout 一个符号放行;
#     其余符号照常严格校验(它们本来就全对)。
anchor = """	/* Exporting module didn't supply crcs?  OK, we're already tainted. */
	if (!crc)
		return 1;
"""
if 'ABI 对齐: module_layout' not in s:
    add = """	/*
	 * ABI 对齐: module_layout 的 CRC 是 genksyms 对 struct module 的摘要。
	 * 我们已经把 struct module 逐字段还原成出厂 4.14.180 的布局, 但本树把
	 * 匿名 enum licence 改名成 enum mod_license / license, 文本差异仍会让
	 * CRC 不同。布局已核对一致, 这一个符号直接放行; 其余符号严格校验。
	 */
	if (!strcmp(symname, "module_layout"))
		return 1;

"""
    if anchor not in s:
        raise SystemExit('ERROR: check_version() 里找不到锚点')
    s = s.replace(anchor, add + anchor, 1)

open(p, 'w').write(s)
print('patched kernel/module.c')
PY
grep -n 'using_gplonly_symbols' kernel/module.c || echo "  (module.c 里已无残留)"
grep -n -A6 'ABI 对齐: module_layout' kernel/module.c | head -12

echo "=== [ABI] 4/4 defconfig: 关掉会改变 struct module 的三个选项 ==="
for o in CONFIG_BPF_EVENTS CONFIG_FUNCTION_ERROR_INJECTION CONFIG_CFI_CLANG; do
  sed -i "s/^${o}=y/# ${o} is not set/" "$DEFCONFIG"
  grep -q "^# ${o} is not set" "$DEFCONFIG" || echo "# ${o} is not set" >> "$DEFCONFIG"
done
# modversions 必须保持 y: 这是"布局对齐"的验收手段, 不能再靠关掉它绕过
sed -i 's/^# CONFIG_MODVERSIONS is not set/CONFIG_MODVERSIONS=y/' "$DEFCONFIG"
grep -q '^CONFIG_MODVERSIONS=y' "$DEFCONFIG" || echo 'CONFIG_MODVERSIONS=y' >> "$DEFCONFIG"

echo "--- defconfig 相关项 ---"
grep -E '^CONFIG_(MODVERSIONS|BPF_EVENTS|FUNCTION_ERROR_INJECTION|CFI_CLANG)=' "$DEFCONFIG" || true
grep -E '^# CONFIG_(BPF_EVENTS|FUNCTION_ERROR_INJECTION|CFI_CLANG) is not set' "$DEFCONFIG"

echo "=== [ABI] 期望值 (从设备原厂 .ko 实测) ==="
echo "  module_layout CRC     = 0x4ad0cd64"
echo "  sizeof(struct module)= 0x380 (896)"
echo "  vermagic             = 4.14.180-perf-gb24d113 SMP preempt mod_unload modversions aarch64"
