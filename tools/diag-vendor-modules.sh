#!/system/bin/sh
# cepheus MIUI wifi/audio vendor 模块现场诊断 (只读, 不改任何文件)
#
# 用法(设备上, root):
#   adb push diag-vendor-modules.sh /data/local/tmp/
#   adb shell su -c 'sh /data/local/tmp/diag-vendor-modules.sh'
#
# 输出贴回来即可判断:
#   1) 出厂模块的 vermagic 是否与内核一致
#   2) 哪些 .ko 真的被 insmod 了 (时序在 init 哪一段)
#   3) wlan/cnss 到底卡在哪一步

set -u
M=/vendor/lib/modules
say() { echo; echo "===== $* ====="; }

say "uname / release"
uname -a
echo "kernel.release: $(cat /proc/version 2>/dev/null)"
echo "vermagic(sysfs): $(cat /sys/module/*/vermagic 2>/dev/null | head -1)"

say "模块目录 $M"
ls -la "$M" 2>/dev/null | head -60
echo "--- 总数: $(ls "$M"/*.ko 2>/dev/null | wc -l)"

say "已加载模块 (lsmod)"
lsmod 2>/dev/null | head -40

say "wifi 相关已加载"
for m in cnss2 cnss_utils cnss_prealloc wlan qca_cld3_wlan; do
  if [ -d "/sys/module/$m" ]; then
    echo "  [LOADED] $m"
    echo "    vermagic: $(cat /sys/module/$m/vermagic 2>/dev/null)"
    echo "    refcnt  : $(cat /sys/module/$m/refcnt 2>/dev/null)"
  else
    echo "  [  --  ] $m"
  fi
done

say "内核里已内建的 wifi/audio 符号 (判断内建是否生效)"
for s in cnss_utils_set_wlan_unsafe_channel cnss_prealloc_get qca_cld3_wlan_init; do
  if grep -q " $s" /proc/kallsyms 2>/dev/null; then
    echo "  [builtin] $s"
  else
    echo "  [   -   ] $s"
  fi
done

say "各 .ko 的 vermagic (与内核比对的关键)"
for f in "$M"/cnss*.ko "$M"/qca_cld3_wlan.ko "$M"/audio_wcd_core.ko "$M"/machine_dlkm.ko "$M"/bolero_cdc_dlkm.ko; do
  [ -f "$f" ] || continue
  v=$(strings -a "$f" 2>/dev/null | grep -m1 '^vermagic=' || echo '(none)')
  printf '%-46s %s\n' "$(basename "$f")" "$v"
done

say "wlan/cnss 相关 dmesg"
dmesg 2>/dev/null | grep -iE 'cnss|wlan|qca|wifi|subsys' | tail -80

say "模块加载失败记录"
dmesg 2>/dev/null | grep -iE 'disagrees about version|Unknown symbol|invalid module format|module verification|exec format' | tail -40

say "init 里谁 insmod 了 wifi (vendor/etc/init)"
grep -rn "insmod.*\(cnss\|wlan\|qca\)" /vendor/etc/init/ /vendor/etc/*.rc /system/etc/init/ 2>/dev/null | head -30

say "wifi 服务状态"
getprop | grep -iE 'wifi|wlan' | head -20
echo "--- interfaces:"
ip link show 2>/dev/null | grep -E '^[0-9]+:' | head -20

say "audio DLKM 状态"
for m in audio_wcd_core bolero_cdc_dlkm machine_dlkm pinctrl_wcd_dlkm swr_dlkm wcd9xxx_dlkm; do
  [ -d "/sys/module/$m" ] && echo "  [LOADED] $m"
done
dmesg 2>/dev/null | grep -iE 'wcd|bolero|asoc|sound' | tail -20

say "done"
cat <<'EOM'

把以上完整输出贴回来。重点看三块:
  1. uname 里的 4.14.x 与各 .ko 的 vermagic 是否逐字符相同
  2. wifi 相关 sys/module 下哪个 LOADED、哪个没有
  3. dmesg 里 "disagrees about version" 出现在哪个模块上
EOM
