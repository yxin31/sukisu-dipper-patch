#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
让 pci-msm 在 cepheus 的 DTB 上能 probe 成功。

背景(实机 dmesg, 2026-11-05):

    pci-msm 1c00000.qcom,pcie: 1c00000.qcom,pcie supply vreg-3.3 not found, using dummy regulator
    msm_pcie_get_resources: Could not get required GPIO perst-gpio
    msm_pcie_probe: PCIe: Driver probe failed for RC0:-2

cepheus 原厂 DTB 的 /soc/qcom,pcie@1c00000 节点里**没有 perst-gpio 属性**
(只有 pinctrl-0 / clocks / resets / vreg-*)。原厂内核能跑, 说明 cepheus 上
PERST# 不是由 pci-msm 用 GPIO 拉的 —— QCA6390 的上电时序由 cnss 侧的
`wlan-en-gpio = <56 169 0>` (GPIO169) 控制。

但 Xirudly 这棵树把 perst-gpio 标成 required=true, 于是 probe 直接 -2 失败,
PCIe 控制器永远不绑定 -> cnss 拿不到 RC0 -> WiFi 起不来。

改三处:
  1. gpio 表里 perst 的 required 1 -> 0
  2. 5 处 gpio_set_value(perst...) 加 num 判空 (否则 num=0 会去拉 GPIO0,
     在 SM8150 上那不是网卡的脚)
  3. msm_pcie_gpio_deinit 的循环加判空 (原代码只看 gpio_n, perst 缺失时
     会 gpio_free(0))

幂等: 已改过就直接跳过。
"""
import io
import re
import sys

P = "drivers/pci/host/pci-msm.c"

PERST = "dev->gpio[MSM_PCIE_GPIO_PERST].num"


def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def write(p, s):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def main():
    s = read(P)
    orig = s
    changed = []

    # ---- 1. perst-gpio: required -> optional -------------------------------
    m = re.search(r'\{"perst-gpio",\s*0,\s*1,\s*0,\s*0,\s*([01])\}', s)
    if not m:
        sys.exit("FATAL: 找不到 perst-gpio 表项, 树变了, 先看现场")
    if m.group(1) == "1":
        s = s[: m.start()] + m.group(0)[:-2] + "0}" + s[m.end():]
        changed.append("perst-gpio required 1 -> 0")
    else:
        print("  [skip] perst-gpio 已经是 optional")

    # ---- 2. 5 处 gpio_set_value(perst) 加判空 ------------------------------
    pat = re.compile(
        r"gpio_set_value\(\s*" + re.escape(PERST) + r"\s*,\s*(.+?)\)\s*;",
        re.S,
    )

    def repl(mo):
        val = " ".join(mo.group(1).split())
        # 单行输出, 避免多行缩进对不齐 (内核不强制 80 列)
        return "if (" + PERST + ") gpio_set_value(" + PERST + ", " + val + ");"

    # 只替换还没被包过 if 的
    cnt = 0
    out = []
    last = 0
    for mo in pat.finditer(s):
        # 看这一处前面 40 字节里有没有刚生成的 if (...) 保护
        head = s[max(0, mo.start() - 60): mo.start()]
        if re.search(r"if\s*\(\s*" + re.escape(PERST) + r"\s*\)\s*$", head.rstrip()):
            continue
        out.append(s[last: mo.start()])
        out.append(repl(mo))
        last = mo.end()
        cnt += 1
    if cnt:
        out.append(s[last:])
        s = "".join(out)
        changed.append("%d 处 gpio_set_value(perst) 加判空" % cnt)
    else:
        print("  [skip] gpio_set_value(perst) 已全部有判空")

    # ---- 3. gpio_deinit 循环加判空 ----------------------------------------
    old_deinit = """	for (i = 0; i < dev->gpio_n; i++)
		gpio_free(dev->gpio[i].num);"""
    new_deinit = """	for (i = 0; i < dev->gpio_n; i++) {
		if (!dev->gpio[i].num)
			continue;
		gpio_free(dev->gpio[i].num);
	}"""
    if old_deinit in s:
        s = s.replace(old_deinit, new_deinit)
        changed.append("gpio_deinit 加判空")
    else:
        print("  [skip] gpio_deinit 已改过或格式不同")

    if s == orig:
        print("pci-msm: 无需改动")
        return

    write(P, s)
    print("pci-msm 已打补丁:")
    for c in changed:
        print("  -", c)

    # 自检
    s2 = read(P)
    assert re.search(r'\{"perst-gpio",\s*0,\s*1,\s*0,\s*0,\s*0\}', s2), "表项没改成 0"
    n_guard = len(re.findall(r"if \(" + re.escape(PERST) + r"\)\s*gpio_set_value", s2))
    n_set = len(re.findall(r"gpio_set_value\(\s*" + re.escape(PERST), s2))
    print("  自检: set_value=%d, 带判空=%d" % (n_set, n_guard))
    assert n_set == n_guard, "还有 %d 处没加判空" % (n_set - n_guard)


if __name__ == "__main__":
    main()
