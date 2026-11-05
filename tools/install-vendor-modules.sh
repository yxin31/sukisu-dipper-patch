#!/system/bin/sh
# 把自编译的 wifi vendor 模块换进 /vendor/lib/modules
#
# 用法(设备上, root):
#   adb push vendor-modules.tar.gz /data/local/tmp/
#   adb shell su -c 'mkdir -p /data/local/tmp/vm && \
#       tar -xzf /data/local/tmp/vendor-modules.tar.gz -C /data/local/tmp/vm && \
#       sh /data/local/tmp/vm/install.sh'
#
#   sh install.sh check     只读检查, 不写任何东西 (推荐先跑这个)
#   sh install.sh install   真正替换 (默认)
#   sh install.sh rollback  从备份还原
#
# 注意: /vendor 是只读的 dm-verity 分区, 必须先关 verity 才能写:
#   adb root && adb disable-verity && adb reboot

set -u
DEST=/vendor/lib/modules
BAK=/data/local/tmp/vendor-modules-backup
SRC=$(cd "$(dirname "$0")" && pwd)
ACTION="${1:-install}"

say() { echo "[vm] $*"; }
die() { echo "[vm] ERROR: $*"; exit 1; }

[ "$(id -u)" = "0" ] || die "需要 root (su -c 'sh install.sh')"
[ -d "$DEST" ] || die "$DEST 不存在, 这不是 cepheus MIUI?"

KREL=$(uname -r)
say "内核 release: $KREL"
say "源目录      : $SRC"
say "目标        : $DEST"

# 每个 .ko 的 vermagic 与当前内核比对 —— 不一致的一律不能换进去
ko_vermagic() {
  strings -a "$1" 2>/dev/null | grep -m1 '^vermagic=' | sed 's/^vermagic=//'
}

# ---------------------------------------------------------------- rollback
if [ "$ACTION" = "rollback" ]; then
  [ -d "$BAK" ] || die "$BAK 里没有备份"
  n=0
  for f in "$BAK"/*.ko; do
    [ -f "$f" ] || continue
    b=$(basename "$f")
    cp -f "$f" "$DEST/$b" && { chmod 0644 "$DEST/$b"; n=$((n+1)); say "还原 $b"; }
  done
  [ "$n" -gt 0 ] || die "备份目录是空的"
  # 还原被禁用的内建替代品 (cnss_utils.ko.disabled -> cnss_utils.ko)
  for f in "$DEST"/*.ko.disabled; do
    [ -f "$f" ] || continue
    mv -f "$f" "${f%.disabled}" && { say "恢复 $(basename "${f%.disabled}")"; n=$((n+1)); }
  done
  say "还原了 $n 个, sync 后 reboot"
  sync
  exit 0
fi

# ------------------------------------------------------------------- check
if [ "$ACTION" = "check" ]; then
  say "== 本包内的模块 =="
  for f in "$SRC"/*.ko; do
    [ -f "$f" ] || continue
    printf '  %-28s %s\n' "$(basename "$f")" "$(ko_vermagic "$f")"
  done
  say "== 设备上现有的模块 =="
  for f in "$DEST"/qca_cld3_wlan.ko "$DEST"/cnss2.ko "$DEST"/cnss_utils.ko "$DEST"/cnss_prealloc.ko; do
    [ -f "$f" ] || { printf '  %-28s (不存在)\n' "$(basename "$f")"; continue; }
    printf '  %-28s %s\n' "$(basename "$f")" "$(ko_vermagic "$f")"
  done
  say "== 当前已加载 =="
  for m in cnss2 cnss_utils cnss_prealloc wlan qca_cld3_wlan; do
    [ -d "/sys/module/$m" ] && echo "  [LOADED] $m  refcnt=$(cat /sys/module/$m/refcnt 2>/dev/null)" \
                            || echo "  [  --  ] $m"
  done
  say "== /vendor 可写? =="
  if touch "$DEST/.vm_write_test" 2>/dev/null; then
    rm -f "$DEST/.vm_write_test"; say "可写 (verity 已关)"
  else
    say "不可写 —— 需要先: adb root && adb disable-verity && adb reboot"
  fi
  exit 0
fi

# ----------------------------------------------------------------- install
WORK=$(mktemp -d /data/local/tmp/vm.XXXXXX) || die "mktemp 失败"
trap 'rm -rf "$WORK"' EXIT

# ---- 1. 只挑 vermagic 与当前内核完全一致的模块 ----
say "逐个校验 vermagic (必须逐字符等于 $KREL)"
OK=""
for f in "$SRC"/*.ko; do
  [ -f "$f" ] || continue
  n=$(basename "$f")
  v=$(ko_vermagic "$f")
  if [ "$v" = "$KREL" ]; then
    cp -f "$f" "$WORK/$n" && OK="$OK $n"
    say "  [ok]   $n"
  else
    say "  [skip] $n  vermagic='$v' != '$KREL'"
  fi
done
[ -n "$OK" ] || die "没有一个模块的 vermagic 匹配, 别换了, 会白折腾"

# ---- 2. /vendor 可写? ----
if ! touch "$DEST/.vm_write_test" 2>/dev/null; then
  say "/vendor 只读, 尝试 remount rw"
  mount -o rw,remount /vendor 2>/dev/null || \
    mount -o rw,remount -t ext4 /dev/block/bootdevice/by-name/vendor /vendor 2>/dev/null || true
fi
touch "$DEST/.vm_write_test" 2>/dev/null || die "$DEST 不可写 —— 先执行:
       adb root && adb disable-verity && adb reboot"
rm -f "$DEST/.vm_write_test"
say "/vendor 可写"

# ---- 3. 备份 ----
mkdir -p "$BAK"
for n in $OK; do
  [ -f "$DEST/$n" ] && { [ -f "$BAK/$n" ] || cp -p "$DEST/$n" "$BAK/$n"; }
done
say "原厂模块已备份到 $BAK"

# ---- 4. 替换 ----
REPLACED=""
for n in $OK; do
  cp -f "$WORK/$n" "$DEST/$n" || die "拷贝 $n 失败"
  chmod 0644 "$DEST/$n"
  chcon u:object_r:vendor_file:s0 "$DEST/$n" 2>/dev/null || true
  REPLACED="$REPLACED $n"
  say "替换 $n"
done

# ---- 5. cnss_utils / cnss_prealloc 已内建进内核, 原厂那两个模块留着只会冲突 ----
for m in cnss_utils cnss_prealloc; do
  if [ -f "$DEST/$m.ko" ] && [ ! -f "$SRC/$m.ko" ]; then
    [ -f "$BAK/$m.ko" ] || cp -p "$DEST/$m.ko" "$BAK/$m.ko"
    mv -f "$DEST/$m.ko" "$DEST/$m.ko.disabled" 2>/dev/null && \
      say "禁用原厂 $m.ko (本内核已内建同名功能)"
  fi
done

sync
say "已替换:$REPLACED"
cat <<EOM

[vm] 完成。下一步:
     reboot
     重启后: dmesg | grep -iE 'cnss|wlan'  和  lsmod | grep -E 'cnss|wlan'
     要回滚: sh $SRC/install.sh rollback
EOM
