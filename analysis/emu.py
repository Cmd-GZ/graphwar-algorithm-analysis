"""Unicorn-based harness to call functions inside libgraphwarrust.so directly."""
import struct, math, sys, os
from unicorn import *
from unicorn.x86_const import *

HERE = os.path.dirname(os.path.abspath(__file__))
SO = os.path.join(HERE, '..', 'libgraphwarrust.so')
if not os.path.exists(SO):
    raise SystemExit(
        "missing binary: %s\n"
        "The oracle harness needs your own copy of libgraphwarrust.so in the\n"
        "repository root (see README.md). graphwar_curve.py does NOT need it." % SO)

STACK = 0x70000000
STACK_SZ = 0x100000
HEAP = 0x50000000
HEAP_SZ = 0x4000000
TRAP = 0x20000000
TRAP_SZ = 0x10000
TLS = 0x30000000
TLS_SZ = 0x40000

XMMR = [UC_X86_REG_XMM0, UC_X86_REG_XMM1, UC_X86_REG_XMM2, UC_X86_REG_XMM3,
        UC_X86_REG_XMM4, UC_X86_REG_XMM5, UC_X86_REG_XMM6, UC_X86_REG_XMM7]


def _safe(fn):
    def w(*a):
        try:
            return fn(*a)
        except (ValueError, OverflowError, ZeroDivisionError):
            return float('nan')
    return w


MATH = {
    'sin': _safe(math.sin), 'cos': _safe(math.cos), 'tan': _safe(math.tan),
    'asin': _safe(math.asin), 'acos': _safe(math.acos), 'atan': _safe(math.atan),
    'sinh': _safe(math.sinh), 'cosh': _safe(math.cosh), 'tanh': _safe(math.tanh),
    'exp': _safe(math.exp), 'log': _safe(math.log), 'log10': _safe(math.log10),
    'log2': _safe(math.log2), 'sqrt': _safe(math.sqrt), 'fabs': _safe(abs),
    'floor': _safe(math.floor), 'ceil': _safe(math.ceil), 'round': _safe(round),
    'trunc': _safe(math.trunc),
}


def parse_elf(path):
    d = open(path, 'rb').read()
    e_phoff, = struct.unpack_from('<Q', d, 0x20)
    e_phentsize, e_phnum = struct.unpack_from('<HH', d, 0x36)
    segs = []
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = \
            struct.unpack_from('<IIQQQQQQ', d, o)
        if p_type == 1:
            segs.append((p_vaddr, p_offset, p_filesz, p_memsz, p_flags))
    return d, segs


class Emu:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.data, segs = parse_elf(SO)
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.segs = segs
        for vaddr, off, filesz, memsz, flags in segs:
            base = vaddr & ~0xfff
            top = (vaddr + memsz + 0xfff) & ~0xfff
            try:
                self.uc.mem_map(base, top - base, UC_PROT_ALL)
            except UcError:
                pass
            blob = self.data[off:off + filesz]
            if blob:
                self.uc.mem_write(vaddr, blob)
        self.uc.mem_map(STACK, STACK_SZ, UC_PROT_ALL)
        self.uc.mem_map(HEAP, HEAP_SZ, UC_PROT_ALL)
        self.uc.mem_map(TRAP, TRAP_SZ, UC_PROT_ALL)
        self.uc.mem_map(TLS, TLS_SZ, UC_PROT_ALL)
        td = None
        try:
            self.uc.mem_write(TLS + 0x4000, self.sec_data('.tdata'))
        except Exception:
            pass
        self.uc.mem_write(TRAP, b'\xcc' * TRAP_SZ)
        self.heap_ptr = HEAP
        self.imports = {}
        self.sizes = {}
        self._apply_relocs()
        self.hook_funcs = {}
        self.traces = {}
        self.total_alloc = 0

    # ---------- ELF dynamic info ----------
    def _sections(self):
        d = self.data
        e_shoff, = struct.unpack_from('<Q', d, 0x28)
        e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHH', d, 0x3a)
        secs = []
        for i in range(e_shnum):
            o = e_shoff + i * e_shentsize
            name, typ, flags, addr, offset, size = struct.unpack_from('<IIQQQQ', d, o)
            secs.append((name, typ, addr, offset, size))
        strtab = secs[e_shstrndx]
        names = {}
        for i, s in enumerate(secs):
            end = d.index(b'\0', strtab[3] + s[0])
            names[d[strtab[3] + s[0]:end].decode()] = i
        return secs, names

    def _apply_relocs(self):
        d = self.data
        secs, names = self._sections()
        dsym = secs[names['.dynsym']]
        dstr = secs[names['.dynstr']]
        syms = []
        for i in range(dsym[4] // 24):
            o = dsym[3] + i * 24
            nm, info, other, shndx, value, size = struct.unpack_from('<IBBHQQ', d, o)
            end = d.index(b'\0', dstr[3] + nm)
            syms.append(d[dstr[3] + nm:end].decode())
        slot = 0
        for relname in ('.rela.dyn', '.rela.plt'):
            if relname not in names:
                continue
            r = secs[names[relname]]
            for i in range(r[4] // 24):
                o = r[3] + i * 24
                off, info, add = struct.unpack_from('<QQq', d, o)
                typ = info & 0xffffffff
                symi = info >> 32
                if typ == 8:  # RELATIVE
                    if 0 < off < 0x100000000:
                        self.uc.mem_write(off, struct.pack('<Q', add & 0xffffffffffffffff))
                elif typ in (6, 7):  # GLOB_DAT, JUMP_SLOT
                    nm = syms[symi]
                    addr = TRAP + slot * 8
                    self.imports[addr] = nm
                    slot += 1
                    self.uc.mem_write(off, struct.pack('<Q', addr))

    def sec_data(self, name):
        d = self.data
        e_shoff, = struct.unpack_from('<Q', d, 0x28)
        e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHH', d, 0x3a)
        secs = []
        for i in range(e_shnum):
            o = e_shoff + i * e_shentsize
            nm, typ, flags, addr, offset, size = struct.unpack_from('<IIQQQQ', d, o)
            secs.append((nm, typ, addr, offset, size))
        strtab = secs[e_shstrndx]
        for s in secs:
            end = d.index(b'\0', strtab[3] + s[0])
            if d[strtab[3] + s[0]:end].decode() == name:
                return d[s[3]:s[3] + s[4]]
        return b''

    # ---------- memory helpers ----------
    def rd(self, addr, n):
        return bytes(self.uc.mem_read(addr, n))

    def wr(self, addr, b):
        self.uc.mem_write(addr, bytes(b))

    def rq(self, addr):
        return struct.unpack('<Q', bytes(self.uc.mem_read(addr, 8)))[0]

    def wq(self, addr, v):
        self.uc.mem_write(addr, struct.pack('<Q', v & 0xffffffffffffffff))

    def rd_f64(self, addr):
        return struct.unpack('<d', self.uc.mem_read(addr, 8))[0]

    def wr_f64(self, addr, v):
        self.uc.mem_write(addr, struct.pack('<d', v))

    def rd_f32(self, addr):
        return struct.unpack('<f', self.uc.mem_read(addr, 4))[0]

    def alloc(self, n, align=16):
        self.heap_ptr = (self.heap_ptr + 15) & ~15
        p = self.heap_ptr
        self.heap_ptr += max(n, 16) + 16
        if self.heap_ptr > HEAP + HEAP_SZ - 4096:
            raise RuntimeError('emulated heap exhausted')
        self.sizes[p] = n
        return p

    def xmm_get(self, i):
        raw = self.uc.reg_read(XMMR[i]) & 0xffffffffffffffff
        return struct.unpack('<d', struct.pack('<Q', raw))[0]

    def xmm_set(self, i, v):
        self.uc.reg_write(XMMR[i], struct.unpack('<Q', struct.pack('<d', v))[0])

    # ---------- hooks ----------
    def hook(self, addr, fn):
        self.hook_funcs[addr] = fn

    def trace(self, addr, fn):
        self.traces.setdefault(addr, []).append(fn)

    def _do_import(self, address):
        uc = self.uc
        name = self.imports[address].split('@')[0]
        rdi = uc.reg_read(UC_X86_REG_RDI)
        rsi = uc.reg_read(UC_X86_REG_RSI)
        rdx = uc.reg_read(UC_X86_REG_RDX)
        ret = None
        if name in MATH:
            self.xmm_set(0, MATH[name](self.xmm_get(0)))
        elif name == 'pow':
            a, b = self.xmm_get(0), self.xmm_get(1)
            try:
                r = a ** b
                if isinstance(r, complex):
                    r = float('nan')
            except OverflowError:
                r = float('inf')
            except ZeroDivisionError:
                r = float('inf')
            except Exception:
                r = float('nan')
            self.xmm_set(0, float(r))
        elif name == 'atan2':
            self.xmm_set(0, math.atan2(self.xmm_get(0), self.xmm_get(1)))
        elif name in ('posix_memalign', 'aligned_alloc'):
            if name == 'posix_memalign':
                align, size = rsi, rdx
                p = self.alloc(size + align, align)
                p = (p + align - 1) // align * align
                self.wq(rdi, p)
                ret = 0
            else:
                ret = self.alloc(rdx + rdi, rdi)
                ret = (ret + rdi - 1) // rdi * rdi
        elif name in ('getrandom', 'getentropy'):
            n = rsi if name == 'getrandom' else rdi
            self.wr(rdi if name == 'getrandom' else rdi, bytes((i * 37 + 11) & 0xff for i in range(n)))
            ret = n
        elif name == '__tls_get_addr':
            mod = self.rq(rdi)
            off = self.rq(rdi + 8)
            blk = TLS + mod * 0x4000
            ret = blk + off
        elif name in ('bcmp', 'memcmp'):
            a = self.rd(rdi, rdx)
            b = self.rd(rsi, rdx)
            ret = 0 if a == b else (1 if a > b else 0xffffffffffffffff)
        elif name in ('memcpy', 'memmove'):
            self.wr(rdi, self.rd(rsi, rdx))
            ret = rdi
        elif name == 'memset':
            self.wr(rdi, bytes([rsi & 0xff]) * rdx)
            ret = rdi
        elif name in ('malloc', '__rust_alloc'):
            if name == '__rust_alloc':
                rdi, rsi = rsi, rdx
            ret = self.alloc(rdi)
        elif name == 'calloc':
            p = self.alloc(rdi * rsi)
            self.wr(p, b'\x00' * (rdi * rsi))
            ret = p
        elif name in ('realloc', '__rust_realloc'):
            if name == '__rust_realloc':
                rdi, rsi = rsi, rdx
            oldn = self.sizes.get(rdi, 0)
            old = self.rd(rdi, oldn) if rdi else b''
            p = self.alloc(rsi)
            self.wr(p, old[:rsi])
            ret = p
        elif name in ('free', '__rust_dealloc', 'pthread_mutex_lock', 'pthread_mutex_unlock'):
            ret = None
        elif name in ('abort', 'exit', '_exit'):
            raise RuntimeError('abort() called')
        else:
            raise RuntimeError('unhandled import %s' % name)
        sp = uc.reg_read(UC_X86_REG_RSP)
        raddr = self.rq(sp)
        uc.reg_write(UC_X86_REG_RSP, sp + 8)
        uc.reg_write(UC_X86_REG_RIP, raddr)
        if ret is not None:
            uc.reg_write(UC_X86_REG_RAX, ret)

    def call(self, addr, args_regs=None, xmm=None, max_steps=500000000):
        uc = self.uc
        sp = STACK + STACK_SZ - 0x1000
        sp &= ~0xf
        self.wq(sp, 0xdeadbeef)
        uc.reg_write(UC_X86_REG_RSP, sp)
        regs = [UC_X86_REG_RDI, UC_X86_REG_RSI, UC_X86_REG_RDX, UC_X86_REG_RCX,
                UC_X86_REG_R8, UC_X86_REG_R9]
        if args_regs:
            for i, v in enumerate(args_regs):
                if v is not None:
                    uc.reg_write(regs[i], v)
        if xmm:
            for i, v in enumerate(xmm):
                if v is not None:
                    self.xmm_set(i, v)
        hooks = dict(self.hook_funcs)
        traces = {k: list(v) for k, v in self.traces.items()}

        def code_hook(uc, address, size, data):
            if address == 0xdeadbeef:
                raise StopIteration
            if address in traces:
                for f in traces[address]:
                    f(uc, address)
            if address in self.imports:
                self._do_import(address)
                return
            h = hooks.get(address)
            if h is not None:
                ret = self.rq(uc.reg_read(UC_X86_REG_RSP))
                res = h(uc)
                uc.reg_write(UC_X86_REG_RSP, uc.reg_read(UC_X86_REG_RSP) + 8)
                uc.reg_write(UC_X86_REG_RIP, ret)
                if res is not None:
                    uc.reg_write(UC_X86_REG_RAX, res)
                return

        h = uc.hook_add(UC_HOOK_CODE, code_hook)
        try:
            uc.emu_start(addr, 0xdeadbeef, count=max_steps)
        except StopIteration:
            pass
        finally:
            uc.hook_del(h)
        return self.rq(uc.reg_read(UC_X86_REG_RAX))
