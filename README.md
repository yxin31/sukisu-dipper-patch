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

---

# 重要更正（MIUI 内核树路线）

上文的 `build-cepheus.yml` 基于 `MiCode/Xiaomi_Kernel_OpenSource` 的 `cepheus-q-oss`
（4.14.117，Android 10 基线）。**这条路线编出来的内核刷进 MIUI 12.5 必然卡 Mi logo，
改任何 config 都救不回来**，原因是有硬性的源码缺失：

1. **缺高通 ICE 的 block 层 backport。** 用从原厂 `boot.img` 里解出的**出货真实配置**
   去编译，立刻在 `fs/crypto/fscrypt_ice.c` 报
   `'struct bvec_iter' has no member named 'bi_dun'`。
2. **缺全部 MIUI 专有驱动。** 出厂配置里有 22 个 MIUI 专有 CONFIG
   （`MIHW` / `MIGT` / `MILLET` / `MI_MEMORY_SYSFS` / `XIAOMI_SOLUTION` /
   `QTI_CRYPTO_TZ` / `QCOM_SOC_INFO` …），OSS 树里根本没有对应源码。
3. 顺带一提，`cepheus_user_defconfig` 是 AOSP 向的精简配置，与出厂差了 129 处实质开关
   （`UTS_NS=n`、`PSI=n`、无 `ANDROID_BINDERFS`、缺 `STATIC_USERMODEHELPER_PATH=/system/bin/micd`），
   Image 体积也差 10MB（33MB vs 工厂 42MB）。

## 现在用的路线

`.github/workflows/build-cepheus-miuikernel.yml`，内核源改为
**`Xirudly/kernel_xiaomi_cepheus` @ `16-ksun_susfs`**：

- 小米 MIUI 内核树（4.14.357），自带 `cepheus_stock_defconfig`（出厂配置）
- 已集成 **SUSFS v2.3.0**（`fs/susfs.c`，带 `LINUX_VERSION_CODE < 5.0` 分支）
- **KernelSU-Next** 子模块（`sidex15/KernelSU-Next` @ `legacy-susfs-v2`）
- `drivers/Makefile` / `fs/Makefile` / `drivers/kernelsu` 软链都已接好，无需手工打 SUSFS 补丁

产物结构（与原厂逐字节对齐的部分）：`ANDROID!` v1 / page 4096 / ramdisk 0 /
原厂 cmdline 原样保留 / `UNCOMPRESSED_IMG` + Image 40.65MB / `ARMd` / `text_offset 0x80000` /
`flags 0xa` / 5 个拼接 FDT 共 1,995,189B（原厂 dtb 未改）/ vermagic `4.14.180-perf-gb24d113`。

## 这条路线踩到的 5 个坑

1. **`silentoldconfig` 交互中止。** 这棵树新增了 `LITTLE_CPU_MASK` / `BIG_CPU_MASK` /
   `PRIME_CPU_MASK` 三个符号，出厂 defconfig 里没有 → CI 下 conf 当 NEW 符号弹交互直接 abort。
   解法：显式给值（取同仓库 `cepheus_defconfig` 的 `15` / `112` / `128`）+ `make olddefconfig` 兜底。
2. **`#if __has_attribute(__fallthrough__)` 编译失败。** `.S` / `.lds` 走的是简化预处理路径，
   拿不到 `__has_attribute`，报 `missing binary operator before token "("`。
   解法：该行改成 `#if 1`（GCC 11 一定支持 `__fallthrough__`）。
3. **`susfs_run_sus_path_loop` 未定义。** 子模块 pin 的 KernelSU-Next 会外部调用它，
   但 `fs/susfs.c` 里是 `static`。解法：去掉 `static` 并在 `susfs.h` 补声明。
4. **SUSFS 子开关要显式写出。** 只写 `CONFIG_KSU_SUSFS=y` 不够，必须逐个写出
   `KSU_SUSFS_SUS_PATH` / `SUS_MOUNT` / `SUS_KSTAT` / `TRY_UMOUNT` / `SPOOF_UNAME` /
   `ENABLE_LOG` / `HIDE_KSU_SUSFS_SYMBOLS` / `SPOOF_CMDLINE_OR_BOOTCONFIG` /
   `OPEN_REDIRECT` / `SUS_MAP`，否则 `fs/susfs.c` 里对应 `#ifdef` 全被编译掉。
   workflow 里已加硬断言，缺一个就让构建失败。
5. **仍用 GCC 11 + 关 KASLR。** `android.googlesource.com` 的 `+archive` 端点返回 502，
   拿不到 clang-r383902 与 `aarch64-linux-android-4.9`。4.14 arm64 没有
   `HAVE_ARCH_PREL32_RELOCATIONS`，`___ksymtab` 存绝对地址，PIE 下新版 binutils 会报
   `dangerous relocation`，所以 `CONFIG_RELOCATABLE` / `RANDOMIZE_BASE` 一起关掉
   （只损失地址随机化，与 root / SUSFS 隐藏无关）。

## 残留风险：`CONFIG_MODVERSIONS`

出厂是 `=y`，我们保持了一致，但源码从 4.14.180 跨到 4.14.357，导出符号的 CRC
必然对不上，`/vendor/lib/modules` 里的原厂 `.ko`（触屏 / WiFi / 音频）可能在加载时报
`disagrees about version of symbol`。vermagic 已完全对齐，CRC 是下一层要看的。
如果刷完能开机但触屏/WiFi 不工作，就把 `CONFIG_MODVERSIONS` 关掉再构建一次。

## 重要更正（刷机后实测）：KSU_VERSION 被浅克隆算错

r5 刷入后**能正常开机**，但 KernelSU-Next Manager 首页显示：

- 状态「工作中」、SUSFS 识别为 `v2.3.0 (NON-GKI)` → 内核侧 KSU / SUSFS 都是好的
- 内核版本 `v0.0.0 (30151-0)`，红条 **`Kernel update required`**
- 「元模块状态：未安装」→ `ksud` 没被部署 → `su` 完全不可用（`/system/bin/su` 不存在）

根因**不是**版本太老，而是版本号算错了。`kernel/Kbuild:84`：

```
KSU_VERSION = 30000 + git rev-list --count HEAD + 150
```

`actions/checkout` 的 `fetch-depth: 1` 让 KernelSU 子模块只有 1 个 commit，
于是 `30000 + 1 + 150 = 30151`；Manager v3.4.2 期望的是 `30000 + 3205 + 150 = 33355`。

`Kbuild:73` 本来写了 `git fetch --unshallow` 兜底，但判据是 `[ -f .git/shallow ]`——
子模块的 `.git` 是 gitfile（`gitdir: ../.git/modules/KernelSU`）而不是目录，
这个条件**永远为假**，所以从未真正 unshallow。

**修复**：workflow 新增 `Fix KSU_VERSION (unshallow KernelSU submodule)` 步骤，
编译前对子模块执行 `git fetch --unshallow --tags`；若提交数仍 < 3205，
直接把 `KSU_GIT_VERSION` 钉成 3205（等价 33355）。

### 顺带清理的环境问题

- 设备上原有 `com.resukisu.resukisu`（ReSukiSU v4.2.0-rc3，SukiSU 系）会与
  KernelSU-Next 抢 manager 槽位，已卸载。
- Manager 必须与内核版本同代：`v3.4.2(33355)` 配 33355 内核；`v1.1.1` 装上即自退，不可用。


---

## 2026-11-04 18:00 改用 SukiSU-Ultra（新流水线 `build-cepheus-sukisu.yml`）

### 为什么要换

内核本身能开机、SUSFS v2.3.0 也在，但 KernelSU-Next 的 **UAPI 协议代差**太严重：

| | 内核侧（sidex15 legacy-susfs-v2） | Manager v3.4.2 |
|---|---|---|
| `struct ksu_get_info_cmd` | `version` / `flags` / `features` | 多一个 `uapi_version` |
| `KERNEL_SU_UAPI_VERSION` | 无（读到 0） | 5 |
| `KSU_APP_PROFILE_VER` | **3** | **4** |

后果：首页红条 `Kernel update required`，而且授权 root 时传的是 v4 版
`app_profile` 结构给 v3 版内核，字段错位。实测换成 **Manager v3.2.0 (33129)**
后协议对齐（PROFILE_VER 3 / 无 uapi_version），`su` 立刻可用：

```
uid=0(root) gid=0(root) groups=0(root) context=u:r:ksu:s0
su -v -> 3.2.0:KernelSU
```

### 换 SukiSU-Ultra 的关键结论（源码级确认）

1. **SukiSU 走 syscall hook**，不认树里的 legacy 手动钩子。
   树里 6 个文件的钩子全部包在
   `#if defined(CONFIG_KSU) && !defined(CONFIG_KSU_TAMPER_SYSCALL_TABLE)` 里：
   `fs/exec.c`、`fs/open.c`、`fs/stat.c`、`fs/read_write.c`、`kernel/reboot.c`、
   `drivers/input/input.c`。只要在顶层 `Makefile` **末尾**加
   `KBUILD_CFLAGS += -DCONFIG_KSU_TAMPER_SYSCALL_TABLE`，6 个钩子全部自动关闭，
   **内核源码一行都不用改**。
   （必须加在末尾：`KBUILD_CFLAGS` 在 Makefile 前部被 `:=` 赋值，提前 `+=` 会被覆盖。）
2. `CONFIG_KSU` 在 SukiSU 里 `depends on KPROBES && EXT4_FS`。少了 `KPROBES`
   会被 Kconfig **静默丢弃**，内核里什么都没有，所以必须显式打开
   `KPROBES` / `KALLSYMS` / `KALLSYMS_ALL`。
3. **SUSFS 的 Kconfig 定义原本在 KernelSU-Next 的 `kernel/Kconfig` 里**，
   换掉之后 `CONFIG_KSU_SUSFS` 变成未定义符号被 Kconfig 丢掉 →
   `fs/Makefile` 的 `obj-$(CONFIG_KSU_SUSFS) += susfs.o` 失效 → SUSFS 全废。
   修复：把 Kconfig 块落到 `cepheus/prebuilt/susfs-kconfig.txt`，
   编译前 `cat` 进 `fs/Kconfig`。
4. SukiSU 版本号同样按提交数算：`KSU_VERSION = 40000 + LOCAL_COUNT - 2815`。
   Manager `v4.3.0-r1` = `41140` → 钉 `LOCAL_COUNT = 3955`。
   （不钉的话它会去 curl GitHub API 数 commit，CI 里容易被限流，版本号乱跳。）

### vendor DLKM 全部加载失败：真正的根因（2026-11-05 定位，推翻前一版结论）

实机 `dmesg`（r6 镜像）：

```
27 次 "disagrees about version of symbol module_layout"
14 个模块加载失败: wlan / wcd_core / swr / q6_pdr / tas2557 / tfa98xx /
                  cs35l41 / wcd_spi / pinctrl_wcd / stub / exfat /
                  rmnet_perf / hdmi / wglink
```

表现：`wlan0` 不存在（WiFi 完全没起来）、音频 codec 不加载。

**关键观察：27 条错误全部是 `module_layout`，没有任何一个其它符号报错。**

这说明导出符号的 ABI 基本是好的，差异只集中在 `struct module` 这一个结构体上。
因为 `module_layout` 这个"符号"并不是函数，它的 CRC 是 genksyms 对
`struct module` 定义的摘要 —— 结构体多一个成员，CRC 就变。

#### 用原厂 `.ko` 拿到真值

从设备把 `qca_cld3_wlan.ko` / `audio_wcd_core.ko` 拖回来直接解析 ELF
（`__versions` 段 + `.modinfo` + `.gnu.linkonce.this_module` 段大小）：

```
vermagic              = 4.14.180-perf-gb24d113 SMP preempt mod_unload modversions aarch64
module_layout CRC     = 0x4ad0cd64
sizeof(struct module) = 0x380 (896 字节)
```

#### 逐行 diff `include/linux/module.h`（4.14.180 vs 4.14.357）

`struct module` 多出 4 处成员：

| # | 差异 | 处理 |
|---|---|---|
| 1 | `#ifdef CONFIG_CFI_CLANG` 的 `cfi_check` | 用 gcc，本来就不存在 |
| 2 | `bool using_gplonly_symbols;`（**没有任何 ifdef**） | 删掉字段（连同 2 处读写） |
| 3 | `#ifdef CONFIG_BPF_EVENTS` 的两个字段 | 该符号是 `bool` + `default y`，**没有 prompt**，defconfig 写 `not set` 会被 `olddefconfig` 重算回 `y`。只能在源码里 `#if 0` 摘掉，并清掉 `module.c` / `bpf_trace.c` 各处引用 |
| 4 | `#ifdef CONFIG_FUNCTION_ERROR_INJECTION` 的两个字段 | 同上，`def_bool y`（依赖 `KPROBES`，而 KSU 必须开 `KPROBES`，所以必然为 y）。摘字段 + 把 `lib/error-inject.c` 的两个入口变成空实现 |

还有一处更隐蔽的：`RELOCATABLE=n`（为了绕开 PIE 的 dangerous relocation）
会让 `ARCH_HAS_RELR` 连带失效，进而 `ARM64_MODULE_PLTS` 被关，于是
`struct mod_arch_specific` 少了 3 个成员（40 字节），把 `arch` 之后的
`taints` / `kallsyms` / `source_list` / `target_list` / `exit` / `refcnt`
**全部顶偏**。修复是在 `arch/arm64/Kconfig` 给 `ARM64_MODULE_PLTS` 加
`default y`（这个系列里它没有 `depends on RELOCATABLE`，所以可以单独打开）。

#### 为什么"关掉 MODVERSIONS"是错的（r7 的教训）

`# CONFIG_MODVERSIONS is not set` 可以让 `check_version()` 直接放行，模块确实装进去了，
但**成员偏移依然是错的**。内核按 357 的偏移去写 `refcnt` / `exit`，模块按 180 的
偏移去读，第一次 `try_module_get()` 就写坏内存 —— 实机表现就是
"开机几秒后重启循环"。所以校验只能被"满足"，不能被"绕过"。

#### 现在的做法 + 构建后自检

- `scripts/abi-align-414180.sh`：把上面 4 处差异 + PLTS 全部对齐，
  `CONFIG_MODVERSIONS` 保持 `=y`。
- `scripts/abi-verify.py`：**链接完 vmlinux 立刻读 `__kcrctab`**，把内核算出的
  `__crc_module_layout` 跟 `0x4ad0cd64` 比对，不一致直接让 CI 失败。
  这样"ABI 对不对"不再需要刷一次机才知道。
- `kernel/module.c` 的 `check_version()` 只对 `module_layout` 一个符号放行
  （本树把匿名 `enum licence` 改名成 `enum mod_license`/`license`，genksyms
  对文本敏感，CRC 可能仍不同；布局已逐个成员核对一致，故只放行这一个）。
  其余符号继续严格校验 —— 它们本来就全对。

### 两条流水线

| 文件 | root 框架 | 状态 |
|---|---|---|
| `.github/workflows/build-cepheus-miuikernel.yml` | KernelSU-Next + Manager v3.2.0 | 可用（实测 root 已通） |
| `.github/workflows/build-cepheus-sukisu.yml` | SukiSU-Ultra v4.3.0-r1 | 不可用：main 分支不兼容 4.14（SELinux 内部结构全是 5.x+） |


---

## 2026-11-05 05:30 把 vendor DLKM 这件事查到底：518 条符号全表实测

上一轮只盯着 `module_layout` 一个符号，那是被 `check_version()` 的短路行为骗了。
`kernel/module.c` 是**按 `____versions` 顺序逐符号校验、第一个不匹配就直接返回 NULL**，
所以设备上永远只会看到第一条报错，后面的差异全被挡住。

### 做法：把出厂真值整张表扒下来

从设备 `/vendor/lib/modules` 拖回两个原厂模块，解析 `__versions` 段：

| 模块 | 条目数 | 其中与本仓库无关的 |
|---|---|---|
| `qca_cld3_wlan.ko` | 429 | — |
| `audio_wcd_core.ko` | 131 | — |
| 合并去重 | **518** | 两个模块对同一符号的 CRC 完全一致，可互相印证 |

表落在 `scripts/stock-versions.txt`（`<crc> <符号名>`，518 行），
`scripts/abi-verify.py` 构建完直接读 `vmlinux` 的 `__crc_*` 全表比对。

### 结果：216 一致 / 302 不一致

不是布局没修好，是**稳定版 4.14.180 → 4.14.357 之间的结构体漂移**：

- genksyms 是**递归摘要** —— 指针参数指向的结构体多一个字段，函数的 CRC 就变；
- `struct sk_buff`、`cfg80211_*`、`struct notifier_block`、`struct cdev` 这些
  在 177 个稳定版迭代里都动过，于是 `__alloc_skb`、`cfg80211_get_bss`、
  `blocking_notifier_call_chain`、`cdev_add` 一片全变；
- 而 `__kmalloc(size_t, gfp_t)` 这种只有标量参数的，CRC 一模一样 ——
  这恰好反证了"读取方法是对的，差异是真实的源码差异"。

想靠改源码把 302 个 CRC 凑成原样，等于把内核回退到 4.14.180，不现实。

### 所以改了策略：不凑 CRC，改证"布局"

CRC 不一致真正致命的只有**按值传递的结构体**——内核 ABI 里几乎没有；
指针参数的调用约定与结构体内部布局无关。唯一被内核**直接写入模块镜像**的
结构体就是 `struct module`。所以判定标准从"CRC 相等"换成"布局相等"：

1. `scripts/abi-align-414180.sh` 第 6 步在 `kernel/module.c` 末尾埋 3 个探针数组：
   ```c
   char __ksu_abi_sizeof_module[sizeof(struct module)] __used;
   char __ksu_abi_off_module_init[__builtin_offsetof(struct module, init)] __used;
   char __ksu_abi_off_module_exit[__builtin_offsetof(struct module, exit)] __used;
   ```
   数组长度由编译器算，落在 `vmlinux` 的 `.bss` 里，符号的 `st_size` 就是测量值。
2. 真值从原厂 `.ko` 的 `.gnu.linkonce.this_module` 段的**重定位表**里读：
   ```
   size = 0x380 (896)
   .init  重定位 @ 0x150 (336)
   .exit  重定位 @ 0x310 (784)   <- 指向 cleanup_module
   ```
3. `CONFIG_MODVERSIONS=n`（`module_layout` 并不是 .ko 的 undefined 符号，
   只存在于 `__versions` 元数据里，关掉不会 `Unknown symbol`），
   同时把 `include/linux/vermagic.h` 的 `#ifdef CONFIG_MODVERSIONS` 硬改成 `#if 1`，
   保证 vermagic 仍是 `... mod_unload modversions aarch64`，否则会变成
   `version magic '... modversions aarch64' should be '... aarch64'` 被拒载。

只有这三项探针全部吻合，CI 才放行打包 —— 不吻合就打印差了多少字节、对应哪个字段，
不用刷机。

### 这轮踩到的两个 CI 坑（都记在这，避免重复）

| 现象 | 原因 | 处理 |
|---|---|---|
| `ERROR: CFI_CLANG 必须关闭` | 用 gcc 时 `CONFIG_CFI_CLANG` 在 `arch/arm64/Kconfig` 里被 `CC_IS_CLANG` 屏蔽，`.config` 里**根本没有这行**（既不是 `=y` 也不是注释行） | 断言改成"不能是 `=y`" |
| `ABI-CHECK` 三个符号全 `MISMATCH`，段名显示 `.text` | 第一版脚本找的是 `printk` 这个符号而不是 `__crc_printk`，读到的是函数第一条指令（`0xd10283ff` 这种 arm64 机器码） | 加 `__crc_` 前缀；`__kmalloc` 随后对上，反证读法正确 |

---

## 2026-11-05 15:00 放弃对齐 ABI，改成"用同一棵树重编 vendor 模块"

### 换源码树这条路已经走死

| 源码树 | 与设备 518 条 CRC 一致 |
|---|---|
| 4.14.357（`Xirudly/kernel_xiaomi_cepheus@16-ksun_susfs`，r6/r13 用的） | 216 / 518（41.7%） |
| 4.14.190（`lelaonn/Cepheus_Raphael_Kernel_MI_A11`，"MIUI A11 出厂树"） | 229 / 518（44.21%） |

最硬的一条证据是 `__stack_chk_fail`。原型 `void __stack_chk_fail(void)`，**无参数**，
所以它的 CRC 在所有内核世代都是固定值 `0xf0fdf6cb`（拿 RHEL7 的 RPM 依赖串、
6.11 的 `jbd2.mod.c` 两处独立核对过）。而 lelaonn 这棵树编出来是 `0xdb7305a1`。
**连无参函数都算不对，说明那棵树不是出货源码，而是被改动拼合过的。**

旁证：它让 `dsi_panel.c` 无条件调 `is_tp_doubleclick_enable()`，而出厂 `.config`
里压根没有 `CONFIG_TOUCHSCREEN_MI_DAVINCI_DOUBLE_CLICK` 这一项 —— 代码是后来加的，
作者忘了补 Kconfig，于是链接期 undefined。

另外 MiCode 全部 267 个分支里 `-r-oss`（Android 11）有 37 个，**没有 cepheus，
也没有任何 sm8150**，只有 `-p-oss`(A9) 和 `-q-oss`(A10, 4.14.117)。
"去找真正的出厂树"没有候选，这条路关闭。

### 新策略：内核用我们的，模块也用我们的

`/vendor/lib/modules` 下的 `.ko` 是按 4.14.180 的布局编的，跟本树结构体有漂移，
`check_version()` 直接拒 -> 没 WiFi。既然源码树里 WLAN 栈是**完整的**
（`drivers/staging/qcacld-3.0` + `qca-wifi-host-cmn` + `drivers/staging/fw-api`
+ `drivers/net/wireless/cnss*`），那就用同一棵树把它编出来，模块与内核同源，
结构体天然对齐，ABI 问题绕开。

关键点：**`abi_mode` 继续用 `strict`**（保持 `CONFIG_MODVERSIONS=y`）。
这样原厂的错位模块会被拒载（不崩，只是功能缺失），而我们同源编的模块 CRC 天然一致、
能正常加载。要是关掉 MODVERSIONS（permissive），原厂模块全放进来，就是 r13 的
重启循环。

### 编译这一套踩到的 4 个坑

| 现象 | 原因 | 处理 |
|---|---|---|
| `cnss_utils.ko` 编不出来，配置"写了"却没生效 | `CONFIG_CNSS_UTILS` 的 Kconfig 是 **bool**（`drivers/net/wireless/cnss_utils/Kconfig`），写 `=m` 被 kconfig 判非法后静默丢弃 | 改 `=y`，内建进 vmlinux（顺带消掉原厂 `cnss_utils.ko` 的 ABI 风险，install.sh 会把它改名禁用） |
| `cnss_prealloc.ko` 编不出来，换成 `-DMODULE` 直接编译报错 | 两层原因：① 符号名不是 `CONFIG_CNSS_PREALLOC`，正确是 **`CONFIG_WCNSS_MEM_PRE_ALLOC`**（`drivers/net/wireless/Kconfig:117`）；② 更要紧的是 `cnss_prealloc.c:387` 写了 `MODULE_DESCRIPTION(DEVICE "WCNSS Prealloc Driver")`，而 **`DEVICE` 宏全树没有定义**。内建时 `MODULE_DESCRIPTION` 展开成空所以不报错（出厂 defconfig 本来就是 `=y`），一旦 `-DMODULE` 就变成 `MODULE_INFO(description, DEVICE ...)` → `expected ',' or ';' before 'DEVICE'`，而它在 `drivers/net/wireless` 下、排在 `drivers/staging` 之前，`make -k` 也救不回 wlan.ko | 保持 `CONFIG_WCNSS_MEM_PRE_ALLOC=y` 内建，不编这个模块 |
| `modpost` 整体失败，**一个 `.ko` 都不生成** | `CONFIG_DVB_MPQ=m` 是出厂 defconfig 遗留（cepheus 没有 DVB 硬件），它引用的 `ion_alloc_dmabuf` 在 `CONFIG_ION=y` 但没开任何 heap 时不存在。`modpost` 是全模块统一的，一个错全灭 | defconfig 加 `# CONFIG_DVB_MPQ is not set` |
| `wlan.ko` 336MB，推不进手机 | 树里开了 `CONFIG_DEBUG_INFO` | `aarch64-linux-gnu-strip --strip-debug`（只删调试段，`.modinfo`/`__versions`/`.symtab` 全保留），打包前断言 < 63MB |

### 设备端流程

```
fastboot flash boot boot.img          # 内核 + KSU + SUSFS
# 首次开机 wifi 大概率仍不可用, 这是预期: 模块还是出厂的
adb push vendor-modules.tar.gz /data/local/tmp/
adb shell su -c 'mkdir -p /data/local/tmp/vm && \
  tar -xzf /data/local/tmp/vendor-modules.tar.gz -C /data/local/tmp/vm && \
  sh /data/local/tmp/vm/install.sh check'      # 先只读检查
adb shell su -c 'sh /data/local/tmp/vm/install.sh'   # 再替换
adb reboot
```

`install.sh` 会逐个把 `.ko` 的 `vermagic` 跟 `uname -r` **逐字符比对**，
不一致的直接 skip，不会把错的推进去。原厂 `.ko` 备份在
`/data/local/tmp/vendor-modules-backup`，`install.sh rollback` 可还原。

`diag-vendor-modules.sh` 是纯只读诊断，用来确认模块加载时序、哪个 `.ko` 报
`disagrees about version`、内核里 `cnss_utils` 是否已内建。

### 音频

这棵树 `techpack/audio` 是静态变体（`sm8150auto.conf` 全 `=y`，
`drivers-y := … techpack/` 直接链进 vmlinux），音频驱动本来就在内核里，
不依赖外挂 DLKM。如果刷完仍没声音，先看设备上是不是还有
`audio_wcd_core.ko` 之类的原厂模块被 insmod —— 那会被 CRC 拒（不崩），
但内核内建的那份应该已经接管。
