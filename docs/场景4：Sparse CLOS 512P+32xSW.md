---
number headings: auto, first-level 1, max 6, 1.1
---
# 1 拓扑

- 拓扑中一共512台NPU
- 每台NPU编号为NPU-CxSy, C代表Cluster，S代表Server
	- 系统一共8个Cluser，64个Server，一共8*64=512P
- 每台NPU有15个400G端口
	- 7个400G端口，分别与Server内的其他7个NPU互联，实现Server内NPU之间的FullMesh直连
		- 分别用NPU-CxSyPFMz表示，z表示与相同server的第z个NPU直连
	- 8个400G端口，分别连到8台SW，用于与其他server的NPU通讯
		- 分别用NPU-CxSyPz表示，Pz代表第z个连SW的端口,z=[1,8]
- Switch(SW)
	- 总共32台SW
	- 每台SW有128个400G端口
	- 每台交换机都会连两个Cluster的所有NPU
	- SW编号为SW-a-b，a和b分别代表两个cluster的编号
		- SW-a-b用于cluster a到cluster b的非相同server之间的NPU之间通信，也用于cluster a到cluster b的非相同server的NPU之间通信
	- SW编号为SW-a-b-S
		- SW-a-b-S 用于cluster a到cluster a的非相同server之间的NPU之间通信，也用于cluster a到cluster b的非相同server的NPU之间通信

具体连接关系

**SW连接关系**

| SW       | Cluster a的与SW连接的NPU端口号 | Cluster b的与SW连接的NPU端口号 |
| :------- | :--------------------- | :--------------------- |
| SW-1-2   | NPU-C1S*P1             | NPU-C2S*P1             |
| SW-1-2-S | NPU-C1S*P2             | NPU-C2S*P2             |
| SW-1-3   | NPU-C1S*P3             | NPU-C3S*P1             |
| SW-1-4   | NPU-C1S*P4             | NPU-C4S*P1             |
| SW-1-5   | NPU-C1S*P5             | NPU-C5S*P1             |
| SW-1-6   | NPU-C1S*P6             | NPU-C6S*P1             |
| SW-1-7   | NPU-C1S*P7             | NPU-C7S*P1             |
| SW-1-8   | NPU-C1S*P8             | NPU-C8S*P1             |
| SW-3-4   | NPU-C3S*P2             | NPU-C4S*P2             |
| SW-3-4-S | NPU-C3S*P3             | NPU-C4S*P3             |
| SW-2-3   | NPU-C2S*P3             | NPU-C3S*P4             |
| SW-2-4   | NPU-C2S*P4             | NPU-C4S*P4             |
| SW-2-5   | NPU-C2S*P5             | NPU-C5S*P2             |
| SW-2-6   | NPU-C2S*P6             | NPU-C6S*P2             |
| SW-2-7   | NPU-C2S*P7             | NPU-C7S*P2             |
| SW-2-8   | NPU-C2S*P8             | NPU-C8S*P2             |
| SW-5-6   | NPU-C5S*P3             | NPU-C6S*P3             |
| SW-5-6-S | NPU-C5S*P4             | NPU-C6S*P4             |
| SW-3-5   | NPU-C3S*P5             | NPU-C5S*P5             |
| SW-3-6   | NPU-C3S*P6             | NPU-C6S*P5             |
| SW-3-7   | NPU-C3S*P7             | NPU-C7S*P3             |
| SW-3-8   | NPU-C3S*P8             | NPU-C8S*P3             |
| SW-4-5   | NPU-C4S*P5             | NPU-C5S*P6             |
| SW-4-6   | NPU-C4S*P6             | NPU-C6S*P6             |
| SW-4-7   | NPU-C4S*P7             | NPU-C7S*P4             |
| SW-4-8   | NPU-C4S*P8             | NPU-C8S*P4             |
| SW-7-8   | NPU-C7S*P5             | NPU-C8S*P5             |
| SW-7-8-S | NPU-C7S*P6             | NPU-C8S*P6             |
| SW-5-7   | NPU-C5S*P7             | NPU-C7S*P7             |
| SW-5-8   | NPU-C5S*P8             | NPU-C8S*P7             |
| SW-6-7   | NPU-C6S*P7             | NPU-C7S*P8             |
| SW-6-8   | NPU-C6S*P8             | NPU-C8S*P8             |
根据以上关系，可以商城


**NPU路由规则**

| Src NPU | Dst NPU | Port | SW | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| NPU-C1S\* | NPU-C1S\* | NPU-C1S\*PFMz | 无 (直连) | 同 Server 内 NPU 之间 FullMesh 直连 |
| NPU-C1S\* | NPU-C1S\* | NPU-C1S\*P2 | SW-1-2-S | C1 内部跨 Server 通信 |
| NPU-C1S\* | NPU-C2S\* | NPU-C1S\*P1 | SW-1-2 | C1 到 C2 跨集群通信（主路由） |
| NPU-C1S\* | NPU-C2S\* | NPU-C1S\*P2 | SW-1-2-S | C1 到 C2 跨集群通信（多路径/备份） |
| NPU-C1S\* | NPU-C3S\* | NPU-C1S\*P3 | SW-1-3 | C1 到 C3 跨集群通信 |
| NPU-C1S\* | NPU-C4S\* | NPU-C1S\*P4 | SW-1-4 | C1 到 C4 跨集群通信 |
| NPU-C1S\* | NPU-C5S\* | NPU-C1S\*P5 | SW-1-5 | C1 到 C5 跨集群通信 |
| NPU-C1S\* | NPU-C6S\* | NPU-C1S\*P6 | SW-1-6 | C1 到 C6 跨集群通信 |
| NPU-C1S\* | NPU-C7S\* | NPU-C1S\*P7 | SW-1-7 | C1 到 C7 跨集群通信 |
| NPU-C1S\* | NPU-C8S\* | NPU-C1S\*P8 | SW-1-8 | C1 到 C8 跨集群通信 |
| NPU-C2S\* | NPU-C2S\* | NPU-C2S\*PFMz | 无 (直连) | 同 Server 内 NPU 之间 FullMesh 直连 |
| NPU-C2S\* | NPU-C2S\* | NPU-C2S\*P2 | SW-1-2-S | C2 内部跨 Server 通信 |
| NPU-C2S\* | NPU-C1S\* | NPU-C2S\*P1 | SW-1-2 | C2 到 C1 跨集群通信（主路由） |
| NPU-C2S\* | NPU-C1S\* | NPU-C2S\*P2 | SW-1-2-S | C2 到 C1 跨集群通信（多路径/备份） |
| NPU-C2S\* | NPU-C3S\* | NPU-C2S\*P3 | SW-2-3 | C2 到 C3 跨集群通信 |
| NPU-C2S\* | NPU-C4S\* | NPU-C2S\*P4 | SW-2-4 | C2 到 C4 跨集群通信 |
| NPU-C2S\* | NPU-C5S\* | NPU-C2S\*P5 | SW-2-5 | C2 到 C5 跨集群通信 |
| NPU-C2S\* | NPU-C6S\* | NPU-C2S\*P6 | SW-2-6 | C2 到 C6 跨集群通信 |
| NPU-C2S\* | NPU-C7S\* | NPU-C2S\*P7 | SW-2-7 | C2 到 C7 跨集群通信 |
| NPU-C2S\* | NPU-C8S\* | NPU-C2S\*P8 | SW-2-8 | C2 到 C8 跨集群通信 |
| NPU-C3S\* | NPU-C3S\* | NPU-C3S\*PFMz | 无 (直连) | 同 Server 内 NPU 之间 FullMesh 直连 |
| NPU-C3S\* | NPU-C3S\* | NPU-C3S\*P3 | SW-3-4-S | C3 内部跨 Server 通信 |
| NPU-C3S\* | NPU-C1S\* | NPU-C3S\*P1 | SW-1-3 | C3 到 C1 跨集群通信 |
| NPU-C3S\* | NPU-C2S\* | NPU-C3S\*P4 | SW-2-3 | C3 到 C2 跨集群通信 |
| NPU-C3S\* | NPU-C4S\* | NPU-C3S\*P2 | SW-3-4 | C3 到 C4 跨集群通信（主路由） |
| NPU-C3S\* | NPU-C4S\* | NPU-C3S\*P3 | SW-3-4-S | C3 到 C4 跨集群通信（多路径/备份） |
| NPU-C3S\* | NPU-C5S\* | NPU-C3S\*P5 | SW-3-5 | C3 到 C5 跨集群通信 |
| NPU-C3S\* | NPU-C6S\* | NPU-C3S\*P6 | SW-3-6 | C3 到 C6 跨集群通信 |
| NPU-C3S\* | NPU-C7S\* | NPU-C3S\*P7 | SW-3-7 | C3 到 C7 跨集群通信 |
| NPU-C3S\* | NPU-C8S\* | NPU-C3S\*P8 | SW-3-8 | C3 到 C8 跨集群通信 |
| NPU-C4S\* | NPU-C4S\* | NPU-C4S\*PFMz | 无 (直连) | 同 Server 内 NPU 之间 FullMesh 直连 |
| NPU-C4S\* | NPU-C4S\* | NPU-C4S\*P3 | SW-3-4-S | C4 内部跨 Server 通信 |
| NPU-C4S\* | NPU-C1S\* | NPU-C4S\*P1 | SW-1-4 | C4 到 C1 跨集群通信 |
| NPU-C4S\* | NPU-C2S\* | NPU-C4S\*P4 | SW-2-4 | C4 到 C2 跨集群通信 |
| NPU-C4S\* | NPU-C3S\* | NPU-C4S\*P2 | SW-3-4 | C4 到 C3 跨集群通信（主路由） |
| NPU-C4S\* | NPU-C3S\* | NPU-C4S\*P3 | SW-3-4-S | C4 到 C3 跨集群通信（多路径/备份） |
| NPU-C4S\* | NPU-C5S\* | NPU-C4S\*P5 | SW-4-5 | C4 到 C5 跨集群通信 |
| NPU-C4S\* | NPU-C6S\* | NPU-C4S\*P6 | SW-4-6 | C4 到 C6 跨集群通信 |
| NPU-C4S\* | NPU-C7S\* | NPU-C4S\*P7 | SW-4-7 | C4 到 C7 跨集群通信 |
| NPU-C4S\* | NPU-C8S\* | NPU-C4S\*P8 | SW-4-8 | C4 到 C8 跨集群通信 |
| NPU-C5S\* | NPU-C5S\* | NPU-C5S\*PFMz | 无 (直连) | 同 Server 内 NPU 之间 FullMesh 直连 |
| NPU-C5S\* | NPU-C5S\* | NPU-C5S\*P4 | SW-5-6-S | C5 内部跨 Server 通信 |
| NPU-C5S\* | NPU-C1S\* | NPU-C5S\*P1 | SW-1-5 | C5 到 C1 跨集群通信 |
| NPU-C5S\* | NPU-C2S\* | NPU-C5S\*P2 | SW-2-5 | C5 到 C2 跨集群通信 |
| NPU-C5S\* | NPU-C3S\* | NPU-C5S\*P5 | SW-3-5 | C5 到 C3 跨集群通信 |
| NPU-C5S\* | NPU-C4S\* | NPU-C5S\*P6 | SW-4-5 | C5 到 C4 跨集群通信 |
| NPU-C5S\* | NPU-C6S\* | NPU-C5S\*P3 | SW-5-6 | C5 到 C6 跨集群通信（主路由） |
| NPU-C5S\* | NPU-C6S\* | NPU-C5S\*P4 | SW-5-6-S | C5 到 C6 跨集群通信（多路径/备份） |
| NPU-C5S\* | NPU-C7S\* | NPU-C5S\*P7 | SW-5-7 | C5 到 C7 跨集群通信 |
| NPU-C5S\* | NPU-C8S\* | NPU-C5S\*P8 | SW-5-8 | C5 到 C8 跨集群通信 |
| NPU-C6S\* | NPU-C6S\* | NPU-C6S\*PFMz | 无 (直连) | 同 Server 内 NPU 之间 FullMesh 直连 |
| NPU-C6S\* | NPU-C6S\* | NPU-C6S\*P4 | SW-5-6-S | C6 内部跨 Server 通信 |
| NPU-C6S\* | NPU-C1S\* | NPU-C6S\*P1 | SW-1-6 | C6 到 C1 跨集群通信 |
| NPU-C6S\* | NPU-C2S\* | NPU-C6S\*P2 | SW-2-6 | C6 到 C2 跨集群通信 |
| NPU-C6S\* | NPU-C3S\* | NPU-C6S\*P5 | SW-3-6 | C6 到 C3 跨集群通信 |
| NPU-C6S\* | NPU-C4S\* | NPU-C6S\*P6 | SW-4-6 | C6 到 C4 跨集群通信 |
| NPU-C6S\* | NPU-C5S\* | NPU-C6S\*P3 | SW-5-6 | C6 到 C5 跨集群通信（主路由） |
| NPU-C6S\* | NPU-C5S\* | NPU-C6S\*P4 | SW-5-6-S | C6 到 C5 跨集群通信（多路径/备份） |
| NPU-C6S\* | NPU-C7S\* | NPU-C6S\*P7 | SW-6-7 | C6 到 C7 跨集群通信 |
| NPU-C6S\* | NPU-C8S\* | NPU-C6S\*P8 | SW-6-8 | C6 到 C8 跨集群通信 |
| NPU-C7S\* | NPU-C7S\* | NPU-C7S\*PFMz | 无 (直连) | 同 Server 内 NPU 之间 FullMesh 直连 |
| NPU-C7S\* | NPU-C7S\* | NPU-C7S\*P6 | SW-7-8-S | C7 内部跨 Server 通信 |
| NPU-C7S\* | NPU-C1S\* | NPU-C7S\*P1 | SW-1-7 | C7 到 C1 跨集群通信 |
| NPU-C7S\* | NPU-C2S\* | NPU-C7S\*P2 | SW-2-7 | C7 到 C2 跨集群通信 |
| NPU-C7S\* | NPU-C3S\* | NPU-C7S\*P3 | SW-3-7 | C7 到 C3 跨集群通信 |
| NPU-C7S\* | NPU-C4S\* | NPU-C7S\*P4 | SW-4-7 | C7 到 C4 跨集群通信 |
| NPU-C7S\* | NPU-C5S\* | NPU-C7S\*P7 | SW-5-7 | C7 到 C5 跨集群通信 |
| NPU-C7S\* | NPU-C6S\* | NPU-C7S\*P8 | SW-6-7 | C7 到 C6 跨集群通信 |
| NPU-C7S\* | NPU-C8S\* | NPU-C7S\*P5 | SW-7-8 | C7 到 C8 跨集群通信（主路由） |
| NPU-C7S\* | NPU-C8S\* | NPU-C7S\*P6 | SW-7-8-S | C7 到 C8 跨集群通信（多路径/备份） |
| NPU-C8S\* | NPU-C8S\* | NPU-C8S\*PFMz | 无 (直连) | 同 Server 内 NPU 之间 FullMesh 直连 |
| NPU-C8S\* | NPU-C8S\* | NPU-C8S\*P6 | SW-7-8-S | C8 内部跨 Server 通信 |
| NPU-C8S\* | NPU-C1S\* | NPU-C8S\*P1 | SW-1-8 | C8 到 C1 跨集群通信 |
| NPU-C8S\* | NPU-C2S\* | NPU-C8S\*P2 | SW-2-8 | C8 到 C2 跨集群通信 |
| NPU-C8S\* | NPU-C3S\* | NPU-C8S\*P3 | SW-3-8 | C8 到 C3 跨集群通信 |
| NPU-C8S\* | NPU-C4S\* | NPU-C8S\*P4 | SW-4-8 | C8 到 C4 跨集群通信 |
| NPU-C8S\* | NPU-C5S\* | NPU-C8S\*P7 | SW-5-8 | C8 到 C5 跨集群通信 |
| NPU-C8S\* | NPU-C6S\* | NPU-C8S\*P8 | SW-6-8 | C8 到 C6 跨集群通信 |
| NPU-C8S\* | NPU-C7S\* | NPU-C8S\*P5 | SW-7-8 | C8 到 C7 跨集群通信（主路由） |
| NPU-C8S\* | NPU-C7S\* | NPU-C8S\*P6 | SW-7-8-S | C8 到 C7 跨集群通信（多路径/备份） |



# 2 路由配置

NPU转发表：
基于**NPU路由规则**查表生成

SW转发表：
基于**SW连接关系**生成，每台SW只保存连接关系表中cluster a和cluster b的所有NPU

