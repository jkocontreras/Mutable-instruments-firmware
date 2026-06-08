#!/usr/bin/env python3
"""
Mutable Instruments WAV Firmware Decoder
=========================================
Decodifica archivos .wav de firmware de Mutable Instruments
(Plaits, Rings, Marbles, Clouds, Braids, etc.) a .bin y .hex
listos para cargar via ST-Link o STM32CubeProgrammer.

Uso:
    python3 mutable_wav_decoder.py firmware.wav output.hex
    python3 mutable_wav_decoder.py firmware.wav output.bin

Dependencias:
    pip3 install numpy scipy

Notas:
    - La dirección de flash por defecto es 0x08008000 (Plaits, Rings, Marbles, etc.)
    - Para módulos con bootloader en 0x08004000, usar --address 0x08004000
"""

import sys
import wave
import struct
import zlib
import numpy as np
from scipy import signal

# Parámetros del bootloader QPSK de Mutable Instruments
SAMPLE_RATE         = 48000
CARRIER_FREQ        = 6000
BIT_RATE            = 12000
SAMPLES_PER_SYMBOL  = SAMPLE_RATE // BIT_RATE * 2  # 8
PACKET_SIZE         = 256
PACKET_SYMS         = (16 + PACKET_SIZE + 4) * 4   # 1104


def read_wav(filename):
    with wave.open(filename, 'rb') as f:
        n_ch = f.getnchannels()
        sw   = f.getsampwidth()
        rate = f.getframerate()
        raw  = f.readframes(f.getnframes())

    print(f"  WAV: {n_ch}ch, {sw*8}-bit, {rate} Hz")

    if sw == 2:
        s = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    else:
        raise ValueError(f"Bit depth {sw*8} no soportado (se requiere 16-bit)")

    if n_ch == 2:
        s = s[::2]
        print("  Estéreo — usando canal izquierdo")

    if rate != SAMPLE_RATE:
        print(f"  Resampling {rate} → {SAMPLE_RATE} Hz...")
        s = signal.resample(s, int(len(s) * SAMPLE_RATE / rate))

    return s


def demodulate(samples):
    n = len(samples)
    t = np.arange(n) / SAMPLE_RATE
    phase = 2 * np.pi * CARRIER_FREQ * t
    sps = SAMPLES_PER_SYMBOL
    i_raw = (samples * np.cos(phase)).reshape(-1, sps).mean(axis=1)
    q_raw = (samples * np.sin(phase)).reshape(-1, sps).mean(axis=1)
    return i_raw, q_raw


def find_packets(i_vals, q_vals):
    symbols = ((i_vals > 0).astype(int) * 2 + (q_vals > 0).astype(int))

    pattern = []
    for b in [0x99]*4 + [0xcc]*4:
        for sh in (6, 4, 2, 0):
            pattern.append((b >> sh) & 3)
    pattern = np.array(pattern)

    hits = []
    for i in range(len(symbols) - 64):
        if np.array_equal(symbols[i:i+32], pattern):
            start = i - 32
            if start >= 0:
                hits.append((start, symbols))
    return hits


def decode_packet(start, symbols):
    end = start + PACKET_SYMS
    if end > len(symbols):
        return None, False
    pkt_syms = symbols[start:end]
    raw = bytearray()
    for k in range(0, len(pkt_syms), 4):
        s = pkt_syms[k:k+4]
        b = ((int(s[0])&3)<<6)|((int(s[1])&3)<<4)|((int(s[2])&3)<<2)|(int(s[3])&3)
        raw.append(b)
    data     = bytes(raw[16:16+PACKET_SIZE])
    crc_recv = struct.unpack('>I', raw[272:276])[0]
    crc_calc = zlib.crc32(data) & 0xFFFFFFFF
    return data, (crc_recv == crc_calc)


def descramble(data):
    state = 0
    result = bytearray()
    for b in data:
        result.append(b ^ (state >> 24))
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
    return bytes(result)


def extract_firmware(hits):
    seen = set()
    unique = []
    ok = bad = 0
    for start, symbols in hits:
        data, crc_ok = decode_packet(start, symbols)
        if data is not None:
            if crc_ok:
                h = hash(data)
                if h not in seen:
                    seen.add(h)
                    unique.append(data)
                ok += 1
            else:
                bad += 1
    print(f"  Paquetes OK: {ok}  |  con error: {bad}  |  únicos: {len(unique)}")
    return descramble(b''.join(unique))


def write_hex(firmware, hex_path, start_address):
    lines = []
    address = start_address
    current_seg = -1

    for offset in range(0, len(firmware), 16):
        chunk = firmware[offset:offset+16]
        byte_count = len(chunk)
        addr_low = address & 0xFFFF
        seg = (address >> 16) & 0xFFFF

        if seg != current_seg:
            current_seg = seg
            b = [0x02, 0x00, 0x00, 0x04, seg >> 8, seg & 0xFF]
            cs = (-sum(b)) & 0xFF
            lines.append(':' + ''.join(f'{x:02X}' for x in b) + f'{cs:02X}')

        b = [byte_count, addr_low >> 8, addr_low & 0xFF, 0x00] + list(chunk)
        cs = (-sum(b)) & 0xFF
        lines.append(':' + ''.join(f'{x:02X}' for x in b) + f'{cs:02X}')
        address += byte_count

    lines.append(':00000001FF')

    with open(hex_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    errors = sum(1 for l in lines if l.startswith(':') and sum(bytes.fromhex(l[1:])) & 0xFF != 0)
    if errors:
        print(f"  ⚠️  {errors} checksums incorrectos en el HEX")
    else:
        print(f"  Checksums verificados: OK")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    wav_file = sys.argv[1]
    out_file = sys.argv[2]
    start_address = 0x08008000
    if '--address' in sys.argv:
        idx = sys.argv.index('--address')
        start_address = int(sys.argv[idx+1], 16)

    make_hex = out_file.lower().endswith('.hex')
    bin_file = out_file if not make_hex else out_file.replace('.hex', '.bin')

    print(f"\n=== Mutable Instruments WAV Decoder ===")
    print(f"Entrada:  {wav_file}")
    print(f"Salida:   {out_file}")
    print(f"Dirección flash: 0x{start_address:08X}\n")

    print("[1/4] Leyendo WAV...")
    samples = read_wav(wav_file)
    print(f"  {len(samples)} muestras ({len(samples)/SAMPLE_RATE:.1f}s)\n")

    print("[2/4] Demodulando QPSK...")
    i_vals, q_vals = demodulate(samples)
    print(f"  {len(i_vals)} símbolos\n")

    print("[3/4] Buscando paquetes...")
    hits = find_packets(i_vals, q_vals)
    print(f"  Preámbulos encontrados: {len(hits)}\n")

    if not hits:
        print("❌ No se encontraron paquetes. ¿Es un WAV de firmware Mutable?")
        sys.exit(1)

    print("[4/4] Decodificando y descifrando...")
    firmware = extract_firmware(hits)

    sp = struct.unpack_from('<I', firmware, 0)[0]
    rv = struct.unpack_from('<I', firmware, 4)[0]
    sp_ok = 0x20000000 <= sp <= 0x20020000
    rv_ok = 0x08000000 <= rv <= 0x080FFFFF
    print(f"  Stack pointer: 0x{sp:08X} {'✓' if sp_ok else '✗'}")
    print(f"  Reset vector:  0x{rv:08X} {'✓' if rv_ok else '✗'}")

    if not (sp_ok and rv_ok):
        print("\n⚠️  El vector table no parece válido para STM32.")
        print("   El firmware puede estar incompleto o usar una dirección diferente.")

    # Guardar BIN
    with open(bin_file, 'wb') as f:
        f.write(firmware)
    print(f"\n  BIN: {bin_file} ({len(firmware)} bytes)")

    # Generar HEX si se pidió
    if make_hex:
        write_hex(firmware, out_file, start_address)
        print(f"  HEX: {out_file}")

    print(f"\n✅ Listo.")
    print(f"\nCargar con ST-Link:")
    print(f"  st-flash write {bin_file} 0x{start_address:08X}")
    print(f"\nCargar con STM32CubeProgrammer:")
    print(f"  Abrir {out_file} → Start address: 0x{start_address:08X} → Program")


if __name__ == '__main__':
    main()
