import sys, os, struct, pickle, bisect
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from elf import Elf
from capstone import Cs, CS_ARCH_X86, CS_MODE_64, CS_OPT_SYNTAX_INTEL
from capstone.x86 import X86_OP_MEM, X86_OP_IMM, X86_REG_RIP

E = Elf(os.path.join(HERE, '..', 'libgraphwarrust.so'))


def _load(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        raise SystemExit(
            "missing index file %s\n"
            "Run `python3 analysis/build_index.py` first (needs capstone)." % name)
    return pickle.load(open(path, 'rb'))


INS = _load('insns.pkl')
XR = _load('xrefs.pkl')
REL = _load('relocs.pkl')
FDES = _load('fdes.pkl')
STARTS = [a for a, b in FDES]
STARTSET = set(STARTS)
FDED = dict(FDES)
MD = Cs(CS_ARCH_X86, CS_MODE_64); MD.detail = True; MD.syntax = CS_OPT_SYNTAX_INTEL


def load_dynsyms():
    d = E.data
    ds = E.sec('.dynsym'); dstr = E.sec('.dynstr')
    syms = {}
    for i in range(ds['size'] // 24):
        name, info, other, shndx, value, size = struct.unpack_from('<IBBHQQ', d, ds['offset'] + i * 24)
        nm = d[dstr['offset'] + name: d.index(b'\0', dstr['offset'] + name)].decode()
        syms[i] = (nm, value)
    return syms


SYMS = load_dynsyms()


def got_names():
    """map GOT slot vaddr -> imported symbol name, from .rela.plt and .rela.dyn R_X86_64_GLOB_DAT/JUMP_SLOT"""
    d = E.data
    out = {}
    for sname in ('.rela.plt', '.rela.dyn'):
        s = E.by_name.get(sname)
        if not s:
            continue
        for i in range(s['size'] // 24):
            off, info, add = struct.unpack_from('<QQq', d, s['offset'] + i * 24)
            typ = info & 0xffffffff
            sym = info >> 32
            if typ in (6, 7) and sym in SYMS:  # GLOB_DAT, JUMP_SLOT
                out[off] = SYMS[sym][0]
    return out


GOT = got_names()


def reloc_val(addr):
    v = REL.get(addr)
    if v:
        return v[0][1]
    return None


def annot(addr):
    """annotate a target address"""
    s = E.sec_of(addr)
    if s is None:
        return ''
    if s == '.rodata':
        b = E.read(addr, 80)
        if b and 32 <= b[0] < 127:
            txt = b.split(b'\0')[0].decode('utf-8', 'replace')
            if len(txt) > 2 and all(31 < c < 127 for c in txt.encode()):
                return '; "%s"' % txt[:70]
        return '; rodata data'
    if s == '.data.rel.ro':
        return '; data.rel.ro'
    if s in ('.data', '.bss'):
        return '; bss/data'
    return ''


def dump_func(addr, max_ins=400, name=''):
    start = fstart(addr)
    nxt = start + FDED[start]
    print(f'### function {start:#x} .. {nxt:#x}  (entry from {addr:#x}) {name}')
    o = E.addr_to_off(start)
    blob = E.data[o:o + min((nxt - start), max_ins * 15)]
    for ins in MD.disasm(blob, start):
        if ins.address >= nxt:
            break
        extra = ''
        for op in ins.operands:
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP:
                tgt = ins.address + ins.size + op.mem.disp
                if ins.mnemonic == 'call' or ins.mnemonic == 'jmp':
                    if tgt in GOT:
                        extra = f'   ; -> {GOT[tgt]}'
                    else:
                        extra = f'   ; -> [{tgt:#x}] {annot(tgt)}'
                else:
                    extra = f'   ; = {tgt:#x} {annot(tgt)}'
            elif op.type == X86_OP_IMM and ins.mnemonic in ('call', 'jmp', 'je', 'jne', 'jmp', 'jg', 'jl', 'jge', 'jle', 'ja', 'jb', 'jae', 'jbe', 'js', 'jns', 'jo', 'jno', 'jz', 'jnz') and op.imm > 0x37b940:
                extra = '   ; ' + ('func' if op.imm in STARTSET else '')
        print(f'{ins.address:08x}  {ins.mnemonic:<7} {ins.op_str}{extra}')
    return start, nxt


def dis_range(a, b, annotate=True):
    o = E.addr_to_off(a)
    blob = E.data[o:o + (b - a)]
    for ins in MD.disasm(blob, a):
        extra = ''
        for op in ins.operands:
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP:
                tgt = ins.address + ins.size + op.mem.disp
                if tgt in GOT:
                    extra = f'   ; -> {GOT[tgt]}'
                else:
                    extra = f'   ; = {tgt:#x} {annot(tgt)}'
        print(f'{ins.address:08x}  {ins.mnemonic:<7} {ins.op_str}{extra}')


def refs_to(addr):
    return XR.get(addr, [])


def fstart(a):
    return STARTS[bisect.bisect_right(STARTS, a) - 1]


def callers(faddr):
    out = []
    for a, ins in INS.items():
        m, ops, size, by = ins
        if m in ('call', 'jmp'):
            if ops.startswith('0x'):
                try:
                    t = int(ops.split()[0], 16)
                except Exception:
                    continue
                if t == faddr:
                    out.append(a)
    return out
