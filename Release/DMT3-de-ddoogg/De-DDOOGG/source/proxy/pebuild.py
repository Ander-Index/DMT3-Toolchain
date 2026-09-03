import struct, re
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

SECTION_ALIGN = 0x1000
FILE_ALIGN = 0x200

SCN_CODE = 0x60000020
SCN_RDATA = 0x40000040
SCN_DATA = 0xC0000040
SCN_IDATA = 0xC0000040
SCN_EDATA = 0x40000040
SCN_RELOC = 0x42000040

def align_up(x, a):
    return (x + a - 1) & ~(a - 1)

class Assembler:
    """Assembles x86 code with local labels and absolute data references."""
    def __init__(self, ks):
        self.ks = ks
        self.data = bytearray()
        self.labels = {}
        self.abs = []       # (offset_of_imm32, symbol_name)
        self.rel32 = []     # (offset_of_disp32, label_name)
        self._pc = 0

    def label(self, name):
        self.labels[name] = len(self.data)

    def raw(self, b):
        self.data += b

    def emit(self, text):
        tokens = []
        def repl(m):
            name = m.group(1)
            add = 0
            if m.group(2):
                add = int(re.sub(r'\s+', '', m.group(2)))
            ph = 0x7f000000 + self._pc
            self._pc += 1
            tokens.append((name, ph + add, add))
            return '0x%x' % (ph + add)
        text2 = re.sub(r'&([A-Za-z_][A-Za-z0-9_]*)\s*([+-]\s*\d+)?', repl, text)
        enc, _ = self.ks.asm(text2)
        b = bytes(enc)
        for name, phval, add in tokens:
            pos = b.find(struct.pack('<I', phval))
            assert pos >= 0, "abs ref %r not found in: %s" % (name, text)
            self.abs.append((len(self.data) + pos, name, add))
        self.data += b

    def _rel(self, opcode, target):
        self.data += opcode
        self.rel32.append((len(self.data), target))
        self.data += b'\x00\x00\x00\x00'

    def call_label(self, name):
        self._rel(b'\xe8', name)

    def jmp_label(self, name):
        self._rel(b'\xe9', name)

    _jcc = {'je':0x84,'jne':0x85,'jb':0x82,'jae':0x83,'jz':0x84,'jnz':0x85,
            'jbe':0x86,'ja':0x87,'jl':0x8c,'jge':0x8d,'jle':0x8e,'jg':0x8f}

    def jcc(self, cc, name):
        self.data += b'\x0f' + bytes([self._jcc[cc]])
        self.rel32.append((len(self.data), name))
        self.data += b'\x00\x00\x00\x00'

    def finalize_labels(self):
        for off, name in self.rel32:
            target = self.labels[name]
            self.data[off:off+4] = struct.pack('<i', target - (off + 4))


class DLLBuilder:
    def __init__(self, image_base=0x10000000, name="out.dll"):
        self.image_base = image_base
        self.name = name
        self.ks = Ks(KS_ARCH_X86, KS_MODE_32)
        self.asm = Assembler(self.ks)
        self.sections = []      # dicts {name, chars, data}
        self.data_syms = []     # (symbol, secname, offset)
        self.imports = {}       # dll -> [funcs]
        self.exports = []       # (name, code_label)
        self.entry_label = None

    def new_section(self, name, chars):
        s = {'name': name, 'chars': chars, 'data': bytearray()}
        self.sections.append(s)
        return s

    def add_data(self, secname, symbol, raw):
        s = next(x for x in self.sections if x['name'] == secname)
        off = len(s['data'])
        s['data'] += raw
        self.data_syms.append((symbol, secname, off))
        return off

    def build(self):
        # drop empty user sections (keeps layout gap-free); .text always kept
        self.sections = [s for s in self.sections
                         if s['name'] == '.text' or len(s['data']) > 0]

        # 1. put assembled text into .text
        text = next(s for s in self.sections if s['name'] == '.text')
        self.asm.finalize_labels()
        text['data'] = bytearray(self.asm.data)

        # 2. compute rvas for user sections in order
        rva = SECTION_ALIGN
        sec_rva = {}
        for s in self.sections:
            s['rva'] = align_up(rva, SECTION_ALIGN)
            sec_rva[s['name']] = s['rva']
            rva = s['rva'] + align_up(len(s['data']), SECTION_ALIGN)

        # 3. resolve data symbols
        syms = {}
        for sym, secname, off in self.data_syms:
            syms[sym] = sec_rva[secname] + off

        # code symbols
        text_rva = sec_rva['.text']
        for lbl, off in self.asm.labels.items():
            syms[lbl] = text_rva + off

        extra = []

        # 4. idata
        if self.imports:
            idata_rva = align_up(rva, SECTION_ALIGN)
            idata_bytes, imp_syms = self._build_idata(idata_rva)
            for sym, off in imp_syms.items():
                syms[sym] = idata_rva + off
            extra.append({'name': '.idata', 'chars': SCN_IDATA, 'data': idata_bytes, 'rva': idata_rva})
            rva = idata_rva + align_up(len(idata_bytes), SECTION_ALIGN)

        # 5. edata
        if self.exports:
            edata_rva = align_up(rva, SECTION_ALIGN)
            edata_bytes = self._build_edata(edata_rva, syms)
            extra.append({'name': '.edata', 'chars': SCN_EDATA, 'data': edata_bytes, 'rva': edata_rva})
            rva = edata_rva + align_up(len(edata_bytes), SECTION_ALIGN)

        # 6. resolve abs refs, collect reloc rvas
        reloc_rvas = []
        for off, name, add in self.asm.abs:
            trva = syms[name] + add
            struct.pack_into('<I', text['data'], off, self.image_base + trva)
            reloc_rvas.append(text_rva + off)

        # 7. reloc
        if reloc_rvas:
            reloc_rva = align_up(rva, SECTION_ALIGN)
            reloc_bytes = self._build_reloc(reloc_rvas)
            extra.append({'name': '.reloc', 'chars': SCN_RELOC, 'data': reloc_bytes, 'rva': reloc_rva})

        all_sections = self.sections + extra

        return self._write_file(all_sections, syms)

    def _build_idata(self, base_rva):
        dlls = list(self.imports.keys())
        ndll = len(dlls)
        off = 0
        def alloc(n):
            nonlocal off
            r = off
            off += n
            return r

        # import descriptors: (ndll+1)*20
        desc_off = alloc((ndll + 1) * 20)
        imp_syms = {}
        descriptors = []
        for dllname in dlls:
            funcs = self.imports[dllname]
            # align names/arrays
            # DLL name string
            name_off = alloc(len(dllname) + 1)
            # INT: (len+1)*4
            int_off = alloc((len(funcs) + 1) * 4)
            # IAT: (len+1)*4
            iat_off = alloc((len(funcs) + 1) * 4)
            # hint/name entries
            hn_offs = []
            for f in funcs:
                hn_offs.append(alloc(2 + len(f) + 1))
            descriptors.append((dllname, name_off, int_off, iat_off, funcs, hn_offs))
            for i, f in enumerate(funcs):
                imp_syms['imp_' + f] = ('idata', iat_off + i * 4)

        # pad to 4
        off = align_up(off, 4)
        data = bytearray(off)

        # fill descriptors (fields are RVAs relative to image base)
        for i, (dllname, name_off, int_off, iat_off, funcs, hn_offs) in enumerate(descriptors):
            d = desc_off + i * 20
            struct.pack_into('<IIIII', data, d,
                             base_rva + int_off, 0, 0,
                             base_rva + name_off, base_rva + iat_off)
            data[name_off:name_off+len(dllname)] = dllname.encode()
            for j, f in enumerate(funcs):
                hn = hn_offs[j]
                struct.pack_into('<H', data, hn, 0)
                data[hn+2:hn+2+len(f)] = f.encode()
                struct.pack_into('<I', data, int_off + j*4, base_rva + hn)
                struct.pack_into('<I', data, iat_off + j*4, base_rva + hn)
        return bytes(data), {k: v[1] for k, v in imp_syms.items()}

    def _build_edata(self, base_rva, syms):
        # exports: sorted by name
        exports = sorted(self.exports, key=lambda x: x[0])
        n = len(exports)
        # directory 40 + functions array n*4 + names array n*4 + ordinals n*2 + name strings + dllname
        dllname = self.name.encode() + b'\x00'
        off = 0
        def alloc(n):
            nonlocal off
            r = off
            off += n
            return r
        dir_off = alloc(40)
        funcs_off = alloc(n * 4)
        names_off = alloc(n * 4)
        ords_off = alloc(n * 2)
        str_offs = {}
        for nm, _ in exports:
            str_offs[nm] = alloc(len(nm) + 1)
        dllname_off = alloc(len(dllname))
        off = align_up(off, 4)
        data = bytearray(off)

        struct.pack_into('<IIHHIIIIIII', data, dir_off,
                         0, 0, 0, 0, base_rva + dllname_off, 1, n, n,
                         base_rva + funcs_off, base_rva + names_off, base_rva + ords_off)
        data[dllname_off:dllname_off+len(dllname)] = dllname
        for i, (nm, lbl) in enumerate(exports):
            struct.pack_into('<I', data, funcs_off + i*4, syms[lbl])
            struct.pack_into('<I', data, names_off + i*4, base_rva + str_offs[nm])
            struct.pack_into('<H', data, ords_off + i*2, i)
            data[str_offs[nm]:str_offs[nm]+len(nm)] = nm.encode()
        return bytes(data)

    def _build_reloc(self, rvas):
        # group by page
        pages = {}
        for r in sorted(set(rvas)):
            page = r & 0xFFFFF000
            pages.setdefault(page, []).append(r & 0xFFF)
        out = bytearray()
        for page in sorted(pages):
            entries = pages[page]
            block_size = 8 + 2 * len(entries)
            out += struct.pack('<II', page, block_size)
            for e in entries:
                out += struct.pack('<H', 0x3000 | e)  # IMAGE_REL_BASED_HIGHLOW
        return bytes(out)

    def _write_file(self, sections, syms):
        # sort sections by rva
        sections = sorted(sections, key=lambda s: s['rva'])
        headers_size = align_up(0x40 + 0xF8 + len(sections) * 40, FILE_ALIGN)
        image_size = align_up(sections[-1]['rva'] + align_up(len(sections[-1]['data']), SECTION_ALIGN), SECTION_ALIGN)

        # entry
        entry_rva = syms[self.entry_label] if self.entry_label else 0

        nsec = len(sections)
        dos = bytearray(0x40)
        dos[0:2] = b'MZ'
        struct.pack_into('<I', dos, 0x3C, 0x40)
        # DOS stub minimal: just a message area, no real stub needed
        dos[0x40:0x40] = b''

        # PE header at 0x40
        pe = bytearray()
        pe += b'PE\x00\x00'
        # COFF header (20)
        pe += struct.pack('<HHIIIHH',
                          0x14c,        # machine
                          nsec,         # sections
                          0,            # timestamp
                          0, 0,         # symtab ptr, count
                          0xE0,         # size of optional header
                          0x2102)       # EXECUTABLE_IMAGE | 32BIT | DLL
        # optional header PE32 (224 = 0xE0)
        opt = bytearray()
        opt += struct.pack('<HBB', 0x10b, 0, 0)                    # magic, linker
        opt += struct.pack('<I', 0)                                 # size of code
        opt += struct.pack('<I', 0)                                 # size of init data
        opt += struct.pack('<I', 0)                                 # size of uninit data
        opt += struct.pack('<I', entry_rva)                         # entry point
        opt += struct.pack('<I', sections[0]['rva'])                # base of code
        opt += struct.pack('<I', 0)                                 # base of data
        opt += struct.pack('<I', self.image_base)                   # image base
        opt += struct.pack('<II', SECTION_ALIGN, FILE_ALIGN)        # alignment
        opt += struct.pack('<HH', 5, 1)                             # OS version
        opt += struct.pack('<HH', 0, 0)                             # image version
        opt += struct.pack('<HH', 5, 1)                             # subsystem version
        opt += struct.pack('<I', 0)                                 # win32 version
        opt += struct.pack('<I', image_size)                        # size of image
        opt += struct.pack('<I', headers_size)                      # size of headers
        opt += struct.pack('<I', 0)                                 # checksum
        opt += struct.pack('<HH', 2, 0)                             # subsystem=GUI, dllchar=0
        opt += struct.pack('<IIII', 0x100000, 0x1000, 0x100000, 0x1000)  # stacks/heaps
        opt += struct.pack('<II', 0, 16)                            # loader flags, num dirs
        # data directories (16 * 8)
        dirs = [(0,0)] * 16
        # export = 0, import = 1, reloc = 5
        exp = next((s for s in sections if s['name'] == '.edata'), None)
        imp = next((s for s in sections if s['name'] == '.idata'), None)
        rel = next((s for s in sections if s['name'] == '.reloc'), None)
        if exp: dirs[0] = (exp['rva'], len(exp['data']))
        if imp: dirs[1] = (imp['rva'], len(imp['data']))
        if rel: dirs[5] = (rel['rva'], len(rel['data']))
        for rva_, sz in dirs:
            opt += struct.pack('<II', rva_, sz)
        pe += bytes(opt)

        # section headers
        sec_hdrs = bytearray()
        raw = headers_size
        for s in sections:
            vsize = len(s['data'])
            rsize = align_up(vsize, FILE_ALIGN)
            sec_hdrs += s['name'].encode().ljust(8, b'\x00')
            sec_hdrs += struct.pack('<IIIIIIHHI',
                                    vsize, s['rva'], rsize, raw,
                                    0, 0, 0, 0, s['chars'])
            raw += rsize

        out = bytearray()
        out += dos
        out += pe
        out += sec_hdrs
        out += b'\x00' * (headers_size - len(out))
        # section raw data
        raw = headers_size
        for s in sections:
            d = s['data']
            out += d
            out += b'\x00' * (align_up(len(d), FILE_ALIGN) - len(d))
        return bytes(out), syms
