# KernelSU + SUSFS for Xiaomi Mi 9 (cepheus)

为小米 9 / MIUI 12.5（Android 11）编译一个**既能 root、又能隐藏 root**的内核。
由 [xiziya/sukisu-dipper-patch](https://github.com/xiziya/sukisu-dipper-patch)（小米 8）改造而来，
root 用 KernelSU（KPROBES），隐藏用 SUSFS 4.14。

## 目标机器

| 项目 | 详情 |
|------|------|
| 设备 | 小米 9 (cepheus) / M1902F1G / F1A / F1T / F1C |
| 平台 | 骁龙 855 (SM8150) |
| 系统 | **MIUI V12.5.6.0.RFACNXM（Android 11）** |
| 原厂内核 | 4.14.180-perf-gb24d113 |
| 原厂基带 | 1.0.c3-00161-1018_1133_f7c3bc9ce |
| 内核源码 | [MiCode/Xiaomi_Kernel_OpenSource](https://github.com/MiCode/Xiaomi_Kernel_OpenSource) 分支 `cepheus-q-oss`（固定 commit `192eca855`） |
| 源码实际版本 | **4.14.117**（Android 10 基线，小米没开源 180） |
| Root 方案 | [KernelSU](https://github.com/tiann/KernelSU) `v1.0.5`（KPROBES，非 GKI） |
| 隐藏方案 | [SUSFS 4.14](https://gitlab.com/simonpunk/susfs4ksu)（v1.5.9，`kernel-4.14` 分支） |
| 编译器 | GCC 11 (aarch64-linux-gnu) |
| 产物 | **`boot.img`**（`fastboot flash boot` 直接刷） |

## 构建状态

已打通，产物可直接刷（GitHub Actions）：

| 项目 | 值 |
|------|-----|
| Release | [`ksususfs-v1.0.5-cepheus-192eca855`](../../releases/tag/ksususfs-v1.0.5-cepheus-192eca855) |
| boot.img 大小 | 35,565,568 B (33.92 MB) |
| MD5 | `f01a10262d5ebb15f2bd91e4f5872c08` |
| Image | 33,564,680 B（原厂 41.99 MB，见下文「为什么变小」） |
| vermagic | `4.14.180-perf-gb24d113`（与原厂完全一致） |
| 全流程耗时 | 约 12 分钟（4 vCPU runner） |

产物结构（本地实测解析）：

```
offset 0       ANDROID!              hdr ver=1, page_size=4096, ramdisk_size=0
offset 4096    "UNCOMPRESSED_IMG"   + u32=33564680
               arm64 Image          magic "ARMd", text_offset=0x80000
               5 个 concatenated FDT 共 1,995,189 B（原厂 dtb 一字未改）
               末尾 1583 B 补零到 4096 对齐
```

镜像内已确认含 `KernelSU` / `susfs` / `ksud` / `kprobe` 字符串，
`Linux version 4.14.180-perf-gb24d113 (gcc version 11.4.0)` 也在。

### 为什么 Image 比原厂小 8 MB

原厂 Image 41.99 MB，本项目 33.56 MB。差异来自 defconfig：
`cepheus_user_defconfig`（OSS 开源的用户版）与小米 MIUI 12.5 出厂用的
内部 defconfig 并不完全相同，出厂版内建了更多调试/日志/私有驱动。
**这不影响启动**（缺的部分大多在 `/vendor/lib/modules` 里作为 `.ko` 提供，
vermagic 已对齐所以能正常加载），但若刷后发现某个硬件（相机/指纹/WiFi）异常，
第一嫌疑就是 defconfig 差异，而不是补丁。


## 为什么是 KernelSU v1.0.5 而不是 SukiSU-Ultra

SUSFS 针对旧内核 4.14 的分支（v1.5.9）只提供**旧版 SUSFS API**，它的 KernelSU 侧补丁
（`10_enable_susfs_for_ksu.patch`）是**基于 upstream KernelSU `v1.0.5`** 写的。

而 SukiSU-Ultra（现代 v3/v4）已经迁移到**新版 SUSFS API**（`struct filename **` + 约 40 个新函数，
只支持 5.x 内核），也没有任何与 v1.0.5 对齐的旧 tag。所以：

- **4.14 内核 + 隐藏 root → upstream KernelSU `v1.0.5` + SUSFS 4.14** 是唯一能干净配对的组合。
- SukiSU-Ultra 的 manager APK 与本内核**不通用**，请用 KernelSU Manager v1.0.x。

## 原厂 boot.img 结构（已实测）

```
Android boot header v1, page_size=4096, ramdisk_size=0
kernel 段 @0x1000, 43,981,273 字节:
  [16B]  "UNCOMPRESSED_IMG"
  [ 4B]  u32 LE = 41,986,064      ← 下面 Image 的长度
  [ N ]  raw arm64 Image           ← magic "ARMd" @0x38, text_offset 0x80000
  [ M ]  dtb blob, 1,995,189 字节   ← 5 个 FDT 连在一起（不同面板/指纹 SKU）
尾部: AVB footer, original_image_size = 43,986,944
```

关键结论：

- **内核是未压缩的 `Image-dtb` 容器**，编译目标是 `Image`（不是 `Image.gz`）。
- **dtb 附在 kernel 段末尾**，所以这里直接**用原厂 header 模板重建 boot.img**，不丢 dtb。
- **没有 ramdisk**（ramdisk_size=0）。

`scripts/build_bootimg.py`：原厂 header 模板 → 写入 `UNCOMPRESSED_IMG + 新 Image 长度 + 新 Image + 原厂 dtb` → 4096 对齐。
用原厂 Image 反向跑，产物和原厂 `boot.img` 前 43,986,944 字节**逐字节一致**，已验证。

## 补丁清单

| 补丁 | 作用 | 打到哪 |
|------|------|--------|
| `cepheus-susfs-kernel.patch` | SUSFS 4.14 内核侧（21 文件：susfs.c/sus_su.c + 挂载/路径/kstat 隐藏） | 内核源码 |
| `ksu-susfs-v105.patch` | SUSFS 4.14 的 KernelSU 侧补丁（18 文件，基于 v1.0.5） | KernelSU `kernel/` |
| `backport-path-umount.patch` | 4.14 缺 `path_umount`，KernelSU 卸载模块需要 | 内核源码 |
| `allow-init-exec-ksud-under-nosuid.patch` | 允许 init 在 nosuid 挂载点执行 `ksud` | 内核源码 |

> `cepheus-susfs-kernel.patch` 相对官方 `50_add_susfs_in_kernel-4.14.patch` 做了这些 4.14/cepheus 适配：
> - 修掉官方补丁 `fs/dcache.c` 里残留的 `current->susfs_task_state`（官方 `e64d394` 重构漏改，会导致编译失败），统一为 `susfs_is_current_non_root_user_app_proc()`（thread_info 标志）。
> - `fs/namespace.c` 的 IDA 用 CAF 旧式 `ida_pre_get/ida_get_new_above` + `ida_simple_get/ida_simple_remove` 替代新版 `ida_alloc_min/ida_free`。
> - `fs/namei.c` 适配 cepheus 的 `lookup_slow`/`lookup_open(int *opened)`，并给 `struct nameidata` 补 `state` 字段。
> - `include/linux/mount.h` 直接加 `susfs_mnt_id_backup`（cepheus 无 Android KABI reserve）。

## 版本号对齐（重要）

workflow 会做三件事把内核版本号伪装成原厂值，让预编译 `.ko` 的 vermagic 能对上：

```make
Makefile:     SUBLEVEL = 180
defconfig:    CONFIG_LOCALVERSION="-perf-gb24d113"
              # CONFIG_LOCALVERSION_AUTO is not set
scripts/setlocalversion: 去掉自动追加的 "+"（见下）
```

`uname -r` 输出 `4.14.180-perf-gb24d113`，和原厂一致。内核代码本身仍是 4.14.117。

### 为什么必须干掉 `+`

内核源码是 git 仓库，打完 SUSFS/KernelSU 补丁后 working tree 变 dirty。
4.14 的 `scripts/setlocalversion` 在 `CONFIG_LOCALVERSION_AUTO=n` 时**仍然**会追加一个 `+`：

```sh
# scripts/setlocalversion:170-171
scm=$(scm_version --short)
res="$res${scm:++}"        # ← dirty 时 ${scm:++} 展开成 "+"
```

结果 `kernel.release` 变成 `4.14.180-perf-gb24d113+`，vermagic 也跟着变成
`...gb24d113+ SMP preempt mod_unload modversions aarch64`，
而 `/vendor/lib/modules/` 里的原厂 `.ko` 期望的是不带 `+` 的版本 →
**触屏、显示、WiFi 等所有 vendor 模块全部加载失败**（表现为开机后大量硬件不工作）。

workflow 里的处理：

```sh
sed -i 's|res="\$res${scm:++}"|res="$res"|' scripts/setlocalversion
```

并且构建完会硬校验：

```sh
REL=$(cat out/include/config/kernel.release)
[ "$REL" = "4.14.180-perf-gb24d113" ] || exit 1
```

> 注意 `CONFIG_LOCALVERSION_AUTO` 在 defconfig 里关掉**并不能**去掉 `+`，
> 它只影响要不要追加 `-g<hash>`；`+` 是独立的一段逻辑。

## 使用方法

### 1. 跑 Actions

本仓库 → Actions → **Build KernelSU + SUSFS for Xiaomi Mi 9 (cepheus)** → Run workflow。
约 12 分钟（4 vCPU runner，全量编译 4.14 + GCC 11）。可选参数 `ksu_ref`（默认 `v1.0.5`）和 `kernel_ref`（默认已固定）。

### 2. 下产物

两个入口都行：

- **Release**（推荐，长期有效）：[`ksususfs-v1.0.5-cepheus-192eca855`](../../releases/tag/ksususfs-v1.0.5-cepheus-192eca855)
- **Actions → Artifacts**（保留 30 天）：`KernelSU-SUSFS-cepheus-boot` → `boot.img` + `boot.img.md5`

刷之前先核 md5：

```bash
md5sum boot.img      # 应为 f01a10262d5ebb15f2bd91e4f5872c08
```

### 3. 刷入

```bash
fastboot getvar product          # 应该输出 cepheus
fastboot flash boot boot.img
fastboot reboot
```

### 4. 配置 root + 隐藏

开机后：

1. 装 **KernelSU Manager**（v1.0.x，与 `v1.0.5` 内核配套）授予 root。
2. 装 **SUSFS 模块 + `ksu_susfs` 工具**（来自 [susfs4ksu](https://gitlab.com/simonpunk/susfs4ksu) 仓库的 `ksu_module_susfs/`），用它配置要隐藏的路径 / 挂载 / uname / kstat。

只有内核打了 SUSFS，`ksu_susfs` 工具和 SUSFS 模块才会真正生效。

### 5. 回滚

```bash
fastboot flash boot <stock-boot.img>
```

## 用 GCC 11 编译 4.14 老内核：踩过的 10 个坑

小米这颗内核是 GCC 4.9 时代的代码，Ubuntu 22.04 只给到 GCC 11，两者之间隔着 6 年。
以下按失败顺序记录，全部已在 workflow 中自动修复（`Patch Makefiles for GCC compatibility` 步骤）：

| # | 现象 | 原因 | 处理 |
|---|------|------|------|
| 1 | `scripts/gcc-wrapper.py: TypeError: unsupported operand type(s) for >>` | 小米自带脚本是 Python 2 语法（`print >> sys.stderr`），Python 3 下崩溃并吞掉 gcc 输出 | 整个文件替换为 Python 3 直通脚本（只透传 stdout/stderr/退出码） |
| 2 | `'for' loop initial declarations are only allowed in C99`（`sucompat.c:301`） | 4.14 默认 `-std=gnu89` | `echo 'ccflags-y += -std=gnu99' >> KernelSU/kernel/Makefile` |
| 3 | `fatal error: linux/bits.h: No such file or directory` | `linux/bits.h` 是 5.0 才拆出来的，4.14 里 `BIT()` 还在 `linux/bitops.h` | 补丁里 `#include <linux/bits.h>` → `<linux/bitops.h>` |
| 4 | `'selinux_state' undeclared` | `selinux_state` 是 5.7+ 的全局结构体，4.14 用裸变量 `selinux_enforcing` | `ksu-4.14-selinux.patch`：`#if LINUX_VERSION_CODE >= KERNEL_VERSION(5,7,0)` 双分支 |
| 5 | `'struct policydb' has no member named 'type_val_to_struct'` | 4.14 用 `flex_array *type_val_to_struct_array` + 旧式 `filename_trans` hashtab | `ksu-4.14-sepolicy.patch`：`add_filename_trans`/`add_type` 加 4.14 stub 返回 false；`get_policydb()` 直接 `extern struct policydb policydb` |
| 6 | `call to '__bad_copy_to' declared with attribute error`（`ipa.c:5933`） | GCC 11 的 `__builtin_object_size` 比 GCC 4.9 精确，老驱动「先查边界再拷」的写法被静态判死 | `include/linux/compiler-gcc.h` 里把 `__compiletime_object_size(obj)` 改成 `(-1)`。**注意：关 `CONFIG_FORTIFY_SOURCE` 无效**，4.14 的 `check_copy_size` 是无条件编译的 |
| 7 | `dangerous relocation: unsupported relocation`（`gsi.o` 的 `__verbose` 段） | GCC 11 默认生成 PIE 代码，而 4.14 的 Makefile 里没有 `-fno-PIE`（4.15 才加） | `arch/arm64/Makefile` 追加 `KBUILD_CFLAGS += -fno-PIE` + `LDFLAGS_vmlinux += -no-pie` |
| 8 | `relocation truncated to fit: R_AARCH64_ADR_PREL_PG_HI21 against 'ss_initialized'` | 小米/高通把 SELinux 变量塞进自定义段 `.bss.rtic`（`__rticdata`），链接脚本把它放在 `_end` / `STABS_DEBUG` 之后，ADRP 的 ±4 GB 寻址溢出 | `include/linux/init.h` 把 `#define __rticdata ...` 改成空定义，变量回标准 `.bss`（仍会被 `__bss_start..stop` 清零） |
| 9 | `kallsyms failure: relative symbol value 0xffffff8008080000 out of range in relative mode` | 第 7 条的副作用：`-no-pie` 下 kallsyms 的 base-relative 模式找不到基准 `_text`。而 `CONFIG_KALLSYMS_BASE_RELATIVE` **无 prompt**，defconfig 关不掉 | 改 `init/Kconfig` 的 default（注意这颗内核写的是 `default !IA64 && !(TILE && 64BIT)`，**不是** `default y`），并且必须在 `make defconfig` **之前**改 |
| 10 | `kernel.release` 多出 `+`，vendor `.ko` 全挂 | 见上文「为什么必须干掉 `+`」 | `sed` 掉 `scripts/setlocalversion` 的 `+`，并加硬校验 |

另外还有两个链接期问题（都在 `Clone KernelSU` 步骤里 sed 掉）：

```sh
# 4.14 没有 inotify_mark_user_mask()
sed -i 's/inotify_mark_user_mask(mark)/mark->mask/' fs/notify/fdinfo.c
# 4.14 只有 strncpy_from_user()，没有 nofault 版本
sed -i 's/strncpy_from_user_nofault(dst, unsafe_addr, count)/strncpy_from_user(dst, unsafe_addr, count)/' KernelSU/kernel/kernel_compat.c
# 4.14 没有 selinux_inode() 辅助函数
sed -i 's/selinux_inode(inode)/(struct inode_security_struct *)inode->i_security/' KernelSU/kernel/sucompat.c
```

## 已知风险

1. **源码版本落差**：4.14.117 vs 4.14.180，63 个 stable 补丁差异。相机（imx586）、屏下指纹（goodix）、部分屏幕面板、WiFi 可能异常。
2. **dtb 用原厂 180 的**：硬件描述准确，但 117 驱动可能不认 180 dtb 里新增属性。
3. **AVB 签名丢失**：重建的 boot.img 无有效 AVB 签名；BL 已解锁的设备会跳过校验正常启动。
4. **SUSFS 是实验性代码**：`path_umount` 场景下 SUSFS 4.14 的 `vfs_statx` 分支存在 path 引用释放不完整（官方补丁原样保留），可能带来轻微泄漏；隐藏能力本身取决于你怎么用 `ksu_susfs` 配置。
5. **SUSFS 4.14 官方补丁本身不完整**：`50_add_susfs_in_kernel-4.14.patch` 缺 `sched.h` hunk 且 `dcache.c` 漏改，本项目已修正（见补丁清单说明）。

## 目录结构

```
cepheus/
  patches/
    cepheus-susfs-kernel.patch     SUSFS 4.14 内核侧（已做 4.14/cepheus 适配）
    ksu-susfs-v105.patch           SUSFS 4.14 的 KernelSU 侧（基于 v1.0.5）
    backport-path-umount.patch     4.14 path_umount backport
    allow-init-exec-ksud-under-nosuid.patch
  prebuilt/
    cepheus-boot-header.bin       原厂 boot header 模板（4096B）
    cepheus-stock-dtb.bin         从原厂 boot.img 提取的 dtb（1.99MB）
  scripts/build_bootimg.py        按原厂结构重建 boot.img
  README.md                       本文档
.github/workflows/build-cepheus.yml   构建流程
```

> GitHub Actions 只识别仓库根目录 `.github/workflows/`，所以小米 9 的构建流程
> 放在根目录的 `build-cepheus.yml`，业务文件全部收在 `cepheus/` 子目录，
> 与仓库原有的小米 8（dipper）`build.yml` 互不影响。

`prebuilt/` 两个文件来自你提供的 `E:\root\FolkPatch\boot.img`。换 ROM / 机器请重新提取。

## 致谢

- [KernelSU](https://github.com/tiann/KernelSU) by weishu
- [susfs4ksu](https://gitlab.com/simonpunk/susfs4ksu) by simonpunk / ShirkNeko
- [Xiaomi Kernel Open Source](https://github.com/MiCode/Xiaomi_Kernel_OpenSource) by Xiaomi
- 原始小米 8 版本 [xiziya/sukisu-dipper-patch](https://github.com/xiziya/sukisu-dipper-patch)
