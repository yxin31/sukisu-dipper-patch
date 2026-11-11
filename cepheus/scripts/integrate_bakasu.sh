#!/usr/bin/env bash
# 把 BakaSU (ReSukiSU) v4.2 内核模块挂进 cepheus 4.14 内核树
#   模式: manual hook, 不带 susfs (susfs 需要 simonpunk 的 4.14 内核侧补丁, 官方只保证 5.10+)
# 用法: integrate_bakasu.sh <kernel_dir> <bakasu_dir>
# 幂等: 重复执行不会重复插入
set -euo pipefail

KERNEL_DIR=${1:?usage: integrate_bakasu.sh <kernel_dir> <bakasu_dir>}
BAKASU_DIR=${2:?usage: integrate_bakasu.sh <kernel_dir> <bakasu_dir>}

KERNEL_DIR=$(cd "$KERNEL_DIR" && pwd)
BAKASU_DIR=$(cd "$BAKASU_DIR" && pwd)

cd "$KERNEL_DIR"

[ -f drivers/Makefile ] || { echo "ERROR: $KERNEL_DIR 不是内核树 (缺 drivers/Makefile)"; exit 1; }
[ -f "$BAKASU_DIR/kernel/Kconfig" ] || { echo "ERROR: $BAKASU_DIR 不是完整的 BakaSU (缺 kernel/Kconfig)"; exit 1; }

# 1) 软链 drivers/kernelsu -> BakaSU/kernel
#    必须用绝对路径软链: BakaSU 的 Kbuild 用 $(KSU_SRC)/../.git 判断 git 仓库,
#    内核路径解析会先展开软链再处理 "..", 因此软链目标必须指向真正的 bakasu 目录。
rm -rf drivers/kernelsu
ln -sfn "$BAKASU_DIR/kernel" drivers/kernelsu
echo "[1/6] drivers/kernelsu -> $(readlink drivers/kernelsu)"

# 2) drivers/Makefile
if grep -q 'kernelsu' drivers/Makefile; then
    echo "[2/6] drivers/Makefile: 已存在"
else
    printf 'obj-$(CONFIG_KSU) += kernelsu/\n' >> drivers/Makefile
    echo "[2/6] drivers/Makefile: 已追加"
fi

# 3) drivers/Kconfig: 插在最后一个 endmenu 之前
python3 - drivers/Kconfig <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
if 'kernelsu/Kconfig' in s:
    print('[3/6] drivers/Kconfig: 已存在')
else:
    i = s.rstrip().rfind('endmenu')
    if i < 0:
        sys.exit('drivers/Kconfig: 找不到 endmenu')
    s = s[:i] + 'source "drivers/kernelsu/Kconfig"\n\n' + s[i:]
    open(p, 'w').write(s)
    print('[3/6] drivers/Kconfig: 已插入')
PY

# 4) kernel/reboot.c
#    这棵树的原始代码只调用不判返回值:
#        ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);
#    BakaSU 的实现返回 0 表示 "这次 reboot 是 supercall, 已处理",
#    不判返回值的话 supercall 走不到, 表现为 root 装上了但所有提权失败。
python3 - kernel/reboot.c <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
old = '\tksu_handle_sys_reboot(magic1, magic2, cmd, &arg);'
new = '\tif (!ksu_handle_sys_reboot(magic1, magic2, cmd, &arg))\n\t\treturn 0;'
if new in s:
    print('[4/6] reboot.c: 已打过')
elif old in s:
    open(p, 'w').write(s.replace(old, new, 1))
    print('[4/6] reboot.c: 已打补丁')
else:
    sys.exit('[4/6] reboot.c: 找不到 ksu_handle_sys_reboot 调用点, 树结构与预期不符')
PY

# 5) include/linux/compiler_types.h
#    vdso 预处理阶段拿不到 __has_attribute, 会报 "missing binary operator before token ("。
python3 - include/linux/compiler_types.h <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
if '#if __has_attribute(__fallthrough__)' in s:
    open(p, 'w').write(s.replace('#if __has_attribute(__fallthrough__)', '#if 1', 1))
    print('[5/6] compiler_types.h: fallthrough 保护改为 #if 1')
else:
    print('[5/6] compiler_types.h: 无需修改')
PY

# 6) 校验
echo "[6/6] === 校验 ==="
ls -l drivers/kernelsu/Kconfig drivers/kernelsu/Kbuild
grep -n 'kernelsu' drivers/Makefile drivers/Kconfig | head -5
grep -n -A2 'ksu_handle_sys_reboot' kernel/reboot.c | head -6
echo "OK: BakaSU 集成完成"
