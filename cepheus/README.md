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

workflow 会做两件事把内核版本号伪装成原厂值，让预编译 `.ko` 的 vermagic 能对上：

```make
Makefile:     SUBLEVEL = 180
defconfig:    CONFIG_LOCALVERSION="-perf-gb24d113"
              # CONFIG_LOCALVERSION_AUTO is not set
```

`uname -r` 输出 `4.14.180-perf-gb24d113`，和原厂一致。内核代码本身仍是 4.14.117。

## 使用方法

### 1. 跑 Actions

本仓库 → Actions → **Build KernelSU + SUSFS for Xiaomi Mi 9 (cepheus)** → Run workflow。
约 25-40 分钟。可选参数 `ksu_ref`（默认 `v1.0.5`）和 `kernel_ref`（默认已固定）。

### 2. 下产物

Artifacts 里的 `KernelSU-SUSFS-cepheus-boot` → `boot.img` + `boot.img.md5`。

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
