# 工业协议与通信规范

## Modbus

Modbus 是一种串行通信协议，广泛应用于工业电子设备之间。Modbus RTU 采用二进制编码，运行于 RS485 总线；Modbus TCP 则运行于以太网。

常见功能码：
- 01：读取线圈状态
- 03：读取保持寄存器
- 04：读取输入寄存器
- 06：写入单个寄存器

## OPC UA

OPC UA（Open Platform Communications Unified Architecture）是一种面向工业 4.0 的跨平台、面向服务的通信协议。OPC UA 提供统一的信息模型、安全机制和订阅/发布模式，支持复杂数据结构与语义互操作。

核心概念：
- AddressSpace：地址空间，包含所有可被访问的节点。
- Node：节点，分为对象、变量、方法等类型。
- Session：客户端与服务端之间的安全会话。

## MQTT

MQTT（Message Queuing Telemetry Transport）是一种轻量级发布/订阅协议，适用于物联网场景。MQTT 通过主题（Topic）进行消息路由，支持 QoS 0、1、2 三种服务质量等级。

主题设计建议：
```
factory/line1/machine/temperature
```

## 协议选型建议

- 实时控制：优先使用 Modbus RTU 或 EtherCAT。
- 设备互联互通：优先使用 OPC UA。
- 云端数据上送：优先使用 MQTT over TLS。
