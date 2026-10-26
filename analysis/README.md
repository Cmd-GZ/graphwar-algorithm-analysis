# analysis/ —— 逆向脚本

* `graphwar_curve.py`（在仓库根目录）是最终产物，这里的是过程脚本。

| 文件 | 说明 |
|---|---|
| `elf.py` | 极简 ELF64 解析 |
| `build_index.py` | capstone 线性反汇编 `.text` + 建 rip-relative 交叉引用索引（生成 `insns.pkl`/`xrefs.pkl`） |
| `dz.py` | 基于上面的索引做反汇编/交叉引用/函数边界查询（函数边界来自 `.eh_frame`） |
| `emu.py` / `gwemu.py` | unicorn 模拟器：把 `libgraphwarrust.so` 映射进 unicorn，直接调用其中的函数（含 allocator/TLS/memcpy 等 hook） |
| `difftest.py` | 定点用例差分测试（模型 vs 二进制） |
| `fuzz.py` | 随机表达式差分测试 |
| `difftest_parser.py` | 解析器对照测试 |
| `final_verify.py` | 端到端（文本 → token → 点序列、修正常数串）差分测试 |
| `gw1_model.py` | GW1（开源版）`processRange()` 数值部分的等价实现，用于两代对比 |
| `discontinuity.py` | 断点/陡坡在两代引擎里的四种组合（REPORT §5.7 ★★ 的数据来源） |
| `gw1_parser.py` | GW1 的 `PolishNotationFunction` 解析器/求值器等价实现 |
| `decomp_*.c` | Ghidra 反编译输出 |
| `shotcalc.asm` | 开火结算函数（0x3c2bc0）的完整反汇编 |
| `pck/` | `Graphwar.pck` 解包结果 |
| `relocs.pkl` `fdes.pkl` `funcstarts.pkl` | 重定位表 / `.eh_frame` FDE 表（函数边界） |

## 不在仓库里的文件（都由 `regen.sh` 生成）

因为体积、版权、以及里面含开发者构建路径，下面这些**不提交**：

```
insns.pkl xrefs.pkl relocs.pkl fdes.pkl funcstarts.pkl funcstarts.txt
lib_strings.txt decomp_*.c shotcalc.asm pck/ pck_index.json ghidra_proj/
```

`./regen.sh` 一次全部重建（需要仓库根目录放好你自己的 `libgraphwarrust.so` / `Graphwar.pck`）。

## 运行测试

```bash
../.venv/bin/python difftest.py            # 704 条定点用例
../.venv/bin/python fuzz.py 300 7          # 随机表达式
../.venv/bin/python difftest_parser.py     # 解析器
../.venv/bin/python final_verify.py        # 端到端 + 修正串
../.venv/bin/python discontinuity.py       # 断点/陡坡/ε 实验
```

所有测试都是"模型 vs 二进制（unicorn）"的逐位比较；没有 `libgraphwarrust.so` 时
`emu.py` 会直接报错并提示把文件放哪里——`graphwar_curve.py` 不需要它。
