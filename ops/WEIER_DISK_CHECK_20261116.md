# weier 磁盘垃圾检查（离线环境操作手册）

**用途**：在 weier 上查出哪些文件是"运行产生的垃圾"、哪些必须保留，然后安全清理。
**日期**：2026-11-16
**适用**：Windows 10 19041 + WSL2（Ubuntu 22.04）

> **本文全部命令只用系统自带工具，不需要联网、不需要装任何东西。**
> **原则：先看，后删。每一条删除命令前面都有对应的"查看"命令。**

---

# 零、先记住三件事

## ① WSL 的磁盘是一个"只长不缩"的虚拟磁盘

```
D:\WSL\Ubuntu\ext4.vhdx     ← 你看到的是这个文件的大小
```

**在 WSL 里删了 5 GB 文件，这个 vhdx 文件一点都不会变小。**
必须做一次"收缩"（本文第五节）才能把空间还给 Windows。

## ② 千万不要用 `wsl -l -v` 来检查 WSL 是否已关闭

那条命令**会把 WSL 唤醒**。检查关闭状态用：

```powershell
Get-Process -Name vmmemWSL -ErrorAction SilentlyContinue
```

**没有任何输出 = 已关闭。**

## ③ 删之前先记录基线

把每一步的输出贴到你的记录里，万一出问题能对照。

---

# 一、Windows 侧：先看 WSL 磁盘多大（**这一步最关键**）

```powershell
Get-ChildItem C:\,D:\ -Recurse -Filter *.vhdx -ErrorAction SilentlyContinue | ForEach-Object { "{0,8:N1} GB  {1}" -f ($_.Length/1GB), $_.FullName }
```

**怎么读**：

| 大小 | 判断 |
|---|---|
| **< 15 GB** | 正常，weier 没多少垃圾，**不用折腾** |
| **15~30 GB** | 有一点，按本文清一遍能省几个 GB |
| **> 30 GB** | 垃圾很多，认真清一遍 |

> 我们发过去的离线包总共约 1.4 GB，装完后正常应该在 **10~25 GB** 之间。

---

# 二、Windows 侧：几个常见垃圾目录

## 2.1 一次看完

```powershell
$t = @("$env:TEMP", "C:\Windows\SoftwareDistribution\Download", "$env:LOCALAPPDATA\pip\Cache", "$env:LOCALAPPDATA\npm-cache", "D:\weier-offline"); foreach ($p in $t) { if (Test-Path $p) { "{0,8:N1} GB  {1}" -f ((Get-ChildItem $p -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum/1GB), $p } }
```

## 2.2 逐项说明

| 目录 | 通常多大 | 能不能删 | 说明 |
|---|---|---|---|
| `$env:TEMP` | 几百 MB~几 GB | ✅ **能删** | 临时文件，删了系统会重建 |
| `SoftwareDistribution\Download` | 几百 MB | ✅ **能删** | Windows 更新缓存，我们离线不用 |
| `LOCALAPPDATA\pip\Cache` | 几百 MB | ✅ 能删 | 如果 Windows 上装过 Python 包 |
| `LOCALAPPDATA\npm-cache` | 几百 MB | ✅ 能删 | 如果 Windows 上用过 npm |
| **`D:\weier-offline`** | **1.4 GB** | ⚠️ **装完之后能删** | 我们的离线安装包。**装完并验证通过后再删** |

## 2.3 安全的删除命令

```powershell
# 临时文件（最安全，随时可删）
Remove-Item "$env:TEMP\*" -Recurse -Force -ErrorAction SilentlyContinue

# Windows 更新缓存
Stop-Service wuauserv -Force -ErrorAction SilentlyContinue
Remove-Item "C:\Windows\SoftwareDistribution\Download\*" -Recurse -Force -ErrorAction SilentlyContinue
Start-Service wuauserv
```

> ⚠️ **`D:\weier-offline` 先别删！** 等 weier 上四件套（三机仿真 + Runtime + 主控台 + 三维）
> 全跑通、验收做完之后再删。它是你唯一的重装材料。

---

# 三、WSL 侧：找出大目录

## 3.1 进 WSL

```powershell
wsl -d Ubuntu
```

## 3.2 一条命令看全部

```bash
du -sh /root/* 2>/dev/null | sort -h | tail -15
```

## 3.3 怎么读这个结果

**按经验，weier 上的大户通常是这几个：**

| 目录 | 通常多大 | 能不能删 | 说明 |
|---|---|---|---|
| `/root/PX4-Autopilot/build/` | **3~8 GB** | ⚠️ **能删但别删** | 编译产物。删了要重新编译（约 40 分钟），演示前别动 |
| `/root/uavswarm/.runtime/` | **1~7 GB** | ✅ **能删，最安全** | Gazebo 运行日志和录制数据。删了不影响任何功能 |
| `/root/.cache/pip` | 几百 MB | ✅ 能删 | pip 下载缓存 |
| `/var/cache/apt/archives` | 几百 MB | ✅ 能删 | apt 包缓存 |
| `/root/wheelhouse` | 75 MB | ✅ 能删 | 装完 pymavlink 就没用了 |
| `/root/PX4-Autopilot/` 整体 | 2~3 GB | ❌ **不能删** | PX4 源码 |
| `/root/uavswarm/` 整体 | 几百 MB | ❌ **不能删** | 项目源码 |

## 3.4 查看后确认再删

```bash
# ① 先看 .runtime 有多大
du -sh /root/uavswarm/.runtime 2>/dev/null

# ② 看它在里面装了什么
ls -lh /root/uavswarm/.runtime 2>/dev/null
```

```bash
# ③ 确认是日志/录制数据后再删
rm -rf /root/uavswarm/.runtime
```

```bash
# ④ 清缓存（安全）
apt clean
rm -rf /root/.cache/pip
rm -rf /root/wheelhouse
```

## 3.5 再确认一次

```bash
du -sh /root/* 2>/dev/null | sort -h | tail -10
```

## 3.6 ⚠️ 注意 WSL 里可能有第二份源码

我们后来用的是 `~/uavswarm-demo`（`demo-20261113` 版本），旧的是 `~/uavswarm`。

```bash
ls -d /root/uavswarm* 2>/dev/null
du -sh /root/uavswarm* 2>/dev/null
```

**如果两个都存在，旧的 `~/uavswarm` 在确认新的能跑之后可以删。**

---

# 四、退出 WSL 并关闭

```bash
exit
```

```powershell
wsl --shutdown
```

```powershell
# 等 10 秒，然后确认（★ 不要用 wsl -l -v，会唤醒它）
Start-Sleep -Seconds 10
Get-Process -Name vmmemWSL -ErrorAction SilentlyContinue
```

**没有输出 = 已关闭，可以收缩了。**

---

# 五、收缩 WSL 虚拟磁盘（把空间还给 Windows）

## 5.1 先找到 vhdx 的真实路径

```powershell
Get-ChildItem C:\,D:\ -Recurse -Filter *.vhdx -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
```

**记下这个路径**，下面要用。常见的两个位置：

```
D:\WSL\Ubuntu\ext4.vhdx          ← 用 wsl --import 导入的（我们是这种）
C:\Users\你\AppData\Local\Packages\...\LocalState\ext4.vhdx   ← 从商店装的
```

## 5.2 用 diskpart 收缩

**把下面路径换成 5.1 查到的真实路径**：

```powershell
@"
select vdisk file="D:\WSL\Ubuntu\ext4.vhdx"
compact vdisk
exit
"@ | diskpart
```

**预期输出里有这么两行**：

```
  100 百分比已完成
DiskPart 已成功压缩虚拟磁盘文件。
```

## 5.3 收缩后再看大小

```powershell
Get-ChildItem D:\WSL -Recurse -Filter *.vhdx | ForEach-Object { "{0,8:N1} GB  {1}" -f ($_.Length/1GB), $_.FullName }
```

**应该比收缩前小。** 如果没变化，说明 WSL 没完全关闭（回到第四节重来）。

---

# 六、检查有没有多余的 WSL 发行版

我们只需要一个 `Ubuntu`。如果之前导入过别的，会白占空间。

```powershell
wsl -l -v
```

**正常情况下只应该有**：

```
  NAME            STATE           VERSION
* Ubuntu          Stopped         2
```

**如果看到 `Ubuntu-22.04`、`weier-fresh` 之类的多余发行版**，确认不用后删掉：

```powershell
wsl --unregister <发行版名字>
```

> ⚠️ `--unregister` 会**直接删除那个发行版的所有文件**，不可恢复。删前确认名字没错。

---

# 七、什么时候**不要**清

| 情况 | 原因 |
|---|---|
| **演示前 3 天内** | 别动任何东西，稳定第一 |
| **PX4 的 `build/` 目录** | 删了要重编 40 分钟，演示前绝对别碰 |
| **`D:\weier-offline`** | 这是唯一的重装材料，验收做完再删 |
| **`~/uavswarm-demo`** | 演示用的版本，不能删 |
| **不确定是什么的目录** | 用 `ls -lh` 看清楚再说，别猜 |

---

# 八、最简流程（如果你只想省点事）

```powershell
# ① 看 WSL 磁盘多大
Get-ChildItem D:\WSL -Recurse -Filter *.vhdx | ForEach-Object { "{0,8:N1} GB  {1}" -f ($_.Length/1GB), $_.FullName }
```

**如果 < 15 GB → 到此为止，不用清了。**

```powershell
# ② 如果 > 15 GB，进 WSL
wsl -d Ubuntu
```

```bash
# ③ 看大户
du -sh /root/* 2>/dev/null | sort -h | tail -10

# ④ 只删最安全的那个
rm -rf /root/uavswarm/.runtime
apt clean
rm -rf /root/.cache/pip

# ⑤ 退出
exit
```

```powershell
# ⑥ 关闭 + 收缩
wsl --shutdown
Start-Sleep -Seconds 10
@"
select vdisk file="D:\WSL\Ubuntu\ext4.vhdx"
compact vdisk
exit
"@ | diskpart
```

**全程约 10 分钟，通常能省 2~8 GB。**

---

# 附：这份文档的来源

本机（开发机）上做过同样的清理，结果是：

| 项 | 清理前 | 清理后 |
|---|---|---|
| Gazebo 日志 | 1,180 MB | 0 |
| pytest 临时目录 | 11 MB（15 个） | 0 |
| `__pycache__` | 12 MB（87 个） | 0 |
| `.runtime` 总计 | 1,243 MB | 33.7 MB |
| worktree 数量 | 31 个 | 14 个 |

**weier 上的结构类似，所以那些目录大概率也存在。**
