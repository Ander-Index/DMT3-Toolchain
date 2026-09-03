import sys, struct, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pebuild import DLLBuilder, SCN_CODE, SCN_DATA, SCN_RDATA

OUT = r'D:\DMT3\RCGrandDogW32.dll'          # proxy will be written here
ORIG_NAME = b'RCGrandDogW32_orig.dll\x00'

FUNCS = [
    ('GetError', 2),
    ('rc_ChangePassword', 3),
    ('rc_CheckDog', 1),
    ('rc_CloseDog', 1),
    ('rc_ConvertData', 4),
    ('rc_CreateDir', 3),
    ('rc_CreateFile', 5),
    ('rc_DecryptData', 5),
    ('rc_DefragFileSystem', 2),
    ('rc_DeleteDir', 2),
    ('rc_DeleteFile', 3),
    ('rc_EncryptData', 5),
    ('rc_ExecuteFile', 7),
    ('rc_GetDogInfo', 3),
    ('rc_GetDogInfoForDB', 5),
    ('rc_GetProductCurrentNo', 2),
    ('rc_GetRandom', 3),
    ('rc_GetUpgradeRequestString', 3),
    ('rc_OpenDog', 3),
    ('rc_ReadFile', 6),
    ('rc_SetKey', 4),
    ('rc_SignData', 5),
    ('rc_Upgrade', 3),
    ('rc_UpgradeForDB', 2),
    ('rc_VerifyPassword', 4),
    ('rc_VisitLicenseFile', 4),
    ('rc_WriteFile', 6),
]

IMPORTS = {'KERNEL32.dll': [
    'LoadLibraryA', 'GetProcAddress', 'WriteFile', 'CreateFileA',
    'CloseHandle', 'IsBadReadPtr', 'GetModuleFileNameA', 'SetFilePointer']}

MAX_ARGS = 7

b = DLLBuilder(image_base=0x6F000000, name='RCGrandDogW32.dll')
b.new_section('.text', SCN_CODE)
b.new_section('.data', SCN_DATA)
b.new_section('.rdata', SCN_RDATA)

# ---- writable globals (.data) ----
b.add_data('.data', 'g_hInst', b'\x00' * 4)
b.add_data('.data', 'g_hLog', b'\x00' * 4)
b.add_data('.data', 'g_hOrig', b'\x00' * 4)
b.add_data('.data', 'g_written', b'\x00' * 4)
b.add_data('.data', 'g_saved_retval', b'\x00' * 4)
b.add_data('.data', 'g_dump_magic', b'\x00' * 4)
b.add_data('.data', 'g_rec', b'\x00' * 256)
b.add_data('.data', 'g_real', b'\x00' * (len(FUNCS) * 4))

# ---- read-only data (.rdata) ----
argcount = b''.join(struct.pack('<I', n) for _, n in FUNCS)
b.add_data('.rdata', 'g_argcount', argcount)
b.add_data('.rdata', 'hdr_str', b'DOGLOG1\n')
b.add_data('.rdata', 'orig_name', ORIG_NAME)
name_syms = []
for i, (nm, _) in enumerate(FUNCS):
    name_syms.append('name_%d' % i)
    b.add_data('.rdata', name_syms[-1], nm.encode() + b'\x00')

a = b.asm

# ---- DllMain ----
a.label('dllmain')
a.emit('mov eax, dword ptr [esp + 4]')
a.emit('mov dword ptr [&g_hInst], eax')
a.emit('mov eax, dword ptr [esp + 8]')
a.emit('cmp eax, 1')
a.jcc('je', 'attach')
a.emit('cmp eax, 0')
a.jcc('je', 'detach')
a.emit('mov eax, 1')
a.emit('ret 12')

# ---- attach ----
a.label('attach')
a.emit('push ebx')
a.emit('push esi')
a.emit('push edi')
# GetModuleFileNameA(g_hInst, g_rec, 260) -> eax = length
a.emit('push 260')
a.emit('push &g_rec')
a.emit('push dword ptr [&g_hInst]')
a.emit('call dword ptr [&imp_GetModuleFileNameA]')
# change ".dll" -> ".log"
a.emit('mov ebx, &g_rec')
a.emit('add eax, ebx')
a.emit('mov byte ptr [eax - 3], 0x6c')   # l
a.emit('mov byte ptr [eax - 2], 0x6f')   # o
a.emit('mov byte ptr [eax - 1], 0x67')   # g
a.emit('mov byte ptr [eax], 0')
# CreateFileA(path, GENERIC_WRITE, 0, 0, CREATE_ALWAYS, NORMAL, 0)
a.emit('push 0')
a.emit('push 0x80')
a.emit('push 2')
a.emit('push 0')
a.emit('push 0')
a.emit('push 0x40000000')
a.emit('push ebx')
a.emit('call dword ptr [&imp_CreateFileA]')
a.emit('mov dword ptr [&g_hLog], eax')
# write header
a.emit('push 0')
a.emit('push &g_written')
a.emit('push 8')
a.emit('push &hdr_str')
a.emit('push dword ptr [&g_hLog]')
a.emit('call dword ptr [&imp_WriteFile]')
# LoadLibraryA(orig)
a.emit('push &orig_name')
a.emit('call dword ptr [&imp_LoadLibraryA]')
a.emit('mov dword ptr [&g_hOrig], eax')
# resolve 27 funcs
for i in range(len(FUNCS)):
    a.emit('push &%s' % name_syms[i])
    a.emit('push dword ptr [&g_hOrig]')
    a.emit('call dword ptr [&imp_GetProcAddress]')
    a.emit('mov dword ptr [&g_real + %d], eax' % (i * 4))
a.emit('pop edi')
a.emit('pop esi')
a.emit('pop ebx')
a.emit('mov eax, 1')
a.emit('ret 12')

# ---- detach ----
a.label('detach')
a.emit('push dword ptr [&g_hLog]')
a.emit('call dword ptr [&imp_CloseHandle]')
a.emit('mov eax, 1')
a.emit('ret 12')

# ---- common_stub ----
a.label('common_stub')
# entry: [esp]=func_id, [esp+4]=ret, [esp+8]=arg1 ...
a.emit('pop eax')
a.emit('mov ebp, esp')
a.emit('mov edi, eax')
# log CALL header
a.emit('mov ebx, &g_rec')
a.emit('mov dword ptr [ebx + 0], 0x43414C4C')
a.emit('mov dword ptr [ebx + 4], edi')
a.emit('mov ecx, dword ptr [&g_argcount + edi*4]')
a.emit('mov dword ptr [ebx + 8], ecx')
for j in range(MAX_ARGS):
    a.emit('mov eax, dword ptr [ebp + %d]' % (4 + 4 * j))
    a.emit('mov dword ptr [ebx + %d], eax' % (12 + 4 * j))
a.emit('lea edx, dword ptr [ecx*4 + 12]')
a.emit('push 0')
a.emit('push &g_written')
a.emit('push edx')
a.emit('push ebx')
a.emit('push dword ptr [&g_hLog]')
a.emit('call dword ptr [&imp_WriteFile]')
# dump BEFORE
a.emit('mov dword ptr [&g_dump_magic], 0x50545242')   # 'PTRB'
a.call_label('dump_args')
# forward call
a.emit('push edi')
a.emit('mov ecx, dword ptr [&g_argcount + edi*4]')
a.emit('lea esi, dword ptr [ebp + ecx*4]')
a.label('fwd_push')
a.emit('test ecx, ecx')
a.jcc('jz', 'fwd_done')
a.emit('push dword ptr [esi]')
a.emit('sub esi, 4')
a.emit('dec ecx')
a.jmp_label('fwd_push')
a.label('fwd_done')
a.emit('call dword ptr [&g_real + edi*4]')
a.emit('mov dword ptr [&g_saved_retval], eax')
a.emit('pop edi')
# dump AFTER
a.emit('mov dword ptr [&g_dump_magic], 0x50545241')   # 'PTRA'
a.call_label('dump_args')
# log RET
a.emit('mov ebx, &g_rec')
a.emit('mov dword ptr [ebx + 0], 0x52455420')
a.emit('mov eax, dword ptr [&g_saved_retval]')
a.emit('mov dword ptr [ebx + 4], eax')
a.emit('push 0')
a.emit('push &g_written')
a.emit('push 8')
a.emit('push ebx')
a.emit('push dword ptr [&g_hLog]')
a.emit('call dword ptr [&imp_WriteFile]')
# return ret N
a.emit('pop ecx')
a.emit('mov edx, dword ptr [&g_argcount + edi*4]')
a.emit('shl edx, 2')
a.emit('add esp, edx')
a.emit('jmp ecx')

# ---- dump_args ----
a.label('dump_args')
a.emit('push ebx')
a.emit('push esi')
a.emit('push edi')
a.emit('mov ecx, dword ptr [&g_argcount + edi*4]')
a.emit('xor edx, edx')
a.label('d_loop')
a.emit('cmp edx, ecx')
a.jcc('jae', 'd_done')
a.emit('mov eax, dword ptr [ebp + 4 + edx*4]')
a.emit('cmp eax, 0x10000')
a.jcc('jb', 'd_next')
a.emit('push ecx')
a.emit('push edx')
a.emit('push 128')
a.emit('push eax')
a.emit('call dword ptr [&imp_IsBadReadPtr]')
a.emit('pop edx')
a.emit('pop ecx')
a.emit('test eax, eax')
a.jcc('jnz', 'd_next')
a.emit('mov ebx, &g_rec')
a.emit('mov eax, dword ptr [&g_dump_magic]')
a.emit('mov dword ptr [ebx + 0], eax')
a.emit('mov dword ptr [ebx + 4], edx')
a.emit('push ecx')
a.emit('push edx')
a.emit('mov esi, dword ptr [ebp + 4 + edx*4]')
a.emit('mov edi, &g_rec')
a.emit('add edi, 8')
a.emit('mov ecx, 32')
a.raw(b'\xf3\xa5')  # rep movsd
a.emit('pop edx')
a.emit('pop ecx')
a.emit('push ecx')
a.emit('push edx')
a.emit('push 0')
a.emit('push &g_written')
a.emit('push 136')
a.emit('push ebx')
a.emit('push dword ptr [&g_hLog]')
a.emit('call dword ptr [&imp_WriteFile]')
a.emit('pop edx')
a.emit('pop ecx')
a.label('d_next')
a.emit('inc edx')
a.jmp_label('d_loop')
a.label('d_done')
a.emit('pop edi')
a.emit('pop esi')
a.emit('pop ebx')
a.emit('ret')

# ---- thunks ----
for i in range(len(FUNCS)):
    a.label('thunk_%d' % i)
    a.emit('push %d' % i)
    a.jmp_label('common_stub')

b.entry_label = 'dllmain'
b.exports = [(nm, 'thunk_%d' % i) for i, (nm, _) in enumerate(FUNCS)]
b.imports = IMPORTS

data, syms = b.build()
open(OUT, 'wb').write(data)
print('wrote proxy to', OUT, len(data), 'bytes')
print('entry', hex(syms['dllmain']))
print('exports:', len(b.exports))
