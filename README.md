# SukiSU-Ultra Kernel for Xiaomi Mi 9 (dipper)

为小米 9 编译集成 SukiSU-Ultra 的 Linux 内核。

## 信息

| 项目 | 详情 |
|------|------|
| 设备 | 小米 9 (dipper) |
| Android 版本 | 9 (Pie) |
| 内核版本 | 4.14.180 |
| 内核源码 | [MiCode/Xiaomi_Kernel_OpenSource](https://github.com/MiCode/Xiaomi_Kernel_OpenSource) (分支: `dipper-p-oss`) |
| Root 方案 | [SukiSU-Ultra](https://github.com/SukiSU-Ultra/SukiSU-Ultra) |
| 编译器 | AOSP Clang r365631c (Clang 9, 最兼容 4.9 内核) |
| Hook 方式 | KPROBES |
| 编译方式 | GitHub Actions (云端) |

## 使用方法

### 1. Fork 本仓库

点击右上角 Fork 按钮，将仓库 Fork 到你自己的 GitHub 账号。

### 2. 运行编译

1. 进入你 Fork 后的仓库页面
2. 点击 **Actions** 标签页
3. 选择左侧的 **Build SukiSU-Ultra Kernel for Xiaomi Mi 9 (dipper)**
4. 点击右侧 **Run workflow** 按钮
5. 保持默认参数（或自定义 SukiSU 版本），点击绿色 **Run workflow** 按钮

### 3. 下载产物

编译完成后（约 15-25 分钟）：
- 在 Actions 运行页面的 **Artifacts** 区域下载 `SukiSU-dipper-boot`
- 或在 Releases 页面下载 `boot.zip`

### 4. 刷入设备

1. 将 `boot.zip` 传输到手机
2. 重启进入 Recovery (TWRP / OrangeFox)
3. 刷入 `boot.zip`
4. 重启系统
5. 安装 [SukiSU-Ultra Manager APK](https://github.com/SukiSU-Ultra/SukiSU-Ultra/releases) 检查是否生效

> ⚠️ **风险提示**：刷机有风险，请确保已备份原始 boot.img。如果出现问题，可通过 fastboot 刷回原始内核。

## 补丁说明

| 补丁 | 说明 |
|------|------|
| `backport-path-umount.patch` | 从高版本内核 backport `path_umount` 到 `fs/namespace.c`，使模块卸载功能正常工作 |
| `allow-init-exec-ksud-under-nosuid.patch` | 允许 init 在 nosuid 挂载点执行 ksud |

## 自定义

修改 `.github/workflows/build.yml` 中的 `env` 部分可以调整：

- `sukisu_branch` / `inputs.sukisu_tag`: SukiSU-Ultra 版本（默认 main，可选 v4.1.3 等）
- `defconfig`: 内核 defconfig（默认 `dipper_user_defconfig`）
- `clang_version`: AOSP Clang 版本（4.9 内核推荐 `r365631c`）

## 技术说明

小米 8 是非 GKI 设备（内核 4.9），SukiSU-Ultra 支持非 GKI 内核（4.4+），但需要手动集成和编译：

1. 使用 `setup.sh` 将 SukiSU 代码集成到内核源码的 `drivers/kernelsu/`
2. 启用 `CONFIG_KPROBES=y` 和 `CONFIG_KSU=y`
3. 应用必要补丁（path_umount backport + selinux 补丁）
4. 使用 AOSP Clang 9 编译内核
5. 打包为 AnyKernel3 可刷入格式

## 致谢

- [SukiSU-Ultra](https://github.com/SukiSU-Ultra/SukiSU-Ultra) by ShirkNeko
- [KernelSU](https://github.com/tiann/KernelSU) by weishu
- [KernelSU-Action](https://github.com/bin456789/KernelSU-Action) by bin456789
- [Xiaomi Kernel Open Source](https://github.com/MiCode/Xiaomi_Kernel_OpenSource) by Xiaomi
