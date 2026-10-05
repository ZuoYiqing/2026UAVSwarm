# 小模型候选与板端路线（2026-10-05）

本轮真正下载和实测的是 Qwen3.5-0.8B 与 MiniCPM5-1B Q4_K_M；后者经用户批准继续比较。
详见[异厂实测与新题集](MINICPM5_1B_EXPERIMENT_20261005.md)。下表其余模型只完成资料核对，未下载、未实测；发布方指标不是本项目成绩。
任务理解、视觉观察、几何规划是三个不同问题，不能用一个语言模型的回答替代检测证据或安全路径证明。

## 候选

| 模型 / 来源 | 规模与用途 | 许可证与部署依据 | 本项目判断 |
| --- | --- | --- | --- |
| [Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B) / 千问 | 0.8B 语言主干；上游有视觉编码器，本轮 GGUF 仅测文本 | Apache-2.0；本机已有支持该架构的 CUDA 引擎 | 资源下限对照；不预设能可靠规划 |
| [MiniCPM5-1B](https://huggingface.co/openbmb/MiniCPM5-1B) / 面壁、OpenBMB | 实际总参数 1,080,632,832；中英文本、任务理解候选 | Apache-2.0；标准 LlamaForCausalLM，上游提供 GGUF 和本地部署说明 | 已固定版本和哈希并在 4050 实测；本次固定采样配置表现不可靠，不能当作厂商最优配置排名 |
| [MiniCPM4-0.5B](https://huggingface.co/openbmb/MiniCPM4-0.5B) / 面壁、OpenBMB | 更小的中英文本模型 | Apache-2.0；原始 Transformers 示例含自定义模型代码，需要固定版本并审查 | 严格资源预算候选；系列的 AGX Orin 加速宣传不能当作本型号/本任务的测量结果 |
| [SmolLM2-360M-Instruct](https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct) / Hugging Face | 360M 文本；系列还有 135M | Apache-2.0；官方有 CPU / GPU 示例 | 极小资源对照；官方明确主要面向英语，不优先承担中文指令 |
| [SmolVLM-500M-Instruct](https://huggingface.co/HuggingFaceTB/SmolVLM-500M-Instruct) / Hugging Face | 500M 图像+文本，不是多机分配算法 | Apache-2.0；官方称单图推理约 1.23GB GPU RAM，尚未在这里验证 | L2 图像观察候选；英文为主，必须用实际场景图像和独立标注验证 |
| [LFM2.5-350M](https://huggingface.co/LiquidAI/LFM2.5-350M) / Liquid AI | 350M 级边缘文本模型 | LFM Open License v1.0，非 Apache/MIT；混合架构需单独验证后端 | 可选补充，不排在面壁之前；许可审查和板端算子审查后再考虑 |

MiniCPM5-2B 也有官方部署说明，但名称中的 2B 指非嵌入规模，总参数约 2.517B，且其部署说明注明 think-only。
因此不能沿用本轮关闭思考、1024 输出 token 的配置便宣称完成公平对照。
优先用支持 No Think 的 MiniCPM5-1B，显式记录采样差异，不照搬发布方综合排名。

## 三种硬件不是同一个部署包

- RTX4050：本轮只做推理，不做训练；量化权重、便携引擎、缓存和日志全在 D 盘。
- NVIDIA Jetson Orin：用户已确认厂商，但尚无 Nano / NX / AGX、内存、JetPack 和功耗档位。
  [Jetson AI Lab](https://www.jetson-ai-lab.com/models/)提供 Orin 与多种引擎的部署资料；Windows x64 可执行文件不能搬到 Linux ARM64 直接运行。
  小型 GGUF + 板端 CUDA 是待验证路线，不是已经取得的板端成绩。共享内存还要预留给相机、定位和其他进程。
- 华为昇腾：型号未定，不能把 910B 的支持结论套用到 310、310B 或 310P。
  [MiniCPM 官方昇腾指南](https://github.com/OpenBMB/MiniCPM/blob/main/docs/deployment/vllm_ascend.md)给出部署入口，但不是所有边缘板的兼容保证。
  [llama.cpp CANN 文档](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/CANN.md)列有 910B / 310P 和格式限制；310P 的量化矩阵运算支持存在限制。
  当前 Q4_K_M 是 CUDA 实验制品，不能因为同为“4位量化”就当作 CANN 可直接部署格式。

TOPS 不能直接推出能跑多大模型或每秒多少 token。需检查 RAM、带宽、算子、量化格式、上下文、散热与真实任务耗时。
最低规格平台允许 CPU 小模型或无语言模型的确定性路径；断网/失联时保留既有安全流程，不能等待模型替代飞控。
本轮不安装板端驱动，不刷固件，不购买设备或租用服务。

## “自己做”的可执行含义

建议做自有领域模型/算法，而非从零预训练通用基础模型：

1. 比较现成 0.8B、面壁 1B 与规则基线，建立错误分类。
2. 扩展中文指令数据：顺序、否定、未知目标、澄清、载具资格、禁止编造安全结论；划分独立开发集和隐藏测试集。
3. 数据合格后尝试 LoRA/SFT 或教师蒸馏；教师也必须本地、开源许可合规，不调用云端闭源模型。
4. 对极端资源板研究意图分类+槽位抽取的小型专用网络，输出相同候选契约；几何路径、分配与约束由确定性算法负责。
5. 独立验证图像检测器；图像采集成功不等于目标观察成功，更不等于任务完成。

4050 先支撑单模型推理和数据闭环；是否需租训练卡，应在数据规模、训练方法和显存试验明确后决定。
本轮没有执行训练、微调或蒸馏，未声称上述路线已经实现。
