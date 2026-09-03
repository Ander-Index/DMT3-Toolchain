import sys, os, struct, gzip
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pebuild import DLLBuilder, SCN_CODE, SCN_DATA, SCN_RDATA
from collections import OrderedDict

# ---- data file resolution: work both in the toolkit layout (..\dumps\*.log)
# and in the redistributed source package (.\data\*.log[.gz]) ----
def _find_data(name):
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, 'data', name),
              os.path.join(here, 'data', name + '.gz'),
              os.path.join(here, '..', 'dumps', name),
              os.path.join(here, '..', 'dumps', name + '.gz')):
        if os.path.exists(p):
            return p
    raise FileNotFoundError('recording not found: %s (looked in data\\ and ..\\dumps\\)' % name)

def _read_data(path):
    if path.endswith('.gz'):
        return gzip.open(path, 'rb').read()
    return open(path, 'rb').read()

# multiDLL proxy = PURE PASSTHROUGH (09_??? ?5.1: replay branch REMOVED)
#                 + LOG   (every DeviceIoControl -> ioctl.log 8224B records)
#                 + RW LOG(ReadFile/WriteFile <=1200B passthrough -> rw.log 4128B records)
#                 + DOG2 INTERCEPT (10_??? ?3.1): 65B 'R6' WriteFile/ReadFile on the dog2
#                   handle are answered in user mode from the captured transcript
#                   (state machine; cmd @wr+10, challenge @wr+13..21)
#
# DeviceIoControl arg offsets inside pushad frame:
#   [esp+32]=ret [36]=hDev [40]=ioctl [44]=inbuf [48]=insz [52]=outbuf [56]=outsz [60]=pBytesRet
# ReadFile/WriteFile:
#   [esp+32]=ret [36]=hFile [40]=buf [44]=size [48]=lpNumBytes [52]=lpOverlapped

# ---- NO replay table (pure passthrough build, per 09_??? ?5.1) ----
keys = []
respdata = b''
nkeys = 0
entries = b''
cursors = b''
print('passthrough build: replay table empty')

# ---- which real multiDLL the proxy delegates the 3 Nexio exports to ----
#   'orig'  -> multiDLL_orig.dll  (红外屏原版, 24576B)
#   'touch' -> multiDLL_touch.dll (触控屏适配版, 219136B)
# Both variants export the same 3 functions (verified 2026-08-28); the proxy
# binary is identical except for this backing-DLL name, so the two flavors can
# coexist in the game dir and be switched by copying the wanted proxy onto
# multiDLL.dll.
BACKING = 'touch'
BACKING_NAME = {'orig': 'multiDLL_orig.dll', 'touch': 'multiDLL_touch.dll'}[BACKING]

# ---- dog1 (Senselock EL) replay table: key = (ioctl, insz, outsz, inbuf[0:64]) ----
# CRITICAL (doc 15): session key = f(UID, PIN, 0x390008 RNG), derived ONCE per run.
#   => 0x39 (RNG) and 0x22 (challenge) MUST come from the SAME run, or the canned
#      challenge ciphertexts will not match the replayed RNG's session key.
# ALSO: 0x47 responses are run-varying (file sizes/offsets differ per run; 161 of 204
#   cross-run keys conflict). Merging runs creates sequence inconsistencies that make
#   the game take a wrong path early. Use ONE self-consistent run for everything.
T7_RUN = _find_data('ioctl_zerorng.log')
T7_SRCS_22 = [T7_RUN]
T7_SRCS_39 = [T7_RUN]
T7_SRCS_47 = [T7_RUN]
t7k = OrderedDict()
def _mask_ib(ioctl, insz, ib):
    # merge duplicate keys that differ only in run-varying pointer/token bytes,
    # so variants accumulate in record order under ONE logical key (Track B fix:
    # ~80 duplicate keys for the same enumeration query made the scan always hit
    # the first sorted key -> wrong device path served -> game re-enumerates forever)
    b = bytearray(ib)
    if ioctl == 0x470813 and insz == 56:
        b[12:16] = b'\x00' * 4
    if (ioctl >> 16) & 0xffff == 0x22 and insz == 17:
        b[13:17] = b'\x00' * 4
    return bytes(b)
def _t7add(srcs, dts):
    for path in srcs:
        _d = _read_data(path)
        for _pos in range(9, len(_d) - 8224 + 1, 8224):
            _m, _hdev, _ioctl, _insz, _outsz, _ret, _inb, _outb = struct.unpack_from('<8I', _d, _pos)
            if (_ioctl >> 16) & 0xffff not in dts:
                continue
            _ib = _mask_ib(_ioctl, _insz, _d[_pos + 32:_pos + 32 + min(_insz, 64)])
            # _outb slot = actual bytes returned by the dog (pBytesRet) for pbr logs;
            # only store those bytes (the rest of the 255B buffer is the game's leaked
            # pointers, which must NOT be overwritten on replay).
            _n = _outb if (0 < _outb <= _outsz) else _outsz
            _ob = _d[_pos + 4128:_pos + 4128 + _n]
            # NO dedup: keep every occurrence in record order so the runtime cursor
            # reproduces the recorded response sequence 1:1 (dedup collapsed repeated
            # responses and misaligned the cursor -> wrong GUID/path variants served,
            # game re-enumerates forever; Track B round 4 finding)
            t7k.setdefault((_ioctl, _insz, _outsz, _ib), []).append(_ob)
_t7add(T7_SRCS_22, {0x22})
_t7add(T7_SRCS_39, {0x39})
_t7add(T7_SRCS_47, {0x47})
t7_entries = []
t7_resps = b''
for _key in sorted(t7k.keys()):
    _ioctl, _insz, _outsz, _ib = _key
    _rl = t7k[_key]
    _stride = 4 + max(len(r) for r in _rl)
    _first = len(t7_resps)
    for _r in _rl:
        t7_resps += struct.pack('<I', len(_r)) + _r + b'\x00' * (_stride - 4 - len(_r))
    t7_entries.append(struct.pack('<II', _ioctl, _insz) + _ib.ljust(64, b'\x00')[:64] +
                      struct.pack('<IIII', _outsz, _first, len(_rl), _stride))
N7KEYS = len(t7_entries)
t7_keys = b''.join(t7_entries)
# per-key compare mask (0xFF=compare, 0x00=ignore). 0x470813 insz=56: bytes 12-15
# are a run-varying heap buffer pointer (the sequential 420B file readout).
t7_masks = b''
for _key in sorted(t7k.keys()):
    _m = bytearray(b'\xff' * 64)
    if _key[0] == 0x470813 and _key[1] == 56:
        _m[12:16] = b'\x00' * 4
    if _key[0] == 0x00220028 and _key[1] == 17:
        # 0501: ignore the run-varying 4B token (inbuf[13:17]) so a single canned
        # response replays for every 0501 call (tests verify-vs-use).
        _m[13:17] = b'\x00' * 4
    t7_masks += bytes(_m)
t7_cursors = b'\x00' * (4 * N7KEYS)
print('dog1 table: %d keys, %d resp bytes (single run: %s)' % (N7KEYS, len(t7_resps), T7_RUN.split('\\')[-1]))

# ---- dog2 interception switch: False = pure passthrough+RW log (capture mode) ----
DOG2_INTERCEPT = True
# ---- caller.log stack snapshot on every ioctl. Heavy synchronous file I/O per
# ioctl -> distorts the timing-sensitive EL protocol (doc 14: "149条卡点" was a
# caller.log artifact). Keep OFF for replay/capture; enable only briefly to map
# a call site, then disable.
CALLER_LOG = False
# ---- replay dog1 SmartCardReader (0x47) with canned data. The 0x47 reads are
# run-varying (file sizes/order + heap pointers), so canned 0x47 replay diverges
# from a fresh run. Set False to PASSTHROUGH 0x47 to the real dog (isolate the EL
# 0x22 challenge test). Set True for a full dog1-free replay once 0x47 is solved.
REPLAY_47 = False
# Which dog1 ioctls to replay (canned) vs passthrough. For the TEA key hunt we want
# ONLY 0x39 (RNG) fixed to a known run's value, and 0x22 passthrough to the real
# dog so the game's EL handshake/challenge works normally (no divergence), while
# the game still derives that known run's session key.
REPLAY_39 = True
REPLAY_22 = True
# Hook the game's own TEA functions (0x6FC5E0 enc / 0x707A50 dec) to log the 16-byte
# session key on every call -> D:\DMT3\tea_key.log. RISK: patches game .text (VMProtect/
# SXProtect may react). Off by default.
TEA_HOOK = False
TEA_ENC = 0x6FC5E0
TEA_DEC = 0x707A50
# Force SystemFunction036 output to all zeros (full determinism: the game's
# RNG-dependent protocol path choices become reproducible; record a reference
# with the same fixed RNG, then canned replay can match it 1:1).
FIX_RNG = False
# Delay (ms) to inject after replaying an EL (0x22) ioctl, to mimic the real dongle's
# USB round-trip latency. 0 = no delay. The EL protocol appears timing-sensitive:
# with an instant canned reply the game diverges (generates RNG early) where it
# would otherwise continue. Non-zero is experimental.
REPLAY_DELAY_MS = 10

# ---- dog2 transcript ----
# Challenges are derived (game-side) from the blob served that session, so the
# driver serves the CAPTURED per-session blob sequence (in game session order)
# and a union challenge table. cmd2 key length @wr+12: 8 or 16 bytes @wr+13.
# TSRCS: capture logs in preference order; a later fuller capture (with song
# load) should replace the startup-only one.
TSRCS = [_find_data('rw_song.log'), _find_data('rw_session1.log')]
_sessions = []   # list of [part0,part1,part2] per cmd3 session, in order
_atr = None
_pairs = []      # (keylen, key16, resp65)
for TSRC in TSRCS:
    if not os.path.exists(TSRC):
        continue
    _td = _read_data(TSRC)
    _ev = []
    for _pos in range(_td.find(b'RWRD'), len(_td) - 4128 + 1, 4128):
        _m, _api, _h, _sz, _ret, _nrd, _bp = struct.unpack_from('<7I', _td, _pos)
        if _m != 0x44525752 or _sz != 65:
            continue
        _n = _nrd if _api == 0 else _sz
        _ev.append((_api, _td[_pos + 32:_pos + 32 + min(_n, 4096)]))
    _i = 0
    while _i < len(_ev):
        _api, _buf = _ev[_i]
        if _api == 1:
            _cmd = struct.unpack_from('<H', _buf, 10)[0]
            if _cmd == 3:
                _sessions.append([_ev[_i + 1 + _k][1][:65] for _k in range(3)])
                _i += 3
            elif _cmd == 1:
                if _atr is None:
                    _atr = _ev[_i + 1][1][:65]
                _i += 1
            elif _cmd == 2:
                _kl = _buf[12]
                _key = _buf[13:13 + _kl]
                if _kl in (8, 16) and _key not in [k for _, k, _ in _pairs]:
                    _pairs.append((_kl, _key, _ev[_i + 1][1][:65]))
                _i += 1
        _i += 1
assert _sessions and _atr and _pairs, 'dog2 transcript parse failed'
NSESS = len(_sessions)
t_sblobs = b''.join(b''.join(s) for s in _sessions)   # NSESS x 195
t_atr = _atr
t_pents = b''.join(struct.pack('<I', kl) + (k + b'\x00' * 16)[:16] + r for kl, k, r in _pairs)  # 85B each
NCHAL = len(_pairs)
# fallback frames for UNKNOWN challenges: last captured response per key length
# (song-load 16B challenge carries game-side entropy -> key never matches;
#  a structurally valid '0e' frame is accepted by the game, zeros are NOT)
t_fb = {8: None, 16: None}
for kl, k, r in _pairs:
    t_fb[kl] = r
t_fb8 = t_fb[8] or (b'\x00' * 65)
t_fb16 = t_fb[16] or (b'\x00' * 65)
print('dog2 transcript: %d sessions, atr, %d chal pairs (%s)' %
      (NSESS, NCHAL, ', '.join(k[:kl].hex() for kl, k, _ in _pairs)))

b = DLLBuilder(image_base=0x6F000000, name='multiDLL.dll')
b.new_section('.text', SCN_CODE)
b.new_section('.data', SCN_DATA)
b.new_section('.rdata', SCN_RDATA)

# ---- .data ----
b.add_data('.data', 'g_hInst', b'\x00' * 4)
b.add_data('.data', 'g_hOrig', b'\x00' * 4)
b.add_data('.data', 'g_real', b'\x00' * 12)
# ioctl log + replay state
b.add_data('.data', 'g_log', b'\x00' * 4)
b.add_data('.data', 'g_written', b'\x00' * 4)
b.add_data('.data', 'g_pDev', b'\x00' * 4)
b.add_data('.data', 'g_origDev', b'\x00' * 16)
b.add_data('.data', 'g_saved_ret', b'\x00' * 4)
b.add_data('.data', 'g_hDevice', b'\x00' * 4)
b.add_data('.data', 'g_ioctl', b'\x00' * 4)
b.add_data('.data', 'g_insize', b'\x00' * 4)
b.add_data('.data', 'g_outsize', b'\x00' * 4)
b.add_data('.data', 'g_inbuf', b'\x00' * 4)
b.add_data('.data', 'g_outbuf', b'\x00' * 4)
b.add_data('.data', 'g_retval', b'\x00' * 4)
b.add_data('.data', 'g_pBytesRet', b'\x00' * 4)
b.add_data('.data', 'g_rec', b'\x00' * 8224)
b.add_data('.data', 'g_nkeys', struct.pack('<I', nkeys))
b.add_data('.data', 'g_respsize', b'\x00' * 4)
b.add_data('.data', 'g_respcount', b'\x00' * 4)
b.add_data('.data', 'g_respoff', b'\x00' * 4)
b.add_data('.data', 'g_cursoraddr', b'\x00' * 4)
b.add_data('.data', 'g_cursors', cursors)
# rw log state
b.add_data('.data', 'g_log2', b'\x00' * 4)
b.add_data('.data', 'g_written2', b'\x00' * 4)
b.add_data('.data', 'g_pRd', b'\x00' * 4)
b.add_data('.data', 'g_origRd', b'\x00' * 16)
b.add_data('.data', 'g_pWr', b'\x00' * 4)
b.add_data('.data', 'g_origWr', b'\x00' * 16)
b.add_data('.data', 'g_prtmp', b'\x00' * 4)
b.add_data('.data', 'g_hookproc', b'\x00' * 4)
b.add_data('.data', 'gR_saved', b'\x00' * 4)
b.add_data('.data', 'gR_h', b'\x00' * 4)
b.add_data('.data', 'gR_buf', b'\x00' * 4)
b.add_data('.data', 'gR_size', b'\x00' * 4)
b.add_data('.data', 'gR_nbr', b'\x00' * 4)
b.add_data('.data', 'gR_ret', b'\x00' * 4)
b.add_data('.data', 'gR_nread', b'\x00' * 4)
b.add_data('.data', 'gR_flag', b'\x00' * 4)
b.add_data('.data', 'gW_saved', b'\x00' * 4)
b.add_data('.data', 'gW_h', b'\x00' * 4)
b.add_data('.data', 'gW_buf', b'\x00' * 4)
b.add_data('.data', 'gW_size', b'\x00' * 4)
b.add_data('.data', 'gW_flag', b'\x00' * 4)
b.add_data('.data', 'g_rec2', b'\x00' * 4128)
# dog2 interception state
b.add_data('.data', 'g_dogh', b'\x00' * 4)       # handle that issued last dog write
b.add_data('.data', 'g_state', b'\x00' * 4)      # 0 idle 1 blob 2 atr 3 chal
b.add_data('.data', 'g_blobpart', b'\x00' * 4)
b.add_data('.data', 'g_chalresp', b'\x00' * 4)   # ptr into t_pents resp or 0
b.add_data('.data', 'g_chalkl', b'\x00' * 4)     # key length of pending challenge (8/16)
b.add_data('.data', 'g_dogwr', b'\x00' * 65)     # last dog write stash
b.add_data('.data', 'g_session', b'\xff' * 4)    # session index, -1 = none yet

# ---- .rdata ----
b.add_data('.rdata', 'g_keys', entries)
b.add_data('.rdata', 'g_respdata', respdata)
b.add_data('.rdata', 'hdr', b'IOCTLOG1\n')
b.add_data('.rdata', 'hdr2', b'RWLOG1\n')
b.add_data('.rdata', 'orig_name', BACKING_NAME.encode() + b'\x00')
b.add_data('.rdata', 'logpath', b'D:\\DMT3\\ioctl.log\x00')
b.add_data('.rdata', 'rwpath', b'D:\\DMT3\\rw.log\x00')
b.add_data('.rdata', 'callerpath', b'D:\\DMT3\\caller.log\x00')
b.add_data('.rdata', 'hdr3', b'CALLER1\n')
b.add_data('.data', 'g_log3', b'\x00' * 4)
b.add_data('.data', 'g_written3', b'\x00' * 4)
b.add_data('.rdata', 'k32', b'kernel32.dll\x00')
b.add_data('.rdata', 'di', b'DeviceIoControl\x00')
b.add_data('.rdata', 'rf', b'ReadFile\x00')
b.add_data('.rdata', 'wf', b'WriteFile\x00')
b.add_data('.rdata', 'n0', b'OpenNexioMulti\x00')
b.add_data('.rdata', 'n1', b'CloseNexioMulti\x00')
b.add_data('.rdata', 'n2', b'WaitNexioMulti\x00')
# dog2 transcript tables
b.add_data('.rdata', 't_sblobs', t_sblobs)  # NSESS x 195 (3x65 per session)
b.add_data('.rdata', 't_atr', t_atr)       # 65
b.add_data('.rdata', 't_pents', t_pents)   # NCHAL x 85: keylen u32 + key16 + resp65
b.add_data('.rdata', 't_zero', b'\x00' * 65)
b.add_data('.rdata', 't_fb8', t_fb8)       # fallback frame for unknown 8B challenges
b.add_data('.rdata', 't_fb16', t_fb16)     # fallback frame for unknown 16B challenges
# dog1 replay tables
b.add_data('.rdata', 't7_keys', t7_keys)   # N7KEYS x 88: ioctl,insz,inbuf64,outsz,first,count,stride
b.add_data('.rdata', 't7_resps', t7_resps) # per-key responses: [outsz u32][data] x stride
b.add_data('.rdata', 't7_masks', t7_masks) # N7KEYS x 64 compare masks
b.add_data('.data', 'g7_cursors', t7_cursors)
b.add_data('.data', 'g7_nkeys', struct.pack('<I', N7KEYS))

# ---- TEA hook state (capture the session key passed to the game's TEA) ----
b.add_data('.data', 'g_tea_keyptr', b'\x00' * 4)
b.add_data('.data', 'g_tea_arg1', b'\x00' * 4)
b.add_data('.data', 'g_tea_arg2', b'\x00' * 4)
b.add_data('.data', 'g_tea_saved_ret', b'\x00' * 4)
b.add_data('.data', 'g_tea_orig_enc', b'\x00' * 20)
b.add_data('.data', 'g_tea_orig_dec', b'\x00' * 20)
b.add_data('.data', 'g_tea_log', b'\x00' * 4)
b.add_data('.data', 'g_tea_written', b'\x00' * 4)
b.add_data('.data', 'g_tea_rec', b'\x00' * 36)
b.add_data('.rdata', 'tealogpath', b'D:\\DMT3\\tea_key.log\x00')
# mem dump for 0501 (insz=17) run-varying 4B token: log [token u32][16B @ token]
b.add_data('.data', 'g_memdump', b'\x00' * 44)
b.add_data('.data', 'g_memlog', b'\x00' * 4)
b.add_data('.data', 'g_mem_written', b'\x00' * 4)
b.add_data('.data', 'g_watch', b'\x00' * 4)
b.add_data('.data', 'g_watch_cnt', b'\x00' * 4)
b.add_data('.data', 'g_watch_rec', b'\x00' * 20)
b.add_data('.data', 'g_allocbuf', b'\x00' * 4)
# ---- patch the game's EL HID enumeration filter string in .rdata ----
# DllMain-time patch gets reverted by VMP init, so do it from a thread with a
# delay (post-unpack): "Vid_0471&Pid_485e" -> "HIDCLASS#0001" (matches velhid).
# Also patch the two .vmp-resident copies (decrypted by then).
PATCH_EL_FILTER = False
EL_FILTER_VA = 0x7FB0F8
EL_FILTER_VA2 = 0x19A55F78
EL_FILTER_VA3 = 0x19A652DC
b.add_data('.rdata', 'elfilter_new', b'HIDCLASS#0001\x00\x00\x00\x00\x00')
b.add_data('.data', 'g_thread', b'\x00' * 4)
# ---- EL HID enum spoofing: velhid's real path lacks "Vid_0471&Pid_485e" so the
# game's SetupDi substring filter never matches it. Spoof:
#  1) SetupDiGetDeviceInterfaceDetailW -> rewrite velhid's detail path to a fake
#     path containing the filter string (same length, fits the caller's buffer)
#  2) SetupDiGetDeviceInstanceIdW    -> rewrite "ROOT\HIDCLASS\0001" -> "Vid_0471&Pid_485e"
#  3) CreateFileW                    -> filename containing vid_0471&pid_485e (ci)
#                                     redirected to velhid's real interface path
SPOOF_EL_ENUM = False
b.add_data('.rdata', 'setupapidll', b'setupapi.dll\x00')
b.add_data('.rdata', 'fn_detail', b'SetupDiGetDeviceInterfaceDetailW\x00')
b.add_data('.rdata', 'fn_instid', b'SetupDiGetDeviceInstanceIdW\x00')
b.add_data('.rdata', 'fn_cfw', b'CreateFileW\x00')
b.add_data('.data', 'g_setupapi', b'\x00' * 4)
b.add_data('.data', 'g_pDetail', b'\x00' * 4)
b.add_data('.data', 'g_pInstId', b'\x00' * 4)
b.add_data('.data', 'g_pCFW', b'\x00' * 4)
b.add_data('.data', 'g_origDetail', b'\x00' * 20)
b.add_data('.data', 'g_origInstId', b'\x00' * 20)
b.add_data('.data', 'g_origCFW', b'\x00' * 20)
b.add_data('.data', 'g_det_saved', b'\x00' * 4)
b.add_data('.data', 'g_det_arg3', b'\x00' * 4)
b.add_data('.data', 'g_ins_saved', b'\x00' * 4)
b.add_data('.data', 'g_ins_arg3', b'\x00' * 4)
b.add_data('.data', 'g_cfw_saved', b'\x00' * 4)
b.add_data('.data', 'g_cfw_arg1', b'\x00' * 4)
def _w(s):
    return s.encode('utf-16-le') + b'\x00\x00'
# 60 wchars exactly, matches velhid ROOT\HIDCLASS\0001 real interface path length
b.add_data('.rdata', 'velhid_real', _w('\\\\?\\ROOT#HIDCLASS#0001#{4d1e55b2-f16f-11cf-88cb-001111000030}'))
b.add_data('.rdata', 'velhid_fake', _w('\\\\?\\HID#Vid_0471&Pid_485e#0001#{4d1e55b2-f16f-11cf-88cb-001111}'))
b.add_data('.rdata', 'instid_real', _w('ROOT\\HIDCLASS\\0001'))
b.add_data('.rdata', 'instid_fake', _w('Vid_0471&Pid_485e'))
b.add_data('.rdata', 'cfw_pat', _w('vid_0471&pid_485e'))
# ---- init/hook-firing markers (diagnose early startup death) ----
b.add_data('.rdata', 'spoofpath', b'D:\\DMT3\\spoof.log\x00')
b.add_data('.rdata', 'spoofmark', b'DLLMAIN')
b.add_data('.data', 'g_spoof_h', b'\x00' * 4)
b.add_data('.data', 'g_mark_c', b'\x00' * 4)
b.add_data('.data', 'g_mark_d', b'\x00' * 4)
b.add_data('.data', 'g_mark_i', b'\x00' * 4)
b.add_data('.data', 'g_init_done', b'\x00' * 4)
b.add_data('.data', 'g_bcrypt', b'\x00' * 4)
b.add_data('.data', 'g_bcrypt_fn', b'\x00' * 4)
b.add_data('.data', 'g_bcrypt_orig', b'\x00' * 20)
b.add_data('.data', 'g_rng_log', b'\x00' * 4)
b.add_data('.data', 'g_rng_written', b'\x00' * 4)
b.add_data('.data', 'g_rng_buf', b'\x00' * 48)
b.add_data('.data', 'g_rng_saved', b'\x00' * 4)
b.add_data('.data', 'g_rng_ptr', b'\x00' * 4)
b.add_data('.data', 'g_rng_cb', b'\x00' * 4)
b.add_data('.rdata', 'bcryptdll', b'advapi32.dll\x00')
b.add_data('.rdata', 'bcryptfn', b'SystemFunction036\x00')
b.add_data('.rdata', 'rnglogpath', b'D:\\DMT3\\rng.log\x00')
b.add_data('.rdata', 'mempath', b'D:\\DMT3\\mem.log\x00')

b.imports = {'KERNEL32.dll': ['LoadLibraryA', 'GetProcAddress', 'GetModuleHandleA',
                              'VirtualProtect', 'CreateFileA', 'WriteFile',
                              'SetFilePointer', 'CloseHandle', 'IsBadReadPtr', 'Sleep', 'VirtualAlloc', 'SetEvent', 'CreateThread', 'ExitThread', 'VirtualQuery']}

# ---- boot stage markers (diagnose DllMain early death): write 1 byte per stage
# to D:\DMT3\boot.log; last byte present = stage reached before the crash.
# (Used to pin down the restore_one reprotect bug 2026-08-28; keep OFF.)
DIAG_BOOT = False
b.add_data('.rdata', 'bootpath', b'D:\\DMT3\\boot.log\x00')
b.add_data('.rdata', 'bootp6', b'D:\\DMT3\\boot_p6.mark\x00')
b.add_data('.data', 'g_bootlog', b'\x00' * 4)
def _bootmark(ch):
    a.emit('mov dword ptr [&g_prtmp], %d' % ord(ch))
    a.emit('push 2'); a.emit('push 0'); a.emit('push 0'); a.emit('push dword ptr [&g_bootlog]'); a.emit('call dword ptr [&imp_SetFilePointer]')
    a.emit('push 0'); a.emit('push &g_written3'); a.emit('push 1'); a.emit('push &g_prtmp'); a.emit('push dword ptr [&g_bootlog]'); a.emit('call dword ptr [&imp_WriteFile]')

a = b.asm

# ---------------- DllMain ----------------
a.label('dllmain')
a.emit('mov eax, dword ptr [esp + 4]'); a.emit('mov dword ptr [&g_hInst], eax')
a.emit('mov eax, dword ptr [esp + 8]'); a.emit('cmp eax, 1'); a.jcc('jne', 'dll_done')
a.emit('push ebx'); a.emit('push esi'); a.emit('push edi')

if DIAG_BOOT:
    a.emit('push 0'); a.emit('push 0x80'); a.emit('push 2'); a.emit('push 0')
    a.emit('push 0'); a.emit('push 0x40000000'); a.emit('push &bootpath')
    a.emit('call dword ptr [&imp_CreateFileA]')
    a.emit('mov dword ptr [&g_bootlog], eax')
    _bootmark('A')
    # direct write probes: which .data pages are actually writable?
    a.emit('mov byte ptr [&g_rec], 0x41')
    _bootmark('r')
    a.emit('mov byte ptr [&g_rec2], 0x41')
    _bootmark('p')
    a.emit('mov byte ptr [&g7_cursors], 0x41')
    _bootmark('q')

a.emit('push 0'); a.emit('push 0x80'); a.emit('push 2'); a.emit('push 0')
a.emit('push 0'); a.emit('push 0x40000000'); a.emit('push &logpath')
a.emit('call dword ptr [&imp_CreateFileA]')
a.emit('mov dword ptr [&g_log], eax')
a.emit('push 0'); a.emit('push &g_written'); a.emit('push 9'); a.emit('push &hdr'); a.emit('push dword ptr [&g_log]')
a.emit('call dword ptr [&imp_WriteFile]')

a.emit('push 0'); a.emit('push 0x80'); a.emit('push 2'); a.emit('push 0')
a.emit('push 0'); a.emit('push 0x40000000'); a.emit('push &rwpath')
a.emit('call dword ptr [&imp_CreateFileA]')
a.emit('mov dword ptr [&g_log2], eax')
a.emit('push 0'); a.emit('push &g_written2'); a.emit('push 7'); a.emit('push &hdr2'); a.emit('push dword ptr [&g_log2]')
a.emit('call dword ptr [&imp_WriteFile]')

a.emit('push 0'); a.emit('push 0x80'); a.emit('push 2'); a.emit('push 0')
a.emit('push 0'); a.emit('push 0x40000000'); a.emit('push &callerpath')
a.emit('call dword ptr [&imp_CreateFileA]')
a.emit('mov dword ptr [&g_log3], eax')
a.emit('push 0'); a.emit('push &g_written3'); a.emit('push 8'); a.emit('push &hdr3'); a.emit('push dword ptr [&g_log3]')
a.emit('call dword ptr [&imp_WriteFile]')

a.emit('push &orig_name'); a.emit('call dword ptr [&imp_LoadLibraryA]'); a.emit('mov dword ptr [&g_hOrig], eax')
if DIAG_BOOT: _bootmark('B')
a.emit('push &n0'); a.emit('push dword ptr [&g_hOrig]'); a.emit('call dword ptr [&imp_GetProcAddress]'); a.emit('mov dword ptr [&g_real + 0], eax')
a.emit('push &n1'); a.emit('push dword ptr [&g_hOrig]'); a.emit('call dword ptr [&imp_GetProcAddress]'); a.emit('mov dword ptr [&g_real + 4], eax')
a.emit('push &n2'); a.emit('push dword ptr [&g_hOrig]'); a.emit('call dword ptr [&imp_GetProcAddress]'); a.emit('mov dword ptr [&g_real + 8], eax')
if DIAG_BOOT: _bootmark('C')

a.emit('push &k32'); a.emit('call dword ptr [&imp_GetModuleHandleA]'); a.emit('mov esi, eax')
if DIAG_BOOT: _bootmark('1')
a.emit('push &di'); a.emit('push esi'); a.emit('call dword ptr [&imp_GetProcAddress]')
a.emit('mov dword ptr [&g_pDev], eax')
a.emit('push &rf'); a.emit('push esi'); a.emit('call dword ptr [&imp_GetProcAddress]')
a.emit('mov dword ptr [&g_pRd], eax')
a.emit('push &wf'); a.emit('push esi'); a.emit('call dword ptr [&imp_GetProcAddress]')
a.emit('mov dword ptr [&g_pWr], eax')
if DIAG_BOOT: _bootmark('2')

a.emit('mov esi, dword ptr [&g_pDev]'); a.emit('mov edi, &g_origDev'); a.emit('mov ecx, 5'); a.raw(b'\xf3\xa4')
a.emit('mov esi, dword ptr [&g_pRd]'); a.emit('mov edi, &g_origRd'); a.emit('mov ecx, 5'); a.raw(b'\xf3\xa4')
a.emit('mov esi, dword ptr [&g_pWr]'); a.emit('mov edi, &g_origWr'); a.emit('mov ecx, 5'); a.raw(b'\xf3\xa4')
if DIAG_BOOT: _bootmark('3')

a.emit('mov esi, dword ptr [&g_pDev]'); a.emit('mov edx, &hookIOCTL'); a.call_label('patch_one')
if DIAG_BOOT: _bootmark('4')
a.emit('mov esi, dword ptr [&g_pRd]'); a.emit('mov edx, &hookRD'); a.call_label('patch_one')
if DIAG_BOOT: _bootmark('5')
if DIAG_BOOT:
    # probe g_rec2 page mapping (WriteFile NOT yet hooked here)
    a.emit('push 28'); a.emit('push &g_tea_rec'); a.emit('push &g_rec2')
    a.emit('call dword ptr [&imp_VirtualQuery]')
    a.emit('push 2'); a.emit('push 0'); a.emit('push 0'); a.emit('push dword ptr [&g_bootlog]'); a.emit('call dword ptr [&imp_SetFilePointer]')
    a.emit('push 0'); a.emit('push &g_written3'); a.emit('push 28'); a.emit('push &g_tea_rec'); a.emit('push dword ptr [&g_bootlog]'); a.emit('call dword ptr [&imp_WriteFile]')
    # also probe one page lower for contrast
    a.emit('push 28'); a.emit('push &g_tea_rec'); a.emit('push &g_rec')
    a.emit('call dword ptr [&imp_VirtualQuery]')
    a.emit('push 2'); a.emit('push 0'); a.emit('push 0'); a.emit('push dword ptr [&g_bootlog]'); a.emit('call dword ptr [&imp_SetFilePointer]')
    a.emit('push 0'); a.emit('push &g_written3'); a.emit('push 28'); a.emit('push &g_tea_rec'); a.emit('push dword ptr [&g_bootlog]'); a.emit('call dword ptr [&imp_WriteFile]')
a.emit('mov esi, dword ptr [&g_pWr]'); a.emit('mov edx, &hookWR'); a.call_label('patch_one')
if DIAG_BOOT:
    # CreateFileA marker (NOT hooked) after patching WriteFile
    a.emit('push 0'); a.emit('push 0x80'); a.emit('push 2'); a.emit('push 0')
    a.emit('push 0'); a.emit('push 0x40000000'); a.emit('push &bootp6')
    a.emit('call dword ptr [&imp_CreateFileA]')
    a.emit('push eax'); a.emit('call dword ptr [&imp_CloseHandle]')
    _bootmark('6')

# ---- TEA hook: capture the session key ----
if TEA_HOOK:
    a.emit('push 0'); a.emit('push 0x80'); a.emit('push 2'); a.emit('push 0')
    a.emit('push 0'); a.emit('push 0x40000000'); a.emit('push &tealogpath')
    a.emit('call dword ptr [&imp_CreateFileA]')
    a.emit('mov dword ptr [&g_tea_log], eax')
    a.emit('mov esi, %d' % TEA_ENC); a.emit('mov edi, &g_tea_orig_enc'); a.emit('mov ecx, 5'); a.raw(b'\xf3\xa4')
    a.emit('mov esi, %d' % TEA_DEC); a.emit('mov edi, &g_tea_orig_dec'); a.emit('mov ecx, 5'); a.raw(b'\xf3\xa4')
    a.emit('mov esi, %d' % TEA_ENC); a.emit('mov edx, &tea_hook_enc'); a.call_label('patch_one')
    a.emit('mov esi, %d' % TEA_DEC); a.emit('mov edx, &tea_hook_dec'); a.call_label('patch_one')

# ---- open mem.log for 0501 4B token memory dump ----
a.emit('push 0'); a.emit('push 0x80'); a.emit('push 2'); a.emit('push 0')
a.emit('push 0'); a.emit('push 0x40000000'); a.emit('push &mempath')
a.emit('call dword ptr [&imp_CreateFileA]')
a.emit('mov dword ptr [&g_memlog], eax')

# ---- allocate a zeroed buffer to use as the 0501 response pointer ----
a.emit('push 0x40'); a.emit('push 0x3000'); a.emit('push 0x100'); a.emit('push 0')
a.emit('call dword ptr [&imp_VirtualAlloc]')
a.emit('mov dword ptr [&g_allocbuf], eax')
if DIAG_BOOT: _bootmark('E')

# ---- hook bcrypt.dll!BCryptGenRandom to log its OUTPUT (the DRBG random bytes) ----
a.emit('push 0'); a.emit('push 0x80'); a.emit('push 2'); a.emit('push 0')
a.emit('push 0'); a.emit('push 0x40000000'); a.emit('push &rnglogpath')
a.emit('call dword ptr [&imp_CreateFileA]')
a.emit('mov dword ptr [&g_rng_log], eax')
a.emit('push &bcryptdll'); a.emit('call dword ptr [&imp_LoadLibraryA]'); a.emit('mov dword ptr [&g_bcrypt], eax')
if DIAG_BOOT: _bootmark('F')
a.emit('push &bcryptfn'); a.emit('push dword ptr [&g_bcrypt]'); a.emit('call dword ptr [&imp_GetProcAddress]'); a.emit('mov dword ptr [&g_bcrypt_fn], eax')
if DIAG_BOOT: _bootmark('G')
a.emit('mov esi, dword ptr [&g_bcrypt_fn]'); a.emit('mov edi, &g_bcrypt_orig'); a.emit('mov ecx, 5'); a.raw(b'\xf3\xa4')
a.emit('mov esi, dword ptr [&g_bcrypt_fn]'); a.emit('mov edx, &hook_bcrypt'); a.call_label('patch_one')
if DIAG_BOOT: _bootmark('H')

# ---- patch the EL HID filter string post-unpack via a delayed thread ----
if PATCH_EL_FILTER:
    a.emit('push 0'); a.emit('push 0'); a.emit('push 0'); a.emit('push &elfilter_thread'); a.emit('push 0'); a.emit('push 0')
    a.emit('call dword ptr [&imp_CreateThread]')
    a.emit('mov dword ptr [&g_thread], eax')

# ---- EL HID enum spoofing hooks (setupapi detail/instanceid + CreateFileW) ----
if SPOOF_EL_ENUM:
    # NOTE: GetModuleHandleA (NOT LoadLibraryA - loader-lock hazard in DllMain);
    # skip each hook if its target failed to resolve (patch_one(NULL) would AV)
    a.emit('push &setupapidll'); a.emit('call dword ptr [&imp_GetModuleHandleA]'); a.emit('mov dword ptr [&g_setupapi], eax')
    a.emit('push &fn_detail'); a.emit('push dword ptr [&g_setupapi]'); a.emit('call dword ptr [&imp_GetProcAddress]'); a.emit('mov dword ptr [&g_pDetail], eax')
    a.emit('push &fn_instid'); a.emit('push dword ptr [&g_setupapi]'); a.emit('call dword ptr [&imp_GetProcAddress]'); a.emit('mov dword ptr [&g_pInstId], eax')
    a.emit('push &k32'); a.emit('call dword ptr [&imp_GetModuleHandleA]')
    a.emit('push &fn_cfw'); a.emit('push eax'); a.emit('call dword ptr [&imp_GetProcAddress]'); a.emit('mov dword ptr [&g_pCFW], eax')
    a.emit('cmp dword ptr [&g_pDetail], 0'); a.jcc('je', 'spoof_skip_detail')
    a.emit('mov esi, dword ptr [&g_pDetail]'); a.emit('mov edi, &g_origDetail'); a.emit('mov ecx, 5'); a.raw(b'\xf3\xa4')
    a.emit('mov esi, dword ptr [&g_pDetail]'); a.emit('mov edx, &hookDetail'); a.call_label('patch_one')
    a.label('spoof_skip_detail')
    a.emit('cmp dword ptr [&g_pInstId], 0'); a.jcc('je', 'spoof_skip_instid')
    a.emit('mov esi, dword ptr [&g_pInstId]'); a.emit('mov edi, &g_origInstId'); a.emit('mov ecx, 5'); a.raw(b'\xf3\xa4')
    a.emit('mov esi, dword ptr [&g_pInstId]'); a.emit('mov edx, &hookInstId'); a.call_label('patch_one')
    a.label('spoof_skip_instid')
    a.emit('cmp dword ptr [&g_pCFW], 0'); a.jcc('je', 'spoof_skip_cfw')
    a.emit('mov esi, dword ptr [&g_pCFW]'); a.emit('mov edi, &g_origCFW'); a.emit('mov ecx, 5'); a.raw(b'\xf3\xa4')
    a.emit('mov esi, dword ptr [&g_pCFW]'); a.emit('mov edx, &hookCFW'); a.call_label('patch_one')
    a.label('spoof_skip_cfw')

a.emit('pop edi'); a.emit('pop esi'); a.emit('pop ebx')
if DIAG_BOOT: _bootmark('I')
a.label('dll_done')
a.emit('mov eax, 1')
a.emit('ret 12')

# ---------------- patch_one: esi=func, edx=hookproc ----------------
# NOTE: edx is volatile across calls, so stash it in memory before VirtualProtect
a.label('patch_one')
a.emit('mov dword ptr [&g_hookproc], edx')
a.emit('push &g_prtmp'); a.emit('push 0x40'); a.emit('push 5'); a.emit('push esi'); a.emit('call dword ptr [&imp_VirtualProtect]')
a.emit('mov ebx, esi')
a.emit('mov eax, dword ptr [&g_hookproc]'); a.emit('sub eax, esi'); a.emit('sub eax, 5')
a.emit('mov byte ptr [ebx], 0xE9'); a.emit('mov dword ptr [ebx + 1], eax')
a.emit('push &g_prtmp'); a.emit('push dword ptr [&g_prtmp]'); a.emit('push 5'); a.emit('push esi'); a.emit('call dword ptr [&imp_VirtualProtect]')
a.emit('ret')

# ---------------- restore_one: esi=func, edi=&origbuf ----------------
# BUGFIX (REPLAY_22 "VMP fast-fail / 0 records" root cause): the second
# VirtualProtect ran AFTER `xchg esi, edi`, so esi = &origbuf (our .data) and
# the call VirtualProtect(&origbuf, 5, oldprot=PAGE_EXECUTE_READ, ...) flipped
# OUR OWN .data page (g_origDev/g_origRd/g_origWr live next to g_rec/g_rec2)
# to read-execute. The next dump_buf write to g_rec/g_rec2 on that page then
# AV'd inside the very first ioctl -> 0 records -> VMP fast-fail. Use edi
# (=func, still holding the target after xchg) for the reprotect.
a.label('restore_one')
a.emit('push &g_prtmp'); a.emit('push 0x40'); a.emit('push 5'); a.emit('push esi'); a.emit('call dword ptr [&imp_VirtualProtect]')
a.emit('xchg esi, edi')
a.emit('mov ecx, 5'); a.raw(b'\xf3\xa4')
a.emit('push &g_prtmp'); a.emit('push dword ptr [&g_prtmp]'); a.emit('push 5'); a.emit('push edi'); a.emit('call dword ptr [&imp_VirtualProtect]')
a.emit('ret')

# ---------------- hookDetail: spoof velhid interface detail path ----------------
# SetupDiGetDeviceInterfaceDetailW(set, did, detail, detailsz, reqsz, didout)
# frame after pushad: [esp+32]=ret [36]=set [40]=did [44]=detail [48]=detailsz
a.label('hookDetail')
a.emit('pushad')
a.emit('cmp dword ptr [&g_mark_d], 0'); a.jcc('jne', 'det_marked')
a.emit('mov dword ptr [&g_mark_d], 1')
a.emit('mov dword ptr [&g_prtmp], 0x44')
a.emit('push 2'); a.emit('push 0'); a.emit('push 0'); a.emit('push dword ptr [&g_spoof_h]'); a.emit('call dword ptr [&imp_SetFilePointer]')
a.emit('push 0'); a.emit('push &g_written3'); a.emit('push 1'); a.emit('push &g_prtmp'); a.emit('push dword ptr [&g_spoof_h]'); a.emit('call dword ptr [&imp_WriteFile]')
a.label('det_marked')
a.emit('mov eax, dword ptr [esp + 32]'); a.emit('mov dword ptr [&g_det_saved], eax')
a.emit('mov eax, dword ptr [esp + 44]'); a.emit('mov dword ptr [&g_det_arg3], eax')
a.emit('mov esi, dword ptr [&g_pDetail]'); a.emit('mov edi, &g_origDetail'); a.call_label('restore_one')
a.emit('mov eax, &detail_ret'); a.emit('mov dword ptr [esp + 32], eax')
a.emit('popad')
a.emit('jmp dword ptr [&g_pDetail]')

a.label('detail_ret')
a.emit('pushad')
a.emit('cmp dword ptr [esp + 28], 0'); a.jcc('je', 'det_done')      # retval==0 skip
a.emit('mov esi, dword ptr [&g_det_arg3]'); a.emit('test esi, esi'); a.jcc('jz', 'det_done')
a.emit('add esi, 4')                                               # ->DevicePath
a.emit('mov edi, &velhid_real'); a.emit('mov ecx, 60')
a.label('det_cmp')
a.emit('mov ax, word ptr [esi]'); a.emit('cmp ax, word ptr [edi]'); a.jcc('jne', 'det_done')
a.emit('add esi, 2'); a.emit('add edi, 2'); a.emit('dec ecx'); a.jcc('jnz', 'det_cmp')
# matched velhid's real path -> overwrite with the fake (60 wchars + null)
a.emit('mov esi, &velhid_fake'); a.emit('mov edi, dword ptr [&g_det_arg3]'); a.emit('add edi, 4')
a.emit('mov ecx, 122'); a.raw(b'\xf3\xa4')
a.label('det_done')
a.emit('mov esi, dword ptr [&g_pDetail]'); a.emit('mov edx, &hookDetail'); a.call_label('patch_one')
a.emit('popad')
a.emit('jmp dword ptr [&g_det_saved]')

# ---------------- hookInstId: spoof velhid instance id ----------------
# SetupDiGetDeviceInstanceIdW(set, did, instid, size, reqsz)
# frame: [esp+32]=ret [36]=set [40]=did [44]=instid [48]=size [52]=reqsz
a.label('hookInstId')
a.emit('pushad')
a.emit('cmp dword ptr [&g_mark_i], 0'); a.jcc('jne', 'ins_marked')
a.emit('mov dword ptr [&g_mark_i], 1')
a.emit('mov dword ptr [&g_prtmp], 0x49')
a.emit('push 2'); a.emit('push 0'); a.emit('push 0'); a.emit('push dword ptr [&g_spoof_h]'); a.emit('call dword ptr [&imp_SetFilePointer]')
a.emit('push 0'); a.emit('push &g_written3'); a.emit('push 1'); a.emit('push &g_prtmp'); a.emit('push dword ptr [&g_spoof_h]'); a.emit('call dword ptr [&imp_WriteFile]')
a.label('ins_marked')
a.emit('mov eax, dword ptr [esp + 32]'); a.emit('mov dword ptr [&g_ins_saved], eax')
a.emit('mov eax, dword ptr [esp + 44]'); a.emit('mov dword ptr [&g_ins_arg3], eax')
a.emit('mov esi, dword ptr [&g_pInstId]'); a.emit('mov edi, &g_origInstId'); a.call_label('restore_one')
a.emit('mov eax, &instid_ret'); a.emit('mov dword ptr [esp + 32], eax')
a.emit('popad')
a.emit('jmp dword ptr [&g_pInstId]')

a.label('instid_ret')
a.emit('pushad')
a.emit('cmp dword ptr [esp + 28], 0'); a.jcc('je', 'ins_done')
a.emit('mov esi, dword ptr [&g_ins_arg3]'); a.emit('test esi, esi'); a.jcc('jz', 'ins_done')
a.emit('mov edi, &instid_real'); a.emit('mov ecx, 17')
a.label('ins_cmp')
a.emit('mov ax, word ptr [esi]'); a.emit('cmp ax, word ptr [edi]'); a.jcc('jne', 'ins_done')
a.emit('add esi, 2'); a.emit('add edi, 2'); a.emit('dec ecx'); a.jcc('jnz', 'ins_cmp')
a.emit('mov esi, &instid_fake'); a.emit('mov edi, dword ptr [&g_ins_arg3]')
a.emit('mov ecx, 36'); a.raw(b'\xf3\xa4')
a.label('ins_done')
a.emit('mov esi, dword ptr [&g_pInstId]'); a.emit('mov edx, &hookInstId'); a.call_label('patch_one')
a.emit('popad')
a.emit('jmp dword ptr [&g_ins_saved]')

# ---------------- hookCFW: redirect fake vid_0471&pid_485e paths to velhid ----------------
# CreateFileW(name, access, share, sa, disp, flags, tmpl)
# frame: [esp+32]=ret [36]=name ...
a.label('hookCFW')
a.emit('pushad')
a.emit('cmp dword ptr [&g_mark_c], 0'); a.jcc('jne', 'cfw_marked')
a.emit('mov dword ptr [&g_mark_c], 1')
a.emit('mov dword ptr [&g_prtmp], 0x43')
a.emit('push 2'); a.emit('push 0'); a.emit('push 0'); a.emit('push dword ptr [&g_spoof_h]'); a.emit('call dword ptr [&imp_SetFilePointer]')
a.emit('push 0'); a.emit('push &g_written3'); a.emit('push 1'); a.emit('push &g_prtmp'); a.emit('push dword ptr [&g_spoof_h]'); a.emit('call dword ptr [&imp_WriteFile]')
a.label('cfw_marked')
a.emit('mov eax, dword ptr [esp + 32]'); a.emit('mov dword ptr [&g_cfw_saved], eax')
a.emit('mov esi, dword ptr [esp + 36]'); a.emit('test esi, esi'); a.jcc('jz', 'cfw_call')
a.emit('mov ebx, 1024')                          # scan bound
a.label('cfw_outer')
a.emit('mov ax, word ptr [esi]'); a.emit('test ax, ax'); a.jcc('jz', 'cfw_call')
a.emit('mov edx, esi'); a.emit('mov edi, &cfw_pat'); a.emit('mov ecx, 18')
a.label('cfw_inner')
a.emit('mov ax, word ptr [edx]'); a.emit('test ax, ax'); a.jcc('jz', 'cfw_next')
a.emit('or ax, 0x20'); a.emit('cmp ax, word ptr [edi]'); a.jcc('jne', 'cfw_next')
a.emit('add edx, 2'); a.emit('add edi, 2'); a.emit('dec ecx'); a.jcc('jnz', 'cfw_inner')
# match -> redirect this CreateFileW to velhid's real interface path
a.emit('mov eax, &velhid_real'); a.emit('mov dword ptr [esp + 36], eax')
a.jmp_label('cfw_call')
a.label('cfw_next')
a.emit('add esi, 2'); a.emit('dec ebx'); a.jcc('jnz', 'cfw_outer')
a.label('cfw_call')
a.emit('mov esi, dword ptr [&g_pCFW]'); a.emit('mov edi, &g_origCFW'); a.call_label('restore_one')
a.emit('mov eax, &cfw_ret'); a.emit('mov dword ptr [esp + 32], eax')
a.emit('popad')
a.emit('jmp dword ptr [&g_pCFW]')

a.label('cfw_ret')
a.emit('pushad')
a.emit('mov esi, dword ptr [&g_pCFW]'); a.emit('mov edx, &hookCFW'); a.call_label('patch_one')
a.emit('popad')
a.emit('jmp dword ptr [&g_cfw_saved]')

# ---------------- elfilter_thread: delayed .rdata filter-string patch ----------------
a.label('elfilter_thread')
a.emit('push 4000'); a.emit('call dword ptr [&imp_Sleep]')
a.emit('push &g_prtmp'); a.emit('push 0x40'); a.emit('push 18'); a.emit('push %d' % EL_FILTER_VA); a.emit('call dword ptr [&imp_VirtualProtect]')
a.emit('test eax, eax'); a.jcc('jz', 'elf_skip_e1')
a.emit('mov esi, &elfilter_new'); a.emit('mov edi, %d' % EL_FILTER_VA); a.emit('mov ecx, 18'); a.raw(b'\xf3\xa4')
a.emit('push &g_prtmp'); a.emit('push dword ptr [&g_prtmp]'); a.emit('push 18'); a.emit('push %d' % EL_FILTER_VA); a.emit('call dword ptr [&imp_VirtualProtect]')
a.label('elf_skip_e1')
a.emit('push 0'); a.emit('call dword ptr [&imp_ExitThread]')


# ---------------- BCryptGenRandom hook (capture the DRBG random output) ----------------
# BCryptGenRandom(hAlg, pbBuffer, cbBuffer, flags)  [esp+4..16]
# after pushad: [esp+32]=ret [esp+36]=hAlg [esp+40]=pbBuffer [esp+44]=cbBuffer
a.label('hook_bcrypt')
a.emit('pushad')
a.emit('mov eax, dword ptr [esp + 32]'); a.emit('mov dword ptr [&g_rng_saved], eax')
a.emit('mov eax, dword ptr [esp + 36]'); a.emit('mov dword ptr [&g_rng_ptr], eax')
a.emit('mov eax, dword ptr [esp + 40]'); a.emit('mov dword ptr [&g_rng_cb], eax')
a.emit('mov esi, dword ptr [&g_bcrypt_fn]'); a.emit('mov edi, &g_bcrypt_orig'); a.call_label('restore_one')
a.emit('mov eax, &bcrypt_ret'); a.emit('mov dword ptr [esp + 32], eax')
a.emit('popad')
a.emit('jmp dword ptr [&g_bcrypt_fn]')

a.label('bcrypt_ret')
a.emit('pushad')
# dump up to 48 bytes of the output buffer into g_rng_buf
a.emit('mov edi, &g_rng_buf'); a.emit('mov ecx, 12'); a.emit('xor eax, eax'); a.raw(b'\xf3\xab')  # zero 48B
a.emit('mov esi, dword ptr [&g_rng_ptr]')
a.emit('mov ecx, dword ptr [&g_rng_cb]')
a.emit('cmp ecx, 48'); a.jcc('jbe', 'bcrypt_cl'); a.emit('mov ecx, 48')
a.label('bcrypt_cl')
a.emit('mov edi, &g_rng_buf')
a.emit('mov ebx, ecx')
a.emit('push ecx'); a.emit('push esi'); a.emit('call dword ptr [&imp_IsBadReadPtr]')
a.emit('mov ecx, ebx')
a.emit('test eax, eax'); a.jcc('jnz', 'bcrypt_rd')
a.raw(b'\xf3\xa4')
a.label('bcrypt_rd')
# write [cbBuffer u32][48B] = 52 bytes
a.emit('push 2'); a.emit('push 0'); a.emit('push 0'); a.emit('push dword ptr [&g_rng_log]'); a.emit('call dword ptr [&imp_SetFilePointer]')
a.emit('push 0'); a.emit('push &g_rng_written'); a.emit('push 4'); a.emit('push &g_rng_cb'); a.emit('push dword ptr [&g_rng_log]'); a.emit('call dword ptr [&imp_WriteFile]')
a.emit('push 0'); a.emit('push &g_rng_written'); a.emit('push 48'); a.emit('push &g_rng_buf'); a.emit('push dword ptr [&g_rng_log]'); a.emit('call dword ptr [&imp_WriteFile]')
if FIX_RNG:
    # overwrite the game's buffer with zeros AFTER logging the real bytes
    a.emit('mov edi, dword ptr [&g_rng_ptr]')
    a.emit('mov ecx, dword ptr [&g_rng_cb]')
    a.emit('xor eax, eax')
    a.raw(b'\xf3\xaa')
# re-patch
a.emit('mov esi, dword ptr [&g_bcrypt_fn]'); a.emit('mov edx, &hook_bcrypt'); a.call_label('patch_one')
a.emit('popad')
a.emit('jmp dword ptr [&g_rng_saved]')

# ---------------- TEA hooks (capture session key) ----------------
# entry frame: [esp]=ret [esp+4]=arg1 [esp+8]=arg2 [esp+12]=arg3(key)
# after pushad: [esp+32]=ret [esp+36]=arg1 [esp+40]=arg2 [esp+44]=arg3
if TEA_HOOK:
    a.label('tea_hook_enc')
    a.emit('pushad')
    a.emit('mov eax, dword ptr [esp + 44]'); a.emit('mov dword ptr [&g_tea_keyptr], eax')
    a.emit('mov eax, dword ptr [esp + 36]'); a.emit('mov dword ptr [&g_tea_arg1], eax')
    a.emit('mov eax, dword ptr [esp + 40]'); a.emit('mov dword ptr [&g_tea_arg2], eax')
    a.emit('mov eax, dword ptr [esp + 32]'); a.emit('mov dword ptr [&g_tea_saved_ret], eax')
    a.emit('mov dword ptr [&g_tea_rec + 0], %d' % TEA_ENC)
    a.emit('mov esi, dword ptr [&g_tea_keyptr]'); a.emit('mov edi, &g_tea_rec + 4'); a.emit('mov ecx, 4'); a.raw(b'\xf3\xa4')
    a.emit('mov esi, dword ptr [&g_tea_arg1]'); a.emit('mov edi, &g_tea_rec + 20'); a.emit('mov ecx, 2'); a.raw(b'\xf3\xa4')
    a.emit('mov esi, dword ptr [&g_tea_arg2]'); a.emit('mov edi, &g_tea_rec + 28'); a.emit('mov ecx, 2'); a.raw(b'\xf3\xa4')
    a.call_label('write_tea_rec')
    a.emit('mov esi, %d' % TEA_ENC); a.emit('mov edi, &g_tea_orig_enc'); a.call_label('restore_one')
    a.emit('mov eax, &tea_ret_enc'); a.emit('mov dword ptr [esp + 32], eax')
    a.emit('popad')
    a.emit('jmp %d' % TEA_ENC)

    a.label('tea_ret_enc')
    a.emit('pushad')
    a.emit('mov esi, %d' % TEA_ENC); a.emit('mov edx, &tea_hook_enc'); a.call_label('patch_one')
    a.emit('popad')
    a.emit('jmp dword ptr [&g_tea_saved_ret]')

    a.label('tea_hook_dec')
    a.emit('pushad')
    a.emit('mov eax, dword ptr [esp + 44]'); a.emit('mov dword ptr [&g_tea_keyptr], eax')
    a.emit('mov eax, dword ptr [esp + 36]'); a.emit('mov dword ptr [&g_tea_arg1], eax')
    a.emit('mov eax, dword ptr [esp + 40]'); a.emit('mov dword ptr [&g_tea_arg2], eax')
    a.emit('mov eax, dword ptr [esp + 32]'); a.emit('mov dword ptr [&g_tea_saved_ret], eax')
    a.emit('mov dword ptr [&g_tea_rec + 0], %d' % TEA_DEC)
    a.emit('mov esi, dword ptr [&g_tea_keyptr]'); a.emit('mov edi, &g_tea_rec + 4'); a.emit('mov ecx, 4'); a.raw(b'\xf3\xa4')
    a.emit('mov esi, dword ptr [&g_tea_arg1]'); a.emit('mov edi, &g_tea_rec + 20'); a.emit('mov ecx, 2'); a.raw(b'\xf3\xa4')
    a.emit('mov esi, dword ptr [&g_tea_arg2]'); a.emit('mov edi, &g_tea_rec + 28'); a.emit('mov ecx, 2'); a.raw(b'\xf3\xa4')
    a.call_label('write_tea_rec')
    a.emit('mov esi, %d' % TEA_DEC); a.emit('mov edi, &g_tea_orig_dec'); a.call_label('restore_one')
    a.emit('mov eax, &tea_ret_dec'); a.emit('mov dword ptr [esp + 32], eax')
    a.emit('popad')
    a.emit('jmp %d' % TEA_DEC)

    a.label('tea_ret_dec')
    a.emit('pushad')
    a.emit('mov esi, %d' % TEA_DEC); a.emit('mov edx, &tea_hook_dec'); a.call_label('patch_one')
    a.emit('popad')
    a.emit('jmp dword ptr [&g_tea_saved_ret]')

    a.label('write_tea_rec')
    a.emit('push 2'); a.emit('push 0'); a.emit('push 0'); a.emit('push dword ptr [&g_tea_log]'); a.emit('call dword ptr [&imp_SetFilePointer]')
    a.emit('push 0'); a.emit('push &g_tea_written'); a.emit('push 36'); a.emit('push &g_tea_rec'); a.emit('push dword ptr [&g_tea_log]'); a.emit('call dword ptr [&imp_WriteFile]')
    a.emit('ret')

# ---------------- dump_buf: esi=src, ecx=size, edi=dst ----------------
a.label('dump_buf')
a.emit('cmp ecx, 4096')
a.jcc('jbe', 'db_clamped')
a.emit('mov ecx, 4096')
a.label('db_clamped')
a.emit('push ecx')
a.emit('push edi')
a.emit('mov ecx, 4096')
a.emit('xor al, al')
a.raw(b'\xf3\xaa')
a.emit('pop edi')
a.emit('pop ecx')
a.emit('test ecx, ecx')
a.jcc('jz', 'db_done')
a.emit('test esi, esi')
a.jcc('jz', 'db_done')
a.emit('mov ebx, ecx')
a.emit('push ecx'); a.emit('push esi'); a.emit('call dword ptr [&imp_IsBadReadPtr]')
a.emit('mov ecx, ebx')
a.emit('test eax, eax')
a.jcc('jnz', 'db_done')
a.raw(b'\xf3\xa4')
a.label('db_done')
a.emit('ret')

# ---------------- write_ioctl_rec: append g_rec (8224B) ----------------
a.label('write_ioctl_rec')
a.emit('push 2'); a.emit('push 0'); a.emit('push 0'); a.emit('push dword ptr [&g_log]'); a.emit('call dword ptr [&imp_SetFilePointer]')
a.emit('push 0'); a.emit('push &g_written'); a.emit('push 8224'); a.emit('push &g_rec'); a.emit('push dword ptr [&g_log]'); a.emit('call dword ptr [&imp_WriteFile]')
a.emit('ret')

# ---------------- write_rw_rec: append g_rec2 (4128B) ----------------
a.label('write_rw_rec')
a.emit('push 2'); a.emit('push 0'); a.emit('push 0'); a.emit('push dword ptr [&g_log2]'); a.emit('call dword ptr [&imp_SetFilePointer]')
a.emit('push 0'); a.emit('push &g_written2'); a.emit('push 4128'); a.emit('push &g_rec2'); a.emit('push dword ptr [&g_log2]'); a.emit('call dword ptr [&imp_WriteFile]')
a.emit('ret')

# ---------------- write_caller_rec: append 8 stack dwords [esp+0x1C..0x38] (32B) ----------------
a.label('write_caller_rec')
a.emit('lea eax, dword ptr [esp + 0x1c]'); a.emit('mov dword ptr [&g_prtmp], eax')
a.emit('push 2'); a.emit('push 0'); a.emit('push 0'); a.emit('push dword ptr [&g_log3]'); a.emit('call dword ptr [&imp_SetFilePointer]')
a.emit('push 0'); a.emit('push &g_written3'); a.emit('push 32'); a.emit('push dword ptr [&g_prtmp]'); a.emit('push dword ptr [&g_log3]'); a.emit('call dword ptr [&imp_WriteFile]')
a.emit('ret')

# ---------------- hookIOCTL (DeviceIoControl) ----------------
a.label('hookIOCTL')
a.emit('pushad')
a.emit('mov eax, dword ptr [esp + 32]'); a.emit('mov dword ptr [&g_saved_ret], eax')
a.emit('mov eax, dword ptr [esp + 36]'); a.emit('mov dword ptr [&g_hDevice], eax')
a.emit('mov eax, dword ptr [esp + 40]'); a.emit('mov dword ptr [&g_ioctl], eax')
a.emit('mov eax, dword ptr [esp + 44]'); a.emit('mov dword ptr [&g_inbuf], eax')
a.emit('mov eax, dword ptr [esp + 48]'); a.emit('mov dword ptr [&g_insize], eax')
a.emit('mov eax, dword ptr [esp + 52]'); a.emit('mov dword ptr [&g_outbuf], eax')
a.emit('mov eax, dword ptr [esp + 56]'); a.emit('mov dword ptr [&g_outsize], eax')
a.emit('mov eax, dword ptr [esp + 60]'); a.emit('mov dword ptr [&g_pBytesRet], eax')
if CALLER_LOG:
    a.call_label('write_caller_rec')
# dump inbuf
a.emit('mov esi, dword ptr [&g_inbuf]')
a.emit('mov ecx, dword ptr [&g_insize]')
a.emit('mov edi, &g_rec')
a.emit('add edi, 32')
a.call_label('dump_buf')
# ---- 0501 (0x220028 insz=17): capture input 4B token; buffer dumped in retIOCTL ----
a.emit('mov dword ptr [&g_memdump + 4], 0')          # flag = 0 (not 0501)
a.emit('mov eax, dword ptr [&g_ioctl]')
a.emit('cmp eax, 0x00220028'); a.jcc('jne', 'mem_skip')
a.emit('mov eax, dword ptr [&g_insize]')
a.emit('cmp eax, 17'); a.jcc('jne', 'mem_skip')
a.emit('mov esi, dword ptr [&g_inbuf]'); a.emit('add esi, 13')
a.emit('mov eax, dword ptr [esi]'); a.emit('mov dword ptr [&g_memdump], eax')  # token
a.emit('mov dword ptr [&g_memdump + 4], 1')          # flag = 1 (0501)
a.label('mem_skip')
# ---- watch: after a 0501, log the response pointer's memory for the next 40 ioctls ----
a.emit('cmp dword ptr [&g_watch_cnt], 0')
a.jcc('jle', 'watch_skip')
a.emit('mov eax, dword ptr [&g_watch_cnt]'); a.emit('dec eax'); a.emit('mov dword ptr [&g_watch_cnt], eax')
a.emit('mov edi, &g_watch_rec'); a.emit('mov ecx, 5'); a.emit('xor eax, eax'); a.raw(b'\xf3\xab')  # zero 20B
a.emit('mov eax, dword ptr [&g_watch]'); a.emit('mov dword ptr [&g_watch_rec], eax')               # rptr
a.emit('mov esi, eax'); a.emit('mov edi, &g_watch_rec + 4'); a.emit('mov ecx, 16')
a.emit('mov ebx, ecx')
a.emit('push ecx'); a.emit('push esi'); a.emit('call dword ptr [&imp_IsBadReadPtr]')
a.emit('mov ecx, ebx')
a.emit('test eax, eax'); a.jcc('jnz', 'watch_rd')
a.raw(b'\xf3\xa4')
a.label('watch_rd')
a.emit('push 2'); a.emit('push 0'); a.emit('push 0'); a.emit('push dword ptr [&g_memlog]'); a.emit('call dword ptr [&imp_SetFilePointer]')
a.emit('push 0'); a.emit('push &g_mem_written'); a.emit('push 20'); a.emit('push &g_watch_rec'); a.emit('push dword ptr [&g_memlog]'); a.emit('call dword ptr [&imp_WriteFile]')
a.label('watch_skip')
# ---- dog1 replay dispatch: dt 0x47/0x39/0x22 -> t7 table engine ----
a.emit('mov eax, dword ptr [esp + 40]'); a.emit('shr eax, 16'); a.emit('and eax, 0xffff')
if REPLAY_47:
    a.emit('cmp eax, 0x47'); a.jcc('je', 'is_dog1')
if REPLAY_39:
    a.emit('cmp eax, 0x39'); a.jcc('je', 'is_dog1')
if REPLAY_22:
    a.emit('cmp eax, 0x22'); a.jcc('je', 'is_dog1')
a.jmp_label('pt_passthrough')

a.label('is_dog1')
a.emit('xor ebx, ebx')
a.label('t7_scan')
a.emit('cmp ebx, %d' % N7KEYS); a.jcc('jae', 't7_miss')
a.emit('mov eax, ebx'); a.emit('imul eax, 88'); a.emit('mov esi, &t7_keys'); a.emit('add esi, eax')
a.emit('mov eax, dword ptr [esp + 40]'); a.emit('cmp eax, dword ptr [esi]'); a.jcc('jne', 't7_next')
a.emit('mov eax, dword ptr [esp + 48]'); a.emit('cmp eax, dword ptr [esi + 4]'); a.jcc('jne', 't7_next')
a.emit('mov eax, dword ptr [esp + 56]'); a.emit('cmp eax, dword ptr [esi + 72]'); a.jcc('jne', 't7_next')
a.emit('mov ebp, &t7_masks'); a.emit('mov eax, ebx'); a.emit('shl eax, 6'); a.emit('add ebp, eax')
a.call_label('t7_cmpin')
a.emit('test eax, eax'); a.jcc('jz', 't7_next')
a.jmp_label('t7_found')
a.label('t7_next'); a.emit('inc ebx'); a.jmp_label('t7_scan')

# t7_cmpin: eax=1 if min(insz,64) unmasked bytes of inbuf == key+8 (esi=key, ebp=mask), else 0
# NOTE: reached via call -> frame offsets are +4 vs the pushad frame
a.label('t7_cmpin')
a.emit('mov ecx, dword ptr [esp + 52]'); a.emit('cmp ecx, 64'); a.jcc('jbe', 't7ci_cl'); a.emit('mov ecx, 64')
a.label('t7ci_cl')
a.emit('mov edx, dword ptr [esp + 48]')
a.emit('lea edi, dword ptr [esi + 8]')
a.label('t7ci_loop')
a.emit('test ecx, ecx'); a.jcc('jz', 't7ci_ok')
a.emit('cmp byte ptr [ebp], 0'); a.jcc('je', 't7ci_skip')
a.emit('mov al, byte ptr [edx]'); a.emit('cmp al, byte ptr [edi]'); a.jcc('jne', 't7ci_no')
a.label('t7ci_skip')
a.emit('inc ebp'); a.emit('inc edx'); a.emit('inc edi'); a.emit('dec ecx'); a.jmp_label('t7ci_loop')
a.label('t7ci_ok'); a.emit('mov eax, 1'); a.emit('ret')
a.label('t7ci_no'); a.emit('xor eax, eax'); a.emit('ret')

# exact-match miss: rescan ignoring outsz (same data read, different requested size)
a.label('t7_miss')
a.emit('xor ebx, ebx')
a.label('t7_scan2')
a.emit('cmp ebx, %d' % N7KEYS); a.jcc('jae', 't7_dead')
a.emit('mov eax, ebx'); a.emit('imul eax, 88'); a.emit('mov esi, &t7_keys'); a.emit('add esi, eax')
a.emit('mov eax, dword ptr [esp + 40]'); a.emit('cmp eax, dword ptr [esi]'); a.jcc('jne', 't7_next2')
a.emit('mov eax, dword ptr [esp + 48]'); a.emit('cmp eax, dword ptr [esi + 4]'); a.jcc('jne', 't7_next2')
a.emit('mov ebp, &t7_masks'); a.emit('mov eax, ebx'); a.emit('shl eax, 6'); a.emit('add ebp, eax')
a.call_label('t7_cmpin')
a.emit('test eax, eax'); a.jcc('jz', 't7_next2')
a.jmp_label('t7_found')
a.label('t7_next2'); a.emit('inc ebx'); a.jmp_label('t7_scan2')

# unknown dog1 call: log marker (retval=0xDEAD, outbuf dump zeroed) then passthrough
a.label('t7_dead')
a.emit('mov esi, 0'); a.emit('mov ecx, 0'); a.emit('mov edi, &g_rec'); a.emit('add edi, 4128'); a.call_label('dump_buf')
a.emit('mov ecx, &g_rec')
a.emit('mov dword ptr [ecx + 0], 0x54434F49')
a.emit('mov eax, dword ptr [&g_hDevice]'); a.emit('mov dword ptr [ecx + 4], eax')
a.emit('mov eax, dword ptr [&g_ioctl]'); a.emit('mov dword ptr [ecx + 8], eax')
a.emit('mov eax, dword ptr [&g_insize]'); a.emit('mov dword ptr [ecx + 12], eax')
a.emit('mov eax, dword ptr [&g_outsize]'); a.emit('mov dword ptr [ecx + 16], eax')
a.emit('mov dword ptr [ecx + 20], 0xDEAD')
a.emit('mov eax, dword ptr [&g_inbuf]'); a.emit('mov dword ptr [ecx + 24], eax')
a.emit('mov eax, dword ptr [&g_outbuf]'); a.emit('mov dword ptr [ecx + 28], eax')
a.call_label('write_ioctl_rec')
a.jmp_label('pt_passthrough')

a.label('t7_found')
# latency for ALL replayed dog1 replies: real dog round-trips take ~ms; instant
# canned replies make the game cycle the EL verify loop forever (Track B finding).
if REPLAY_DELAY_MS:
    a.emit('push %d' % REPLAY_DELAY_MS); a.emit('call dword ptr [&imp_Sleep]')
# resp = t7_resps + key.first + cursor*key.stride
a.emit('mov edi, &g7_cursors'); a.emit('mov eax, ebx'); a.emit('shl eax, 2'); a.emit('add edi, eax')
a.emit('mov edx, dword ptr [edi]')
a.emit('mov eax, dword ptr [esi + 84]'); a.emit('imul eax, edx'); a.emit('add eax, dword ptr [esi + 76]'); a.emit('add eax, &t7_resps')
a.emit('mov ecx, dword ptr [eax]'); a.emit('mov dword ptr [&g_respsize], ecx')
a.emit('mov ecx, dword ptr [&g_respsize]'); a.emit('cmp ecx, dword ptr [esp + 56]'); a.jcc('jbe', 't7_cp'); a.emit('mov ecx, dword ptr [esp + 56]')
a.label('t7_cp')
a.emit('mov dword ptr [&g_respsize], ecx')
a.emit('lea esi, dword ptr [eax + 4]')
a.emit('mov edi, dword ptr [esp + 52]')
a.raw(b'\xf3\xa4')
# (0501 allocbuf overwrite REMOVED: the game validates the 0501 response 4B
#  pointer value itself -> must serve the recorded pointer verbatim)
# ---- complete the OVERLAPPED if the game issued this ioctl asynchronously ----
# (the 0x470800 "open" is async: real driver pends+signals; a canned reply that
#  never signals the event makes the game time out and re-open forever -> #522)
a.emit('mov eax, dword ptr [esp + 64]')          # lpOverlapped
a.emit('test eax, eax'); a.jcc('jz', 't7_noovl')
a.emit('mov ecx, dword ptr [&g_respsize]')
a.emit('mov dword ptr [eax + 4], ecx')           # OVERLAPPED.InternalHigh = bytes
a.emit('mov edx, dword ptr [eax + 16]')          # OVERLAPPED.hEvent
a.emit('test edx, edx'); a.jcc('jz', 't7_noovl')
a.emit('push edx'); a.emit('call dword ptr [&imp_SetEvent]')
a.label('t7_noovl')
a.emit('mov eax, dword ptr [esp + 60]'); a.emit('test eax, eax'); a.jcc('jz', 't7_nobr')
a.emit('mov ecx, dword ptr [&g_respsize]'); a.emit('mov dword ptr [eax], ecx')
a.label('t7_nobr')
# advance cursor with wrap
a.emit('mov eax, ebx'); a.emit('imul eax, 88'); a.emit('mov esi, &t7_keys'); a.emit('add esi, eax')
a.emit('mov edi, &g7_cursors'); a.emit('mov eax, ebx'); a.emit('shl eax, 2'); a.emit('add edi, eax')
a.emit('mov edx, dword ptr [edi]'); a.emit('inc edx')
a.emit('cmp edx, dword ptr [esi + 80]'); a.jcc('jb', 't7_cw'); a.emit('xor edx, edx')
a.label('t7_cw'); a.emit('mov dword ptr [edi], edx')
# log the replayed answer (ret=1)
a.emit('mov esi, dword ptr [esp + 52]'); a.emit('mov ecx, dword ptr [&g_respsize]'); a.emit('mov edi, &g_rec'); a.emit('add edi, 4128'); a.call_label('dump_buf')
a.emit('mov ecx, &g_rec')
a.emit('mov dword ptr [ecx + 0], 0x54434F49')
a.emit('mov eax, dword ptr [&g_hDevice]'); a.emit('mov dword ptr [ecx + 4], eax')
a.emit('mov eax, dword ptr [&g_ioctl]'); a.emit('mov dword ptr [ecx + 8], eax')
a.emit('mov eax, dword ptr [&g_insize]'); a.emit('mov dword ptr [ecx + 12], eax')
a.emit('mov eax, dword ptr [&g_outsize]'); a.emit('mov dword ptr [ecx + 16], eax')
a.emit('mov dword ptr [ecx + 20], 1')
a.emit('mov eax, dword ptr [&g_inbuf]'); a.emit('mov dword ptr [ecx + 24], eax')
a.emit('mov eax, dword ptr [&g_outbuf]'); a.emit('mov dword ptr [ecx + 28], eax')
a.call_label('write_ioctl_rec')
a.emit('mov dword ptr [esp + 28], 1'); a.emit('popad'); a.emit('ret 32')

# ---- passthrough with logging (non-dog1 ioctls) ----
a.label('pt_passthrough')
a.emit('mov eax, &retIOCTL')
a.emit('mov dword ptr [esp + 32], eax')
a.emit('mov esi, dword ptr [&g_pDev]'); a.emit('mov edi, &g_origDev'); a.call_label('restore_one')
a.emit('popad')
a.emit('jmp dword ptr [&g_pDev]')

# ---------------- retIOCTL (passthrough return) ----------------
a.label('retIOCTL')
a.emit('mov dword ptr [&g_retval], eax')
a.emit('pushad')
a.emit('mov esi, dword ptr [&g_outbuf]')
a.emit('mov ecx, dword ptr [&g_outsize]')
a.emit('mov edi, &g_rec')
a.emit('add edi, 4128')
a.call_label('dump_buf')
a.emit('mov ecx, &g_rec')
a.emit('mov dword ptr [ecx + 0], 0x54434F49')
a.emit('mov eax, dword ptr [&g_hDevice]'); a.emit('mov dword ptr [ecx + 4], eax')
a.emit('mov eax, dword ptr [&g_ioctl]'); a.emit('mov dword ptr [ecx + 8], eax')
a.emit('mov eax, dword ptr [&g_insize]'); a.emit('mov dword ptr [ecx + 12], eax')
a.emit('mov eax, dword ptr [&g_outsize]'); a.emit('mov dword ptr [ecx + 16], eax')
a.emit('mov eax, dword ptr [&g_retval]'); a.emit('mov dword ptr [ecx + 20], eax')
a.emit('mov eax, dword ptr [&g_inbuf]'); a.emit('mov dword ptr [ecx + 24], eax')
# log actual bytes returned (*pBytesRet) in the outb slot
a.emit('mov eax, dword ptr [&g_pBytesRet]')
a.emit('test eax, eax'); a.jcc('jz', 'pbr_zero')
a.emit('mov eax, dword ptr [eax]'); a.jmp_label('pbr_done')
a.label('pbr_zero'); a.emit('xor eax, eax')
a.label('pbr_done')
a.emit('mov dword ptr [ecx + 28], eax')
a.call_label('write_ioctl_rec')
# ---- dump the 0501 buffer AFTER the real dog filled it ----
a.emit('cmp dword ptr [&g_memdump + 4], 1'); a.jcc('jne', 'mem2_skip')
a.emit('mov edi, &g_memdump + 8'); a.emit('mov ecx, 9'); a.emit('xor eax, eax'); a.raw(b'\xf3\xab')  # zero 36B (input mem16 + resp ptr4 + resp mem16)
a.emit('mov esi, dword ptr [&g_memdump]'); a.emit('mov edi, &g_memdump + 8'); a.emit('mov ecx, 16')
a.emit('mov ebx, ecx')
a.emit('push ecx'); a.emit('push esi'); a.emit('call dword ptr [&imp_IsBadReadPtr]')
a.emit('mov ecx, ebx')
a.emit('test eax, eax'); a.jcc('jnz', 'mem2_in')
a.raw(b'\xf3\xa4')
a.label('mem2_in')
# response 4B = outbuf[1:5]
a.emit('mov esi, dword ptr [&g_outbuf]'); a.emit('add esi, 1')
a.emit('mov eax, dword ptr [esi]'); a.emit('mov dword ptr [&g_memdump + 24], eax')  # resp ptr
a.emit('mov dword ptr [&g_watch], eax')           # watch this rptr
a.emit('mov dword ptr [&g_watch_cnt], 40')        # for the next 40 ioctls
a.emit('mov esi, eax'); a.emit('mov edi, &g_memdump + 28'); a.emit('mov ecx, 16')
a.emit('mov ebx, ecx')
a.emit('push ecx'); a.emit('push esi'); a.emit('call dword ptr [&imp_IsBadReadPtr]')
a.emit('mov ecx, ebx')
a.emit('test eax, eax'); a.jcc('jnz', 'mem2_out')
a.raw(b'\xf3\xa4')
a.label('mem2_out')
a.emit('push 2'); a.emit('push 0'); a.emit('push 0'); a.emit('push dword ptr [&g_memlog]'); a.emit('call dword ptr [&imp_SetFilePointer]')
a.emit('push 0'); a.emit('push &g_mem_written'); a.emit('push 44'); a.emit('push &g_memdump'); a.emit('push dword ptr [&g_memlog]'); a.emit('call dword ptr [&imp_WriteFile]')
a.label('mem2_skip')
a.emit('mov esi, dword ptr [&g_pDev]'); a.emit('mov edx, &hookIOCTL'); a.call_label('patch_one')
a.emit('popad')
a.emit('jmp dword ptr [&g_saved_ret]')

# ---------------- hookRD (ReadFile) ----------------
a.label('hookRD')
a.emit('pushad')
a.emit('mov eax, dword ptr [esp + 32]'); a.emit('mov dword ptr [&gR_saved], eax')
if not DOG2_INTERCEPT:
    a.jmp_label('rd_notdog')
# ---- dog2 read interception: 65B read on the dog handle (answered from transcript) ----
# only intercept when a response is pending (g_state != 0); idle reads fall through
# to the real ReadFile so they BLOCK like the real dongle (instant zeros -> busy loop!)
a.emit('cmp dword ptr [esp + 44], 65')
a.jcc('jne', 'rd_notdog')
a.emit('cmp dword ptr [&g_state], 0')
a.jcc('je', 'rd_notdog')
a.emit('mov eax, dword ptr [esp + 36]')
a.emit('cmp eax, dword ptr [&g_dogh]')
a.jcc('jne', 'rd_notdog')
a.emit('test eax, eax')
a.jcc('jz', 'rd_notdog')
# pick response by state into esi
a.emit('mov eax, dword ptr [&g_state]')
a.emit('cmp eax, 1'); a.jcc('je', 'rd_dog_blob')
a.emit('cmp eax, 2'); a.jcc('je', 'rd_dog_atr')
a.emit('cmp eax, 3'); a.jcc('je', 'rd_dog_chal')
a.emit('mov esi, &t_zero'); a.jmp_label('rd_dog_serve')
a.label('rd_dog_blob')
# esi = &t_sblobs + min(session,NSESS-1)*195 + blobpart*65
a.emit('mov eax, dword ptr [&g_session]')
a.emit('cmp eax, %d' % (NSESS - 1)); a.jcc('jbe', 'rd_dog_sess_ok')
a.emit('mov eax, %d' % (NSESS - 1))
a.label('rd_dog_sess_ok')
a.emit('imul eax, %d' % (NSESS and 195))
a.emit('mov ecx, dword ptr [&g_blobpart]')
a.emit('imul ecx, 65')
a.emit('add eax, ecx')
a.emit('add eax, &t_sblobs'); a.emit('mov esi, eax')
a.emit('mov ecx, dword ptr [&g_blobpart]')
a.emit('inc ecx'); a.emit('cmp ecx, 3'); a.jcc('jb', 'rd_dog_blob_more')
a.emit('xor ecx, ecx'); a.emit('mov dword ptr [&g_state], 0')
a.label('rd_dog_blob_more')
a.emit('mov dword ptr [&g_blobpart], ecx')
a.jmp_label('rd_dog_serve')
a.label('rd_dog_atr')
a.emit('mov esi, &t_atr'); a.emit('mov dword ptr [&g_state], 0')
a.jmp_label('rd_dog_serve')
a.label('rd_dog_chal')
a.emit('mov esi, dword ptr [&g_chalresp]'); a.emit('test esi, esi'); a.jcc('jnz', 'rd_dog_chal_ok')
# unknown challenge: serve a structurally valid frame for this key length
a.emit('cmp dword ptr [&g_chalkl], 16'); a.jcc('je', 'rd_dog_fb16')
a.emit('mov esi, &t_fb8'); a.jmp_label('rd_dog_chal_ok')
a.label('rd_dog_fb16')
a.emit('mov esi, &t_fb16')
a.label('rd_dog_chal_ok')
a.emit('mov dword ptr [&g_state], 0')
a.label('rd_dog_serve')
a.emit('mov edi, dword ptr [esp + 40]')
a.emit('mov ecx, 65')
a.raw(b'\xf3\xa4')
a.emit('mov eax, dword ptr [esp + 48]'); a.emit('test eax, eax'); a.jcc('jz', 'rd_dog_nobr')
a.emit('mov dword ptr [eax], 65')
a.label('rd_dog_nobr')
# log the served response (api=0, ret=1, nread=65)
a.emit('mov esi, dword ptr [esp + 40]'); a.emit('mov ecx, 65'); a.emit('mov edi, &g_rec2'); a.emit('add edi, 32'); a.call_label('dump_buf')
a.emit('mov ecx, &g_rec2')
a.emit('mov dword ptr [ecx + 0], 0x44525752')
a.emit('mov dword ptr [ecx + 4], 0')
a.emit('mov eax, dword ptr [esp + 36]'); a.emit('mov dword ptr [ecx + 8], eax')
a.emit('mov dword ptr [ecx + 12], 65')
a.emit('mov dword ptr [ecx + 16], 1')
a.emit('mov dword ptr [ecx + 20], 65')
a.emit('mov eax, dword ptr [esp + 40]'); a.emit('mov dword ptr [ecx + 24], eax')
a.call_label('write_rw_rec')
a.emit('popad')
a.emit('mov eax, 1')
a.emit('ret 20')
a.label('rd_notdog')
a.emit('mov dword ptr [&gR_flag], 0')
a.emit('mov eax, dword ptr [esp + 44]')
a.emit('cmp eax, 1200')
a.jcc('ja', 'rd_skiplog')
a.emit('mov eax, dword ptr [esp + 36]')
a.emit('cmp eax, dword ptr [&g_log]'); a.jcc('je', 'rd_skiplog')
a.emit('cmp eax, dword ptr [&g_log2]'); a.jcc('je', 'rd_skiplog')
a.emit('mov dword ptr [&gR_flag], 1')
a.emit('mov eax, dword ptr [esp + 36]'); a.emit('mov dword ptr [&gR_h], eax')
a.emit('mov eax, dword ptr [esp + 40]'); a.emit('mov dword ptr [&gR_buf], eax')
a.emit('mov eax, dword ptr [esp + 44]'); a.emit('mov dword ptr [&gR_size], eax')
a.emit('mov eax, dword ptr [esp + 48]'); a.emit('mov dword ptr [&gR_nbr], eax')
a.label('rd_skiplog')
a.emit('mov esi, dword ptr [&g_pRd]'); a.emit('mov edi, &g_origRd'); a.call_label('restore_one')
a.emit('mov eax, &retRD')
a.emit('mov dword ptr [esp + 32], eax')
a.emit('popad')
a.emit('jmp dword ptr [&g_pRd]')

a.label('retRD')
a.emit('mov dword ptr [&gR_ret], eax')
a.emit('pushad')
a.emit('cmp dword ptr [&gR_flag], 1')
a.jcc('jne', 'rd_nolog')
a.emit('mov dword ptr [&gR_nread], 0')
a.emit('mov eax, dword ptr [&gR_nbr]')
a.emit('test eax, eax')
a.jcc('jz', 'rd_nonread')
a.emit('push 4'); a.emit('push eax'); a.emit('call dword ptr [&imp_IsBadReadPtr]')
a.emit('test eax, eax')
a.jcc('jnz', 'rd_nonread')
a.emit('mov ecx, dword ptr [&gR_nbr]')
a.emit('mov eax, dword ptr [ecx]')
a.emit('mov dword ptr [&gR_nread], eax')
a.label('rd_nonread')
a.emit('mov esi, dword ptr [&gR_buf]')
a.emit('mov ecx, dword ptr [&gR_nread]')
a.emit('mov edi, &g_rec2')
a.emit('add edi, 32')
a.call_label('dump_buf')
a.emit('mov ecx, &g_rec2')
a.emit('mov dword ptr [ecx + 0], 0x44525752')
a.emit('mov dword ptr [ecx + 4], 0')
a.emit('mov eax, dword ptr [&gR_h]'); a.emit('mov dword ptr [ecx + 8], eax')
a.emit('mov eax, dword ptr [&gR_size]'); a.emit('mov dword ptr [ecx + 12], eax')
a.emit('mov eax, dword ptr [&gR_ret]'); a.emit('mov dword ptr [ecx + 16], eax')
a.emit('mov eax, dword ptr [&gR_nread]'); a.emit('mov dword ptr [ecx + 20], eax')
a.emit('mov eax, dword ptr [&gR_buf]'); a.emit('mov dword ptr [ecx + 24], eax')
a.call_label('write_rw_rec')
a.label('rd_nolog')
a.emit('mov esi, dword ptr [&g_pRd]'); a.emit('mov edx, &hookRD'); a.call_label('patch_one')
a.emit('popad')
a.emit('jmp dword ptr [&gR_saved]')

# ---------------- hookWR (WriteFile) ----------------
a.label('hookWR')
a.emit('pushad')
a.emit('mov eax, dword ptr [esp + 32]'); a.emit('mov dword ptr [&gW_saved], eax')
if not DOG2_INTERCEPT:
    a.jmp_label('wr_notdog')
# ---- dog2 write interception: 65B write with 'R6' magic @7-8 ----
a.emit('cmp dword ptr [esp + 44], 65')
a.jcc('jne', 'wr_notdog')
a.emit('mov esi, dword ptr [esp + 40]')
a.emit('test esi, esi')
a.jcc('jz', 'wr_notdog')
a.emit('cmp byte ptr [esi + 7], 0x52')
a.jcc('jne', 'wr_notdog')
a.emit('cmp byte ptr [esi + 8], 0x36')
a.jcc('jne', 'wr_notdog')
# is dog write: stash handle + bytes
a.emit('mov eax, dword ptr [esp + 36]'); a.emit('mov dword ptr [&g_dogh], eax')
a.emit('mov edi, &g_dogwr'); a.emit('mov ecx, 65'); a.raw(b'\xf3\xa4')
# command dispatch (cmd u16 @10)
a.emit('movzx eax, word ptr [&g_dogwr + 10]')
a.emit('cmp eax, 3'); a.jcc('je', 'wr_dog_cmd3')
a.emit('cmp eax, 1'); a.jcc('je', 'wr_dog_cmd1')
a.emit('cmp eax, 2'); a.jcc('je', 'wr_dog_cmd2')
a.emit('mov dword ptr [&g_state], 0'); a.jmp_label('wr_dog_done')
a.label('wr_dog_cmd3')
# new session: session++ (clamp to NSESS-1), state=blob, part=0
a.emit('mov eax, dword ptr [&g_session]')
a.emit('inc eax')
a.emit('cmp eax, %d' % NSESS); a.jcc('jb', 'wr_dog_sess_ok')
a.emit('mov eax, %d' % (NSESS - 1))
a.label('wr_dog_sess_ok')
a.emit('mov dword ptr [&g_session], eax')
a.emit('mov dword ptr [&g_state], 1'); a.emit('mov dword ptr [&g_blobpart], 0'); a.jmp_label('wr_dog_done')
a.label('wr_dog_cmd1')
a.emit('mov dword ptr [&g_state], 2'); a.jmp_label('wr_dog_done')
a.label('wr_dog_cmd2')
a.emit('mov dword ptr [&g_state], 3')
a.emit('mov dword ptr [&g_chalresp], 0')
# challenge lookup: keylen byte @g_dogwr+12, key @g_dogwr+13; entries 85B: [keylen u32][key16][resp65]
a.emit('movzx edx, byte ptr [&g_dogwr + 12]')
a.emit('mov dword ptr [&g_chalkl], edx')
a.emit('xor ebx, ebx')
a.label('wr_dog_cloop')
a.emit('cmp ebx, %d' % NCHAL); a.jcc('jae', 'wr_dog_done')
a.emit('mov edi, &t_pents'); a.emit('mov eax, ebx'); a.emit('imul eax, 85'); a.emit('add edi, eax')
a.emit('cmp edx, dword ptr [edi]'); a.jcc('jne', 'wr_dog_cnext')
a.emit('mov esi, &g_dogwr'); a.emit('add esi, 13')
a.emit('mov eax, dword ptr [esi]'); a.emit('cmp eax, dword ptr [edi + 4]'); a.jcc('jne', 'wr_dog_cnext')
a.emit('mov eax, dword ptr [esi + 4]'); a.emit('cmp eax, dword ptr [edi + 8]'); a.jcc('jne', 'wr_dog_cnext')
a.emit('cmp edx, 16'); a.jcc('jb', 'wr_dog_cmatch')
a.emit('mov eax, dword ptr [esi + 8]'); a.emit('cmp eax, dword ptr [edi + 12]'); a.jcc('jne', 'wr_dog_cnext')
a.emit('mov eax, dword ptr [esi + 12]'); a.emit('cmp eax, dword ptr [edi + 16]'); a.jcc('jne', 'wr_dog_cnext')
a.label('wr_dog_cmatch')
a.emit('lea eax, dword ptr [edi + 20]'); a.emit('mov dword ptr [&g_chalresp], eax')
a.jmp_label('wr_dog_done')
a.label('wr_dog_cnext'); a.emit('inc ebx'); a.jmp_label('wr_dog_cloop')
a.label('wr_dog_done')
# set *lpNumberOfBytesWritten = 65
a.emit('mov eax, dword ptr [esp + 48]'); a.emit('test eax, eax'); a.jcc('jz', 'wr_dog_nobw')
a.emit('mov dword ptr [eax], 65')
a.label('wr_dog_nobw')
# log the intercepted write (api=1, ret=1)
a.emit('mov esi, &g_dogwr'); a.emit('mov ecx, 65'); a.emit('mov edi, &g_rec2'); a.emit('add edi, 32'); a.call_label('dump_buf')
a.emit('mov ecx, &g_rec2')
a.emit('mov dword ptr [ecx + 0], 0x44525752')
a.emit('mov dword ptr [ecx + 4], 1')
a.emit('mov eax, dword ptr [&g_dogh]'); a.emit('mov dword ptr [ecx + 8], eax')
a.emit('mov dword ptr [ecx + 12], 65')
a.emit('mov dword ptr [ecx + 16], 1')
a.emit('mov dword ptr [ecx + 20], 0')
a.emit('mov eax, dword ptr [esp + 40]'); a.emit('mov dword ptr [ecx + 24], eax')
a.call_label('write_rw_rec')
a.emit('popad')
a.emit('mov eax, 1')
a.emit('ret 20')
a.label('wr_notdog')
a.emit('mov dword ptr [&gW_flag], 0')
a.emit('mov eax, dword ptr [esp + 44]')
a.emit('cmp eax, 1200')
a.jcc('ja', 'wr_skiplog')
a.emit('mov eax, dword ptr [esp + 36]')
a.emit('cmp eax, dword ptr [&g_log]'); a.jcc('je', 'wr_skiplog')
a.emit('cmp eax, dword ptr [&g_log2]'); a.jcc('je', 'wr_skiplog')
a.emit('mov dword ptr [&gW_flag], 1')
a.emit('mov eax, dword ptr [esp + 36]'); a.emit('mov dword ptr [&gW_h], eax')
a.emit('mov eax, dword ptr [esp + 40]'); a.emit('mov dword ptr [&gW_buf], eax')
a.emit('mov eax, dword ptr [esp + 44]'); a.emit('mov dword ptr [&gW_size], eax')
a.emit('mov esi, dword ptr [&g_pWr]'); a.emit('mov edi, &g_origWr'); a.call_label('restore_one')
a.emit('mov esi, dword ptr [&gW_buf]')
a.emit('mov ecx, dword ptr [&gW_size]')
a.emit('mov edi, &g_rec2')
a.emit('add edi, 32')
a.call_label('dump_buf')
a.emit('mov ecx, &g_rec2')
a.emit('mov dword ptr [ecx + 0], 0x44525752')
a.emit('mov dword ptr [ecx + 4], 1')
a.emit('mov eax, dword ptr [&gW_h]'); a.emit('mov dword ptr [ecx + 8], eax')
a.emit('mov eax, dword ptr [&gW_size]'); a.emit('mov dword ptr [ecx + 12], eax')
a.emit('mov dword ptr [ecx + 16], 0')
a.emit('mov dword ptr [ecx + 20], 0')
a.emit('mov eax, dword ptr [&gW_buf]'); a.emit('mov dword ptr [ecx + 24], eax')
a.call_label('write_rw_rec')
a.jmp_label('wr_logged')
a.label('wr_skiplog')
a.emit('mov esi, dword ptr [&g_pWr]'); a.emit('mov edi, &g_origWr'); a.call_label('restore_one')
a.label('wr_logged')
a.emit('mov eax, &retWR')
a.emit('mov dword ptr [esp + 32], eax')
a.emit('popad')
a.emit('jmp dword ptr [&g_pWr]')

a.label('retWR')
a.emit('pushad')
a.emit('mov esi, dword ptr [&g_pWr]'); a.emit('mov edx, &hookWR'); a.call_label('patch_one')
a.emit('popad')
a.emit('jmp dword ptr [&gW_saved]')

# ---------------- export thunks ----------------
for i in range(3):
    a.label('thunk_%d' % i)
    a.emit('jmp dword ptr [&g_real + %d]' % (i * 4))

b.entry_label = 'dllmain'
b.exports = [('OpenNexioMulti', 'thunk_0'), ('CloseNexioMulti', 'thunk_1'), ('WaitNexioMulti', 'thunk_2')]

data, syms = b.build()
_suffix = {'orig': '', 'touch': '_touch'}[BACKING]
outname = ('multiDLL_rwreplay%s.dll' % _suffix) if DOG2_INTERCEPT else ('multiDLL_rwpt%s.dll' % _suffix)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), outname)
open(out, 'wb').write(data)
print('wrote', out, len(data), 'bytes')
