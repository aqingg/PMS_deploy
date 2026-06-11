# Calibration Report 自动删除规则说明

本文档整理 `QSTL0446_ Calibration_Report_CN_En_Cn_V1_6.docm` 模板中与自动删除相关的规则，规则来源为模板 3.2、3.2.1、3.3、3.4 章节及当前图片标注。本文只描述规则逻辑，不描述代码实现。

## 1. 输入字段

自动删除主要读取以下配置字段：

- `Calibration Scope`：用于判断整章是否适用。
- `Peripheral Sensor`：用于判断 UFS、PAS、PPS、RCS 及 Y 通道传感器是否配置。
- `Inertial Sensor`：用于判断中央惯性传感器是否只有 1 个 `SMAx`。
- `Fire Loops`：用于判断是否存在 `BATD` 相关点火回路。

传感器命名按包含关系判断，例如 `UFS6` 视为配置 UFS，`RCS-Y` 视为配置 RCS-Y。

## 2. 章节级删除规则

章节级规则用于删除整个章节或小节。

- 检查 `Calibration Scope`，如果不包含 `FSR` 或 `IDF`，则删除 `3.2 Front algorithm 正碰算法`。
- 检查 `Calibration Scope`，如果不包含 `IDF`，则删除 `3.2.2 Integrated collision detection front function (IDF)`。
- 检查 `Calibration Scope`，如果不包含 `FSR`，则删除 `3.3 Rear algorithm 后碰算法`。


- 检查 `Calibration Scope`，如果不包含 `CSABS` 或 `Offzone`，则删除 `3.4 Side algorithm 侧碰算法`。
- 检查 `Calibration Scope`，如果不包含 `Rose1`、`Rose1+`、`Rose_Angle`、`Rose_Static` 或 `RoseStatic`，则删除 `3.5 Roll over algorithm 侧翻算法`。
- 检查 `Calibration Scope`，如果不包含 `Rose_Static` 或 `RoseStatic`，则删除 `3.5.1 Static roll-over algorithm`。
- 检查 `Calibration Scope`，如果不包含 `PitchOver`，则删除 `3.6 Pitch-over algorithm`。
- 检查 `Calibration Scope`，如果不包含 `EPP` 或 `IDP`，则删除 `3.7 Pedestrian protection algorithm`。
- 检查 `Calibration Scope`，如果不包含 `IDP`，则删除 `3.7.1 Integrated collision detection pedestrian function`。
- 检查 `Calibration Scope`，如果不包含 `PCP`，则删除 `3.8 Pre-Crash positioning function`。
- 检查 `Calibration Scope`，如果不包含 `CrashGuard(SDD)`，则删除 `3.9 Crash-guard algorithm`。

- 检查 `Calibration Scope`，如果包含 `FSR` 且 `Peripheral Sensor` 包含 `RCS`，则保留 `3.3.1` 章节；否则删除 `3.3.1` 章节。

## 3. 3.2 Front algorithm 内容规则

### 3.2 首段传感器描述

模板原意为：中央传感器、UFS、PAS 用来探测正面碰撞。该句需要根据 `Peripheral Sensor` 自动保留已配置的传感器名称。

- 检查 `Peripheral Sensor`，如果同时包含 UFS 和 PAS，则保留 UFS 和 PAS 描述，并删除模板中的可选标记。
- 检查 `Peripheral Sensor`，如果只包含 UFS 且不包含 PAS，则只保留 UFS 相关描述，删除 PAS 相关描述。
- 检查 `Peripheral Sensor`，如果只包含 PAS 且不包含 UFS，则只保留 PAS 相关描述，删除 UFS 相关描述。
- 检查 `Peripheral Sensor`，如果既不包含 UFS 也不包含 PAS，则只保留中央传感器描述，删除 UFS 和 PAS 相关描述。

### 3.2 校验传感器描述

模板包含三类可选校验描述：UFS 失效后使用第二片中央传感器、UFS 失效后使用中央传感器第二通道、只使用第二片中央传感器。根据配置保留其中一种。

- 检查 `Peripheral Sensor`，如果不包含 UFS，则保留第四红字段落，删除二三。
- 检查 `Peripheral Sensor`，如果包含 UFS，且 `Inertial Sensor` 只有 1 个 `SMAx`，则保留第三红字段落，删除二四。
- 检查 `Peripheral Sensor`，如果包含 UFS，且 `Inertial Sensor` 不只是 1 个 `SMAx`，则保留第二红字段落，删除三四。

## 4. 3.2.1 UFS-defect strategy 内容规则

- 暂定默认自动删除该小节红色的段落。该删除与 `Calibration Scope`、`Peripheral Sensor`、`Inertial Sensor` 均无关。

## 5. 3.3 Rear algorithm 内容规则

### 3.3 首段传感器描述

同3.2

### 3.3 后碰 CRO 描述

模板中“后碰只发送 CRO、不点爆回路”的段落根据 `Fire Loops` 判断。

- 检查 `Fire Loops`，如果包含 `BATD` 关键字，则删除该 CRO 段落。
- 检查 `Fire Loops`，如果不包含 `BATD` 关键字，则保留该 CRO 段落。

### 3.3 中央后碰校验描述
已知3.3有6个红色段落。
第3、4段中的 `UFS/RCS`、`前碰/后碰传感器` 为占位写法，需要根据 `Peripheral Sensor` 改写。

- 检查 `Peripheral Sensor`，如果只包含 UFS 且不包含 RCS，则第3、4段中只保留 UFS 描述，删除 RCS 描述。
- 检查 `Peripheral Sensor`，如果只包含 RCS 且不包含 UFS，则第3、4段中只保留 RCS 描述，删除 UFS 描述。
- 检查 `Peripheral Sensor`，如果同时包含 UFS 和 RCS，则第3、4段中只保留 RCS 描述，删除 UFS 描述。
- 检查 `Peripheral Sensor`，如果同时既 UFS 和 RCS，则第3、4段中删除 UFS和RCS 描述。
- 检查 `Inertial Sensor`，如果不只有 1 个 `SMA`，则保留四，删除三。
- 检查 `Inertial Sensor`，如果只有 1 个 `SMA`，则保留三，删除四。
- 如果`Peripheral Sensor`既不包含 UFS 也不包含 RCS，则保留五，否则删除5.

默认删除段落六



### 3.3 RCS-based 后碰校验描述

模板中“RCS based rear crash detection”段落只在存在 RCS 相关配置时适用。

- 检查 `Peripheral Sensor`，如果包含 RCS，则保留 RCS based 相关描述。
- 检查 `Peripheral Sensor`，如果不包含 RCS，则删除 RCS based 相关描述。

### 3.3.1 RCS-defect Strategy

图片标注中该小节暂未绑定具体配置项。

- 暂定默认自动删除 `3.3.1 RCS-defect Strategy` 中带有可选性质的 RCS defect 策略说明。
- 如果后续需要按 RCS 配置控制该小节，应优先以 `Peripheral Sensor` 是否包含 RCS 作为判断条件。

## 6. 3.4 Side algorithm 内容规则

### 3.4 首段传感器列表
第一个红色段落
模板原意为：PAS/PPS、UFS-Y、RCS-Y 和中央传感器用来探测侧碰。该句需要根据 `Peripheral Sensor` 自动保留已配置的传感器名称，并删除模板中的编辑提示。

- 检查 `Peripheral Sensor`，如果同时包含 PAS 和 PPS，则保留 PAS 和 PPS 描述。
- 检查 `Peripheral Sensor`，如果只包含 PAS 且不包含 PPS，则只保留 PAS 描述，删除 PPS 描述。
- 检查 `Peripheral Sensor`，如果只包含 PPS 且不包含 PAS，则只保留 PPS 描述，删除 PAS 描述。
- 检查 `Peripheral Sensor`，如果既不包含 PAS 也不包含 PPS，则删除 PAS/PPS 相关描述。
- 检查 `Peripheral Sensor`，如果不包含 UFS-Y，则删除 UFS-Y 相关描述。
- 检查 `Peripheral Sensor`，如果不包含 RCS-Y，则删除 RCS-Y 相关描述。
- 检查 `Peripheral Sensor`，如果不包含 UFS 或 RCS，则保留该段其余描述。
-当PAS,PPS、UFS-Y、RCS-Y都不包含的时候，直接删除第一段落。
### 3.4 独立传感器确认描述



第二个红色段落。已知原来最后一句话是。
This could be e.g. a peripheral acceleration sensor and a central sensor, 
two independent peripheral acceleration sensors,  
or the two independent sensor channels of the central sensor. 
这种情况可以是一个外围传感器和一个中央传感器，或者是两个外围传感器，也可以是中央传感器的两个单独的传感器通道。

（1）检查Peripheral sensor配置：如果包含PAS & PPS。
就保留为This could be e.g. a peripheral acceleration sensor and a central sensor, or two independent peripheral acceleration sensors.
这种情况可以是一个外围传感器和一个中央传感器，或者是两个外围传感器。

（2）如果PPS 或PAS都不包含，同时Inertial sensor不只有1个SMA*。
就保留为This could be e.g. the two independent sensor channels of the central sensor. 
这种情况可以是中央传感器的两个单独的传感器通道。

（3）否则
就保留为This could be e.g. a peripheral acceleration sensor and a central sensor.
这种情况可以是一个外围传感器和一个中央传感器。

检查中英文多余标点。

### 3.5.1 
检查 Calibration scope，如果包含 Rose_Static，则保留 3.5.1 整章，否则删除
已知 3.5.1 有 4 个红色字体段落
检查 Inertial Sensor，如果包含 SMI8 或 SMI9，则保留第一个段落
检查 Inertial Sensor，如果包含 SMI7，则保留第二个段落
检查 Inertial Sensor，如果包含 SMA7 或 SMA8，则保留第三个段落
检查 Inertial Sensor，如果包含 SMU3，则保留第四个段落
删除没有对应的红色字体段落。

### 4.1 
已知 4.1 有 5 个红色字体段落

第二段 检查Calibration scope和Peripheral sensor，如果Calibration scope包含EPP且Peripheral sensor配置包含PTS，则保留该段，反之删除。

第四段 检查Calibration scope，如果包含EPP，则保留段落内文字。“and pedestrian Protection”，中文‘和行人保护’，否则删除。

第五段检查Calibration scope，如果包含Rose1或Rose1+或Rose_Angle，则保留该段；同时如果Calibration scope包含PitchOver，则保留"and Pitchover"及其中文"和俯仰碰撞"；反之删除对应部分。


### 5
Firing loop & Device configuration 根据Fire Loops填写占位符.
Sensor configuration 根据Product Category + Inertial sensor + Peripheral sensor填写占位符

### 8
已知本章节有两个段落
检查owner的后缀，EPD5-CN为中国，MS/EAB-VM为越南。
如果EPD5-CN则删除第二段，
如果MS/EAB-VM为则删除第一段。

## 7. 固定描述句式

新增或维护规则时建议使用以下固定句式：

- 章节删除：`检查 <字段名>，如果不包含 <关键词>，则删除 <章节号 章节名>。`
- 内容保留：`检查 <字段名>，如果 <条件>，则保留 <描述>，删除 <不适用描述>。`
- 内容改写：`检查 <字段名>，如果 <条件>，则将 <原描述> 改写为 <目标描述>。`
- 默认删除：`当前没有配置项可以判断适用性，暂定默认自动删除 <描述>。`

## 8. 注意事项

- `Calibration Scope` 控制章节是否存在；`Peripheral Sensor`、`Inertial Sensor`、`Fire Loops` 控制章节内部的可选内容。
- 先执行章节级删除，再执行章节内部段落删除和文字改写。
- 内容改写时应同时处理英文和中文描述。
- 删除多个可选短语后，需要再次清理多余逗号、句点、括号和连接词。
