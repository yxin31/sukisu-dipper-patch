#!/system/bin/sh
# 把自编译的 wifi vendor 模块换进 /vendor/lib/modules
#
# 用法(设备上, root):
#   adb push vendor-modules.tar.gz /data/local/tmp/
#   adb shell su -c 'cd /data/local/tmp && tar -xzf vendor-modules.tar.gz -C vm && sh vm/install.sh'
#
# 或者把本脚本和 .ko 一起放到同一目录后直接:
#   su -c 'sh install.sh'
#
# 注意: /vendor 是只读的 dm-verity 分区, 必须先关 verity 才能写:
#   adb root && adb disable-verity && adb reboot
# 重启后再 adb root && adb remount (或本脚本里的 mount -o rw,remount)

set -u
DEST=/vendor/lib/modules
BAK=/data/local/tmp/vendor-modules-backup
SRC=$(cd "$(dirname "$0")" && pwd)

say() { echo "[vm] $*"; }
die() { echo "[vm] ERROR: $*"; exit 1; }

[ "$(id -u)" = "0" ] || die "需要 root (su -c 'sh install.sh')"
[ -d "$DEST" ] || die "$DEST 不存在, 这不是 cepheus MIUI?"

say "源目录: $SRC"
say "目标  : $DEST"

# ---- 1. 让 /vendor 可写 ----
if ! touch "$DEST/.vm_write_test" 2>/dev/null; then
  say "/vendor 只读, 尝试 remount rw"
  mount -o rw,remount /vendor 2>/dev/null || \
    mount -o rw,remount -t ext4 /dev/block/bootdevice/by-name/vendor /vendor 2>/dev/null || true
fi
if ! touch "$DEST/.vm_write_test" 2>/dev/null; then
  die "$DEST 仍然不可写 —— 需要先在电脑上执行:
       adb root && adb disable-verity && adb reboot
     重启后再跑一次本脚本 (或者 adb root && adb remount)"
fi
rm -f "$DEST/.vm_write_test"
say "/vendor 可写"

# ---- 2. 备份 ----
mkdir -p "$BAK"
say "备份到 $BAK (已存在的不覆盖)"
for f in "$DEST"/*.ko; do
  b="$BAK/$(basename "$f")"
  [ -f "$b" ] || cp -p "$f" "$b"
done

# ---- 3. 替换 ----
REPLACED=""
SKIPPED=""
for f in "$SRC"/*.ko; do
  [ -f "$f" ] || continue
  n=$(basename "$f")
  if [ -f "$DEST/$n" ]; then
    cp -f "$f" "$DEST/$n" || die "拷贝 $n 失败"
    chmod 0644 "$DEST/$n"
    chcon u:object_r:vendor_file:s0 "$DEST/$n" 2>/dev/null || true
    REPLACED="$REPLACED $n"
    say "替换 $n  ($(wc -c < "$f") bytes)"
  else
    SKIPPED="$SKIPPED $n"
    say "跳过 $n (设备上没有同名文件)"
  fi
done

[ -n "$REPLACED" ] || die "一个都没替换成功, 检查 tar 包内容"

# ---- 4. 报告仍然不匹配的原厂模块 ----
echo
say "已替换:$REPLACED"
[ -n "$SKIPPED" ] && say "未使用:$SKIPPED"

echo
say "剩下的原厂 .ko (它们的 CRC 与我们的内核不一致, 下次开机会报"
say "'disagrees about version of symbol module_layout', 属于预期):"
for f in "$DEST"/*.ko; do
  n=$(basename "$f")
  case " $REPLACED " in *" $n "*) continue;; esac
  echo "   $n"
done

cat <<'EOM'

[vm] 完成。下一步:
      sync
      reboot
     重启后看 dmesg | grep -i -E 'wlan|cnss' 以及 lsmod
     要回滚: 把 /data/local/tmp/vendor-modules-backup/*.ko 拷回 /vendor/lib/modules
EOM
